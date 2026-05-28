# NK DevKB Agent

一个本地可运行的知识库 Agent 初版。

你可以把 Markdown、TXT、JSON、HTML 文档导入本地知识库，然后用 CLI 搜索、提问、摘要。当前版本先跑通本地流程：SQLite 存储、本地关键词检索、简单 rerank、mock LLM、reflection 门控。真实 LLM、Embedding、Qdrant 还没有接入代码，但接口边界已经预留。

## 环境一眼看清

必须有：

- Python 3.11 或更高版本。
- pip。
- 一个可以执行 shell 命令的终端。

脚本会自动安装：

- 项目本身：`nk-devkb-agent`
- 测试工具：`pytest`

当前不需要：

- LLM API key。
- Qdrant 账号。
- OpenAI / DeepSeek / Qwen 配置。
- Docker。

可选：

- Microsoft MarkItDown。只有导入 PDF/DOCX 时才需要。

当前项目验证环境：

```text
Python 3.13.13
pytest 9.0.3
```

`pyproject.toml` 里声明的最低版本是 Python 3.11。

## 推荐初始化方式

第一次使用，直接执行环境初始化脚本：

```bash
cd /root/nk-devkb-agent
scripts/setup_env.sh
```

脚本会做这些事：

```text
检查 Python 版本
创建 .venv 虚拟环境
升级 pip
安装当前项目
安装 pytest
运行测试
```

脚本执行完成后，激活虚拟环境：

```bash
source .venv/bin/activate
```

然后直接使用：

```bash
kb init
kb ingest file ./architecture.md
kb ask "这个系统的问答链路是什么？"
```

如果你还需要 PDF/DOCX 支持，执行：

```bash
scripts/setup_env.sh --with-markitdown
```

如果你的系统里 Python 命令叫 `python3`，执行：

```bash
PYTHON_BIN=python3 scripts/setup_env.sh
```

## 现在能做什么

- 初始化本地知识库。
- 导入本地文件。
- 搜索已导入内容。
- 对知识库提问。
- 对全部文档或单个文件做摘要。
- 查看已导入来源。
- 刷新已导入文件。
- 保存每日 12:00 的采集计划配置。

支持的本地文件：

- Markdown：`.md`、`.markdown`
- Text：`.txt`
- JSON：`.json`
- HTML：`.html`、`.htm`

PDF 和 DOCX 预留了 Microsoft MarkItDown 转换入口。当前如果没有安装 MarkItDown，会提示不支持。

## 从零开始上手

如果不使用 `scripts/setup_env.sh`，也可以手动初始化环境。

### 1. 进入项目目录

```bash
cd /root/nk-devkb-agent
```

如果你是从别的地方拿到项目，先进入你本机的项目目录：

```bash
cd /path/to/nk-devkb-agent
```

### 2. 检查 Python 版本

```bash
python --version
```

需要看到 `Python 3.11` 或更高版本。

如果你的系统里 Python 命令叫 `python3`，后面的命令可以把 `python` 换成 `python3`。

### 3. 创建虚拟环境

```bash
python -m venv .venv
```

激活虚拟环境：

macOS / Linux：

```bash
source .venv/bin/activate
```

Windows PowerShell：

```powershell
.venv\Scripts\Activate.ps1
```

### 4. 安装项目

```bash
python -m pip install --upgrade pip
python -m pip install -e .
```

安装完成后，检查 `kb` 命令：

```bash
kb --help
```

如果能看到 `init`、`ingest`、`ask`、`search`、`summarize` 等命令，说明安装成功。

### 5. 安装测试工具

```bash
python -m pip install pytest
```

运行测试：

```bash
pytest -q
```

看到类似下面的结果就说明本地环境正常：

```text
11 passed
```

## 安装命令速查

在项目目录执行：

```bash
cd /root/nk-devkb-agent
python -m pip install -e .
```

安装后会得到 `kb` 命令。

如果不想安装，也可以用：

```bash
PYTHONPATH=src python -m nk_devkb_agent <command>
```

## 可选环境

### PDF / DOCX 支持

当前默认支持 Markdown、TXT、JSON、HTML。如果你要导入 PDF 或 DOCX，需要安装 MarkItDown：

```bash
python -m pip install markitdown
```

然后可以尝试：

```bash
kb ingest file ./docs/example.pdf
kb ingest file ./docs/example.docx
```

### .env 文件

当前本地 MVP 不读取 `.env`，也不需要任何 API key。

为了后续接真实 LLM、Embedding、Qdrant，可以先准备一个 `.env` 文件，但现在不会生效：

```env
LLM_PROVIDER=openai
LLM_MODEL=gpt-4.1-mini
LLM_API_KEY=your_api_key
LLM_BASE_URL=https://api.openai.com/v1

EMBEDDING_PROVIDER=openai
EMBEDDING_MODEL=text-embedding-3-small
EMBEDDING_API_KEY=your_api_key
EMBEDDING_BASE_URL=https://api.openai.com/v1

QDRANT_URL=https://your-cluster.qdrant.io
QDRANT_API_KEY=your_qdrant_key
QDRANT_COLLECTION=devkb_default
QDRANT_VECTOR_SIZE=1536
QDRANT_DISTANCE=Cosine
```

`.env` 已经在 `.gitignore` 中，不应该提交到仓库。

## 最快跑通

```bash
kb init
kb ingest file ./architecture.md
kb search "问答链路"
kb ask "这个系统的问答链路是什么？"
```

运行后会在当前目录创建本地工作区：

```text
.kb/kb.sqlite
```

这是本地 SQLite 数据库，里面保存 namespace、source、chunk、schedule 等数据。

## 常用命令

初始化：

```bash
kb init
```

导入文件：

```bash
kb ingest file ./architecture.md
kb ingest file ./docs/notes.md
```

搜索：

```bash
kb search "RAG pipeline"
kb search "问答链路"
```

提问：

```bash
kb ask "这个系统的问答链路是什么？"
```

摘要全部知识库：

```bash
kb summarize collection
```

摘要单个文件：

```bash
kb summarize file architecture.md
```

查看已导入来源：

```bash
kb sources
```

刷新已导入来源：

```bash
kb refresh
```

保存每日采集计划：

```bash
kb schedule set --daily-at 12:00 --timezone local
kb schedule list
```

手动触发一次计划采集：

```bash
kb schedule run-now
```

注意：当前 `schedule run-now` 会复用 `refresh` 逻辑；真正的后台定时 worker 还没实现。

## 指定项目目录

默认使用当前目录作为知识库项目目录。也可以显式指定：

```bash
kb init --root /path/to/project
kb ingest file /path/to/project/docs/a.md --root /path/to/project
kb ask "这里的核心设计是什么？" --root /path/to/project
```

## 指定 namespace

默认 namespace 是 `default`。可以这样指定：

```bash
kb init --namespace my-project
kb ingest file ./architecture.md --namespace my-project
kb ask "问答链路是什么？" --namespace my-project
```

## 问答流程

`kb ask` 当前流程：

```text
用户问题
  -> 本地检索 SQLite chunks
  -> 简单 rerank
  -> 如果命中内容：基于检索内容生成答案和引用
  -> 如果没命中：使用 default_system_prompt + 用户问题生成 no_rag_context 答案
  -> Reflection 检查
  -> 输出答案或拒答原因
```

输出里会包含：

- 答案正文
- reflection 结果
- 是否使用 RAG
- 是否是 no_rag_context
- citations 引用来源

## 当前 LLM 配置状态

当前版本不需要配置 LLM API key。

代码里使用的是本地 mock：

- 文件：`src/nk_devkb_agent/llm.py`
- 类：`LocalLLMClient`

它不会调用 OpenAI、DeepSeek、Qwen 或其他云端模型。

后续接真实 LLM 时，建议 `.env` 配置长这样：

```env
LLM_PROVIDER=openai
LLM_MODEL=gpt-4.1-mini
LLM_API_KEY=your_api_key
LLM_BASE_URL=https://api.openai.com/v1
```

需要替换的代码位置：

- `LocalLLMClient` -> 真实 `LLMClient`
- `RAGTool` 中注入真实 LLM client

## 当前 Qdrant 配置状态

当前版本没有接 Qdrant。

现在的检索是：

```text
SQLite chunks
  -> 本地关键词检索
  -> 简单 rerank
```

相关代码：

- `src/nk_devkb_agent/store.py`
- `src/nk_devkb_agent/retrieval.py`

后续接 Qdrant 时，建议 `.env` 配置长这样：

```env
QDRANT_URL=https://your-cluster.qdrant.io
QDRANT_API_KEY=your_qdrant_key
QDRANT_COLLECTION=devkb_default
QDRANT_VECTOR_SIZE=1536
QDRANT_DISTANCE=Cosine
```

还需要 embedding 配置：

```env
EMBEDDING_PROVIDER=openai
EMBEDDING_MODEL=text-embedding-3-small
EMBEDDING_API_KEY=your_api_key
EMBEDDING_BASE_URL=https://api.openai.com/v1
```

后续替换方向：

- SQLite 继续保存 chunk 正文和 metadata。
- Qdrant 保存 vector、chunk_id、namespace 和轻量 metadata。
- `LocalRetriever` 替换为 embedding + Qdrant 检索。

## 测试

```bash
pytest -q
```

当前测试覆盖：

- SQLite 存储
- 文档转换
- Markdown 分块
- 中文短查询检索
- RAG 命中问答
- no-RAG fallback
- CLI 主流程
- schedule 命令

## 当前限制

- 没有真实 LLM 调用。
- 没有真实 embedding。
- 没有 Qdrant 向量检索。
- 没有后台常驻 scheduler worker。
- arXiv 和 GitHub 采集命令还没实现。
- PDF/DOCX 需要安装 MarkItDown 后才可用。

## 推荐下一步

1. 加 `.env` 配置加载器。
2. 接真实 LLM provider。
3. 接 embedding provider。
4. 接 Qdrant vector store。
5. 实现 arXiv/GitHub collector。
6. 实现真正的定时 worker。
