"""Single place for all settings. Change model here only."""

import os

# Set OLLAMA_HOST for the ollama Python SDK — routes LLM calls to cloud GPU
# The SDK reads this env var automatically, so no code changes needed in llm.py
if not os.getenv("OLLAMA_HOST"):
    os.environ["OLLAMA_HOST"] = "https://described-completing-classroom-fans.trycloudflare.com"

# Ollama model name. Changed from phi4-mini to phi4 (cloud GPU).
MODEL_NAME: str = os.getenv("C03_MODEL_NAME", "phi4")

# NEVER let the LLM write free Cypher at run time. Small models make mistakes.
# Only fixed functions in kg_client.py may talk to the graph.
ALLOW_FREE_CYPHER: bool = False

# Year-to-year jump limit (30%). If change is bigger, flag it.
YEAR_CHANGE_LIMIT: float = 0.30

# Small number tolerance for float maths (1 cent).
AMOUNT_TOLERANCE: float = 0.01

# API version tag for findings. Old versions are kept, never overwritten.
FINDINGS_STATUS_DEFAULT: str = "pending_auditor_review"
