# AestheticLens v2.0.0

建筑效果图美学评分桌面工具。模型外置分发，双击即用，零配置。

## 功能

| 模式 | 说明 |
|------|------|
| 单图评分 | 拖入建筑效果图，获得 1-10 美学评分 + 等级判定 |
| 批量模式 | 选择文件夹批量评分，等级色带标识，导出 CSV/JSON |
| 对比模式 | 两张图片 PK，直观比较优劣 |

### 评分等级（卡牌稀有度分色）

| 等级 | 分数 | 稀有度 | 色值 |
|------|------|--------|------|
| 卓越 | 9.0 – 10.0 | Legendary | `#FF8C00` 橙金 |
| 优秀 | 7.0 – 8.9 | Epic | `#A335EE` 紫 |
| 良好 | 5.0 – 6.9 | Rare | `#0070DD` 蓝 |
| 一般 | 3.0 – 4.9 | Common | `#9D9D9D` 灰白 |
| 较差 | 1.0 – 2.9 | Corrupted | `#8E2A2A` 暗红 |

## 技术架构

```
┌─────────────────────────────────────────┐
│  frontend (HTML/CSS/JS)                 │
│  pywebview 窗口 ← JS Bridge API ─→ 后端 │
├─────────────────────────────────────────┤
│  app.py — 主入口 + API 路由             │
│  backend/                               │
│    scorer.py    — ONNX Runtime 推理引擎  │
│    model_crypto — AES-256 加解密        │
│    export.py    — CSV/JSON 导出         │
├─────────────────────────────────────────┤
│  ONNX Runtime 1.19.2 (纯 CPU)          │
│  CLIP ViT-L-14 → MLP 回归头            │
│  模型 AES-256-CBC 加密存储             │
│  运行时内存解密，不落盘                  │
└─────────────────────────────────────────┘
```

### 模型

- **特征提取**: CLIP ViT-L-14 (open_clip, LAION-2B 预训练)
- **评分头**: 微调 MLP 回归 (572 张多人评分平均，V3 模型 MAE=0.86)
- **推理**: ONNX Runtime, CPUExecutionProvider
- **模型文件**:
  - `clip_visual.onnx.enc` — 1160 MB (加密)
  - `mlp_head.onnx.enc` — 3.5 MB (加密)

### 项目结构

```
aesthetic-lens/
├── app.py              # 主入口 (321行)
├── backend/
│   ├── scorer.py       # 推理引擎 (248行)
│   ├── model_crypto.py # AES-256 加解密 (87行)
│   └── export.py       # 导出 (43行)
├── frontend/
│   ├── index.html      # 界面结构
│   ├── style.css       # 样式 (电影画报/暗色调)
│   └── app.js          # 交互逻辑 (384行)
├── models/             # 加密模型 (git 排除)
├── build.py            # PyInstaller --onedir 打包 (GPU, 详见 BUILD.md)
├── rthook_ort.py       # ORT DLL 运行时路径修复
├── model_export.py     # 模型 ONNX 导出 + 加密
└── requirements.txt
```

### 打包

- PyInstaller `--onedir --noconsole`，GPU 自适应（有 N 卡走 CUDA，无卡退 CPU）
- 产出: `dist/AestheticLens/` 文件夹（约 4.5GB，含 exe + `_internal/` + `models/`）
- **完整流程、避坑清单与验证步骤见 [BUILD.md](BUILD.md)**
- 打包必须用 `venv-gpu` 环境（系统 Python 没有 nvidia CUDA 依赖）

## 分发

将整个 `dist/AestheticLens/` 文件夹打成 zip 发给用户，或用 Inno Setup（`installer.iss`）编译为单个 `Setup.exe`。

双击 `AestheticLens.exe` 运行。模型文件更新时只需替换 `models/` 下对应 .enc 文件，无需重新打包 exe。

**系统要求**: Windows 10 21H2+ (自带 WebView2 Runtime)。GPU 加速需 NVIDIA 显卡 + 驱动，否则自动用 CPU。

## 开发

```bash
# 安装依赖
pip install -r requirements.txt

# 导出加密模型 (首次，需要 torch + open_clip)
python model_export.py

# 开发运行
python app.py

# 打包（必须用 venv-gpu，详见 BUILD.md）
venv-gpu\Scripts\python.exe build.py
```

## 运行环境

- Python 3.10+
- onnxruntime 1.19.2 (CPU)
- pywebview 5.4
- Pillow, numpy, cryptography

## CHANGELOG

### v2.0.0 (2026-05-10) — V3 模型 + 模型外置

**模型**
- V3 MLP 评分头：基于 572 张多人评分平均数据（avg_manual）微调
  - 训练：80 epochs, lr=2e-4, batch=64, cosine annealing, early stop patience=15
  - 验证：572 张 476 训练 / 96 验证，8:2 随机划分
  - V2 baseline MAE=1.8148 → V3 best MAE=0.8618 (epoch 42)，提升 52.5%
  - 从 V2 best 权重继续微调（非预训练权重），保护已有学习
- ONNX 导出 + AES-256 加密：PyTorch → ONNX diff=0.000000
  - `mlp_head.onnx.enc` (3.5 MB) — V3 模型
  - `clip_visual.onnx.enc` (1160 MB) — CLIP 不变

**打包重构**
- 模型外置：exe 从 2750MB 降到 69MB
- `build.py` 去掉 `--add-data=models;models`
- `AestheticLens.spec` datas 清空
- `scorer.py` 已有 `_resolve_models_dir()` 优先 exe 同级 models/
- 发行结构：`AestheticLens.exe` + `models/` 目录
- 更新模型只需替换 .enc 文件，不用重新打包

**评分维度设计**（面向未来）
- 当前只有效果图维度，非效果图 → 0 分
- 未来加总图维度时：全量数据补 type 标签 → 全量重训一次 → 之后新维度可继续微调
- 推理时维度通过文本前缀指定（路线 B：一个模型多维度）

### v1.1.0 (2026-05-05) — 打包修复里程碑

**修复**
- 打包 exe 评分失效：本机安装的 onnxruntime-gpu 在无 CUDA 的机器上 DLL 初始化崩溃
- 改用纯 CPU 版 onnxruntime 1.19.2 打包，排除 CUDA/TensorRT provider DLL
- scorer.py 硬编码 CUDAExecutionProvider → 动态检测可用 providers
- PyInstaller runtime hook (rthook_ort.py) 修复 DLL 搜索路径
- build.py 添加 cryptography hidden-import
- 打包模式从 --console 目录分发 → --onefile 单文件分发

**UI**
- 批量模式等级分色改为卡牌稀有度体系（橙金/紫/蓝/灰白/暗红）
- 底部 4px 等级色带 (z-index:4, opacity:1)
- 评分数字白色 + text-shadow 保持可读性

**工程**
- git 独立初始化，排除模型/构建产物/wheels
- build.py 支持从本地 wheels 目录离线安装依赖
- 打包体积 1365MB (目录) / 2750MB (单文件)

### v1.0.0 (2026-05-04) — 首版

- 单图/批量/对比三种评分模式
- CLIP ViT-L-14 + 微调 MLP 模型
- AES-256-CBC 模型加密，内存解密
- pywebview 桌面窗口，电影画报暗色调 UI
- PyInstaller 目录模式打包
