"""
PyInstaller runtime hook for onnxruntime DLL loading.
This runs BEFORE any user code, ensuring DLL paths are set up early enough.
"""
import os
import sys
from pathlib import Path

if getattr(sys, 'frozen', False):
    _meipass = Path(sys._MEIPASS)
    _exe_dir = Path(sys.executable).parent
    _extra = [
        str(_exe_dir),
        str(_meipass),
        str(_meipass / "onnxruntime" / "capi"),
        str(_meipass / "numpy.libs"),
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
