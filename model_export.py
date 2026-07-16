#!/usr/bin/env python3
"""
model_export.py — 将 PyTorch 模型导出为加密 ONNX 文件

运行一次即可，产出:
  models/clip_visual.onnx.enc   (CLIP ViT-L-14 visual encoder, FP16)
  models/mlp_head.onnx.enc      (AestheticMLP head, FP32)

用法:
  python model_export.py

前置:
  - CLIP 权重: /mnt/c/tmp/clip_model/open_clip_pytorch_model.bin
  - MLP 权重:  arch-ai-platform/image-library/aesthetic-scorer/finetuned/mlp_best_v2.pth
"""

import io
import os
import sys
from pathlib import Path

import numpy as np
import onnx
import torch
import torch.nn as nn

# ---------------------------------------------------------------------------
# 加密工具
# ---------------------------------------------------------------------------
from backend.model_crypto import encrypt_file

# ---------------------------------------------------------------------------
# MLP 架构 (与训练时一致)
# ---------------------------------------------------------------------------
CLIP_MODEL = "ViT-L-14"
CLIP_PRETRAINED = "laion2b_s32b_b82k"
CLIP_LOCAL_WEIGHT = r"C:\tmp\clip_model\open_clip_pytorch_model.bin"
MLP_WEIGHT = r"G:\Agent\arch-ai-platform\image-library\aesthetic-scorer\finetuned\mlp_best_v3.pth"
MODELS_DIR = Path(__file__).parent / "models"


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


def load_mlp_weights(mlp: AestheticMLP, weight_path: str):
    """加载微调权重, 处理 key 前缀映射"""
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
    print(f"  MLP weights loaded from {weight_path}")


def export_mlp_onnx(mlp: AestheticMLP, output_path: str):
    """导出 MLP head 为 ONNX (FP32, 模型小不需要 FP16)"""
    mlp.eval()
    dummy = torch.randn(1, 768)
    torch.onnx.export(
        mlp,
        dummy,
        output_path,
        input_names=["image_features"],
        output_names=["score"],
        dynamic_axes={"image_features": {0: "batch"}},
        opset_version=17,
    )
    print(f"  MLP ONNX exported → {output_path} ({os.path.getsize(output_path)/1024:.0f} KB)")


def export_clip_onnx(visual: nn.Module, output_path: str):
    """导出 CLIP visual encoder 为 ONNX (FP16)"""
    visual.eval()
    dummy = torch.randn(1, 3, 224, 224)

    # 先导出 FP32
    fp32_path = output_path.replace(".onnx", "_fp32.onnx")
    torch.onnx.export(
        visual,
        dummy,
        fp32_path,
        input_names=["pixel_values"],
        output_names=["image_features"],
        dynamic_axes={"pixel_values": {0: "batch"}},
        opset_version=17,
        do_constant_folding=True,
    )
    print(f"  CLIP ONNX FP32 → {fp32_path} ({os.path.getsize(fp32_path)/1024/1024:.0f} MB)")

    # 转换为 FP16
    model_fp32 = onnx.load(fp32_path)
    from onnxconverter_common import float16
    model_fp16 = float16.convert_float_to_float16(model_fp32, keep_io_types=True)
    onnx.save(model_fp16, output_path)
    print(f"  CLIP ONNX FP16 → {output_path} ({os.path.getsize(output_path)/1024/1024:.0f} MB)")

    # 清理临时 FP32
    os.remove(fp32_path)


def verify_consistency(visual, mlp, clip_onnx_path, mlp_onnx_path):
    """验证 ONNX 推理与 PyTorch 推理结果一致"""
    import onnxruntime as ort

    dummy_img = torch.randn(1, 3, 224, 224)

    # PyTorch
    with torch.no_grad():
        pt_feat = visual(dummy_img)
        pt_feat = pt_feat / pt_feat.norm(dim=-1, keepdim=True)
        pt_score = mlp(pt_feat).item()

    # ONNX CLIP
    clip_sess = ort.InferenceSession(clip_onnx_path, providers=["CPUExecutionProvider"])
    onnx_feat = clip_sess.run(
        ["image_features"],
        {"pixel_values": dummy_img.numpy()},
    )[0]
    # L2 normalize
    onnx_feat = onnx_feat / np.linalg.norm(onnx_feat, axis=-1, keepdims=True)

    # ONNX MLP
    mlp_sess = ort.InferenceSession(mlp_onnx_path, providers=["CPUExecutionProvider"])
    onnx_score = mlp_sess.run(
        ["score"],
        {"image_features": onnx_feat.astype(np.float32)},
    )[0][0, 0]

    diff = abs(pt_score - float(onnx_score))
    print(f"\n  验证一致性:")
    print(f"    PyTorch score: {pt_score:.4f}")
    print(f"    ONNX score:    {float(onnx_score):.4f}")
    print(f"    差异:          {diff:.4f}")

    if diff < 0.1:
        print("    ✅ 一致性通过 (差异 < 0.1)")
    else:
        print("    ⚠️  差异较大, 请检查模型导出")
    return diff < 0.1


def main():
    MODELS_DIR.mkdir(parents=True, exist_ok=True)

    # --- Step 1: 导出 MLP ---
    print("\n[1/3] 导出 MLP head...")
    mlp = AestheticMLP()
    load_mlp_weights(mlp, MLP_WEIGHT)
    mlp_onnx = str(MODELS_DIR / "mlp_head.onnx")
    export_mlp_onnx(mlp, mlp_onnx)

    # --- Step 2: 导出 CLIP Visual ---
    print("\n[2/3] 导出 CLIP ViT-L-14 visual encoder...")
    import open_clip

    if os.path.isfile(CLIP_LOCAL_WEIGHT):
        clip_model, _, _ = open_clip.create_model_and_transforms(
            CLIP_MODEL, pretrained=CLIP_LOCAL_WEIGHT
        )
    else:
        clip_model, _, _ = open_clip.create_model_and_transforms(
            CLIP_MODEL, pretrained=CLIP_PRETRAINED
        )
    clip_model.eval()
    visual = clip_model.visual
    del clip_model

    clip_onnx = str(MODELS_DIR / "clip_visual.onnx")
    export_clip_onnx(visual, clip_onnx)

    # --- Step 3: 验证一致性 ---
    print("\n[3/3] 验证 ONNX vs PyTorch 一致性...")
    verify_consistency(visual, mlp, clip_onnx, mlp_onnx)

    # --- Step 4: 加密 ---
    print("\n[4/4] AES 加密...")
    encrypt_file(clip_onnx, clip_onnx + ".enc")
    encrypt_file(mlp_onnx, mlp_onnx + ".enc")

    # 清理明文 ONNX
    os.remove(clip_onnx)
    os.remove(mlp_onnx)
    print(f"\n✅ 完成! 加密模型已保存到 {MODELS_DIR}/")
    print(f"  clip_visual.onnx.enc  ({os.path.getsize(clip_onnx + '.enc')/1024/1024:.0f} MB)")
    print(f"  mlp_head.onnx.enc     ({os.path.getsize(mlp_onnx + '.enc')/1024:.0f} KB)")


if __name__ == "__main__":
    main()
