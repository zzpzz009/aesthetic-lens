#!/usr/bin/env python3
"""
build.py — AestheticLens 单文件打包脚本 (PyInstaller --onefile)

产出: dist/AestheticLens.exe — 单个可执行文件，无外部依赖
代价: 首次启动需 ~15-30s 解压到临时目录（1.1GB 模型）
"""

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.resolve()
DIST = ROOT / "dist"


def clean():
    """清理旧的构建产物"""
    for d in ["build", "dist"]:
        p = ROOT / d
        if p.exists():
            shutil.rmtree(p)
            print(f"  清理 {p}")


def build():
    """PyInstaller --onefile 打包"""
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--name=AestheticLens",
        "--noconfirm",
        "--noconsole",
        "--onefile",
        # 收集 frontend 目录
        "--add-data=frontend;frontend",
        # 收集加密模型
        "--add-data=models;models",
        # runtime hook — DLL 路径修复
        "--runtime-hook=rthook_ort.py",
        # 隐式导入
        "--hidden-import=backend",
        "--hidden-import=backend.scorer",
        "--hidden-import=backend.model_crypto",
        "--hidden-import=backend.export",
        "--hidden-import=onnxruntime",
        "--hidden-import=PIL",
        "--hidden-import=numpy",
        "--hidden-import=cryptography",
        "--hidden-import=cryptography.hazmat.primitives.ciphers",
        "--hidden-import=cryptography.hazmat.primitives.padding",
        "--hidden-import=cryptography.hazmat.backends",
        # 排除不需要的大模块
        "--exclude-module=torch",
        "--exclude-module=open_clip",
        "--exclude-module=tensorflow",
        "--exclude-module=matplotlib",
        # 排除 CUDA/TensorRT providers
        "--exclude-module=onnxruntime_providers_cuda",
        "--exclude-module=onnxruntime_providers_tensorrt",
        # 入口
        "app.py",
    ]

    # icon 如果存在
    icon_path = ROOT / "assets" / "icon.ico"
    if icon_path.exists():
        cmd.insert(-1, f"--icon={icon_path}")

    print("\n  打包命令:")
    print("  " + " ".join(cmd))
    print()

    result = subprocess.run(cmd, cwd=str(ROOT))
    if result.returncode != 0:
        print("\n打包失败")
        sys.exit(1)


def main():
    print("=" * 50)
    print("  AestheticLens 单文件构建")
    print("=" * 50)

    print("\n[1/3] 清理旧构建...")
    clean()

    print("\n[2/3] PyInstaller --onefile 打包（含模型，较慢）...")
    build()

    print("\n[3/3] 统计...")
    exe_path = DIST / "AestheticLens.exe"
    if exe_path.exists():
        size_mb = exe_path.stat().st_size / 1024 / 1024
        print(f"\n{'='*50}")
        print(f"  构建完成!")
        print(f"  产出: {exe_path}")
        print(f"  体积: {size_mb:.0f} MB")
        print(f"\n  使用方式:")
        print(f"    复制 AestheticLens.exe 到目标电脑")
        print(f"    双击即可运行")
        print(f"    首次启动需等待 ~15-30s 解压模型")
        print(f"    需要: Windows 10 21H2+ (自带 WebView2 Runtime)")
    else:
        print("\n  错误: exe 未生成")


if __name__ == "__main__":
    main()
