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

# ---------------------------------------------------------------------------
# API Bridge — 前端 JS 通过 window.pywebview.api.xxx() 调用
# ---------------------------------------------------------------------------
class Api:
    def __init__(self):
        self._scorer = None
        self._window = None

    def _ensure_scorer(self):
        if self._scorer is None:
            self._scorer = AestheticScorer()
        return self._scorer

    # ---- 系统信息 ----
    def get_version(self):
        return {"version": "1.0.0", "name": "AestheticLens"}

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
        models_dir = Path(__file__).parent / "models"
        clip_enc = models_dir / "clip_visual.onnx.enc"
        mlp_enc = models_dir / "mlp_head.onnx.enc"
        return {
            "clip_exists": clip_enc.exists(),
            "mlp_exists": mlp_enc.exists(),
            "clip_size_mb": round(clip_enc.stat().st_size / 1024 / 1024, 1) if clip_enc.exists() else 0,
            "mlp_size_kb": round(mlp_enc.stat().st_size / 1024, 0) if mlp_enc.exists() else 0,
        }

    # ---- 单图评分 ----
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

    # ---- 文件选择对话框 ----
    def open_file_dialog(self):
        """打开文件选择对话框, 返回 base64 编码图片列表"""
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
            with open(path, "rb") as f:
                b64 = base64.b64encode(f.read()).decode()
            ext = path.suffix.lower()
            mime = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png",
                    "webp": "image/webp", "bmp": "image/bmp"}.get(ext.lstrip("."), "image/jpeg")
            images.append({
                "filename": path.name,
                "data": f"data:{mime};base64,{b64}",
            })

        return images

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
                with open(f, "rb") as fh:
                    b64 = base64.b64encode(fh.read()).decode()
                ext = f.suffix.lower()
                mime = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png",
                        "webp": "image/webp", "bmp": "image/bmp"}.get(ext.lstrip("."), "image/jpeg")
                images.append({
                    "filename": f.name,
                    "filepath": str(f),
                    "data": f"data:{mime};base64,{b64}",
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


def main():
    api = Api()

    frontend_dir = _resolve_path("frontend")
    index_html = frontend_dir / "index.html"

    if not index_html.exists():
        print(f"错误: 前端文件不存在 {index_html}")
        sys.exit(1)

    log.info("AestheticLens 启动中...")

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

    # Windows 下居中显示
    webview.start(debug=("--debug" in sys.argv))


if __name__ == "__main__":
    main()
