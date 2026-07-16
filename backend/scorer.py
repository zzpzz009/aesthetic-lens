"""
scorer.py — ONNX Runtime 推理引擎

加载加密模型 → 内存解密 → ONNX Runtime 推理 → 返回美学分数

流程:
  图片路径/PIL Image → resize 224x224 → normalize → CLIP ONNX → MLP ONNX → score

支持多模型版本（v4.2 / v4.3），运行时可切换
"""

import io
import time
import logging
import sys
import os
from pathlib import Path

import numpy as np
from PIL import Image

from backend.model_crypto import decrypt_to_bytes

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 常量 (与训练时一致)
# ---------------------------------------------------------------------------
CLIP_MEAN = np.array([0.48145466, 0.4578275, 0.40821073], dtype=np.float32)
CLIP_STD = np.array([0.26862954, 0.26130258, 0.27577711], dtype=np.float32)
IMG_SIZE = 224

# ---------------------------------------------------------------------------
# 可用模型注册表
# ---------------------------------------------------------------------------
AVAILABLE_MODELS = {
    "v4.2": {
        "file": "mlp_head_v4.2.onnx.enc",
        "label": "V4.2",
        "desc": "MSE回归 · MAE=0.941 · r=0.873",
    },
    "v4.3": {
        "file": "mlp_head_v4.3.onnx.enc",
        "label": "V4.3",
        "desc": "最新版 · 数据增强优化",
    },
    "v4.530": {
        "file": "mlp_head_v4.530.onnx.enc",
        "label": "V4.530",
        "desc": "全量评分V4.530",
    },
}

DEFAULT_MODEL = sorted(AVAILABLE_MODELS.keys(),
    key=lambda v: tuple(int(x.replace("v","")) for x in v.split(".") if x),
    reverse=True)[0]


class AestheticScorer:
    """美学评分引擎 — 线程安全, 可复用, 支持多模型切换"""

    def __init__(self, models_dir: str | None = None, model_version: str | None = None, use_gpu: bool = True):
        if models_dir is None:
            models_dir = self._resolve_models_dir()

        self.models_dir = Path(models_dir)
        self._clip_sess = None
        self._mlp_sessions = {}  # version -> ort.InferenceSession
        self._current_model = model_version or DEFAULT_MODEL
        self._use_gpu = use_gpu

        # 加载CLIP（共享，只需加载一次）
        self._load_clip()

        # 加载初始MLP模型
        self._ensure_mlp(self._current_model)

    @staticmethod
    def _resolve_models_dir() -> str:
        """模型目录 — exe同级 > _MEIPASS > 源码相对路径"""
        if getattr(sys, 'frozen', False):
            exe_dir = Path(sys.executable).parent
            candidate = exe_dir / "models"
            if candidate.exists():
                return str(candidate)
            meipass = Path(sys._MEIPASS)
            candidate = meipass / "models"
            if candidate.exists():
                return str(candidate)
            return str(exe_dir / "models")
        return str(Path(__file__).parent.parent / "models")

    def _get_providers(self, use_gpu: bool = True):
        """检测可用的 ORT providers，use_gpu=False 时仅用 CPU"""
        import onnxruntime as ort
        available = ort.get_available_providers()
        provider_list = []
        if use_gpu and "CUDAExecutionProvider" in available:
            provider_list.append(("CUDAExecutionProvider", {
                "arena_extend_strategy": "kSameAsRequested",
                "gpu_mem_limit": str(2 * 1024 * 1024 * 1024),  # 2GB
            }))
        if "CPUExecutionProvider" in available:
            provider_list.append("CPUExecutionProvider")
        if not provider_list:
            provider_list = ["CPUExecutionProvider"]
        return provider_list

    def _make_session_options(self) -> "ort.SessionOptions":
        """创建优化的 SessionOptions — 限制内存池 + 单线程推理"""
        import onnxruntime as ort
        opts = ort.SessionOptions()
        opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        opts.enable_mem_pattern = True
        opts.enable_cpu_mem_arena = True
        opts.add_session_config_entry("session.intra_op.allow_spinning", "0")
        opts.add_session_config_entry("session.inter_op.allow_spinning", "0")
        # 单线程避免线程竞争（批量评分外部串行调度）
        opts.intra_op_num_threads = 1
        opts.inter_op_num_threads = 1
        return opts

    def _setup_ort_dll(self):
        """PyInstaller 打包后加载 ORT DLL + GPU 依赖 DLL (cuDNN/cublas/nvrtc)"""
        # --- GPU 依赖：自动发现 nvidia DLL 目录 ---
        extra_dirs = []
        search_roots = list(sys.path)
        # PyInstaller 打包：_MEIPASS (= _internal/) 内含 nvidia/*/bin
        if getattr(sys, 'frozen', False):
            search_roots.insert(0, sys._MEIPASS)
        for p in search_roots:
            for pkg in ("nvidia/cudnn/bin", "nvidia/cublas/bin", "nvidia/cuda_nvrtc/bin"):
                d = os.path.join(p, pkg)
                if os.path.isdir(d) and d not in extra_dirs:
                    extra_dirs.append(d)
        # CUDA Toolkit 系统安装
        for v in sorted(Path("C:/Program Files/NVIDIA GPU Computing Toolkit/CUDA").glob("v12*/bin"), reverse=True):
            if v.is_dir() and str(v) not in extra_dirs:
                extra_dirs.append(str(v))
                break  # 只取最新版本

        for d in extra_dirs:
            if d not in os.environ.get("PATH", ""):
                os.environ["PATH"] = d + os.pathsep + os.environ.get("PATH", "")
                try:
                    os.add_dll_directory(d)
                except OSError:
                    pass

        # --- PyInstaller 打包：ORT DLL ---
        if getattr(sys, 'frozen', False):
            import ctypes
            base = sys._MEIPASS
            exe_dir = str(Path(sys.executable).parent)
            ort_capi = os.path.join(base, "onnxruntime", "capi")
            ort_dll = os.path.join(ort_capi, "onnxruntime.dll")
            if not os.path.exists(ort_dll):
                ort_dll = os.path.join(exe_dir, "onnxruntime.dll")
            if os.path.exists(ort_dll):
                kernel32 = ctypes.windll.kernel32
                kernel32.LoadLibraryW.argtypes = [ctypes.c_wchar_p]
                kernel32.LoadLibraryW.restype = ctypes.c_void_p
                kernel32.LoadLibraryW(ort_dll)
            for d in [exe_dir, ort_capi, os.path.join(base, "numpy.libs")]:
                if d and os.path.isdir(d):
                    try:
                        os.add_dll_directory(d)
                    except OSError:
                        pass

    def _load_clip(self):
        """加载CLIP visual encoder（所有模型共享）"""
        self._setup_ort_dll()
        import onnxruntime as ort

        clip_enc = self.models_dir / "clip_visual.onnx.enc"
        if not clip_enc.exists():
            raise FileNotFoundError(f"CLIP模型不存在: {clip_enc}")

        t0 = time.time()
        clip_bytes = decrypt_to_bytes(str(clip_enc))

        sess_opts = self._make_session_options()
        providers = self._get_providers(self._use_gpu)

        self._clip_sess = ort.InferenceSession(
            clip_bytes, sess_opts, providers=providers
        )
        # CLIP 解密后的 bytes 不再需要
        del clip_bytes

        elapsed = time.time() - t0
        log.info("CLIP加载完成 (%.1fs), providers=%s", elapsed, self._clip_sess.get_providers())

    def _ensure_mlp(self, version: str):
        """确保指定版本的MLP已加载"""
        if version in self._mlp_sessions:
            return

        if version not in AVAILABLE_MODELS:
            raise ValueError(f"未知模型版本: {version}，可用: {list(AVAILABLE_MODELS.keys())}")

        import onnxruntime as ort

        mlp_file = AVAILABLE_MODELS[version]["file"]
        mlp_enc = self.models_dir / mlp_file

        if not mlp_enc.exists():
            # 兼容旧版：尝试 mlp_head.onnx.enc
            fallback = self.models_dir / "mlp_head.onnx.enc"
            if fallback.exists():
                log.warning("MLP %s 不存在，使用默认 mlp_head.onnx.enc", version)
                mlp_enc = fallback
            else:
                raise FileNotFoundError(f"MLP模型不存在: {mlp_enc}")

        t0 = time.time()
        mlp_bytes = decrypt_to_bytes(str(mlp_enc))

        sess_opts = self._make_session_options()
        providers = self._get_providers()

        self._mlp_sessions[version] = ort.InferenceSession(
            mlp_bytes, sess_opts, providers=providers
        )
        # 解密后的 bytes 不再需要
        del mlp_bytes

        elapsed = time.time() - t0
        log.info("MLP %s 加载完成 (%.1fs)", version, elapsed)

    # ---- 模型切换API ----

    def switch_model(self, version: str) -> dict:
        """切换当前使用的模型版本，卸载旧模型释放内存"""
        if version not in AVAILABLE_MODELS:
            return {"error": f"未知模型: {version}"}

        old_version = self._current_model
        self._ensure_mlp(version)
        self._current_model = version

        # 卸载旧模型（仅保留当前版本，按需加载）
        if old_version != version and old_version in self._mlp_sessions:
            log.info("卸载旧模型 %s 释放内存", old_version)
            del self._mlp_sessions[old_version]

        info = AVAILABLE_MODELS[version]
        log.info("切换到模型 %s", version)
        return {"version": version, "label": info["label"], "desc": info["desc"]}

    def get_current_model(self) -> dict:
        """获取当前模型信息"""
        version = self._current_model
        info = AVAILABLE_MODELS.get(version, {})
        return {
            "version": version,
            "label": info.get("label", version),
            "desc": info.get("desc", ""),
        }

    @staticmethod
    def list_models() -> list[dict]:
        """列出所有可用模型"""
        models = []
        for ver, info in AVAILABLE_MODELS.items():
            models.append({
                "version": ver,
                "label": info["label"],
                "desc": info["desc"],
            })
        return models

    @staticmethod
    def check_gpu_available() -> dict:
        """检测 GPU 加速是否可用（不加载模型，轻量级）"""
        try:
            import onnxruntime as ort
            available = ort.get_available_providers()
            cuda_available = "CUDAExecutionProvider" in available
            return {
                "gpu_available": cuda_available,
                "providers": list(available),
            }
        except Exception as e:
            return {"gpu_available": False, "error": str(e)}

    def preprocess(self, image: Image.Image | str | bytes) -> np.ndarray:
        """
        图片预处理 → (1, 3, 224, 224) float32 numpy array

        支持: PIL Image / 文件路径 / 图片 bytes
        """
        if isinstance(image, str):
            img = Image.open(image).convert("RGB")
        elif isinstance(image, bytes):
            img = Image.open(io.BytesIO(image)).convert("RGB")
        elif isinstance(image, Image.Image):
            img = image.convert("RGB")
        else:
            raise TypeError(f"不支持的输入类型: {type(image)}")

        # Resize to 224x224 (bilinear, 与训练一致)
        img = img.resize((IMG_SIZE, IMG_SIZE), Image.BICUBIC)

        # To numpy: (H, W, C) uint8 → float32
        arr = np.array(img, dtype=np.float32) / 255.0

        # Normalize
        arr = (arr - CLIP_MEAN) / CLIP_STD

        # HWC → CHW
        arr = arr.transpose(2, 0, 1)

        # Add batch dim → (1, 3, 224, 224)
        return arr[np.newaxis].astype(np.float32)

    def score(self, image: Image.Image | str | bytes) -> dict:
        """
        评分单张图片

        Returns:
            {
                "score": float,       # 1-10 美学分
                "tier": str,          # 等级: 卓越/优秀/良好/一般/较差
                "elapsed_ms": float,  # 推理耗时
                "model": str,         # 使用的模型版本
            }
        """
        t0 = time.perf_counter()

        pixel_values = self.preprocess(image)

        # CLIP visual encoding
        features = self._clip_sess.run(
            ["image_features"],
            {"pixel_values": pixel_values},
        )[0]  # (1, 768)

        # L2 normalize (与训练时一致)
        features = features / np.linalg.norm(features, axis=-1, keepdims=True)

        # MLP regression — 使用当前模型
        mlp_sess = self._mlp_sessions[self._current_model]
        score_val = mlp_sess.run(
            ["score"],
            {"image_features": features.astype(np.float32)},
        )[0][0, 0]  # scalar

        elapsed_ms = (time.perf_counter() - t0) * 1000

        # Clamp to [1, 10]
        score_val = max(1.0, min(10.0, float(score_val)))

        return {
            "score": round(score_val, 2),
            "tier": self._tier(score_val),
            "elapsed_ms": round(elapsed_ms, 1),
            "model": self._current_model,
        }

    def score_batch(self, images: list, callback=None) -> list[dict]:
        """
        批量评分

        Args:
            images: 图片列表 (路径/PIL Image/bytes)
            callback: 可选回调 fn(index, total, result)

        Returns:
            结果列表
        """
        results = []
        total = len(images)
        for i, img in enumerate(images):
            try:
                result = self.score(img)
                result["index"] = i
                result["error"] = None
            except Exception as e:
                result = {"score": 0, "tier": "错误", "elapsed_ms": 0, "index": i,
                          "model": self._current_model, "error": str(e)}

            results.append(result)
            if callback:
                callback(i, total, result)

        return results

    @staticmethod
    def _tier(score: float) -> str:
        if score >= 9.0:
            return "卓越"
        elif score >= 7.0:
            return "优秀"
        elif score >= 5.0:
            return "良好"
        elif score >= 3.0:
            return "一般"
        else:
            return "较差"
