from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Nomos Component 02 - Audit Knowledge Graph & Ledger"

    # Neo4j AuraDB
    neo4j_uri: str = "neo4j://localhost:7687"
    neo4j_username: str = "neo4j"
    neo4j_password: str = ""
    neo4j_database: str = "neo4j"

    # LLM for KG construction, any OpenAI-compatible server (Ollama, vLLM on RunPod)
    # llm_provider: openai (real server) or fake (no server, fixed answers)
    llm_provider: str = "openai"
    llm_base_url: str = "http://localhost:11434/v1"
    llm_api_key: str = "not-needed"
    llm_model: str = "phi4-mini"
    llm_temperature: float = 0.0
    llm_timeout: float = 120.0
    llm_max_retries: int = 2

    # embeddings can be served from a different pod than the chat model
    embedding_base_url: str | None = None
    embedding_model: str = "nomic-embed-text"
    embedding_dim: int = 768


@lru_cache
def get_settings() -> Settings:
    return Settings()
