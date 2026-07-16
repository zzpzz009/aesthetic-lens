#!/usr/bin/env python3
"""
app.py — AestheticLens 主入口

pywebview 桌面窗口 + JS bridge API
"""

import base64
import io
import json
import logging
import os
import sys
import tempfile
from pathlib import Path

# ---------------------------------------------------------------------------
# PyInstaller DLL 路径修复 — 必须在 import onnxruntime/webview 之前
# ---------------------------------------------------------------------------
if getattr(sys, 'frozen', False):
    _exe_dir = Path(sys.executable).parent
    _meipass = Path(sys._MEIPASS)
    # onnxruntime DLL 放在 exe 同级目录
    _extra_dirs = [
        str(_exe_dir),
        str(_meipass),
        str(_meipass / "onnxruntime" / "capi"),
        str(_meipass / "numpy.libs"),
    ]
    for d in _extra_dirs:
        if Path(d).is_dir():
            os.add_dll_directory(d)
    existing = os.environ.get("PATH", "")
    new_paths = ";".join(d for d in _extra_dirs if Path(d).is_dir())
    os.environ["PATH"] = new_paths + ";" + existing

import webview

from backend.scorer import AestheticScorer
from backend.export import export_csv, export_json

# ---------------------------------------------------------------------------
# 日志
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("AestheticLens")

# --noconsole 模式 stderr 被吞，额外写一份日志到 exe 同级 app.log 便于诊断
try:
    _log_dir = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).parent
    _fh = logging.FileHandler(_log_dir / "app.log", mode="w", encoding="utf-8")
    _fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
    logging.getLogger().addHandler(_fh)
except OSError:
    pass

# ---------------------------------------------------------------------------
# API Bridge — 前端 JS 通过 window.pywebview.api.xxx() 调用
# ---------------------------------------------------------------------------
class Api:
    def __init__(self):
        self._scorer = None
        self._window = None
        self._use_gpu = True  # 默认尝试 GPU

    @staticmethod
    def _resolve_models_dir() -> Path:
        """模型目录 — exe同级 > _MEIPASS(onefile解压目录) > 源码相对路径"""
        if getattr(sys, 'frozen', False):
            exe_dir = Path(sys.executable).parent
            candidate = exe_dir / "models"
            if candidate.exists():
                return candidate
            # onefile: 模型打包进 _MEIPASS 临时解压目录
            meipass = Path(getattr(sys, '_MEIPASS', exe_dir))
            candidate = meipass / "models"
            if candidate.exists():
                return candidate
            return exe_dir / "models"
        return Path(__file__).parent / "models"

    def _ensure_scorer(self, use_gpu: bool = None):
        """获取或创建 scorer，use_gpu 变更时会重建"""
        if use_gpu is None:
            use_gpu = self._use_gpu
        if self._scorer is not None and self._use_gpu != use_gpu:
            self._scorer = None
        self._use_gpu = use_gpu
        if self._scorer is None:
            self._scorer = AestheticScorer(use_gpu=use_gpu)
        return self._scorer

    # ---- 模型管理 ----
    def list_models(self):
        """列出所有可用评分模型"""
        scorer = self._ensure_scorer()
        current = scorer.get_current_model()
        models = AestheticScorer.list_models()
        return {"models": models, "current": current}

    def switch_model(self, version: str):
        """切换评分模型版本"""
        scorer = self._ensure_scorer()
        return scorer.switch_model(version)

    def get_current_model(self):
        """获取当前模型信息"""
        scorer = self._ensure_scorer()
        return scorer.get_current_model()

    # ---- GPU 加速 ----
    def check_gpu_available(self):
        """检测 GPU 加速是否可用（轻量级，不加载模型）"""
        return AestheticScorer.check_gpu_available()

    def set_gpu_mode(self, enabled: bool):
        """切换 GPU 加速模式（重建 scorer）"""
        use_gpu = enabled and AestheticScorer.check_gpu_available()["gpu_available"]
        scorer = self._ensure_scorer(use_gpu=use_gpu)
        providers = scorer._clip_sess.get_providers() if scorer._clip_sess else []
        return {
            "gpu_enabled": use_gpu,
            "providers": providers,
        }

    # ---- 系统信息 ----
    def get_version(self):
        return {"version": "2.3.0", "name": "AestheticLens"}

    def close(self):
        if self._window:
            self._window.destroy()

    def minimize(self):
        if self._window:
            self._window.minimize()

    def toggle_maximize(self):
        if not self._window:
            return
        # pywebview 5.x 没有直接判断最大化状态的属性
        # 通过比较窗口尺寸和屏幕尺寸来判断
        import ctypes
        screen_w = ctypes.windll.user32.GetSystemMetrics(0)
        screen_h = ctypes.windll.user32.GetSystemMetrics(1)
        if self._window.width >= screen_w and self._window.height >= screen_h:
            self._window.restore()
        else:
            self._window.maximize()

    def check_models(self):
        """检查模型文件是否存在"""
        models_dir = self._resolve_models_dir()
        clip_enc = models_dir / "clip_visual.onnx.enc"

        result = {
            "clip_exists": clip_enc.exists(),
            "clip_size_mb": round(clip_enc.stat().st_size / 1024 / 1024, 1) if clip_enc.exists() else 0,
            "mlp_models": {},
        }

        from backend.scorer import AVAILABLE_MODELS
        for ver, info in AVAILABLE_MODELS.items():
            mlp_enc = models_dir / info["file"]
            result["mlp_models"][ver] = {
                "exists": mlp_enc.exists(),
                "size_kb": round(mlp_enc.stat().st_size / 1024, 0) if mlp_enc.exists() else 0,
                "label": info["label"],
            }

        return result

    # ---- 单图评分（base64，用于拖拽） ----
    def score_image(self, image_data: str):
        """
        评分单张图片 (base64 编码)

        Args:
            image_data: "data:image/jpeg;base64,xxxxx" 格式

        Returns:
            {"score": 7.8, "tier": "优秀", "elapsed_ms": 120, "error": null}
        """
        try:
            scorer = self._ensure_scorer()

            # 解码 base64
            if "," in image_data:
                image_data = image_data.split(",", 1)[1]
            img_bytes = base64.b64decode(image_data)

            result = scorer.score(img_bytes)
            result["error"] = None
            return result

        except Exception as e:
            log.error("评分失败: %s", e, exc_info=True)
            return {"score": 0, "tier": "错误", "elapsed_ms": 0, "error": str(e)}

    # ---- 单图评分（文件路径，用于文件对话框） ----
    def score_image_path(self, filepath: str):
        """直接从文件路径评分（避免 base64 桥接开销）"""
        try:
            scorer = self._ensure_scorer()
            result = scorer.score(str(filepath))
            result["error"] = None
            return result
        except Exception as e:
            log.error("评分失败 %s: %s", filepath, e, exc_info=True)
            return {"score": 0, "tier": "错误", "elapsed_ms": 0, "error": str(e)}

    # ---- 批量评分 ----
    def score_batch_start(self, images_json: str):
        """
        批量评分入口 — 逐张评分，统一返回结果

        Args:
            images_json: [{"filename": "a.jpg", "data": "base64..."}, ...]

        Returns:
            {"results": [...], "total": N}
            每个 result: {"filename": ..., "score": ..., "tier": ..., "error": ...}
        """
        try:
            scorer = self._ensure_scorer()
            items = json.loads(images_json)
            total = len(items)

            results = []
            for i, item in enumerate(items):
                try:
                    data = item["data"]
                    if "," in data:
                        data = data.split(",", 1)[1]
                    img_bytes = base64.b64decode(data)

                    result = scorer.score(img_bytes)
                    result["filename"] = item.get("filename", f"image_{i}")
                    result["error"] = None
                except Exception as e:
                    result = {
                        "filename": item.get("filename", f"image_{i}"),
                        "score": 0,
                        "tier": "错误",
                        "elapsed_ms": 0,
                        "error": str(e),
                    }
                results.append(result)

                # 推送进度（仅更新进度条，不操作DOM）
                if self._window:
                    self._window.evaluate_js(
                        f"window.__batchProgress({i + 1}, {total})"
                    )

            return {"results": results, "total": total}

        except Exception as e:
            log.error("批量评分失败: %s", e, exc_info=True)
            return {"results": [{"error": str(e)}], "total": 1}

    # ---- 批量评分（文件路径） ----
    def score_batch_paths(self, paths_json: str):
        """
        批量评分（文件路径列表）— 服务端逐张推理，推送进度

        Args:
            paths_json: JSON 数组 ["path/a.jpg", "path/b.png", ...]

        Returns:
            {"results": [...], "total": N}
        """
        try:
            scorer = self._ensure_scorer()
            paths = json.loads(paths_json)
            total = len(paths)
            results = []

            for i, filepath in enumerate(paths):
                try:
                    result = scorer.score(str(filepath))
                    result["filename"] = Path(filepath).name
                    result["error"] = None
                except Exception as e:
                    result = {
                        "filename": Path(filepath).name,
                        "score": 0,
                        "tier": "错误",
                        "elapsed_ms": 0,
                        "error": str(e),
                    }
                result["index"] = i
                results.append(result)

                # 推送进度
                if self._window:
                    pct = round((i + 1) / total * 100)
                    self._window.evaluate_js(
                        f"if(window.__onBatchProgress)window.__onBatchProgress({i},{total},{json.dumps(result)})"
                    )

            return {"results": results, "total": total}

        except Exception as e:
            log.error("批量路径评分失败: %s", e, exc_info=True)
            return {"results": [{"error": str(e)}], "total": 1}

    # ---- 导出 ----
    def export_results(self, results_json: str, format: str = "csv"):
        """
        导出评分结果

        Args:
            results_json: JSON 字符串
            format: "csv" 或 "json"

        Returns:
            {"path": "保存路径"} 或 {"error": "..."}
        """
        try:
            results = json.loads(results_json)
            timestamp = __import__("time").strftime("%Y%m%d_%H%M%S")
            desktop = Path.home() / "Desktop"

            if format == "csv":
                path = desktop / f"aesthetic_scores_{timestamp}.csv"
                export_csv(results, str(path))
            else:
                path = desktop / f"aesthetic_scores_{timestamp}.json"
                export_json(results, str(path))

            return {"path": str(path)}

        except Exception as e:
            return {"error": str(e)}

    # ---- 另存图片到文件夹 ----
    def pick_save_folder(self):
        """打开文件夹选择对话框（用于选择保存目标）"""
        if not self._window:
            return {"folder": None}
        result = self._window.create_file_dialog(webview.FOLDER_DIALOG)
        if not result:
            return {"folder": None}
        return {"folder": result[0]}

    def save_images_to_folder(self, images_json: str, dest_folder: str):
        """
        将图片保存到目标文件夹

        Args:
            images_json: [{"filename": "a.jpg", "filepath": "...", "data": "base64..."}, ...]
            dest_folder: 目标文件夹路径

        Returns:
            {"count": N, "folder": "..."} 或 {"error": "..."}
        """
        try:
            import shutil
            images = json.loads(images_json)
            dest = Path(dest_folder)
            if not dest.is_dir():
                return {"error": "目标文件夹不存在"}

            count = 0
            for img in images:
                filename = img.get("filename", "image.jpg")
                # 去重：同名文件加序号
                target = dest / filename
                stem, ext = target.stem, target.suffix
                c = 1
                while target.exists():
                    target = dest / f"{stem}_{c}{ext}"
                    c += 1

                if img.get("filepath"):
                    # 有源文件路径 → 直接复制
                    shutil.copy2(img["filepath"], str(target))
                elif img.get("data"):
                    # 只有 base64 → 解码写入
                    data = img["data"]
                    if "," in data:
                        data = data.split(",", 1)[1]
                    with open(str(target), "wb") as f:
                        f.write(base64.b64decode(data))
                else:
                    continue
                count += 1

            return {"count": count, "folder": str(dest)}

        except Exception as e:
            log.error("保存图片失败: %s", e, exc_info=True)
            return {"error": str(e)}

    # ---- 文件选择对话框 ----
    def open_file_dialog(self):
        """打开文件选择对话框, 返回文件路径列表（不含 base64，避免桥接层撑爆）"""
        if not self._window:
            return []

        result = self._window.create_file_dialog(
            webview.OPEN_DIALOG,
            directory="",
            allow_multiple=True,
            file_types=("Image Files (*.jpg;*.jpeg;*.png;*.webp;*.bmp)",),
        )
        if not result:
            return []

        images = []
        for file_path in result:
            path = Path(file_path)
            images.append({
                "filename": path.name,
                "filepath": str(path),
            })

        return images

    def get_image_data(self, filepath: str):
        """从文件路径读取图片，返回 data URI（用于显示）"""
        try:
            path = Path(filepath)
            with open(path, "rb") as f:
                b64 = base64.b64encode(f.read()).decode()
            ext = path.suffix.lower()
            mime = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png",
                    "webp": "image/webp", "bmp": "image/bmp"}.get(ext.lstrip("."), "image/jpeg")
            return f"data:{mime};base64,{b64}"
        except Exception as e:
            log.error("读取图片失败 %s: %s", filepath, e)
            return ""

    def get_thumbnail(self, filepath: str, size: int = 200):
        """生成缩略图 data URI（最大边=size），大批量网格用"""
        try:
            from PIL import Image
            import io as io_mod

            path = Path(filepath)
            img = Image.open(path).convert("RGB")
            # 等比缩放，最大边 = size
            img.thumbnail((size, size), Image.LANCZOS)
            buf = io_mod.BytesIO()
            img.save(buf, format="JPEG", quality=85)
            b64 = base64.b64encode(buf.getvalue()).decode()
            return f"data:image/jpeg;base64,{b64}"
        except Exception as e:
            log.error("缩略图生成失败 %s: %s", filepath, e)
            return ""

    def save_temp_image(self, base64_data: str, filename: str):
        """将 base64 图片保存为临时文件，返回文件路径

        Args:
            base64_data: "data:image/jpeg;base64,xxxxx" 格式
            filename: 原始文件名（用于保留扩展名）

        Returns:
            str: 临时文件的绝对路径
        """
        try:
            # 解码 base64
            if "," in base64_data:
                base64_data = base64_data.split(",", 1)[1]
            img_bytes = base64.b64decode(base64_data)

            # 确保临时目录存在
            tmp_dir = Path(tempfile.gettempdir()) / "aesthetic-lens"
            tmp_dir.mkdir(parents=True, exist_ok=True)

            # 使用原始文件名（加随机后缀防冲突）
            stem = Path(filename).stem
            suffix = Path(filename).suffix or ".jpg"
            fd, tmp_path = tempfile.mkstemp(
                prefix=f"{stem}_", suffix=suffix, dir=str(tmp_dir)
            )
            with os.fdopen(fd, "wb") as f:
                f.write(img_bytes)

            return tmp_path
        except Exception as e:
            log.error("临时图片保存失败 %s: %s", filename, e)
            return ""

    def open_folder_dialog(self):
        """打开文件夹选择对话框, 递归扫描所有图片"""
        if not self._window:
            return []

        result = self._window.create_file_dialog(
            webview.FOLDER_DIALOG,
        )
        if not result:
            return []

        folder = Path(result[0])
        exts = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
        images = []

        for f in sorted(folder.rglob("*")):
            if f.suffix.lower() in exts and f.is_file():
                images.append({
                    "filename": f.name,
                    "filepath": str(f),
                })

        return images


# ---------------------------------------------------------------------------
# 启动
# ---------------------------------------------------------------------------
def _resolve_path(relative: str) -> Path:
    """
    解析资源文件路径 — 兼容三种环境:
    1. 开发环境: 项目根目录下
    2. PyInstaller 打包: sys._MEIPASS (_internal/) 下
    3. exe 同级目录: 用户手动放置
    """
    # 优先: exe 同级目录（方便用户替换前端文件）
    if getattr(sys, 'frozen', False):
        exe_dir = Path(sys.executable).parent
        candidate = exe_dir / relative
        if candidate.exists():
            return candidate
        # 其次: PyInstaller _MEIPASS
        meipass = Path(sys._MEIPASS)
        candidate = meipass / relative
        if candidate.exists():
            return candidate
        # 兜底返回 exe 同级
        return exe_dir / relative
    else:
        return Path(__file__).parent / relative


def _check_webview2() -> bool:
    """检测 WebView2 Runtime 是否已安装。

    用微软官方方式: 查 EdgeUpdate 注册表里 WebView2 Runtime 客户端 GUID 的 pv 值。
    注意: EdgeUpdate 是 32 位组件, 在 64 位系统上写到 WOW6432Node 下, 必须显式查该路径。
    旧实现靠探测 WebView2Loader.dll 固定路径, 极易假阴性(已装也判为未装)。
    """
    try:
        import winreg
    except ImportError:
        return True  # 非 Windows, 交给 pywebview 自行处理

    guid = "{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"
    suffix = "Microsoft\\EdgeUpdate\\Clients\\" + guid
    locations = [
        (winreg.HKEY_LOCAL_MACHINE, "SOFTWARE\\WOW6432Node\\" + suffix),  # 64位系统(每机器)
        (winreg.HKEY_LOCAL_MACHINE, "SOFTWARE\\" + suffix),               # 32位系统(每机器)
        (winreg.HKEY_CURRENT_USER, "SOFTWARE\\" + suffix),                # 每用户安装
    ]
    for hive, subkey in locations:
        try:
            with winreg.OpenKey(hive, subkey) as k:
                pv, _ = winreg.QueryValueEx(k, "pv")
                if pv and pv != "0.0.0.0":
                    return True
        except OSError:
            continue
    return False


def _show_webview2_missing_dialog():
    """显示 WebView2 缺失提示"""
    import ctypes
    ctypes.windll.user32.MessageBoxW(
        0,
        "AestheticLens 需要 Microsoft Edge WebView2 运行时。\n\n"
        "请下载安装 WebView2 Runtime：\n"
        "https://go.microsoft.com/fwlink/p/?LinkId=2124703\n\n"
        "或从安装目录运行 WebView2 安装程序。",
        "AestheticLens — 缺少 WebView2",
        0x10  # MB_ICONERROR
    )


def _selftest() -> int:
    """无界面自检 — 加载模型跑一次推理, 把结果写到 exe 同级 selftest_result.txt。
    用于打包后验证 GPU/CPU 推理链路 (DLL 是否齐全)。用法: AestheticLens.exe --selftest"""
    import io
    import traceback
    import numpy as np
    from PIL import Image

    if getattr(sys, "frozen", False):
        out_path = Path(sys.executable).parent / "selftest_result.txt"
    else:
        out_path = Path(__file__).parent / "selftest_result.txt"

    lines = []
    try:
        api = Api()
        scorer = api._ensure_scorer()
        providers = scorer._clip_sess.get_providers() if scorer._clip_sess else []
        img = Image.fromarray(np.random.randint(0, 255, (300, 400, 3), dtype=np.uint8))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        r = scorer.score(buf.getvalue())
        gpu = "CUDAExecutionProvider" in providers
        lines.append("SELFTEST: OK")
        lines.append(f"providers={providers}")
        lines.append(f"gpu_active={gpu}")
        lines.append(f"score={r}")
        rc = 0
    except Exception as e:
        lines.append("SELFTEST: FAIL")
        lines.append(f"error={e!r}")
        lines.append(traceback.format_exc())
        rc = 1

    text = "\n".join(lines)
    out_path.write_text(text, encoding="utf-8")
    print(text)
    return rc


def main():
    if "--selftest" in sys.argv:
        sys.exit(_selftest())

    api = Api()

    # 强制 edgechromium，启动前检测 WebView2
    if not _check_webview2():
        log.error("WebView2 Runtime 未安装")
        _show_webview2_missing_dialog()
        sys.exit(1)

    frontend_dir = _resolve_path("frontend")
    index_html = frontend_dir / "index.html"

    if not index_html.exists():
        print(f"错误: 前端文件不存在 {index_html}")
        sys.exit(1)

    # WebView2 黑屏兜底。整窗黑屏(shown 触发但 loaded 不触发)= 渲染进程起不来，常见三因：
    #   --disable-gpu/--disable-gpu-compositing : GPU 合成失败(Intel 核显/老驱动)
    #   --no-sandbox                            : Chromium 沙箱子进程创建被阻止(受限账户/策略)
    #   --disable-features=RendererCodeIntegrity: 安全软件拦截渲染器 DLL 注入
    # 用 setdefault 允许高级用户用真实环境变量覆盖。
    os.environ.setdefault(
        "WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS",
        "--disable-gpu --disable-gpu-compositing --no-sandbox "
        "--disable-features=RendererCodeIntegrity",
    )
    log.info("WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS=%s",
             os.environ.get("WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"))

    log.info("AestheticLens 启动中... frontend=%s", index_html)

    window = webview.create_window(
        title="AestheticLens",
        url=str(index_html),
        js_api=api,
        width=1200,
        height=800,
        min_size=(900, 600),
        frameless=True,        # 无边框 → 自定义标题栏
        transparent=False,
        background_color="#0a0a0f",
    )
    api._window = window

    # 诊断：记录页面事件，定位黑屏卡在"导航未完成"还是"渲染未出来"
    try:
        window.events.shown += lambda: log.info("窗口事件: shown")
        window.events.loaded += lambda: log.info("窗口事件: loaded (DOM 已加载)")
    except Exception as e:
        log.warning("绑定窗口事件失败: %s", e)

    # WebView2 用户数据目录放到可写位置(%LOCALAPPDATA%)。
    # 否则当程序位于只读目录(如网盘下载目录 E:\...)时，WebView2 默认在 exe 同级建
    # 缓存目录失败 → 整页不渲染、纯黑屏。
    storage_path = None
    try:
        base = os.environ.get("LOCALAPPDATA") or tempfile.gettempdir()
        storage_path = str(Path(base) / "AestheticLens" / "webview2")
        Path(storage_path).mkdir(parents=True, exist_ok=True)
        log.info("WebView2 storage_path=%s", storage_path)
    except OSError as e:
        log.warning("创建 storage_path 失败，回退默认: %s", e)
        storage_path = None

    # gui 参数属于 start() 而非 create_window() (pywebview 5.x)
    # 强制 edgechromium (WebView2)，不回退到 mshtml
    log.info("调用 webview.start ...")
    webview.start(
        gui="edgechromium",
        debug=("--debug" in sys.argv),
        storage_path=storage_path,
        private_mode=False,
    )
    log.info("webview.start 返回(窗口已关闭)")


def _run_with_crashlog():
    """顶层异常兜底 — 把 traceback 写到 exe 同级 crash.log。
    --noconsole 模式下 stderr 被吞, 没有这个用户只会看到 PyInstaller 的
    'Unhandled exception in script' 框, 拿不到任何错误信息。"""
    try:
        main()
    except SystemExit:
        raise
    except BaseException:
        import traceback
        tb = traceback.format_exc()
        if getattr(sys, "frozen", False):
            log_path = Path(sys.executable).parent / "crash.log"
        else:
            log_path = Path(__file__).parent / "crash.log"
        try:
            log_path.write_text(tb, encoding="utf-8")
        except OSError:
            pass
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(
                0, f"AestheticLens 启动失败:\n\n{tb[-1500:]}",
                "AestheticLens — 启动错误", 0x10
            )
        except Exception:
            pass
        raise


if __name__ == "__main__":
    _run_with_crashlog()
