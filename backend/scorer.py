"""
scorer.py — ONNX Runtime 推理引擎

加载加密模型 → 内存解密 → ONNX Runtime 推理 → 返回美学分数

流程:
  图片路径/PIL Image → resize 224x224 → normalize → CLIP ONNX → MLP ONNX → score
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


class AestheticScorer:
    """美学评分引擎 — 线程安全, 可复用"""

    def __init__(self, models_dir: str | None = None):
        if models_dir is None:
            models_dir = self._resolve_models_dir()

        self.models_dir = Path(models_dir)
        self._clip_sess = None
        self._mlp_sess = None
        self._load_models()

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

    def _get_providers(self):
        """检测可用的 ORT providers，CUDA 优先，CPU 兜底"""
        import onnxruntime as ort
        available = ort.get_available_providers()
        preferred = ["CUDAExecutionProvider", "CPUExecutionProvider"]
        providers = [p for p in preferred if p in available]
        if not providers:
            providers = ["CPUExecutionProvider"]
        return providers

    def _load_models(self):
        """解密并加载 ONNX 模型到内存"""
        if getattr(sys, 'frozen', False):
            import ctypes
            base = sys._MEIPASS
            exe_dir = str(Path(sys.executable).parent)
            ort_capi = os.path.join(base, "onnxruntime", "capi")
            ort_dll = os.path.join(ort_capi, "onnxruntime.dll")
            # 也检查 exe 同级目录
            if not os.path.exists(ort_dll):
                ort_dll = os.path.join(exe_dir, "onnxruntime.dll")
            if os.path.exists(ort_dll):
                kernel32 = ctypes.windll.kernel32
                kernel32.LoadLibraryW.argtypes = [ctypes.c_wchar_p]
                kernel32.LoadLibraryW.restype = ctypes.c_void_p
                kernel32.LoadLibraryW(ort_dll)
            # 确保 DLL 搜索路径
            for d in [exe_dir, ort_capi, os.path.join(base, "numpy.libs")]:
                if d and os.path.isdir(d):
                    try:
                        os.add_dll_directory(d)
                    except OSError:
                        pass

        import onnxruntime as ort

        clip_enc = self.models_dir / "clip_visual.onnx.enc"
        mlp_enc = self.models_dir / "mlp_head.onnx.enc"

        if not clip_enc.exists():
            raise FileNotFoundError(
                f"加密模型文件不存在: {clip_enc}\n"
                "请先运行 model_export.py 导出模型"
            )
        if not mlp_enc.exists():
            raise FileNotFoundError(
                f"加密模型文件不存在: {mlp_enc}\n"
                "请先运行 model_export.py 导出模型"
            )

        t0 = time.time()

        # 解密到内存 → ONNX Runtime 从字节流加载
        clip_bytes = decrypt_to_bytes(str(clip_enc))
        mlp_bytes = decrypt_to_bytes(str(mlp_enc))

        sess_opts = ort.SessionOptions()
        sess_opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL

        providers = self._get_providers()

        # CLIP FP32
        self._clip_sess = ort.InferenceSession(
            clip_bytes, sess_opts,
            providers=providers
        )

        # MLP FP32
        self._mlp_sess = ort.InferenceSession(
            mlp_bytes, sess_opts,
            providers=providers
        )

        elapsed = time.time() - t0
        active_providers = self._clip_sess.get_providers()
        log.info(
            "模型加载完成 (%.1fs), providers=%s",
            elapsed, active_providers
        )

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

        # MLP regression
        score_val = self._mlp_sess.run(
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
                result = {"score": 0, "tier": "错误", "elapsed_ms": 0, "index": i, "error": str(e)}

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
