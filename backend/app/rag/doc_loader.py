"""RAG 文档加载：递归扫描知识库目录，按真实格式归一化文档并写入领域元数据。"""
from __future__ import annotations

import logging
import shutil
from pathlib import Path

import pythoncom
import win32com.client
from llama_index.core import SimpleDirectoryReader
from llama_index.core.schema import Document
from llama_index.readers.file import DocxReader

from app.core.config import settings
from app.rag.domains import resolve_domain

logger = logging.getLogger(__name__)

# 支持的知识库文档后缀
_SUPPORTED_SUFFIXES = {".md", ".doc", ".docx"}

# 文件头魔数：OLE2 复合文档（旧版 doc）
_OLE2_MAGIC = bytes.fromhex("D0CF11E0A1B11AE1")
# 文件头魔数：ZIP 容器（docx）
_ZIP_MAGIC = b"PK\x03\x04"
# Word 另存为 docx 对应的 FileFormat 常量（wdFormatXMLDocument）
_WD_FORMAT_DOCX = 16


def _detect_format(path: Path) -> str:
    """按文件头魔数判断真实格式，返回 ole2 或 zip。"""
    with open(path, "rb") as f:
        head = f.read(8)
    if head == _OLE2_MAGIC:
        return "ole2"
    if head[:4] == _ZIP_MAGIC:
        return "zip"
    raise ValueError(f"无法识别的文档格式：{path}")


def _is_cache_fresh(source: Path, cache: Path) -> bool:
    """缓存文件存在且修改时间不早于源文件时，视为可复用。"""
    if not cache.exists():
        return False
    return cache.stat().st_mtime >= source.stat().st_mtime


def _convert_doc_to_docx(source: Path, target: Path) -> None:
    """用 Word COM 把旧版 doc 另存为 docx。"""
    pythoncom.CoInitialize()
    word = None
    doc = None
    try:
        try:
            word = win32com.client.DispatchEx("Word.Application")
            word.Visible = False
            word.DisplayAlerts = 0
            doc = word.Documents.Open(str(source), ReadOnly=True)
            doc.SaveAs2(str(target), FileFormat=_WD_FORMAT_DOCX)
        except Exception:
            logger.exception("Word 转换失败：%s", source)
            raise
    finally:
        if doc is not None:
            doc.Close(False)
            doc = None
        if word is not None:
            word.Quit()
            word = None
        pythoncom.CoUninitialize()


def _collect_sources() -> dict[Path, str]:
    """递归扫描知识库根目录，返回 源文件 -> 领域。未命中的文件跳过并记录日志。"""
    data_dir = settings.data_dir_path
    sources: dict[Path, str] = {}
    for root in settings.rag_knowledge_dir_paths:
        if not root.exists():
            logger.warning("知识库根目录不存在，跳过：%s", root)
            continue
        for path in sorted(root.rglob("*")):
            if not path.is_file() or path.suffix.lower() not in _SUPPORTED_SUFFIXES:
                continue
            relative = path.relative_to(data_dir).as_posix()
            domain = resolve_domain(relative)
            if domain is None:
                logger.warning("未映射知识域，跳过文档：%s", relative)
                continue
            sources[path] = domain
    return sources


def _prepare_files(sources: dict[Path, str]) -> dict[Path, tuple[Path, str]]:
    """归一化文档为可加载文件，返回 加载文件 -> (源文件, 领域)。

    旧版 doc 转换为 docx 缓存在按领域划分的子目录下，避免同名文件互相覆盖。
    """
    cache_root = settings.rag_cache_dir_path
    prepared: dict[Path, tuple[Path, str]] = {}
    for source, domain in sources.items():
        if source.suffix.lower() == ".md":
            prepared[source] = (source, domain)
            continue

        cache = cache_root / domain / f"{source.stem}.docx"
        cache.parent.mkdir(parents=True, exist_ok=True)
        fmt = _detect_format(source)
        if _is_cache_fresh(source, cache):
            logger.info("复用缓存：%s -> %s", source.name, cache)
        elif fmt == "zip":
            shutil.copy2(source, cache)
            logger.info("ZIP 格式直接复制到缓存：%s -> %s", source.name, cache)
        else:
            _convert_doc_to_docx(source, cache)
            logger.info("旧版 doc 已转换为 docx：%s -> %s", source.name, cache)
        prepared[cache] = (source, domain)
    return prepared


def _build_metadata(source: Path, domain: str) -> dict[str, str]:
    """构造文档元数据：保留原始文件信息与领域标识。"""
    return {
        "file_name": source.name,
        "source": str(source),
        "file_type": source.suffix.lower().lstrip("."),
        "domain": domain,
    }


def load_documents() -> list[Document]:
    """加载知识库全部文档，每个文件一个 Document，并写入原始文件信息与领域标识。"""
    sources = _collect_sources()
    logger.info("知识库扫描完成，命中文档 %d 个", len(sources))

    prepared = _prepare_files(sources)
    documents: list[Document] = []

    # doc/docx 统一走缓存 docx 读取
    docx_files = [path for path in prepared if path.suffix.lower() == ".docx"]
    if docx_files:
        reader = SimpleDirectoryReader(
            input_files=[str(path) for path in docx_files],
            file_extractor={".docx": DocxReader()},
            filename_as_id=True,
        )
        for doc in reader.load_data():
            source, domain = prepared[Path(doc.metadata["file_path"])]
            doc.metadata.update(_build_metadata(source, domain))
            documents.append(doc)

    # markdown 直接读取文本，交由后续分块统一处理
    for source, domain in prepared.values():
        if source.suffix.lower() == ".md":
            documents.append(
                Document(
                    text=source.read_text(encoding="utf-8"),
                    metadata=_build_metadata(source, domain),
                )
            )

    domain_counts: dict[str, int] = {}
    for doc in documents:
        key = doc.metadata["domain"]
        domain_counts[key] = domain_counts.get(key, 0) + 1
    logger.info("文档加载完成，共 %d 个文档，领域分布：%s", len(documents), domain_counts)
    return documents
