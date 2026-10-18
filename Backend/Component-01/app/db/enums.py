"""String enums stored as plain text columns (not database ENUM types), so
adding a value later never needs an ALTER TYPE migration."""

from enum import Enum


class DocumentStatus(str, Enum):
    UPLOADED = "uploaded"
    PROCESSING = "processing"
    NEEDS_REVIEW = "needs_review"
    VERIFIED = "verified"
    FAILED = "failed"


class DocumentSource(str, Enum):
    """Ethics gate (D12): demo/sample data vs. the research corpus."""

    DEMO = "demo"
    RESEARCH = "research"


class RunStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class PipelineMode(str, Enum):
    OCR_ONLY = "ocr_only"
    STATIC_HYBRID = "static_hybrid"  # Phase 2
    ADAPTIVE = "adaptive"  # Phase 3