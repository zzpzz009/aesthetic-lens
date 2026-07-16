#!/usr/bin/env python3
"""
export_mlp_multi.py — 导出多个版本的MLP ONNX加密文件

在Windows Python环境下运行（需要torch）:
  python export_mlp_multi.py
"""
import os
import sys
from pathlib import Path

# 添加项目根目录到 path
PROJECT = Path(__file__).parent
sys.path.insert(0, str(PROJECT))

import numpy as np
import torch
import torch.nn as nn

from backend.model_crypto import encrypt_file


class AestheticMLP(nn.Module):
    def __init__(self):
        super().__init__()
        self.layers = nn.Sequential(
            nn.Linear(768, 1024),
            nn.Dropout(0.2),
            nn.Linear(1024, 128),
            nn.Dropout(0.2),
            nn.Linear(128, 64),
            nn.Dropout(0.1),
            nn.Linear(64, 16),
            nn.Linear(16, 1),
        )

    def forward(self, x):
        return self.layers(x)


def load_mlp_weights(mlp, weight_path):
    state = torch.load(weight_path, map_location="cpu", weights_only=True)
    if isinstance(state, dict):
        for candidate in ("state_dict", "model", "module"):
            if candidate in state and isinstance(state[candidate], dict):
                state = state[candidate]
                break
        remapped = {}
        for k, v in state.items():
            new_key = k if k.startswith("layers.") else f"layers.{k}"
            remapped[new_key] = v
        mlp.load_state_dict(remapped, strict=True)


# 模型版本配置
MODELS = {
    "v4.2": {
        "weight": r"G:\Agent\arch-ai-platform\image-library\aesthetic-scorer\finetuned\mlp_best_v4.2.pth",
        "desc": "V4.2 — MSE回归 · MAE=0.941 · r=0.873",
    },
    "v4.3": {
        "weight": r"G:\Agent\arch-ai-platform\image-library\aesthetic-scorer\finetuned\mlp_best_v4.3.pth",
        "desc": "V4.3 — 最新版 · 数据增强优化",
    },
    "v4.530": {
        "weight": r"G:\Agent\arch-ai-platform\image-library\aesthetic-scorer\finetuned\mlp_best_v4.530.pth",
        "desc": "V4.530 — 全量评分V4.530",
    },
}

MODELS_DIR = PROJECT / "models"


def main():
    MODELS_DIR.mkdir(parents=True, exist_ok=True)

    for version, cfg in MODELS.items():
        weight_path = cfg["weight"]
        desc = cfg["desc"]

        if not os.path.isfile(weight_path):
            print(f"  SKIP {version}: 权重不存在 {weight_path}")
            continue

        onnx_name = f"mlp_head_{version}.onnx"
        enc_name = f"mlp_head_{version}.onnx.enc"
        onnx_path = str(MODELS_DIR / onnx_name)
        enc_path = str(MODELS_DIR / enc_name)

        # 如果加密文件已存在且比权重新，跳过
        if os.path.isfile(enc_path) and os.path.getmtime(enc_path) > os.path.getmtime(weight_path):
            existing_size = os.path.getsize(enc_path) / 1024
            print(f"  SKIP {version}: 已存在 {enc_name} ({existing_size:.0f} KB)")
            continue

        print(f"\n[{version}] {desc}")

        # 加载权重
        mlp = AestheticMLP()
        load_mlp_weights(mlp, weight_path)
        mlp.eval()

        # 导出ONNX
        dummy = torch.randn(1, 768)
        torch.onnx.export(
            mlp, dummy, onnx_path,
            input_names=["image_features"],
            output_names=["score"],
            dynamic_axes={"image_features": {0: "batch"}},
            opset_version=17,
        )
        onnx_size = os.path.getsize(onnx_path) / 1024
        print(f"  ONNX: {onnx_path} ({onnx_size:.0f} KB)")

        # 加密
        encrypt_file(onnx_path, enc_path)
        enc_size = os.path.getsize(enc_path) / 1024
        print(f"  ENC:  {enc_path} ({enc_size:.0f} KB)")

        # 删除明文
        os.remove(onnx_path)

        print(f"  OK: {version} 导出完成")

    # 保留旧的 mlp_head.onnx.enc 作为默认（向后兼容）
    default_enc = MODELS_DIR / "mlp_head.onnx.enc"
    if not default_enc.exists():
        # 复制v4.3作为默认
        import shutil
        src = MODELS_DIR / "mlp_head_v4.3.onnx.enc"
        if src.exists():
            shutil.copy2(str(src), str(default_enc))
            print(f"\n默认模型: mlp_head.onnx.enc <- v4.3")

    print("\n全部完成!")


if __name__ == "__main__":
    main()
