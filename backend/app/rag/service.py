"""RAG 服务：中文分块、Chroma 向量持久化、向量/混合检索与重排。

索引在首次检索时惰性构建，构建结果缓存在模块单例中；Chroma 集合已存在时直接复用，
不重复向量化。
"""
from __future__ import annotations

import logging
import re
import threading
import time
from typing import Any

import chromadb
from llama_index.core import StorageContext, VectorStoreIndex
from llama_index.core.ingestion import IngestionPipeline
from llama_index.core.node_parser import SentenceSplitter
from llama_index.core.retrievers import QueryFusionRetriever
from llama_index.core.retrievers.fusion_retriever import FUSION_MODES
from llama_index.core.schema import BaseNode, QueryBundle, TextNode
from llama_index.core.vector_stores import MetadataFilter, MetadataFilters
from llama_index.retrievers.bm25 import BM25Retriever
from llama_index.vector_stores.chroma import ChromaVectorStore

from app.core.config import settings
from app.rag.doc_loader import load_documents
from app.rag.embeddings import get_embedding
from app.rag.reranker import get_reranker
from app.rag.rewriter import get_rewrite_llm

logger = logging.getLogger(__name__)

# 查询改写提示词：要求模型输出多个语义等价的中文查询，每行一个
_QUERY_GEN_PROMPT = """你是汽车销售领域的检索查询改写助手。请基于原始问题生成 {num_queries} 个语义等价、表述不同的中文检索查询，可补充同义词或书面化表述。每行一个查询，不要编号，不要输出其他内容。
原始问题：{query}"""

# 中文按单字切分，英文与数字按连续字符切分，供 BM25 分词使用
_BM25_TOKEN_PATTERN = r"[\u4e00-\u9fff]|[A-Za-z0-9]+"


def _split_chinese_sentences(text: str) -> list[str]:
    """按中文标点与换行断句，供 SentenceSplitter 使用。"""
    parts = re.split(r"(?<=[。！？；])|\n+", text)
    return [p.strip() for p in parts if p.strip()]


class RAGService:
    """RAG 检索服务：负责索引生命周期与检索流程编排。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._index: VectorStoreIndex | None = None
        self._collection: Any = None
        self._nodes: list[BaseNode] = []
        # 按领域缓存的 BM25 检索器，键为领域标识，空串表示全库
        self._bm25: dict[str, BM25Retriever] = {}
        self._document_count: int = 0

    # ---------------- Chroma 集合 ----------------

    def _get_collection(self) -> Any:
        """获取（或创建）Chroma 持久化集合，距离度量使用余弦。"""
        client = chromadb.PersistentClient(path=str(settings.rag_chroma_dir_path))
        return client.get_or_create_collection(
            name=settings.RAG_COLLECTION,
            metadata={"hnsw:space": "cosine"},
        )

    # ---------------- 索引构建 ----------------

    def _build(self, collection: Any) -> tuple[int, list[BaseNode]]:
        """加载文档、中文分块并向量化写入 Chroma。"""
        start = time.time()
        documents = load_documents()

        splitter = SentenceSplitter(
            chunk_size=settings.RAG_CHUNK_SIZE,
            chunk_overlap=settings.RAG_CHUNK_OVERLAP,
            chunking_tokenizer_fn=_split_chinese_sentences,
        )
        pipeline = IngestionPipeline(transformations=[splitter])
        nodes = pipeline.run(documents=documents, show_progress=False)

        vector_store = ChromaVectorStore(chroma_collection=collection)
        storage_context = StorageContext.from_defaults(vector_store=vector_store)
        VectorStoreIndex(
            nodes=nodes,
            storage_context=storage_context,
            embed_model=get_embedding(),
            show_progress=False,
        )

        logger.info(
            "索引构建完成：文档 %d 篇，分块 %d 个，耗时 %.2f 秒",
            len(documents),
            len(nodes),
            time.time() - start,
        )
        return len(documents), list(nodes)

    def ensure_index(self) -> VectorStoreIndex:
        """返回可用的向量索引；已构建则直接复用，避免重复向量化。"""
        if self._index is not None:
            return self._index

        with self._lock:
            # 锁内二次检查，避免并发重复构建
            if self._index is not None:
                return self._index

            collection = self._get_collection()
            if collection.count() == 0:
                self._document_count, self._nodes = self._build(collection)
            else:
                start = time.time()
                data = collection.get(include=["documents", "metadatas"])
                self._nodes = [
                    TextNode(text=text, metadata=metadata or {})
                    for text, metadata in zip(data["documents"], data["metadatas"])
                ]
                self._document_count = len(
                    {node.metadata.get("file_name", "") for node in self._nodes}
                )
                logger.info(
                    "复用已有 Chroma 集合：文档 %d 篇，分块 %d 个，耗时 %.2f 秒",
                    self._document_count,
                    len(self._nodes),
                    time.time() - start,
                )

            self._collection = collection
            self._index = VectorStoreIndex.from_vector_store(
                vector_store=ChromaVectorStore(chroma_collection=collection),
                embed_model=get_embedding(),
            )
            return self._index

    def rebuild(self) -> dict[str, int]:
        """删除已有集合后全量重建索引，返回文档数与分块数。"""
        with self._lock:
            client = chromadb.PersistentClient(path=str(settings.rag_chroma_dir_path))
            if any(c.name == settings.RAG_COLLECTION for c in client.list_collections()):
                client.delete_collection(name=settings.RAG_COLLECTION)
                logger.info("已删除旧 Chroma 集合 %s", settings.RAG_COLLECTION)

            self._index = None
            self._collection = None
            self._nodes = []
            self._bm25 = {}
            self._document_count = 0

            collection = self._get_collection()
            self._document_count, self._nodes = self._build(collection)
            self._collection = collection
            self._index = VectorStoreIndex.from_vector_store(
                vector_store=ChromaVectorStore(chroma_collection=collection),
                embed_model=get_embedding(),
            )
            return {"documents": self._document_count, "chunks": len(self._nodes)}

    # ---------------- 检索 ----------------

    def _domain_nodes(self, domain: str | None) -> list[BaseNode]:
        """返回指定领域的分块；domain 为空时返回全部分块。"""
        if domain is None:
            return self._nodes
        return [node for node in self._nodes if node.metadata.get("domain") == domain]

    def _get_bm25_retriever(self, domain: str | None, top_k: int) -> BM25Retriever | None:
        """获取指定领域的 BM25 检索器，按领域惰性构建并缓存；领域内无分块返回 None。"""
        nodes = self._domain_nodes(domain)
        if not nodes:
            return None

        cache_key = domain or ""
        retriever = self._bm25.get(cache_key)
        if retriever is None:
            retriever = BM25Retriever.from_defaults(
                nodes=nodes,
                similarity_top_k=top_k,
                skip_stemming=True,
                token_pattern=_BM25_TOKEN_PATTERN,
            )
            self._bm25[cache_key] = retriever
            logger.info("BM25 检索器已就绪：领域 %s，分块 %d 个", cache_key or "全部", len(nodes))
        else:
            retriever.similarity_top_k = top_k
        return retriever

    def retrieve(self, query: str, top_k: int | None = None, domain: str | None = None) -> list[dict]:
        """检索知识库：按领域过滤后向量召回（可选混合、查询改写）再重排并截断。"""
        index = self.ensure_index()

        # 领域内没有分块时直接返回空结果，不扩展到其他领域
        if domain is not None and not self._domain_nodes(domain):
            return []

        recall_k = settings.RAG_RETRIEVE_TOP_K
        rewrite_enabled = settings.RAG_QUERY_REWRITE_ENABLED

        filters = None
        if domain is not None:
            filters = MetadataFilters(filters=[MetadataFilter(key="domain", value=domain)])
        vector_retriever = index.as_retriever(similarity_top_k=recall_k, filters=filters)

        retrievers = [vector_retriever]
        if settings.RAG_HYBRID_ENABLED:
            bm25_retriever = self._get_bm25_retriever(domain, recall_k)
            if bm25_retriever is not None:
                retrievers.append(bm25_retriever)

        if settings.RAG_HYBRID_ENABLED or rewrite_enabled:
            # 混合检索用 RRF 融合。QueryFusionRetriever 要求必须传入 llm 实例，
            # 未开启查询改写时 num_queries 为 1，不会真正调用模型
            fusion = QueryFusionRetriever(
                retrievers,
                llm=get_rewrite_llm(),
                query_gen_prompt=_QUERY_GEN_PROMPT if rewrite_enabled else None,
                mode=FUSION_MODES.RECIPROCAL_RANK,
                similarity_top_k=recall_k,
                num_queries=settings.RAG_REWRITE_NUM_QUERIES if rewrite_enabled else 1,
                use_async=False,
            )
            nodes = fusion.retrieve(query)
        else:
            nodes = vector_retriever.retrieve(query)

        if settings.RAG_RERANK_ENABLED and nodes:
            nodes = get_reranker().postprocess_nodes(nodes, query_bundle=QueryBundle(query))

        final_k = top_k or settings.RAG_RERANK_TOP_N
        return [
            {
                "content": node.node.get_content().strip(),
                "source": node.node.metadata.get("file_name", ""),
                "score": round(float(node.score or 0.0), 4),
            }
            for node in nodes[:final_k]
        ]


rag_service = RAGService()
