# 智能知识库 Agent 架构设计

## 1. 目标与范围

本项目的首版目标是构建一个面向个人和小团队的智能知识库 Agent。系统以 CLI 为主要入口，支持本地项目目录型知识库，同时预留全局知识库模式。MVP 优先支持文档问答、单篇摘要和多篇摘要，后续再扩展企业内部知识库检索、总结、权限隔离和团队共享能力。

首版知识来源包括：

- 本地文档：PDF、Markdown、TXT、DOCX、HTML、JSON。
- arXiv：论文元数据、摘要、PDF 正文。
- GitHub：仓库 README、docs、Markdown、文本说明文件，代码导入作为后续扩展。

首版交互形态为 CLI。RAG 能力作为 Tool 级 pipeline 暴露，不作为完整应用系统强绑定。入口类为 `RAGTool`，继承自通用 `Tool`，通过 `create_rag_pipeline` 创建处理管道。

## 2. 总体分层

系统采用五层分层设计，每层通过接口解耦，可独立替换。

```text
用户层：CLI / RAGTool 统一接口
  ↓
应用层：多步智能问答、搜索、摘要、知识库管理
  ↓
处理层：来源采集、文档解析、Markdown 转换、智能分块、向量化
  ↓
存储层：Qdrant Cloud、SQLite 本地文档库
  ↓
基础层：Embedding API、Rerank API、LLM API、arXiv API、GitHub API、数据库驱动、配置与密钥管理
```

核心设计原则：

- RAG 是可复用 Tool pipeline，而不是固定业务模块。
- 默认保护正文隐私：Qdrant Cloud 默认不保存 chunk 正文。
- 多 namespace 隔离多个知识库。
- 向量数据库、嵌入模型、LLM、文档转换器、检索策略都通过接口替换。
- API key 和敏感配置只通过 `.env` 或环境变量注入，不写入代码、日志、索引或 SQLite 明文字段。
- 先支持个人和小团队使用，再向企业权限、审计和共享扩展。

## 3. 用户层：CLI 与 RAGTool

### 职责

用户层负责接收用户命令，并将命令转换为 RAG pipeline 调用。首版以 CLI 为主要入口，同时保留 `RAGTool` 作为后续被其他 Agent 或应用调用的统一接口。

CLI 支持两种知识库组织方式：

- 项目目录型：默认模式，在当前项目目录初始化和使用知识库。
- 全局知识库型：通过参数启用，适合个人长期积累资料。

### 建议命令

```bash
kb init
kb init --global
kb ingest file ./docs
kb ingest arxiv 2401.12345
kb ingest arxiv "retrieval augmented generation"
kb ingest github https://github.com/org/repo
kb ask "这个项目的核心架构是什么？"
kb summarize file <doc_id>
kb summarize collection
kb search "向量数据库对比"
kb sources
kb refresh
kb schedule set --daily-at 12:00 --timezone local
kb schedule list
kb schedule run-now
```

### RAGTool 接口

`RAGTool` 是用户层和应用层之间的统一入口。

```python
class RAGTool(Tool):
    def __init__(self, pipeline_config: RAGPipelineConfig):
        ...

    def ingest(self, source: SourceSpec, namespace: str) -> IngestResult:
        ...

    def ask(self, question: str, namespace: str, options: AskOptions) -> Answer:
        ...

    def search(self, query: str, namespace: str, options: SearchOptions) -> list[SearchResult]:
        ...

    def summarize(self, target: SummaryTarget, namespace: str) -> Summary:
        ...

    def refresh(self, namespace: str) -> RefreshResult:
        ...
```

### 依赖关系

- 依赖应用层的问答、搜索、摘要和管理服务。
- 不直接依赖 Qdrant、SQLite、Embedding API 或 LLM API。
- 通过 `create_rag_pipeline` 获取完整 pipeline 实例。

## 4. 应用层：问答、搜索、摘要、管理

### 职责

应用层负责编排用户意图和 RAG 能力，包含四类核心能力：

- 智能问答：多步 agent 问答。
- 搜索：基础检索和扩展检索。
- 摘要：单篇摘要、多篇摘要。
- 管理：知识库初始化、namespace 管理、来源列表、刷新、删除。

### 多步智能问答

`kb ask` 默认采用多步 agent 问答，不只是一次性检索生成。

流程如下：

```text
用户问题 / user_prompt
  ↓
Planner 判断问题类型并拆解子问题
  ↓
Retriever 对每个子问题执行检索
  ↓
Evidence Gate 判断是否有可用 RAG 证据
  ↓
如果有可用证据：Reader 从候选 chunk 中提取证据
  ↓
Synthesizer 基于证据综合生成答案
  ↓
如果没有可用证据：PromptBuilder 拼接 default_system_prompt 和 user_prompt
  ↓
LLM 生成 no_rag_context 答案
  ↓
Reflection 检查答案质量、证据一致性、幻觉风险和输出规则
  ↓
通过时 Finalizer 输出答案和来源引用；不通过时返回拒答原因
```

核心规则：

- 有可用 RAG 证据时，回答必须优先基于检索证据。
- 没有可用 RAG 证据时，允许使用默认 prompt 加用户输入的 `user_prompt` 直接调用 LLM，但结果必须标记为 `no_rag_context`。
- Reflection 是最终输出门控，必须返回结构化结果，例如 `passed`、`reasons`、`suggested_action`。
- Reflection 不通过时，不输出生成答案正文，只返回拒答原因或需要补充的信息。
- 基于 RAG 证据的输出应包含引用来源，例如文件路径、arXiv ID、GitHub URL、页码、heading_path。
- 多步检索需要限制轮数和 token 预算，避免成本失控。

### 搜索能力

搜索能力由 `search_vectors_expanded` 统一调度，支持三种召回策略和可选 rerank：

- 基础向量搜索：直接对用户 query 生成 embedding 并检索。
- MQE：Multi Query Expansion，用 LLM 生成同义或改写查询，并行检索后合并去重。
- HyDE：Hypothetical Document Embeddings，先让 LLM 生成假设答案，再用假设答案向量检索。
- Rerank：对合并去重后的候选 chunk 进行二次排序，可使用本地 reranker 或云端 rerank API。

默认参数：

- `top_k`：最终返回数量。
- `candidate_pool_size`：默认 `4 * top_k`。
- 去重规则：按 `chunk_id` 去重。
- 召回排序：按归一化分数排序得到候选池。
- rerank 输入数量：默认等于 `candidate_pool_size`。
- rerank 输出数量：默认截断返回 `top_k`。
- rerank 不可用时：默认回退到召回排序，并记录降级原因。

### 摘要能力

摘要支持两种目标：

- 单篇摘要：对一个文档或一个来源做分层摘要。
- 多篇摘要：对多个文档或一个 collection 做聚合摘要。

长文档摘要采用 map-reduce 思路：

```text
chunk 摘要
  ↓
section 摘要
  ↓
document 摘要
  ↓
collection 摘要
```

### 接口

```python
class QAService:
    def ask(self, question: str, namespace: str, options: AskOptions) -> Answer:
        ...

class SearchService:
    def search(self, query: str, namespace: str, options: SearchOptions) -> list[SearchResult]:
        ...

class SummaryService:
    def summarize(self, target: SummaryTarget, namespace: str) -> Summary:
        ...

class KnowledgeBaseService:
    def init_namespace(self, namespace: str, config: NamespaceConfig) -> None:
        ...

    def list_sources(self, namespace: str) -> list[SourceRecord]:
        ...

    def refresh(self, namespace: str) -> RefreshResult:
        ...

    def configure_schedule(self, namespace: str, schedule: CollectionSchedule) -> None:
        ...

    def run_scheduled_collection(self, namespace: str, options: CollectionRunOptions) -> CollectionRunResult:
        ...
```

### 依赖关系

- 依赖处理层提供 ingestion、chunking、embedding 和检索能力。
- 依赖基础层 LLM 完成 query expansion、HyDE、问答生成和摘要。
- 不直接操作底层存储，必须通过 repository 或 store 接口访问。

## 5. 外部采集 Agent：Scheduler、Analyzer、Collector、Organizer

### 总体职责

外部数据采集采用 Scheduler 加三个 agent 协作，但文档转换、分块、向量化和写入存储仍由确定性工具执行，避免 LLM 自由写入导致重复、污染或不可测试。

```text
Scheduler 每天 12:00 触发 CollectionJob
  ↓
Analyzer
  ↓
Collector
  ↓
Organizer
  ↓
Ingestion Pipeline
```

### Scheduler

职责：

- 按 namespace 配置的 schedule 创建采集任务。
- MVP 默认每天 12:00 准时触发一次采集整理。
- 为每次运行生成 `collection_run_id`，记录开始时间、结束时间、状态、错误和统计信息。
- 控制同一 namespace 同一时间只允许一个采集任务运行。
- 支持错过触发时间后的补偿策略，例如启动后检查上次运行时间并补跑一次。

默认配置：

```text
collection_schedule = "0 12 * * *"
collection_timezone = "local"
```

规则：

- `collection_timezone` 默认使用本机时区，也可在 namespace 配置中指定，例如 `Asia/Shanghai`。
- Scheduler 只负责触发和运行状态管理，不直接调用 LLM 生成采集判断。
- Scheduler 创建的是结构化 `CollectionJob`，后续由 Analyzer、Collector、Organizer 顺序处理。
- 定时采集与手动 `kb refresh` 共用去重、hash、commit 检查和 ingestion pipeline。

接口：

```python
class Scheduler:
    def register(self, schedule: CollectionSchedule) -> None:
        ...

    def tick(self, now: datetime) -> list[CollectionJob]:
        ...

    def run_job(self, job: CollectionJob) -> CollectionRunResult:
        ...
```

### Analyzer

职责：

- 理解用户的采集目标。
- 判断需要采集 arXiv、GitHub 还是本地文件。
- 生成采集计划，例如关键词、arXiv ID、GitHub URL、repo 分支。
- 对候选来源做初步相关性判断。

边界：

- 不下载文件。
- 不写入知识库。
- 不做向量化。

接口：

```python
class Analyzer:
    def analyze(self, request: CollectionRequest) -> CollectionPlan:
        ...
```

依赖：

- 可选依赖 LLM。
- 可依赖 arXiv/GitHub 搜索工具的轻量 metadata 查询。

### Collector

职责：

- 根据 `CollectionPlan` 拉取原始资料。
- 支持 arXiv PDF 和 metadata 下载。
- 支持 GitHub 仓库文件列表、README、docs 和 Markdown 文档拉取。
- 处理认证、重试、限流和下载失败。

边界：

- 不做知识判断。
- 不做分块和向量化。
- 不直接生成答案。

接口：

```python
class Collector:
    def collect(self, plan: CollectionPlan) -> list[RawDocument]:
        ...
```

依赖：

- arXiv API。
- GitHub API。
- 本地文件系统。

### Organizer

职责：

- 对采集结果去重、分类和补充 metadata。
- 生成统一的 `SourceRecord` 和 `RawDocument`。
- 决定是否进入 ingestion pipeline。
- 维护来源与 namespace 的关系。

边界：

- 不直接调用 LLM 生成最终回答。
- 不直接写 Qdrant，必须通过 ingestion pipeline。

接口：

```python
class Organizer:
    def organize(self, documents: list[RawDocument], namespace: str) -> OrganizedBatch:
        ...
```

依赖：

- SQLite metadata repository。
- 去重和 hash 工具。
- 可选 LLM，用于主题分类和质量筛选。

### Agent 上下文控制

三个采集 agent 不共享无限增长的对话上下文。每次采集运行都基于结构化 `JobContext` 构造短上下文，长期状态统一保存在 SQLite。

`JobContext` 建议字段：

```text
run_id
namespace
schedule_id
collection_goal
source_scope
budget
allowed_tools
previous_run_summary
last_seen_state
```

上下文边界：

- Analyzer 只读取采集目标、namespace 配置、source scope、历史运行摘要和允许工具。
- Collector 只读取 `CollectionPlan`、认证配置引用、限流参数和下载目标。
- Organizer 只读取 RawDocument metadata、hash、namespace、去重规则和已有 source 状态。
- Ingestion pipeline 只接收 `OrganizedBatch`，不读取 agent 的完整推理过程。

长期状态：

- 历史采集结果、source hash、GitHub commit、arXiv metadata、运行摘要和错误记录写入 SQLite。
- LLM prompt 只注入必要状态摘要，不注入完整历史日志、完整文档正文或无关问答上下文。
- 每个 agent 输出结构化结果，供下一个阶段消费；自由文本说明只能作为日志或 summary。
- 每次运行结束后生成 `run_summary`，供下一次定时采集使用。

## 6. 处理层：解析、转换、分块、向量化

### 职责

处理层负责将不同来源和格式的资料统一转成可检索 chunk。

主流程：

```text
本地文件 / arXiv PDF / GitHub 文档 / JSON
  ↓
Source Connector 获取原始内容
  ↓
Document Converter 转 Markdown
  ↓
Markdown Cleaner 清洗
  ↓
Markdown Semantic Chunker 分块
  ↓
Embedding Service 向量化
  ↓
Storage Writer 写入 Qdrant Cloud 和 SQLite
```

### 文档转换

首版格式支持：

- PDF。
- Markdown。
- TXT。
- DOCX。
- HTML。
- JSON。

转换策略：

- PDF、Markdown、TXT、DOCX、HTML：优先使用 Microsoft MarkItDown 转换为 Markdown。
- JSON：使用专门的 JSON parser 转为带字段路径的 Markdown 或文本表示。

JSON 示例：

```text
# JSON Document

## $.title
...

## $.items[0].name
...
```

这样可以保留结构路径，便于检索和引用。

### Markdown 智能分块

分块以 Markdown 标题层级为核心，保留 `heading_path`。

策略：

- 优先按标题层级切分。
- 单个 section 过长时按段落和 token 限制继续切分。
- chunk 之间可配置 overlap。
- 每个 chunk 必须保留来源、标题路径、位置和 hash。

chunk metadata 示例：

```json
{
  "chunk_id": "sha256:...",
  "namespace": "project-rag-agent",
  "source_type": "local_file",
  "source_id": "docs/design.pdf",
  "heading_path": ["Architecture", "Storage Layer"],
  "page": 12,
  "content_hash": "sha256:...",
  "created_at": "2026-05-25T00:00:00Z"
}
```

### Embedding 服务

首版云端模型优先，支持 OpenAI、DeepSeek、Qwen、百炼等供应商。

注意：embedding fallback 不能简单混用在同一个 collection 或 namespace 中。

安全规则：

- 每个 namespace 固定一个 embedding profile。
- embedding profile 包含 provider、model、dimension、distance metric。
- 如果更换 embedding 模型，必须新建 namespace、重建索引，或执行显式迁移。
- TF-IDF 不应作为 dense embedding 的透明 fallback；它属于关键词或稀疏检索降级路径。

建议 fallback 策略：

```text
建库阶段：
主 embedding provider 不可用 → 报错，或用户显式选择备用 profile 并创建新 namespace

查询阶段：
主 embedding provider 不可用 → 报错，或降级到本地关键词/SQLite FTS 搜索
```

### 接口

```python
class DocumentConverter:
    def convert(self, raw: RawDocument) -> MarkdownDocument:
        ...

class Chunker:
    def split(self, document: MarkdownDocument, options: ChunkOptions) -> list[Chunk]:
        ...

class EmbeddingService:
    def embed_documents(self, chunks: list[Chunk], profile: EmbeddingProfile) -> list[EmbeddedChunk]:
        ...

    def embed_query(self, query: str, profile: EmbeddingProfile) -> QueryEmbedding:
        ...
```

### 依赖关系

- 依赖 MarkItDown。
- 依赖 JSON parser。
- 依赖 embedding provider API。
- 依赖 tokenizer 或 token estimator。
- 输出写入存储层。

## 7. 存储层：Qdrant Cloud 与 SQLite

### 总体职责

存储层负责持久化向量索引、chunk 原文、来源 metadata、导入状态和 namespace 配置。

采用双存储：

- Qdrant Cloud：向量检索和轻量 payload 过滤。
- SQLite：本地正文、来源记录、导入状态、namespace 配置。

### Qdrant Cloud

默认存储内容：

- embedding vector。
- `chunk_id`。
- `namespace`。
- 最小 metadata。
- 用于过滤的字段，例如 `source_type`、`source_id`、`heading_path`、`created_at`。

默认不存：

- chunk 正文。
- 原始文档二进制内容。

可选 namespace 模式：

- 特定 namespace 可配置 `text_storage_mode = qdrant_payload`。
- 该模式允许 Qdrant payload 保存 chunk 正文和 metadata。
- 适合非敏感资料、跨机器使用或轻量部署。

### SQLite

SQLite 默认保存：

- namespace 配置。
- source 记录。
- chunk 原文。
- chunk metadata。
- content hash。
- ingest status。
- refresh 时间。
- collection schedule。
- collection run 状态。
- agent 运行摘要。
- 错误记录。

建议表结构：

```text
namespaces
- namespace
- qdrant_collection
- embedding_provider
- embedding_model
- embedding_dimension
- distance_metric
- text_storage_mode
- created_at

sources
- source_id
- namespace
- source_type
- uri
- title
- content_hash
- ingest_status
- last_ingested_at
- last_refreshed_at
- error_message

chunks
- chunk_id
- namespace
- source_id
- chunk_text
- heading_path_json
- position_json
- content_hash
- token_count
- created_at

ingest_runs
- run_id
- namespace
- started_at
- finished_at
- status
- stats_json
- error_message

collection_schedules
- schedule_id
- namespace
- cron_expr
- timezone
- enabled
- collection_goal
- source_scope_json
- budget_json
- created_at
- updated_at

collection_runs
- collection_run_id
- schedule_id
- namespace
- started_at
- finished_at
- status
- trigger_type
- run_summary
- stats_json
- error_message

agent_run_steps
- step_id
- collection_run_id
- agent_name
- started_at
- finished_at
- status
- input_summary
- output_summary
- token_usage_json
- error_message
```

### Namespace 隔离

namespace 表示一个逻辑知识库。

每个 namespace 固定：

- Qdrant collection 或 collection filter 策略。
- embedding profile。
- text storage mode。
- chunking profile。
- retrieval profile。
- source scope。

推荐隔离方案：

- MVP 默认每个 namespace 一个 Qdrant collection。
- 原因是不同 namespace 可使用不同 embedding 维度和模型，隔离更清楚。
- 后续可支持同 embedding profile 下多个 namespace 共享 collection，并通过 payload filter 隔离。

### 接口

```python
class VectorStore:
    def upsert(self, namespace: str, points: list[VectorPoint]) -> None:
        ...

    def search(self, namespace: str, vector: list[float], filters: dict, top_k: int) -> list[VectorHit]:
        ...

    def delete_by_source(self, namespace: str, source_id: str) -> None:
        ...

class DocumentStore:
    def save_chunks(self, chunks: list[Chunk]) -> None:
        ...

    def get_chunks(self, chunk_ids: list[str]) -> list[Chunk]:
        ...

    def save_source(self, source: SourceRecord) -> None:
        ...
```

### 依赖关系

- Qdrant Cloud 依赖 endpoint、API key、collection schema。
- SQLite 依赖本地项目目录或全局 workspace。
- 应用层和处理层只能通过 `VectorStore` 和 `DocumentStore` 访问存储。

## 8. 基础层：模型、API、数据库驱动

### 职责

基础层封装外部服务和底层依赖，避免业务层直接绑定具体供应商。

包含：

- LLM provider client。
- Embedding provider client。
- Rerank provider client。
- Qdrant client。
- SQLite connection manager。
- arXiv client。
- GitHub client。
- MarkItDown adapter。
- `.env` config loader 和 secret manager。

### LLM Provider

LLM 用于：

- 多步问答中的 planning、reading、synthesis 和 reflection。
- 无可用 RAG 证据时基于 `default_system_prompt` 和 `user_prompt` 生成 `no_rag_context` 答案。
- MQE 查询改写。
- HyDE 假设答案生成。
- 摘要生成。
- 可选的外部资料筛选和分类。

设计要求：

- 支持多 provider，例如 OpenAI、DeepSeek、Qwen、百炼。
- 每次调用记录模型、token 使用、耗时和错误。
- 支持预算限制和最大轮数。
- 问答链路中的 reflection 必须输出结构化判定，禁止只返回自由文本。
- `no_rag_context` 答案必须在响应 metadata 中显式标记，便于 CLI 展示、日志记录和后续评估。

### Embedding Provider

Embedding 用于：

- chunk 向量化。
- query 向量化。
- HyDE 生成文本后的向量化。

设计要求：

- 每个 namespace 固定 embedding profile。
- 不同 embedding dimension 不混写同一个 collection。
- 不透明 fallback 到不同向量空间。

### Rerank Provider

Rerank 用于：

- 对向量召回、MQE、HyDE 合并后的候选 chunk 二次排序。
- 提高复杂问题、短 query 或语义相近 chunk 的排序质量。
- 为 Reader 提供更少但更相关的证据集合。

设计要求：

- rerank profile 可按 namespace 或 retrieval profile 配置。
- reranker 输入必须来自候选池，不直接扩大检索范围。
- rerank 结果需要保留原始召回分数、rerank 分数和排序阶段，便于调试和评估。
- reranker 不可用时可以降级到原始召回排序，但必须记录降级事件。

### 配置与密钥管理

安全与密钥管理由基础层统一处理，不允许业务层直接读取散落的环境变量。

规则：

- API key、Qdrant endpoint、provider base URL 等敏感配置存放在 `.env`，通过环境变量注入运行时。
- 仓库只提交 `.env.example`，`.env` 必须加入 `.gitignore`。
- CLI 启动时加载 `.env`，再合并系统环境变量；系统环境变量优先级高于 `.env`。
- 日志、错误信息、评估结果和测试快照必须脱敏，不输出完整 API key、token、Authorization header。
- SQLite 和 Qdrant payload 不保存 API key、访问 token 或 provider secret。
- 配置对象只向下游传递必要字段，避免把完整 secret map 传入业务层。

### 接口

```python
class LLMClient:
    def complete(self, messages: list[Message], options: LLMOptions) -> LLMResponse:
        ...

class EmbeddingClient:
    def embed(self, texts: list[str], options: EmbeddingOptions) -> list[list[float]]:
        ...

class RerankClient:
    def rerank(self, query: str, candidates: list[RerankCandidate], options: RerankOptions) -> list[RerankResult]:
        ...

class ConfigLoader:
    def load(self, scope: ConfigScope) -> RuntimeConfig:
        ...
```

### 依赖关系

- 被应用层和处理层调用。
- 不反向依赖业务对象。
- 通过配置注入 API key、base URL、模型名称和超时参数。
- 负责密钥读取、配置校验和敏感字段脱敏。

## 9. 数据流

### Ingestion 数据流

```text
用户执行 kb ingest
  ↓
RAGTool.ingest
  ↓
Analyzer 可选生成采集计划
  ↓
Collector 获取原始资料
  ↓
Organizer 去重、分类、补 metadata
  ↓
DocumentConverter 转 Markdown
  ↓
MarkdownCleaner 清洗
  ↓
Chunker 按 heading_path 分块
  ↓
EmbeddingService 生成向量
  ↓
DocumentStore(SQLite) 保存 chunk 正文和状态
  ↓
VectorStore(Qdrant Cloud) 保存向量和 payload
```

### Ask 数据流

```text
用户执行 kb ask
  ↓
RAGTool.ask
  ↓
QAService Planner 拆解问题
  ↓
SearchService 对子问题执行基础检索 / MQE / HyDE
  ↓
Qdrant Cloud 返回候选 chunk_id 和 metadata
  ↓
Evidence Gate 判断是否命中可用 RAG 证据
  ↓
如果命中：SQLite 根据候选 chunk_id 取 chunk 正文
  ↓
如果命中：Reranker 对候选 chunk 二次排序并截断 top_k
  ↓
如果命中：Reader 提取证据
  ↓
如果命中：Synthesizer 基于证据生成答案
  ↓
如果未命中：PromptBuilder 拼接 default_system_prompt 和 user_prompt
  ↓
如果未命中：LLM 生成 no_rag_context 答案
  ↓
Reflection 检查答案质量、证据一致性、幻觉风险和输出规则
  ↓
通过时 Finalizer 输出答案和来源引用；不通过时返回拒答原因
```

如果 namespace 配置为 `qdrant_payload`，检索命中可直接从 Qdrant payload 获取正文用于 rerank 和 Reader，但仍建议用 SQLite 校验 source 和 ingest 状态。

### Summarize 数据流

```text
用户执行 kb summarize
  ↓
定位目标文档或 collection
  ↓
SQLite 读取相关 chunk
  ↓
按 heading_path 聚合
  ↓
LLM 生成 chunk/section/document 摘要
  ↓
输出摘要和来源
```

### Refresh 数据流

```text
用户执行 kb refresh
  ↓
检查 source hash / GitHub commit / arXiv metadata
  ↓
识别新增、更新、删除
  ↓
删除过期 chunk 和 vector
  ↓
重新 ingestion
  ↓
更新 SQLite 状态
```

手动 `kb refresh` 主要用于用户主动刷新指定 namespace 或 source；定时采集则由 Scheduler 自动触发。

### 定时采集数据流

```text
Scheduler 每天 12:00 按 namespace schedule 触发
  ↓
创建 CollectionJob 和 collection_run_id
  ↓
加载 JobContext：namespace 配置、采集目标、source scope、预算、上次运行摘要
  ↓
Analyzer 生成 CollectionPlan
  ↓
Collector 拉取 arXiv / GitHub / 本地 source 的新增或变化资料
  ↓
Organizer 去重、分类、补 metadata，生成 OrganizedBatch
  ↓
Ingestion Pipeline 转 Markdown、分块、embedding、写 SQLite 和 Qdrant
  ↓
写入 collection_runs、agent_run_steps、source 状态和 run_summary
```

调度规则：

- 默认每日 12:00 触发，时区由 `collection_timezone` 决定。
- 同一 namespace 同一时间只允许一个 collection run 处于 running 状态。
- 如果上一次运行失败，下一次运行复用 source hash、commit 和 metadata 状态继续增量采集。
- 如果任务执行时发现内容未变化，则只更新运行状态和统计信息，不重复写入 chunk 和 vector。
- 定时采集失败不删除旧索引；只有新的 ingestion 成功后才更新对应 source 的最新状态。

## 10. 评估架构

### 职责

评估架构用于自动化衡量 ingestion、检索、rerank、问答和摘要质量，避免只依赖主观体验判断系统是否变好。

评估目标：

- 检索是否能召回正确 chunk。
- rerank 是否能把更相关 chunk 排到前面。
- 答案是否基于证据，是否包含正确引用。
- 摘要是否覆盖关键内容且不引入无依据内容。
- 不同模型、chunking profile、retrieval profile 的变更是否造成质量回退。

### 自动化评估集

评估数据保存在仓库内的可版本化目录，例如 `evals/`。

建议结构：

```text
evals/
- datasets/
  - local_docs_qa.jsonl
  - retrieval_cases.jsonl
  - summarization_cases.jsonl
- fixtures/
  - docs/
  - expected_chunks.jsonl
- baselines/
  - retrieval_baseline.json
  - qa_baseline.json
- reports/
```

评估样例类型：

- 检索样例：query、namespace、期望 source_id、期望 heading_path、期望 chunk_id。
- rerank 样例：query、候选 chunk 列表、期望排序或相关性标签。
- 问答样例：question、允许使用的 source、参考答案要点、必需引用。
- 摘要样例：target、参考要点、禁止出现的无依据内容。

### 自动化指标

检索和 rerank 指标：

- Recall@K。
- MRR。
- nDCG@K。
- rerank 前后排序提升率。

问答指标：

- 引用命中率：答案引用是否来自期望 source 或 chunk。
- 证据覆盖率：答案要点是否能在检索证据中找到。
- 无依据内容率：答案中无法由证据支持的断言比例。
- 拒答正确率：证据不足时是否明确说明无法确认。

摘要指标：

- 要点覆盖率。
- 引用完整性。
- 无依据内容率。
- 长文档 map-reduce 各层摘要一致性。

### 评估运行方式

评估应通过命令自动执行，可在本地和 CI 中运行。

建议命令：

```bash
kb eval retrieval --dataset evals/datasets/retrieval_cases.jsonl
kb eval rerank --dataset evals/datasets/retrieval_cases.jsonl
kb eval qa --dataset evals/datasets/local_docs_qa.jsonl
kb eval summarize --dataset evals/datasets/summarization_cases.jsonl
kb eval all
```

运行规则：

- 默认使用固定 fixture 和固定 namespace，避免污染用户真实知识库。
- 对 LLM 输出采用结构化 judge 或规则校验，judge prompt 和模型版本必须记录。
- 评估报告输出 JSON，包含模型、profile、样例数、指标、失败样例和耗时。
- CI 中至少运行检索、rerank 和关键问答回归集。
- 如果使用云端 LLM 或 rerank API，评估命令必须读取 `.env`，但报告不得包含任何 secret。

## 11. 测试架构

### 职责

测试架构用于自动化验证代码正确性、接口契约和端到端数据流。测试不依赖人工检查，不把人工体验作为通过条件。

测试目标：

- 每层组件可以独立测试。
- 外部 provider 可以通过 fake、mock 或 recorded fixture 替代。
- ingestion、search、rerank、ask、summarize 的核心路径有自动化回归测试。
- 配置和密钥处理有安全测试，确保不会泄露 secret。

### 测试分层

单元测试：

- JSON parser 字段路径转换。
- Markdown cleaner 和 semantic chunker。
- chunk hash、source hash、去重逻辑。
- embedding profile 校验。
- Scheduler cron、timezone、missed run 和 namespace 锁逻辑。
- JobContext 裁剪和 agent 输入 schema 校验。
- retrieval candidate 合并、去重、归一化排序。
- rerank 结果合并、截断和降级逻辑。
- secret redaction 和 config merge 优先级。

集成测试：

- MarkItDown adapter 对 PDF、DOCX、HTML、TXT、Markdown fixture 的转换。
- SQLite repository 的 source、chunk、namespace、ingest_runs、collection_schedules、collection_runs 读写。
- Qdrant VectorStore 使用测试 collection 或 fake server 验证 upsert、search、delete。
- EmbeddingClient、LLMClient、RerankClient 使用 mock provider 验证请求和错误处理。

端到端测试：

- `kb init` 创建项目目录知识库。
- `kb ingest file ./fixtures/docs` 完成转换、分块、向量化和写入。
- `kb search` 返回带 source、heading_path、score、rerank_score 的结果。
- `kb ask` 返回基于 fixture 证据的答案和引用。
- `kb summarize file` 返回分层摘要。
- `kb refresh` 能识别新增、更新、删除并同步索引。
- `kb schedule run-now` 能触发 Scheduler、三个采集 agent 和 ingestion pipeline。

契约测试：

- `RAGTool` 对外方法的输入输出 schema。
- `VectorStore`、`DocumentStore`、`LLMClient`、`EmbeddingClient`、`RerankClient` 接口行为。
- CLI 命令参数、退出码和错误信息格式。

### 测试运行方式

测试应通过标准命令自动执行。

建议命令：

```bash
pytest
pytest tests/unit
pytest tests/integration
pytest tests/e2e
pytest tests/security
```

运行规则：

- 单元测试默认不访问网络。
- 集成测试默认使用 fake provider；访问真实 Qdrant 或真实模型 API 的测试必须显式开启。
- 端到端测试使用临时目录和测试 namespace，测试结束后清理。
- 所有测试日志必须脱敏。
- CI 默认执行单元测试、关键集成测试、安全测试和小型端到端 smoke test。
- 需要真实 API key 的测试只在配置存在时运行，否则自动 skip，不允许失败时打印 secret。

## 12. 关键设计决策

### 12.1 RAG 是 Tool 级 Pipeline

决策：

- 入口是 `RAGTool`。
- Pipeline 由 `create_rag_pipeline` 创建。
- 不将 RAG 绑定为单体应用模块。

理由：

- 后续可被 CLI、Web、其他 Agent 或服务复用。
- 每层可替换，便于演进到企业版。

### 12.2 默认项目目录型，支持全局知识库

决策：

- 默认在项目目录使用本地 `.kb/` 或等价 workspace。
- 支持 `--global` 使用全局知识库目录。
- 默认可为 namespace 配置每日 12:00 的定时采集任务。

理由：

- 项目目录型隔离清楚，适合 MVP。
- 全局模式满足长期个人知识积累。
- 定时采集让知识库能自动跟进 arXiv、GitHub 和本地资料变化。

### 12.3 Qdrant Cloud 作为向量数据库

决策：

- MVP 使用 Qdrant Cloud。
- 通过 `VectorStore` 抽象访问，避免业务层绑定 Qdrant。

理由：

- 避免本地部署数据库。
- 后续可迁移到 Milvus、pgvector、Pinecone 或其他向量库。

### 12.4 正文存储 namespace 级可配置

决策：

- 默认 `text_storage_mode = local_sqlite`。
- 可选 `text_storage_mode = qdrant_payload`。

理由：

- 默认降低 Qdrant Cloud 中的正文暴露。
- 对非敏感资料可简化跨机器使用。

### 12.5 每个 namespace 固定 embedding profile

决策：

- namespace 创建后固定 embedding provider、model、dimension 和 distance metric。
- 不允许不同 embedding 空间混写。

理由：

- 不同模型的向量不可直接比较。
- 保证检索结果稳定可解释。

### 12.6 MarkItDown 统一文档转换

决策：

- 常见文档格式优先通过 MarkItDown 转 Markdown。
- JSON 走专门 parser。

理由：

- Markdown 便于保留标题层级。
- heading_path 可直接服务分块、摘要和引用。

### 12.7 MQE、HyDE 和 rerank 是可选检索增强

决策：

- 基础检索始终可用。
- MQE 和 HyDE 通过 `search_vectors_expanded` 调度。
- rerank 在候选池合并去重后执行，只改变排序和截断，不改变召回范围。
- 默认 candidate pool 为 `4 * top_k`。

理由：

- 保持简单路径稳定。
- 给复杂问题提供更高召回能力。
- 通过 rerank 提升最终证据排序质量。
- 控制 LLM 成本和延迟。

### 12.8 API key 使用 `.env` 和环境变量管理

决策：

- 项目本地开发使用 `.env` 保存 API key 和 provider endpoint。
- 仓库只提交 `.env.example`，不提交 `.env`。
- 运行时配置由统一 `ConfigLoader` 读取，业务层不直接访问 secret。

理由：

- 减少密钥误提交和日志泄露风险。
- 让 CLI、本地测试、CI 和部署环境使用同一套配置入口。
- 便于后续替换为系统 keychain、Vault 或云平台 secret manager。

### 12.9 自动化评估和自动化测试作为质量门禁

决策：

- 评估集、测试 fixture、baseline 和报告都可版本化。
- 检索、rerank、问答、摘要质量通过自动化评估命令衡量。
- 单元、集成、端到端、安全和契约测试通过 CI 自动运行。

理由：

- RAG 质量容易随模型、chunking、prompt 和 rerank 调整发生回退。
- 自动化评估能把质量变化量化，适合作为版本迭代依据。
- 自动化测试能保证接口、存储、配置和安全规则不被破坏。

### 12.10 Agent 使用短上下文和结构化状态

决策：

- Scheduler、Analyzer、Collector、Organizer 之间传递结构化对象，不传递完整对话历史。
- 每个 agent 只读取当前阶段必需的 `JobContext` 子集。
- 长期状态、运行摘要、hash、commit 和错误记录保存在 SQLite。

理由：

- 避免定时任务长期运行后上下文无限增长。
- 降低 LLM token 成本和隐私暴露面。
- 让采集流程可测试、可恢复、可审计。

## 13. 风险与约束

### 隐私风险

- 即使 Qdrant Cloud 默认不保存正文，chunk 正文仍会发送给云端 embedding 和 LLM provider。
- metadata 可能包含敏感路径、repo 名称、论文主题或内部项目名。
- `.env`、日志、测试报告或评估报告如果处理不当，可能泄露 API key。

缓解：

- 支持 namespace 级 text storage mode。
- 支持 metadata 最小化。
- `.env` 加入 `.gitignore`，只提交 `.env.example`。
- 所有日志、异常、测试快照和评估报告必须执行 secret redaction。
- 后续增加脱敏、私有模型和企业策略配置。

### 成本风险

- 多步问答、MQE、HyDE 和多篇摘要都会增加 LLM 调用。
- rerank 和自动化评估会增加额外模型或 API 调用。
- 每日定时采集会带来持续的 API、下载、embedding 和 LLM 成本。
- arXiv 和 GitHub 大量导入会产生大量 embedding 成本。

缓解：

- 增加 token 预算、最大检索轮数、最大导入文件数。
- 为 collection schedule 配置 source scope、预算和最大新增文档数。
- 默认关闭 MQE、HyDE 和云端 rerank，或只在用户显式开启时使用。
- CI 中使用小型评估集和 mock provider，完整评估通过 scheduled CI 或 release gate 触发。
- 记录每次调用成本和耗时。

### 定时采集风险

- Scheduler 重复触发可能造成同一 namespace 并发写入。
- 采集任务失败可能留下部分 source 状态。
- 本机时区或部署时区变化可能导致 12:00 触发时间不符合预期。

缓解：

- SQLite 中记录 collection run 锁和状态，同一 namespace 同时只允许一个 running 任务。
- ingestion 成功后再更新 source 的最新 hash、commit 和 ingest status。
- namespace 显式保存 `collection_timezone`，默认值写入配置和运行日志。
- 失败任务记录 error_message 和 run_summary，下次增量采集继续处理。

### Agent 上下文风险

- 如果把完整历史日志或完整文档正文塞入 agent prompt，会导致成本上升和隐私风险。
- 多个 agent 共享自由文本上下文会降低可测试性和可复现性。

缓解：

- 只传递结构化 `JobContext` 和阶段输出。
- 历史状态保存在 SQLite，prompt 只读取必要摘要。
- agent 输出必须落到明确 schema，供下一阶段消费。

### 检索质量风险

- Markdown 转换质量会影响分块。
- heading_path 依赖文档结构，结构差的 PDF 可能效果不稳定。
- GitHub 仓库如果导入过多文件会引入噪音。
- rerank 模型可能把表面相似但证据不足的 chunk 排到前面。

缓解：

- 首版 GitHub 以 README、docs、Markdown 文档为主。
- 对每个 source 保存转换状态和错误信息。
- 支持手动排除路径和文件类型。
- 保留召回分数和 rerank 分数，用自动化评估监控排序回退。

### Embedding fallback 风险

- 不同 embedding 模型不能透明 fallback 到同一个索引。
- TF-IDF 不等价于 dense embedding。

缓解：

- namespace 固定 embedding profile。
- provider 不可用时优先报错或降级到单独关键词检索。
- 更换 embedding 模型需要重建索引。

### 跨机器使用风险

- 默认正文存在本地 SQLite。
- 如果只迁移 Qdrant Cloud collection，不迁移 SQLite，则无法还原正文。

缓解：

- 增加导出/导入功能。
- 对非敏感 namespace 可启用 Qdrant payload 存正文。

## 14. 后续待定项

- Qdrant namespace 隔离最终采用每 namespace 一个 collection，还是共享 collection + filter。
- CLI 配置文件格式和路径。
- GitHub 是否在 MVP 导入源代码文件。
- arXiv 搜索结果筛选规则。
- SQLite FTS 是否作为关键词检索降级。
- MQE 和 HyDE 默认是否开启。
- rerank 默认使用本地模型还是云端 provider。
- 自动化评估集首版规模和 CI 阈值。
- 每日 12:00 定时采集默认使用本机时区还是要求 namespace 显式设置时区。
- Scheduler 使用进程内 APScheduler、系统 cron，还是独立 worker。
- 企业版权限模型、审计日志和团队共享方式。
