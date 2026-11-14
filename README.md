# ScreenToAgent

**在屏幕上圈出问题、写下问题，交给本地 Codex CLI 或 OpenAI 兼容 API 回答。**

[简体中文](README.md) | [English](README.en.md)

ScreenToAgent 是一个 Windows 桌面工具：按住全局热键框选屏幕区域，直接在截图上标注文字问题，把“标注后的截图 + 问题”发送给本地 Codex CLI 或其他命令行 Agent，也可以转发给配置好的 OpenAI 兼容 API。回答完成后在右下角通知；轻点热键打开全屏半透明会话界面阅读历史与最新回答。

当前版本：`0.10.0`　平台：Windows 10/11 x64　界面：PySide6（Qt 6）

```text
按住 F1（约 250ms） → 框选区域 → 标注问题 → Ctrl+Enter 发送
                                              ↓
                                  Codex CLI / OpenAI 兼容 API
                                              ↓
                       回答完成通知（会话隐藏时） → 轻点 F1 查看会话
```

## 功能特性

- **截图提问**：按住热键进入框选，标注文字会烧录进发送的图像，同时作为本次问题文本。
- **草稿保持**：截图/标注中再按热键、按退出快捷键或取消，会保留问题草稿，下次框选自动回填。
- **会话界面**：全屏半透明，展示历史消息、图片缩略图与流式回答；底部输入栏可继续追问。
- **会话管理**：Codex CLI 模式下默认续接最近会话；`/new` 新建，`/resume` 切换，历史只读解析 CLI 会话文件。
- **模型切换**：顶部模型选择器；CLI 模式读取 Codex 模型目录并传 `-m`，API 模式使用配置的模型列表。
- **流式输出**：CLI 使用 `--json` 事件流，API 使用 SSE；同一条 Agent 消息增量更新，完成时校正为最终文本。
- **图文历史**：历史图片以缩略图展示，可点击预览；图片来自附件缓存或 CLI 历史路径，缺失时显示占位。
- **显示调节**：会话正文字号 9–24pt、图片宽度 160–1200px 可调；角色标签固定比正文大 2pt。
- **通知策略**：发送后不显示“正在生成”；仅当会话界面隐藏时，回答完成才弹右下角通知。
- **可配置**：截图热键、附件存储根目录、截图/会话的发送与退出快捷键、字号、图片宽度均可在设置页调整。
- **隐私边界**：不建立本地问答数据库，不写入或改名 Codex CLI 会话文件，日志不记录问题、回答或图片内容。

## 系统要求

| 项目 | 要求 |
| --- | --- |
| 操作系统 | Windows 10 / 11 x64 |
| Python | 3.11 及以上（源码运行） |
| 依赖管理 | [uv](https://docs.astral.sh/uv/)（推荐）或 pip |
| Codex CLI | CLI 模式必需；安装并登录，确保 `codex` 在 `PATH` 中 |
| API Key | API 模式必需；通过环境变量提供，不写入配置文件 |

> 应用仅支持 Windows：全局热键、截图与键盘回退监听依赖 Win32 API。

## 快速开始

### 使用 uv（推荐）

```bash
cd ScreenToAgent
uv sync --extra dev
uv run python -m screen_to_agent
```

也可以使用入口脚本：

```bash
uv run python main.py
```

首次启动会生成默认配置、注册热键并在系统托盘显示图标。若热键被其他程序占用，应用会提示并允许在设置中更换。

### 使用 pip

```bash
cd ScreenToAgent
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
python -m screen_to_agent
```

### 打包为单文件 exe

仅在发布或交付时需要打包，日常开发直接运行源码即可。请先安装开发依赖，并在已激活项目虚拟环境的终端中执行：

```bat
build.bat
```

产物为 `dist\ScreenToAgent.exe`，目标机无需安装 Python 或 PySide6。Codex CLI 不会被打包进 exe，仍需单独安装或配置 `codex.executable`。

## 使用方式

### 截图提问

1. **按住**截图热键约 250ms，屏幕冻结并进入框选。
2. 拖拽选择区域，在标注框中输入问题；文字会写入图像并作为本次问题发送。
3. 按 `Ctrl+Enter`（默认）发送；按 `Esc` 或再次按热键退出，问题草稿会保留。
4. 回答完成后，仅在会话界面隐藏时收到右下角通知。

轻点热键（不按住）用于打开或隐藏会话界面：没有会话时会打开空会话。

### 会话界面

- 轻点热键打开/隐藏；`Esc` 只关闭输入焦点，不隐藏会话。
- 滚轮、`PageUp` / `PageDown` 或滚动条浏览历史。
- 底部输入栏发送文字问题；`Enter` 发送，`Shift+Enter` 换行（可在设置中修改）。
- 顶部可切换模型；流式生成期间选择器与会话切换命令暂时禁用。
- 输入 `/` 开头的命令：

| 命令 | 作用 |
| --- | --- |
| `/new` | 切换到新会话；下一条 CLI 消息创建新 Codex 会话 |
| `/resume [id\|名称]` | 切换到指定 CLI 会话；不带参数时打开会话选择器 |
| `/rename [名称]` | 当前 Codex CLI 未提供重命名命令，应用明确提示不支持 |
| `/help` | 查看命令帮助 |

> API 模式为单轮请求，不保留历史；`/resume` 和 `/rename` 在该模式下不可用。

### 设置

托盘菜单 →「设置…」：

| 分组 | 可配置项 |
| --- | --- |
| 截图快捷键 | `F1`–`F12`，可叠加 `Ctrl` / `Alt` / `Shift` / `Win`；保存前探测冲突 |
| 附件存储位置 | 自定义根目录；实际附件位于 `<根目录>\attachments`，不自动迁移旧附件 |
| 输入快捷键 | 截图发送/退出、会话发送/退出；同场景冲突、与截图热键冲突、`Shift+Enter` 发送会被阻止 |
| 会话显示 | 正文字号 9–24pt；历史图片宽度 160–1200px；带字号预览 |

## 后端

### Codex CLI（默认）

- 应用不管理会话：上下文、历史与续接都由 Codex CLI 负责。
- 默认沿用最近一次 Codex 会话；只有执行 `/new` 后的下一条请求才创建新会话。
- 会话列表与历史只读解析 `~/.codex/sessions/` 下的 rollout 文件，不写入、不改名、不删除。
- 模型来自 `codex debug models --bundled`，请求时通过 `-m` 传递，不修改全局 CLI 配置。
- 流式更新由 CLI 的 JSONL 事件驱动，实际粒度取决于 Codex CLI。

### OpenAI 兼容 API（单轮）

在 `config.json` 中把 `default_backend` 改为非 `codex-cli` 的值（例如 `openai-compatible`），并配置：

```json
{
  "default_backend": "openai-compatible",
  "api": {
    "base_url": "https://your-api-host/v1",
    "model": "your-model",
    "api_key_env": "SCREEN_TO_AGENT_API_KEY",
    "timeout_seconds": 120,
    "models": ["your-model"]
  }
}
```

然后设置环境变量（PowerShell）：

```powershell
$env:SCREEN_TO_AGENT_API_KEY = "your-api-key"
```

- 请求地址为 `<base_url>/chat/completions`，优先使用 SSE 流式，服务端不支持时回退普通响应。
- API 模式不携带任何历史上下文，每次提问都是独立请求；`/new` 仅清空当前界面消息。
- API Key 目前只从环境变量读取，不会写入配置文件或日志。

## 配置

默认配置文件：`%APPDATA%\ScreenToAgent\config.json`（首次启动自动创建）。

```json
{
  "hotkey": "F1",
  "default_backend": "codex-cli",
  "answer_overlay": {
    "opacity": 0.72
  },
  "storage": {
    "root": ""
  },
  "conversation": {
    "font_size": 13,
    "image_width": 360
  },
  "input_shortcuts": {
    "screenshot": {
      "send": "Ctrl+Return",
      "exit": "Esc"
    },
    "conversation": {
      "send": "Return",
      "exit": "Esc"
    }
  },
  "codex": {
    "executable": "codex",
    "sandbox": "read-only",
    "resume": true,
    "model": ""
  },
  "api": {
    "base_url": "",
    "model": "",
    "api_key_env": "SCREEN_TO_AGENT_API_KEY",
    "timeout_seconds": 120,
    "models": []
  }
}
```

| 字段 | 说明 |
| --- | --- |
| `hotkey` | 全局截图/会话热键；默认 `F1` |
| `default_backend` | `codex-cli` 使用 Codex CLI；其他值走 OpenAI 兼容 API |
| `answer_overlay.opacity` | 会话界面不透明度，限制在 0.5–0.9 |
| `storage.root` | 附件根目录；为空时使用 `%APPDATA%\ScreenToAgent` |
| `conversation.font_size` | 会话正文字号，9–24pt，默认 13 |
| `conversation.image_width` | 历史图片缩略图宽度，160–1200px，默认 360 |
| `input_shortcuts.*` | 截图/会话的发送与退出快捷键 |
| `codex.executable` | Codex CLI 可执行文件或命令名 |
| `codex.sandbox` | Codex CLI 沙箱级别，默认 `read-only` |
| `codex.resume` | 是否默认续接最近会话 |
| `codex.model` | Codex CLI 模型；为空时使用 CLI 默认值 |
| `api.*` | OpenAI 兼容 API 的地址、模型、密钥环境变量与超时 |

相关环境变量：

| 变量 | 用途 |
| --- | --- |
| `SCREEN_TO_AGENT_API_KEY` | API 模式密钥；变量名可由 `api.api_key_env` 覆盖 |
| `SCREEN_TO_AGENT_ATTACHMENTS` | 默认存储根目录下附件目录的覆盖路径 |
| `SCREEN_TO_AGENT_CONFIG` | 指定其他配置文件路径，便于开发与测试 |

## 数据与隐私

- 附件按 SHA-256 内容寻址保存：默认 `%APPDATA%\ScreenToAgent\attachments`，自定义根目录时为 `<root>\attachments`。
- 切换存储位置不迁移旧附件；旧历史仍按原绝对路径展示，缺失时显示“图片不可用”。
- 应用不建立本地会话/问答数据库；Codex CLI 的会话文件只读解析。
- 启动时清理当前附件目录中超过 30 天的文件；只遍历该目录，不递归删除子目录。
- 日志默认位于 `%APPDATA%\ScreenToAgent\logs\app.log`，不记录问题正文、标注文字、回答内容、图片内容或密钥。
- API Key 只通过环境变量读取；请勿把 `.env`、密钥或个人截图提交到版本库。

## 项目结构

```text
ScreenToAgent/
├── screen_to_agent/
│   ├── app.py                    # 应用控制器、热键路由、托盘与应用编排
│   ├── config.py                 # 配置模型、默认值与读写
│   ├── domain/                   # 领域模型（消息、截图、会话、结果）
│   ├── application/              # 交互状态机、问题提示词
│   ├── infrastructure/           # Codex/API 后端、会话读取、热键、截屏、附件
│   └── presentation/             # 截图标注、会话界面、设置页、会话选择器
├── tests/                        # pytest 测试（Qt offscreen）
├── docs/                         # 架构设计 + 按需求编号组织的需求文档
├── assets/                       # 应用图标
├── main.py                       # 本地开发入口
├── build.bat                     # PyInstaller 单文件 exe 构建
├── pyproject.toml
└── AGENTS.md                     # 协作流程、编码规范与交互不变量
```

## 开发与测试

```bash
# 安装开发依赖
uv sync --extra dev

# 运行全部测试（使用 offscreen Qt）
uv run pytest

# 代码检查与格式检查
uv run ruff check .
uv run ruff format --check .
```

本项目采用规格驱动开发：功能先写入 `docs/YYYY-MM-DD-<需求名称>/requirements.md`，需求状态按“草稿 → 已确认 → 实现中 → 已完成”流转。架构与模块边界见 [docs/architecture.md](docs/architecture.md)，协作规则见 [AGENTS.md](AGENTS.md)。

## 文档

| 文档 | 内容 |
| --- | --- |
| [架构设计](docs/architecture.md) | 分层、模块、线程模型、配置、安全与测试策略 |
| [REQ-001 截图提问转发 Agent](docs/2026-11-14-截图提问转发Agent/requirements.md) | 截图、标注、通知、回答层基础需求 |
| [REQ-002 会话式回答界面](docs/2026-11-14-会话式回答界面/requirements.md) | 历史、输入栏、隐藏/恢复、会话命令、长按/轻点 |
| [REQ-003 模型切换流式输出与图片历史](docs/2026-11-14-模型切换流式输出与图片历史/requirements.md) | 模型切换、SSE/JSONL 流式、图文历史与附件缓存 |
| [REQ-004 存储位置与输入快捷键设置](docs/2026-11-14-存储位置与输入快捷键设置/requirements.md) | 自定义附件目录、发送/退出快捷键与冲突校验 |
| [REQ-005 会话字体大小设置](docs/2026-11-14-会话字体大小设置/requirements.md) | 字号、角色标签与历史图片宽度 |

## 已知限制

- API Key 的 DPAPI 加密存储与后端切换设置页尚未实现；当前通过环境变量与配置文件切换。
- API 模式无历史上下文，不支持 `/resume` 或 `/rename`。
- `/rename` 依赖 Codex CLI 后续提供命令；应用不会在本地伪造改名。
- Codex CLI 的流式粒度取决于 CLI 的 JSONL 事件，暂未接入 Codex app-server。
- 暂不支持粘贴/拖拽图片、旧附件迁移、多标注、单实例保护、代码签名与安装器。
- 仅支持 Windows 10/11 x64。

## 许可证

本项目尚未添加 `LICENSE` 文件；如需开源发布，请在发布前补充许可证。
