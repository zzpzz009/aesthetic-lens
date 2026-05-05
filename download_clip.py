"""Download CLIP ViT-L-14 model using hf-mirror on Windows."""
import os
os.environ['HF_ENDPOINT'] = 'https://hf-mirror.com'
os.environ['HF_HOME'] = r'C:\Users\Admin\.cache\huggingface'

import open_clip
print("Downloading CLIP ViT-L-14 via hf-mirror...")
model, _, _ = open_clip.create_model_and_transforms('ViT-L-14', pretrained='laion2b_s32b_b82k')
print("SUCCESS: Model downloaded and loaded!")
print(f"Visual type: {type(model.visual)}")

# Save state dict for later use
import torch
save_path = r'G:\Agent\aesthetic-lens\models\clip_vitl14_laion2b.pth'
os.makedirs(os.path.dirname(save_path), exist_ok=True)
torch.save({
    'visual_state': model.visual.state_dict(),
    'model_state': model.state_dict(),
}, save_path)
print(f"Saved to: {save_path}")
