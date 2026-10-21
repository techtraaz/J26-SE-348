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
    # none turns off thinking on reasoning models (Qwen 3.5 on Ollama); empty = server default
    llm_reasoning_effort: str | None = None
    # paragraphs sent to the LLM at the same time; match the server's parallel slots
    llm_workers: int = 1

    # embeddings can be served from a different pod than the chat model
    embedding_base_url: str | None = None
    embedding_model: str = "nomic-embed-text"
    embedding_dim: int = 768

    # read-only Cypher endpoint for people (debugging, demo); agents use the fixed queries
    query_cypher_enabled: bool = True
    query_cypher_timeout: float = 10.0
    query_cypher_max_rows: int = 500

    # S3-compatible object storage (Garage), same bucket as the other components
    garage_endpoint: str = ""
    garage_access_key: str = ""
    garage_secret_key: str = ""
    garage_bucket: str = "uploads"
    policies_prefix: str = "c02-policies"
    policy_max_mb: int = 50

    # comma separated origins allowed to call the API from a browser (the frontend)
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"


@lru_cache
def get_settings() -> Settings:
    return Settings()
