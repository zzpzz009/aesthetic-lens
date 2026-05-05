# AestheticLens v1.1.0

建筑效果图美学评分桌面工具。单文件 exe，双击即用，零配置。

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
- **评分头**: 微调 MLP 回归 (1072 张建筑效果图人工标注)
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
├── build.py            # PyInstaller --onefile 打包
├── rthook_ort.py       # ORT DLL 运行时路径修复
├── model_export.py     # 模型 ONNX 导出 + 加密
└── requirements.txt
```

### 打包

- PyInstaller `--onefile --noconsole`
- 纯 CPU 版 onnxruntime 1.19.2（排除 CUDA/TensorRT）
- 产出: 单个 `AestheticLens.exe` (~2750 MB)
- 首次启动 ~15-30s（解压模型到临时目录），后续启动有缓存更快

## 分发

复制 `dist/AestheticLens.exe` 到目标电脑，双击运行。

**系统要求**: Windows 10 21H2+ (自带 WebView2 Runtime)

## 开发

```bash
# 安装依赖
pip install -r requirements.txt

# 导出加密模型 (首次，需要 torch + open_clip)
python model_export.py

# 开发运行
python app.py

# 打包
python build.py
```

## 运行环境

- Python 3.10+
- onnxruntime 1.19.2 (CPU)
- pywebview 5.4
- Pillow, numpy, cryptography

## CHANGELOG

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
