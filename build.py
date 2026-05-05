#!/usr/bin/env python3
"""
build.py — AestheticLens PyInstaller 打包脚本

关键点：
  - onnxruntime DLL 必须放在 exe 同级目录（不是 _internal 内）
    因为 PyInstaller 的 sys._MEIPASS DLL 搜索有兼容性问题
  - 模型文件放在 exe 同级 models/ 目录
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.resolve()
DIST = ROOT / "dist" / "AestheticLens"


def clean():
    """清理旧的构建产物"""
    for d in ["build", "dist"]:
        p = ROOT / d
        if p.exists():
            shutil.rmtree(p)
            print(f"  清理 {p}")


def build():
    """PyInstaller 打包（最小化打包，不含 onnxruntime DLL）"""
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--name=AestheticLens",
        "--noconfirm",
        "--noconsole",
        "--windowed",
        # 收集 frontend 目录
        f"--add-data=frontend;frontend",
        # 隐式导入
        "--hidden-import=backend",
        "--hidden-import=backend.scorer",
        "--hidden-import=backend.model_crypto",
        "--hidden-import=backend.export",
        "--hidden-import=onnxruntime",
        "--hidden-import=PIL",
        "--hidden-import=numpy",
        # 排除不需要的大模块
        "--exclude-module=torch",
        "--exclude-module=open_clip",
        "--exclude-module=tensorflow",
        "--exclude-module=matplotlib",
        # 排除 CUDA/TensorRT providers（我们用 CPU）
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


def copy_onnxruntime_dlls():
    """
    手动复制 onnxruntime DLL 到 exe 同级目录
    这是最可靠的方式——绕过 PyInstaller 的 _MEIPASS 加载机制
    """
    import onnxruntime
    ort_capi = Path(onnxruntime.__file__).parent / "capi"

    # 只复制需要的 DLL（排除 CUDA/TensorRT provider）
    needed = [
        "onnxruntime.dll",
        "onnxruntime_pybind11_state.pyd",
    ]

    for name in needed:
        src = ort_capi / name
        if src.exists():
            dst = DIST / name
            shutil.copy2(src, dst)
            size_mb = src.stat().st_size / 1024 / 1024
            print(f"  复制 ORT DLL: {name} ({size_mb:.1f} MB)")
        else:
            print(f"  警告: 未找到 {name}")

    # 也复制 providers_shared（小文件，可能需要）
    shared = ort_capi / "onnxruntime_providers_shared.dll"
    if shared.exists():
        shutil.copy2(shared, DIST / shared.name)
        print(f"  复制 ORT DLL: {shared.name}")


def copy_models():
    """复制加密模型到 dist"""
    models_src = ROOT / "models"
    models_dst = DIST / "models"

    if not models_src.exists():
        print("  models/ 目录不存在, 跳过模型复制")
        return

    models_dst.mkdir(parents=True, exist_ok=True)

    for f in models_src.glob("*.enc"):
        dst_file = models_dst / f.name
        if dst_file.exists() and dst_file.stat().st_size == f.stat().st_size:
            print(f"  跳过(已存在): {f.name}")
            continue
        shutil.copy2(f, dst_file)
        size_mb = f.stat().st_size / 1024 / 1024
        print(f"  复制模型: {f.name} ({size_mb:.1f} MB)")


def copy_readme():
    """复制 README"""
    src = ROOT / "README.md"
    if src.exists():
        shutil.copy2(src, DIST / "README.md")
        print("  复制 README.md")


def cleanup_internal_ort():
    """删除 _internal 中多余的 onnxruntime CUDA/TensorRT DLL"""
    internal_ort = DIST / "_internal" / "onnxruntime" / "capi"
    if not internal_ort.exists():
        return

    removed_size = 0
    for f in list(internal_ort.glob("onnxruntime_providers_*")):
        if "shared" not in f.name:
            size = f.stat().st_size
            f.unlink()
            print(f"  删除多余: {f.name} ({size/1e6:.1f} MB)")
            removed_size += size

    if removed_size > 0:
        print(f"  节省: {removed_size/1e6:.0f} MB")


def main():
    print("=" * 50)
    print("  AestheticLens 构建")
    print("=" * 50)

    print("\n[1/5] 清理旧构建...")
    clean()

    print("\n[2/5] PyInstaller 打包...")
    build()

    print("\n[3/5] 复制 onnxruntime DLLs...")
    copy_onnxruntime_dlls()

    print("\n[4/5] 复制模型文件...")
    copy_models()

    print("\n[5/5] 清理多余文件 + 复制 README...")
    cleanup_internal_ort()
    copy_readme()

    # 统计
    if DIST.exists():
        total_size = sum(f.stat().st_size for f in DIST.rglob("*") if f.is_file())
        print(f"\n{'='*50}")
        print(f"  构建完成!")
        print(f"  产出目录: {DIST}")
        print(f"  总体积: {total_size / 1024 / 1024:.0f} MB")
        print(f"\n  使用方式:")
        print(f"    将 dist/AestheticLens/ 整个文件夹复制到目标电脑")
        print(f"    双击 AestheticLens.exe 即可运行")
        print(f"    需要: Windows 10 21H2+ (自带 WebView2 Runtime)")


if __name__ == "__main__":
    main()
