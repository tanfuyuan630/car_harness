"""应用配置：从环境变量加载，集中管理所有可插拔组件的配置。"""
import os
from pathlib import Path
from typing import Literal
from urllib.parse import quote_plus

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # LLM 配置（OpenAI 兼容端点）
    OPENAI_API_BASE: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    OPENAI_API_KEY: str = ""
    OPENAI_MODEL: str = "kimi-k3"

    # LLM 可选参数：默认 None 表示不传，由模型使用默认值。
    # 不同模型支持的参数不同（如 kimi-k3 不支持 temperature），按需在 .env 中设置。
    LLM_TEMPERATURE: float | None = None
    LLM_MAX_TOKENS: int | None = None
    LLM_TOP_P: float | None = None

    # 多层模型路由：默认关闭，开启后按问题复杂度选择模型档位。
    # 三档模型名与分类模型均从环境变量读取，修改后需重启服务生效。
    LLM_TIER_ENABLED: bool = False
    LLM_TIER_HIGH_MODEL: str = "qwen3.8-max-0902"
    LLM_TIER_MEDIUM_MODEL: str = "qwen-plus"
    LLM_TIER_LOW_MODEL: str = "qwen-turbo"
    # 复杂度分类模型与输出 token 上限（分类结果很短）
    LLM_CLASSIFIER_MODEL: str = "qwen-turbo"
    LLM_CLASSIFIER_MAX_TOKENS: int = 200

    # 服务配置
    HOST: str = "0.0.0.0"
    PORT: int = 8000

    # 数据路径
    DATA_DIR: str = "../data"

    # 可插拔：文件系统后端 local | memory
    FILESYSTEM_BACKEND: Literal["local", "memory"] = "local"
    WORKSPACE_DIR: str = "./workspace"

    # 可插拔：Checkpointer 类型 redis | memory（memory 仅用于测试）
    CHECKPOINTER_TYPE: Literal["memory", "redis"] = "redis"

    # Redis 配置：LangGraph 检查点与线程索引
    REDIS_HOST: str = "127.0.0.1"
    REDIS_PORT: int = 6379
    REDIS_PASSWORD: str = ""
    REDIS_DB: int = 0
    # 检查点默认保留 3 天
    REDIS_CHECKPOINT_TTL_MINUTES: int = 4320
    # 维护任务扫描间隔（秒）
    REDIS_MAINTENANCE_INTERVAL_SECONDS: int = 3600
    REDIS_SOCKET_TIMEOUT_SECONDS: int = 5
    REDIS_RETRY_ATTEMPTS: int = 3

    # 错误恢复策略：临时错误重试次数、可恢复错误回到 Agent 的次数、模型请求超时
    LLM_MAX_RETRIES: int = 3
    MAX_RECOVERABLE_RETRIES: int = 2
    OPENAI_TIMEOUT_SECONDS: int = 120

    # 可插拔：子智能体开关（逗号分隔）
    ENABLED_SUBAGENTS: str = ""

    # MySQL 数据库配置
    MYSQL_HOST: str = "127.0.0.1"
    MYSQL_PORT: int = 3306
    MYSQL_USER: str = "root"
    MYSQL_PASSWORD: str = ""
    MYSQL_DATABASE: str = "car_harness"

    # JWT 鉴权配置
    JWT_SECRET: str = "change-me"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 1440

    # 飞书渠道配置：默认关闭，开启需配置应用凭据
    FEISHU_ENABLED: bool = False
    FEISHU_APP_ID: str = ""
    FEISHU_APP_SECRET: str = ""

    # RAG 知识库开关
    RAG_ENABLED: bool = True

    # RAG 知识库根目录（相对 DATA_DIR，逗号分隔，递归扫描）
    RAG_KNOWLEDGE_DIRS: str = "docs,insurance"
    # Chroma 持久化目录（相对 DATA_DIR）
    RAG_CHROMA_DIR: str = "chroma_db"
    # Chroma 集合名
    RAG_COLLECTION: str = "car_knowledge"
    # 旧版 doc 转换缓存目录（相对 backend 目录）
    RAG_CACHE_DIR: str = ".cache/rag_docs"

    # RAG 模型：embedding 与 rerank
    RAG_EMBEDDING_MODEL: str = "qwen3.7-text-embedding-flash"
    RAG_RERANK_MODEL: str = "qwen3.7-text-rerank"
    RAG_RERANK_ENABLED: bool = True
    # 可选能力开关，默认关闭
    RAG_HYBRID_ENABLED: bool = False
    RAG_QUERY_REWRITE_ENABLED: bool = False
    RAG_REWRITE_NUM_QUERIES: int = 3

    # RAG 检索参数
    RAG_RETRIEVE_TOP_K: int = 10
    RAG_RERANK_TOP_N: int = 4
    RAG_CHUNK_SIZE: int = 512
    RAG_CHUNK_OVERLAP: int = 64

    # 高德地图 Web 服务 API Key（环境变量名为 AMAP_WEBSERVICE_KEY）
    AMAP_API_KEY: str = Field(default="", alias="AMAP_WEBSERVICE_KEY")

    # ACP（Agent Client Protocol）文件生成链路：默认关闭，开启需本地安装并登录 TRAE CLI
    ACP_ENABLED: bool = False
    ACP_COMMAND: str = "traecli"
    ACP_ARGS: str = "acp serve"
    ACP_TIMEOUT_SECONDS: int = 300

    @property
    def mysql_url(self) -> str:
        return (
            f"mysql+pymysql://{self.MYSQL_USER}:{self.MYSQL_PASSWORD}"
            f"@{self.MYSQL_HOST}:{self.MYSQL_PORT}/{self.MYSQL_DATABASE}"
            f"?charset=utf8mb4"
        )

    @property
    def redis_url(self) -> str:
        """Redis 连接串，密码做 URL 编码；无密码时省略认证段。"""
        auth = f":{quote_plus(self.REDIS_PASSWORD)}@" if self.REDIS_PASSWORD else ""
        return f"redis://{auth}{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"

    @property
    def data_dir_path(self) -> Path:
        return Path(self.DATA_DIR).resolve()

    @property
    def workspace_dir_path(self) -> Path:
        p = Path(self.WORKSPACE_DIR)
        if not p.is_absolute():
            p = Path(__file__).resolve().parent.parent / p
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def rag_knowledge_dirs_list(self) -> list[str]:
        """知识库根目录列表，相对 DATA_DIR。"""
        return [d.strip() for d in self.RAG_KNOWLEDGE_DIRS.split(",") if d.strip()]

    @property
    def rag_knowledge_dir_paths(self) -> list[Path]:
        """知识库根目录绝对路径列表。"""
        return [self.data_dir_path / d for d in self.rag_knowledge_dirs_list]

    @property
    def rag_chroma_dir_path(self) -> Path:
        """Chroma 持久化目录：DATA_DIR 下，目录不存在时自动创建。"""
        p = self.data_dir_path / self.RAG_CHROMA_DIR
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def rag_cache_dir_path(self) -> Path:
        """旧版 doc 转换为 docx 的缓存目录：相对 backend 目录，自动创建。"""
        p = Path(self.RAG_CACHE_DIR)
        if not p.is_absolute():
            # config.py 位于 backend/app/core，三级 parent 才是 backend 目录
            p = Path(__file__).resolve().parent.parent.parent / p
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def enabled_subagents_list(self) -> list[str]:
        if not self.ENABLED_SUBAGENTS.strip():
            return []
        return [s.strip() for s in self.ENABLED_SUBAGENTS.split(",") if s.strip()]


settings = Settings()
