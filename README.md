# AestheticLens — 建筑效果图美学评分工具

双击 `AestheticLens.exe` 即可使用。

## 功能

- **单图评分**: 拖入建筑效果图，获得 1-10 美学评分
- **批量模式**: 选择文件夹，批量评分并导出 CSV
- **对比模式**: 两张图片 PK，直观比较优劣

## 模型

- CLIP ViT-L-14 + 微调 MLP (1072 张建筑效果图标注)
- ONNX Runtime 推理，支持 CPU / GPU
- 模型文件加密存储，运行时内存解密

## 开发

```bash
# 安装依赖
pip install -r requirements.txt

# 导出加密模型 (首次)
python model_export.py

# 开发运行
python app.py --debug

# 打包
python build.py
```

## 分发

`dist/AestheticLens/` 文件夹整体分发，用户双击 exe 即可。
