"""Single place for all settings. Change model here only."""

# Ollama model name. Start with phi4-mini, change later in 1 place.
MODEL_NAME: str = "phi4-mini"

# NEVER let the LLM write free Cypher at run time. Small models make mistakes.
# Only fixed functions in kg_client.py may talk to the graph.
ALLOW_FREE_CYPHER: bool = False

# Year-to-year jump limit (30%). If change is bigger, flag it.
YEAR_CHANGE_LIMIT: float = 0.30

# Small number tolerance for float maths (1 cent).
AMOUNT_TOLERANCE: float = 0.01

# API version tag for findings. Old versions are kept, never overwritten.
FINDINGS_STATUS_DEFAULT: str = "pending_auditor_review"
