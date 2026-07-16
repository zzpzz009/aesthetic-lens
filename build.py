#!/usr/bin/env python3
"""
build.py — AestheticLens 打包脚本 (PyInstaller --onefile + 外置模型)

产出: dist/AestheticLens/ 目录结构
  ├── AestheticLens.exe   (单文件，Python+依赖+前端+DLL 全在 exe 内)
  └── models/             (外置评分模型，可单独替换 .enc 不用重打包)
  └── nvidia/             (仅 GPU 版：外置 CUDA DLL，rthook 从 exe 同级加载)

为什么 onefile + 外置模型：onedir 是 1000+ 文件的文件夹，用网盘传极易丢文件，
导致目标机报 "Failed to start embedded python interpreter!"。单 exe 传输不丢，
模型外置则便于单独更新。
"""

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.resolve()
DIST = ROOT / "dist"
OUT_DIR = DIST / "AestheticLens"

# 需要完整复制 bin/ 的 nvidia 子包。
# 重要: 不能只挑个别 DLL —— cuDNN 9 是拆分式架构, cudnn64_9.dll 只是调度器,
# 运行时按需加载同目录下的 cudnn_cnn / cudnn_graph / cudnn_engines_* 等子库。
# 漏掉任意一个, GPU provider 能初始化但首次卷积推理就会崩。
NVIDIA_PACKAGES = ["cudnn", "cublas", "cuda_nvrtc"]


def find_nvidia_root(site_packages: Path) -> Path | None:
    nvidia = site_packages / "nvidia"
    return nvidia if nvidia.is_dir() else None


def copy_gpu_dlls(nvidia_root: Path, internal_dir: Path):
    """复制 GPU DLL 到 _internal/nvidia/ —— 整目录复制每个包的 bin/"""
    dst_nvidia = internal_dir / "nvidia"
    count = 0
    total_mb = 0
    for pkg in NVIDIA_PACKAGES:
        src_bin = nvidia_root / pkg / "bin"
        if not src_bin.is_dir():
            print(f"    警告: 未找到 {pkg}/bin")
            continue
        dst_bin = dst_nvidia / pkg / "bin"
        dst_bin.mkdir(parents=True, exist_ok=True)
        for src in sorted(src_bin.glob("*.dll")):
            shutil.copy2(src, dst_bin / src.name)
            mb = src.stat().st_size / 1024 / 1024
            total_mb += mb
            count += 1
            print(f"    {pkg}/{src.name} ({mb:.0f} MB)")
    print(f"  已复制 {count} 个 GPU DLL, 共 {total_mb:.0f} MB")


def clean():
    for d in ["build", "dist"]:
        p = ROOT / d
        if p.exists():
            shutil.rmtree(p)
            print(f"  清理 {p}")


def build():
    """PyInstaller --onefile 打包(代码+DLL 全在单个 exe 内，模型/GPU DLL 外置)"""
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--name=AestheticLens",
        "--noconfirm",
        "--noconsole",
        "--onefile",
        "--add-data=frontend;frontend",
        "--runtime-hook=rthook_ort.py",
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
        "--exclude-module=torch",
        "--exclude-module=open_clip",
        "--exclude-module=tensorflow",
        "--exclude-module=matplotlib",
    ]

    icon_path = ROOT / "assets" / "icon.ico"
    if icon_path.exists():
        cmd.insert(-1, f"--icon={icon_path}")

    cmd.append("app.py")

    print("\n  打包命令:")
    print("  " + " ".join(cmd))
    print()

    result = subprocess.run(cmd, cwd=str(ROOT), check=False)
    if result.returncode != 0:
        print(f"\n打包失败 (exit code: {result.returncode})")
        sys.exit(1)


def main():
    print("=" * 55)
    print("  AestheticLens 打包构建 (onefile + 外置模型)")
    print("=" * 55)

    site_packages = Path(sys.prefix) / "Lib" / "site-packages"
    if not site_packages.is_dir():
        site_packages = Path(sys.base_prefix) / "Lib" / "site-packages"

    nvidia_root = find_nvidia_root(site_packages)

    print("\n[1/4] 清理旧构建...")
    clean()

    print("\n[2/4] PyInstaller --onefile 打包...")
    build()

    # onefile: PyInstaller 把单个 exe 输出到 dist/AestheticLens.exe。
    # 整理成发布目录 dist/AestheticLens/，exe + 外置 models/(+nvidia/) 同级。
    built_exe = DIST / "AestheticLens.exe"
    if not built_exe.exists():
        print("\n  错误: exe 未生成")
        sys.exit(1)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    exe_path = OUT_DIR / "AestheticLens.exe"
    shutil.move(str(built_exe), str(exe_path))

    print("\n[3/4] 复制 GPU DLL (外置到 exe 同级，rthook 会从此处加载)...")
    if nvidia_root:
        copy_gpu_dlls(nvidia_root, OUT_DIR)
    else:
        print("  未找到 nvidia GPU DLL，跳过（仅 CPU 模式可用）")

    # 复制模型文件(外置到 exe 同级 models/，可随时替换 .enc 无需重打包)
    src_models = ROOT / "models"
    dst_models = OUT_DIR / "models"
    if src_models.is_dir() and any(src_models.iterdir()):
        dst_models.mkdir(parents=True, exist_ok=True)
        print("\n[3.5/4] 复制模型文件...")
        model_mb = 0
        for f in src_models.glob("*.onnx.enc"):
            shutil.copy2(f, dst_models / f.name)
            mb = f.stat().st_size / 1024 / 1024
            model_mb += mb
            print(f"    {f.name} ({mb:.0f} MB)")
        print(f"  已复制模型文件, 共 {model_mb:.0f} MB")
    else:
        print("\n[3.5/4] 警告: 未找到模型文件，请手动复制 models/ 到 dist/AestheticLens/")

    print("\n[4/4] 统计...")
    exe_mb = exe_path.stat().st_size / 1024 / 1024
    total_mb = sum(f.stat().st_size for f in OUT_DIR.rglob("*") if f.is_file()) / 1024 / 1024

    print(f"\n{'='*55}")
    print(f"  构建完成!")
    print(f"  产出: {OUT_DIR}")
    print(f"    AestheticLens.exe ({exe_mb:.0f} MB, 单文件，代码+DLL 全在内)")
    print(f"    models/  (外置模型，可单独替换)")
    print(f"  总: {total_mb:.0f} MB")
    print(f"\n  分发: 把整个 AestheticLens/ 文件夹打 zip(就 exe+models 几个文件)")
    print("=" * 55)


if __name__ == "__main__":
    main()
