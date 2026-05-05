#!/usr/bin/env python3
"""
reexport_clip_fp32.py — 从 PyTorch 重新导出 CLIP ViT-L-14 为纯 FP32 ONNX
在 Windows 侧运行: python reexport_clip_fp32.py
"""
import os
import sys

# 路径
CLIP_LOCAL_WEIGHT = r"C:\tmp\clip_model\open_clip_pytorch_model.bin"
OUTPUT_DIR = r"G:\Agent\aesthetic-lens\models"
CLIP_ONNX = os.path.join(OUTPUT_DIR, "clip_visual.onnx")
CLIP_ENC = CLIP_ONNX + ".enc"

print("=== Re-export CLIP ViT-L-14 as FP32 ONNX ===\n")

# Step 1: 加载 CLIP
print("[1/3] Loading CLIP model...")
import torch
import open_clip

model, _, _ = open_clip.create_model_and_transforms(
    "ViT-L-14",
    pretrained=CLIP_LOCAL_WEIGHT if os.path.isfile(CLIP_LOCAL_WEIGHT) else "laion2b_s32b_b82k"
)
model.eval()
visual = model.visual
del model

# Step 2: 导出 FP32 ONNX (不做 FP16 转换)
print("[2/3] Exporting FP32 ONNX...")
dummy = torch.randn(1, 3, 224, 224)
torch.onnx.export(
    visual,
    dummy,
    CLIP_ONNX,
    input_names=["pixel_values"],
    output_names=["image_features"],
    dynamic_axes={"pixel_values": {0: "batch"}},
    opset_version=17,
    do_constant_folding=True,
)
size_mb = os.path.getsize(CLIP_ONNX) / 1024 / 1024
print(f"  -> {CLIP_ONNX} ({size_mb:.0f} MB)")

# Step 3: 加密
print("[3/3] Encrypting...")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from backend.model_crypto import encrypt_file

if os.path.exists(CLIP_ENC):
    os.remove(CLIP_ENC)
encrypt_file(CLIP_ONNX, CLIP_ENC)
print(f"  -> {CLIP_ENC} ({os.path.getsize(CLIP_ENC) / 1024 / 1024:.0f} MB)")

# 删除明文 ONNX
os.remove(CLIP_ONNX)

print("\nDone!")
print(f"  clip_visual.onnx.enc ({os.path.getsize(CLIP_ENC) / 1024 / 1024:.0f} MB)")
print(f"  mlp_head.onnx.enc (unchanged)")
