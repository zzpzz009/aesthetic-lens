"""
PyInstaller runtime hook for onnxruntime DLL loading.
Runs BEFORE any user code. Compatible with --onefile and --onedir.
"""
import os
import sys
from pathlib import Path

if getattr(sys, 'frozen', False):
    # --onedir: _MEIPASS = _internal/ 目录
    # --onefile: _MEIPASS = %TEMP%/_MEIxxxxx/ 解压目录
    _meipass = Path(sys._MEIPASS)
    _exe_dir = Path(sys.executable).parent

    _extra = [
        str(_exe_dir),                   # exe 同级目录
        str(_meipass),                   # 打包根目录
        str(_meipass / "onnxruntime" / "capi"),
        str(_meipass / "numpy.libs"),
    ]

    # NVIDIA GPU DLL 目录 — 同时检查 MEIPASS（--onedir）和 exe_dir（--onefile 外部 DLL）
    for base in (_meipass, _exe_dir):
        for pkg in ("nvidia/cudnn/bin", "nvidia/cublas/bin", "nvidia/cuda_nvrtc/bin"):
            d = base / pkg
            if d.exists():
                _extra.append(str(d))

    # 注入 PATH
    existing = os.environ.get("PATH", "")
    new_paths = ";".join(d for d in _extra if Path(d).is_dir())
    if new_paths:
        os.environ["PATH"] = new_paths + ";" + existing

    # Windows 8+ 用 os.add_dll_directory 注册 DLL 搜索路径
    for d in _extra:
        if Path(d).is_dir():
            try:
                os.add_dll_directory(d)
            except (OSError, AttributeError):
                pass
