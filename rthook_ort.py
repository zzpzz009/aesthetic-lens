"""
PyInstaller runtime hook for onnxruntime DLL loading.
This runs BEFORE any user code, ensuring DLL paths are set up early enough.
"""
import os
import sys
from pathlib import Path

if getattr(sys, 'frozen', False):
    _base = Path(sys._MEIPASS)
    _extra = [
        str(_base),
        str(_base / "onnxruntime" / "capi"),
        str(_base / "numpy.libs"),
    ]
    existing = os.environ.get("PATH", "")
    new_paths = ";".join(d for d in _extra if Path(d).is_dir())
    os.environ["PATH"] = new_paths + ";" + existing
    for d in _extra:
        if Path(d).is_dir():
            try:
                os.add_dll_directory(d)
            except OSError:
                pass
