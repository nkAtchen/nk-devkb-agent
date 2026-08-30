# NK DevKB Agent 使用说明

这是一个本地可运行的知识库 Agent。使用前先准备环境，然后进入项目目录初始化知识库，最后通过 `kb` 命令导入文档、搜索、提问和摘要。

项目规划、当前限制、LLM/Qdrant 后续接入说明放在 `plan.md`。

## 第一步：准备环境

### 需要什么环境

必须安装：

- Python 3.11 或更高版本。
- pip。
- bash 终端。

项目初始化脚本会自动安装：

- 当前项目：`nk-devkb-agent`
- 测试工具：`pytest`

当前本地版本不需要：

- LLM API key
- Qdrant 账号
- OpenAI / DeepSeek / Qwen 配置
- Docker

可选安装：

- MarkItDown。只有导入 PDF/DOCX 文件时才需要。

当前验证过的环境：

```text
Python 3.13.13
pytest 9.0.3
```

### 安装命令

先进入项目目录：

```bash
cd /root/nk-devkb-agent
```

执行环境初始化脚本：

```bash
scripts/setup_env.sh
```

这个脚本会自动执行：

```text
检查 Python 版本
创建 .venv 虚拟环境
安装当前项目
安装 pytest
运行测试
```

脚本成功后，激活虚拟环境：

```bash
source .venv/bin/activate
```

如果你的系统里 Python 命令是 `python3`，使用：

```bash
PYTHON_BIN=python3 scripts/setup_env.sh
```

如果需要 PDF/DOCX 支持，使用：

```bash
scripts/setup_env.sh --with-markitdown
```

如果不想使用脚本，也可以手动安装：

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .
python -m pip install pytest
pytest -q
```

测试看到类似结果，说明环境正常：

```text
11 passed
```

## 第二步：进入项目并初始化

进入项目目录：

```bash
cd /root/nk-devkb-agent
source .venv/bin/activate
```

初始化本地知识库：

```bash
kb init
```

初始化后，项目目录下会生成：

```text
.kb/kb.sqlite
```

这是本地 SQLite 知识库数据库。

导入一份文档：

```bash
kb ingest file ./architecture.md
```

搜索导入内容：

```bash
kb search "问答链路"
```

向知识库提问：

```bash
kb ask "这个系统的问答链路是什么？"
```

如果你不想安装 `kb` 命令，也可以用模块方式运行：

```bash
PYTHONPATH=src python -m nk_devkb_agent init
PYTHONPATH=src python -m nk_devkb_agent ingest file ./architecture.md
PYTHONPATH=src python -m nk_devkb_agent ask "这个系统的问答链路是什么？"
```

## 第三步：使用项目命令

忘记命令时，直接查帮助：

```bash
kb --help
```

查看某个子命令帮助：

```bash
kb ingest --help
kb schedule --help
```

### 初始化

```bash
kb init
```

### 导入文件

支持 Markdown、TXT、JSON、HTML：

```bash
kb ingest file ./architecture.md
kb ingest file ./docs/notes.txt
kb ingest file ./docs/data.json
kb ingest file ./docs/page.html
```

### 搜索

```bash
kb search "RAG pipeline"
kb search "问答链路"
```

### 提问

```bash
kb ask "这个系统的问答链路是什么？"
```

### 摘要

摘要整个知识库：

```bash
kb summarize collection
```

摘要单个文件：

```bash
kb summarize file architecture.md
```

### 查看来源

```bash
kb sources
```

### 刷新已导入文件

```bash
kb refresh
```

### 配置每日采集计划

保存每日 12:00 的采集配置：

```bash
kb schedule set --daily-at 12:00 --timezone local
```

查看采集计划：

```bash
kb schedule list
```

手动触发一次采集：

```bash
kb schedule run-now
```

注意：当前 `schedule run-now` 复用的是 `refresh` 逻辑，还不是后台常驻定时任务。

### 指定项目目录

默认使用当前目录作为项目目录。也可以手动指定：

```bash
kb init --root /path/to/project
kb ingest file /path/to/project/docs/a.md --root /path/to/project
kb ask "这里的核心设计是什么？" --root /path/to/project
```

### 指定 namespace

默认 namespace 是 `default`。可以手动指定：

```bash
kb init --namespace my-project
kb ingest file ./architecture.md --namespace my-project
kb ask "问答链路是什么？" --namespace my-project
```

## 常见问题

### kb 命令不存在

先确认已经激活虚拟环境：

```bash
source .venv/bin/activate
```

再确认项目已安装：

```bash
python -m pip install -e .
```

### Python 版本太低

检查版本：

```bash
python --version
```

需要 Python 3.11 或更高版本。

### PDF/DOCX 导入失败

默认只支持 Markdown、TXT、JSON、HTML。PDF/DOCX 需要安装 MarkItDown：

```bash
scripts/setup_env.sh --with-markitdown
```
