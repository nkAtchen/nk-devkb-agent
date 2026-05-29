# 项目规划与当前状态

本文档记录项目当前能力、限制和后续规划。项目使用方法请看 `README.md`。

## 当前版本定位

当前版本是本地可运行的知识库 Agent 初版。

它可以把 Markdown、TXT、JSON、HTML 文档导入本地知识库，然后用 CLI 搜索、提问、摘要。当前版本先跑通本地流程：

- SQLite 存储。
- 本地关键词检索。
- 简单 rerank。
- mock LLM。
- reflection 门控。

真实 LLM、Embedding、Qdrant 还没有接入代码，但接口边界已经预留。

## 当前能做什么

- 初始化本地知识库。
- 导入本地文件。
- 搜索已导入内容。
- 对知识库提问。
- 对全部文档或单个文件做摘要。
- 查看已导入来源。
- 刷新已导入文件。
- 保存每日 12:00 的采集计划配置。

## 当前支持的文件格式

- Markdown：`.md`、`.markdown`
- Text：`.txt`
- JSON：`.json`
- HTML：`.html`、`.htm`

PDF 和 DOCX 预留了 Microsoft MarkItDown 转换入口。当前如果没有安装 MarkItDown，会提示不支持。

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

当前版本支持两种 LLM 模式：

- 默认模式：不配置 `.env`，使用本地 mock LLM。
- 真实 LLM 模式：在 `.env` 中配置 OpenAI-compatible Chat Completions API。

本地 mock 代码：

- 文件：`src/nk_devkb_agent/llm.py`
- 类：`LocalLLMClient`

它不会调用 OpenAI、DeepSeek、Qwen 或其他云端模型。

真实 LLM 配置方式：

```bash
cp .env.example .env
```

然后编辑 `.env`：

```env
LLM_PROVIDER=openai
LLM_MODEL=gpt-4.1-mini
LLM_API_KEY=your_api_key
LLM_BASE_URL=https://api.openai.com/v1
```

`kb ask` 会先查询本地 RAG 知识库。如果检索到内容，会把检索上下文和用户输入的 user prompt 一起发给 LLM；如果没有检索到内容，会使用 `default_system_prompt + user_prompt` 生成 `no_rag_context` 答案。

相关代码：

- `src/nk_devkb_agent/config.py`
- `src/nk_devkb_agent/llm.py`
- `src/nk_devkb_agent/pipeline.py`

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

## 当前限制

- 没有真实 LLM 调用。
- 没有真实 embedding。
- 没有 Qdrant 向量检索。
- 没有后台常驻 scheduler worker。
- arXiv 和 GitHub 采集命令还没实现。
- PDF/DOCX 需要安装 MarkItDown 后才可用。

## 推荐下一步

1. 接 embedding provider。
2. 接 Qdrant vector store。
3. 实现 arXiv/GitHub collector。
4. 实现真正的定时 worker。
5. 给真实 LLM 调用增加重试、超时配置和错误分类。
