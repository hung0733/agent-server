# EmbeddingAgent 使用指南

## 概述

`EmbeddingAgent` 提供文本嵌入（embedding）和重排序（rerank）功能，使用 Hugging Face Text Embeddings Inference (TEI) 服務。

## 環境配置

在 `.env` 文件中配置以下變量：

```bash
# Embedding 服務 endpoint
EMBEDDING_ENDPOINT=http://localhost:8605

# Reranker 服務 endpoint
RERANK_ENDPOINT=http://localhost:8606
```

## Docker 服務配置

參考 `embedding.yml` 啟動服務：

```yaml
services:
  # Embedding 服務 (負責將 Text 變做 Vector)
  embedding-api:
    container_name: embedding-ai
    image: ghcr.io/huggingface/text-embeddings-inference:cpu-1.6
    ports:
      - "8605:80"
    volumes:
      - /mnt/models/huggingface/hub/:/data
    command: --model-id BAAI/bge-m3

  # Reranker 服務 (負責重新排序，提高精準度)
  reranker-api:
    container_name: reranker-ai
    image: ghcr.io/huggingface/text-embeddings-inference:cpu-1.6
    ports:
      - "8606:80"
    volumes:
      - /mnt/models/huggingface/hub/:/data
    command: --model-id BAAI/bge-reranker-v2-m3
```

啟動服務：
```bash
docker-compose -f embedding.yml up -d
```

## 使用方法

### 基本使用

```python
from llm.embedding_agent import EmbeddingAgent

# 創建 Agent（自動從環境變量讀取配置）
agent = EmbeddingAgent()

# 或使用自定義 endpoint
agent = EmbeddingAgent(
    embedding_endpoint="http://localhost:8605",
    rerank_endpoint="http://localhost:8606"
)
```

### Embedding

```python
# 單個文本嵌入
embedding = await agent.embed("Hello world")
print(f"Vector dimension: {len(embedding)}")

# 批量文本嵌入
embeddings = await agent.embed(["Hello", "World", "Test"])
print(f"Number of embeddings: {len(embeddings)}")

# 專門用於查詢的嵌入
query_embedding = await agent.embed_query("機器學習是什麼？")

# 專門用於文檔的嵌入
doc_embeddings = await agent.embed_documents(["文檔 1", "文檔 2", "文檔 3"])
```

### Rerank

```python
# 基本重排序
query = "機器學習"
documents = ["深度學習基礎", "烹飪食譜大全", "神經網絡原理", "旅遊指南"]

results = await agent.rerank(query, documents)
# 返回：[(索引，分數), ...] 按相關性降序排列

# 限制返回數量
top_2 = await agent.rerank(query, documents, top_n=2)

# 只返回索引，不返回分數
indices_only = await agent.rerank(query, documents, return_scores=False)
```

### 相似度搜索

```python
# 準備文檔和預先計算的嵌入
documents = ["文檔 A", "文檔 B", "文檔 C"]
doc_embeddings = await agent.embed_documents(documents)

# 執行相似度搜索
query = "人工智能"
results = await agent.similarity_search(
    query=query,
    documents=documents,
    document_embeddings=doc_embeddings,
    top_n=3,
    threshold=0.5  # 相似度閾值
)

# 返回：[(索引，文檔內容，相似度分數), ...]
for idx, doc, score in results:
    print(f"[{score:.3f}] {doc}")
```

### 使用 Context Manager

```python
async with EmbeddingAgent() as agent:
    embedding = await agent.embed("Hello")
    # 自動清理資源
```

### 手動關閉

```python
agent = EmbeddingAgent()
try:
    embedding = await agent.embed("Hello")
finally:
    await agent.close()
```

## API 參數說明

### embed() 方法

| 參數 | 類型 | 默認值 | 說明 |
|------|------|--------|------|
| texts | str \| List[str] | - | 單個文本或文本列表 |
| normalize | bool | True | 是否標準化向量 |
| pooling | str | "cls" | pooling 策略："cls" 或 "mean" |

### rerank() 方法

| 參數 | 類型 | 默認值 | 說明 |
|------|------|--------|------|
| query | str | - | 查詢文本 |
| documents | List[str] | - | 待排序的文檔列表 |
| top_n | int \| None | None | 返回前 N 個結果 |
| return_scores | bool | True | 是否返回分數 |

### similarity_search() 方法

| 參數 | 類型 | 默認值 | 說明 |
|------|------|--------|------|
| query | str | - | 查詢文本 |
| documents | List[str] | - | 文檔列表 |
| document_embeddings | List[List[float]] | - | 預先計算的文檔向量 |
| top_n | int | 5 | 返回最相似的 N 個結果 |
| threshold | float | 0.0 | 相似度閾值 |

## 錯誤處理

```python
try:
    embedding = await agent.embed("Hello")
except Exception as e:
    print(f"Embedding failed: {e}")
```

常見錯誤：
- 服務未啟動：檢查 Docker 容器是否運行
- 連接超時：檢查 endpoint 配置是否正確
- 模型加載失敗：檢查模型文件是否存在於指定目錄
