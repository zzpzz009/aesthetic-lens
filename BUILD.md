# AestheticLens 打包指南（GPU onedir 版）

> 本文记录经验证可用的打包流程，供后续复用。最后验证：2026-06-18。

## 1. 目标与决策

| 项 | 选择 | 原因 |
|----|------|------|
| 交付形态 | **onedir 文件夹**（`dist/AestheticLens/`） | `--onefile` 每次启动要把全部内容解压到 `%TEMP%`（慢、占空间、易被杀软误杀），不可取 |
| 目标系统 | **Win10+** | WebView2、Python 3.10 都要求 Win10+ |
| 推理后端 | **CPU 版（默认）** | 纯 CPU `onnxruntime`，约 1.3GB，任何机器可跑、无需 NVIDIA 显卡。单图约 1 秒，够用 |

**两种构建**（当前默认 CPU 版）：

| 版本 | 环境 | 体积 | 适用 |
|------|------|------|------|
| **CPU 版（默认）** | `venv-cpu` | ~1.3GB | 任何机器，无需显卡 |
| GPU 版（可选） | `venv-gpu` | ~4.5GB | 有 NVIDIA 卡时加速；自动退 CPU |

> GPU/CPU 自适应逻辑在 `backend/scorer.py` 的 `_get_providers` / `check_gpu_available`，无需改代码：CPU 环境下 `get_available_providers()` 只返回 CPU，自动用 CPU。
>
> 若将来必须支持 Win7：需 Python 3.8 + CEF 渲染引擎 + 老版 onnxruntime，属另一条技术线，本文不涉及。

## 2. 前置条件（重要）

**用专门的虚拟环境打包，不要用系统 Python310**（系统 Python 里 CPU 版和 GPU 版 onnxruntime 同时装着、会冲突）。

### CPU 版环境 `venv-cpu`（默认）
关键：onnxruntime 必须是**纯 CPU 版**（包名 `onnxruntime`，不是 `onnxruntime-gpu`）。一次性搭建：
```powershell
python -m venv venv-cpu
venv-cpu\Scripts\python.exe -m pip install onnxruntime==1.19.2 pywebview==5.4 Pillow numpy cryptography pyinstaller pythonnet
```
确认是纯 CPU（providers 里**不应有** CUDA）：
```powershell
venv-cpu\Scripts\python.exe -c "import onnxruntime as o; print(o.get_available_providers())"
# 期望: ['AzureExecutionProvider', 'CPUExecutionProvider']
```

### GPU 版环境 `venv-gpu`（可选）
只有 `venv-gpu` 的 site-packages 里有 `nvidia/`（cudnn / cublas / cuda_nvrtc）。用没有 nvidia 的环境打 GPU 版会**静默跳过 GPU DLL**，产出残缺版。

## 3. 打包

```powershell
# CPU 版（默认）
venv-cpu\Scripts\python.exe build.py

# GPU 版（可选）
venv-gpu\Scripts\python.exe build.py
```

`build.py` 流程：
1. 清理 `build/`、`dist/`
2. PyInstaller `--onedir --noconsole` 打包 `app.py`
3. 复制 GPU DLL —— **检测不到 `nvidia/` 会自动跳过**（CPU 版即走这条，无需改参数）；GPU 版则整目录复制 `nvidia/{cudnn,cublas,cuda_nvrtc}/bin/*.dll`
4. 复制 `models/*.onnx.enc` 到 `dist/AestheticLens/models/`

## 4. 产物结构

```
dist/AestheticLens/
├── AestheticLens.exe          # 单文件 onefile：Python+依赖+前端+所有 DLL 全在 exe 内 (~41MB)
├── models/                    # 外置加密模型（1.2GB CLIP + 4 个 mlp 头），可单独替换
└── nvidia/                    # 仅 GPU 版：外置 CUDA DLL，rthook 从 exe 同级加载
```
**为什么是 onefile + 外置模型(而非 onedir)**：onedir 的 `_internal/` 是 1000+ 个小 DLL 的文件夹，
用网盘/U盘传极易丢文件，目标机随之报 **"Failed to start embedded python interpreter!"**(引导器缺一个 DLL)。
改成单 exe 后，代码部分是**一个文件**，传输不会缺件；模型外置便于单独更新。exe 同级必须有 `models/`，
两者要一起分发。CPU 版总约 1.2GB。

## 5. 验证（每次打包后必做）

```powershell
# ① GPU 推理自检（无界面）
dist\AestheticLens\AestheticLens.exe --selftest
type dist\AestheticLens\selftest_result.txt
#   期望：SELFTEST: OK  /  gpu_active=True  /  score=...

# ② GUI 启动（双击 exe，应出现 AestheticLens 窗口，无报错框）
```

## 6. 避坑清单（历史上反复失败的 4 个根因）

打包这个项目踩过的坑，复用时逐条核对：

1. **cuDNN 9 是拆分式 DLL，必须整目录复制。**
   `cudnn64_9.dll` 只是 265KB 调度器，运行时按需加载同目录的 `cudnn_cnn` / `cudnn_graph` / `cudnn_engines_*` 等共 10 个子库。只复制个别 DLL → GPU provider 能初始化，但**首次卷积推理崩溃**（CLIP patch embedding 用卷积），表现为"打开后一操作就闪退"。
   → `build.py` 已用 `NVIDIA_PACKAGES` 整目录复制，勿改回硬编码清单。

2. **WebView2 检测别用 DLL 路径探测。**
   旧做法找固定路径的 `WebView2Loader.dll`，装了也判未装，弹"缺少 WebView2"框拦住启动。
   → 改用注册表：`HKLM\SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}` 的 `pv` 值（EdgeUpdate 是 32 位组件，64 位系统在 `WOW6432Node` 下，必须显式查该路径）。见 `app.py` 的 `_check_webview2()`。

3. **pywebview 5.x 的 `gui` 参数属于 `start()` 不是 `create_window()`。**
   传给 `create_window()` 会 `TypeError: create_window() got an unexpected keyword argument 'gui'`，frozen 启动必崩。
   → `webview.start(gui="edgechromium", ...)`。见 `app.py` 的 `main()`。

4. **`--noconsole` 会吞掉所有 stderr。**
   出错时用户只看到 PyInstaller 的 "Unhandled exception in script" 框，拿不到任何信息。
   → `app.py` 入口用 `_run_with_crashlog()` 兜底：异常写入 exe 同级 `crash.log` 并弹框显示。

## 7. 故障排查

诊断文件（都在 exe 同级目录）：
- `app.log` —— 每次启动写一份运行日志（含前端路径、WebView2 参数、API 调用错误）。
- `crash.log` —— 仅在启动抛未处理异常时生成（含 traceback）。
- `selftest_result.txt` —— `--selftest` 的输出。

常见问题：

- **窗口全黑、UI 不渲染** → WebView2 没渲染出页面。靠 `app.log` 里的事件日志判断卡在哪一步：
  - 有 `shown` 但**没有 `loaded`** → 页面导航/初始化失败（多半是 WebView2 用户数据目录建不出来）。`app.py` 已把 storage_path 指到 `%LOCALAPPDATA%\AestheticLens\webview2`（可写），避免程序位于**只读目录（如网盘下载目录 `E:\BaiduNetdiskDownload\...`）**时默认在 exe 同级建缓存失败导致纯黑。若仍黑，让用户把程序复制到 `C:\` 下可写目录（如桌面）再试。
  - 有 `loaded` 但仍黑 → 渲染/合成问题（GPU）。`app.py` 已默认设 `WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS=--disable-gpu --disable-gpu-compositing` 强制软件渲染。仍不行可让用户设系统环境变量加 `--in-process-gpu` 再试。
  - 注意：黑屏通常**不**产生 crash.log（窗口开了只是没渲染），全靠 app.log 诊断。
  - 终极方案：若某机器 WebView2 怎么都不渲染，需改用自带 Chromium 的 CEF 引擎（cefpython3），但它只支持 Python ≤3.9，要降 Python 版本，属另一条技术线。
- **打开报错** → 看 exe 同级 `crash.log` 的 traceback。
- **GPU 没生效（gpu_active=False）** → 先 `--selftest` 看 providers；若只有 CPU，检查 `_internal/nvidia/cudnn/bin` 是否有 10 个 DLL、目标机是否装了 NVIDIA 驱动。
- **想看实时日志** → 临时把 `build.py` 的 `--noconsole` 去掉重打，用控制台版定位。
- **快速调试 GUI 启动问题** → 只跑裸 PyInstaller（不复制 models/nvidia，因为 webview 启动在加载模型之前），几十秒出包，看 crash.log：
  ```powershell
  venv-gpu\Scripts\python.exe -m PyInstaller --name=AestheticLens --noconfirm --noconsole --onedir ^
    --add-data="frontend;frontend" --runtime-hook=rthook_ort.py ^
    --hidden-import=backend.scorer --hidden-import=onnxruntime --hidden-import=PIL ^
    --hidden-import=numpy --hidden-import=cryptography app.py
  ```

## 8. 分发

- 直接把 `dist/AestheticLens/` 整个文件夹打成 zip 发给用户（模型已加密，压缩率不高，zip 后约 4GB）。
- 或用 Inno Setup 编译 `installer.iss` → 单个 `Setup.exe` 安装包。
- 用户机器需有 Edge WebView2 运行时（Win10 2004+ / Win11 基本自带；缺失时 app 会弹提示引导安装）——这是 GPU 版唯一无法绕开的外部依赖。
