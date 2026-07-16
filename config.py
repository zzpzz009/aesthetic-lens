"""
config.py — 部署环境配置加载器

从项目根目录的 .env 文件读取 KEY=VALUE 形式的配置，仅在变量未设置时
填充默认值（os.environ.setdefault 语义），绝不覆盖已有环境变量。

对功能零侵入：
  - 现有代码继续通过 os.environ.get(...) 读取，无需改动
  - 部署时只需在 app.py 顶部加一行  import config
  - 缺少 .env 时静默跳过，不影响开发环境运行

支持行内注释（# 开头）和引号包裹的值。
"""
import os
from pathlib import Path


def _load_env_file(env_path: Path) -> int:
    """读取 .env 文件，返回成功加载的条目数。"""
    if not env_path.is_file():
        return 0
    loaded = 0
    try:
        for raw in env_path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            if not key:
                continue
            value = value.strip().strip('"').strip("'")
            # 仅填充未定义的变量；已有环境变量（系统 export / 命令行）优先级最高
            if key not in os.environ:
                os.environ[key] = value
                loaded += 1
    except OSError:
        pass
    return loaded


# 加载项目根 .env
_ROOT = Path(__file__).parent
_load_env_file(_ROOT / ".env")

# --- AestheticLens 默认值（仅在未设置时生效） ---
os.environ.setdefault("AESTHETICLENS_LOG_LEVEL", "INFO")
os.environ.setdefault(
    "WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS",
    "--disable-gpu --disable-gpu-compositing --no-sandbox "
    "--disable-features=RendererCodeIntegrity",
)
os.environ.setdefault("ORT_LOG_LEVEL", "3")
