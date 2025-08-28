"""
Production-grade user context for the RAG stack.

Responsibilities
- Capture per-request identity, scoping, preferences, and feature flags
- Provide safe logging views (PII-aware)
- Build LlamaIndex metadata filters
- Provide stable cache key seeds
- Bind/clear structlog contextvars
- Offer flexible constructors for Azure Functions / FastAPI / direct usage

This module intentionally avoids Pydantic to prevent attribute setting constraints
in runtime pipelines.
"""
from __future__ import annotations

import hashlib
import os
import uuid
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional

import structlog
from llama_index.core.vector_stores import MetadataFilter, MetadataFilters

# --------------------------------------------------------------------------------------
# Constants & helpers
# --------------------------------------------------------------------------------------
REDACT_TOKEN = "«redacted»"
DEFAULT_LOCALE = os.getenv("APP_DEFAULT_LOCALE", "en-US")
DEFAULT_TZ = os.getenv("APP_DEFAULT_TZ", "UTC")


def _redact(value: Optional[str]) -> Optional[str]:
    if value in (None, ""):
        return value
    tail = value[-4:] if len(value) > 4 else value
    return f"{REDACT_TOKEN}:{tail}"


def _coerce_int(v: Any, default: int) -> int:
    try:
        return int(v)
    except Exception:
        return default


def _coerce_float(v: Any, default: float) -> float:
    try:
        return float(v)
    except Exception:
        return default


# --------------------------------------------------------------------------------------
# Data classes
# --------------------------------------------------------------------------------------
@dataclass
class FeatureFlags:
    enable_cache: bool = True
    enable_rerank: bool = True
    enable_debug_logs: bool = False
    include_user_ids_in_logs: bool = False  # controls PII in logs
    trace_headers_to_log: bool = True       # copy correlation/request ids into logs


@dataclass
class RetrievalPrefs:
    top_k: int = 6
    similarity_threshold: float = 0.15
    min_results: int = 3

    def normalize(self) -> None:
        # Basic safety clamps
        self.top_k = max(1, min(self.top_k, 1000))
        self.min_results = max(0, min(self.min_results, self.top_k))
        self.similarity_threshold = max(0.0, min(self.similarity_threshold, 1.0))


@dataclass
class SecurityContext:
    roles: List[str] = field(default_factory=list)
    scopes: List[str] = field(default_factory=list)

    def as_logging_dict(self) -> Dict[str, Any]:
        return {
            "roles": sorted(set(self.roles)) if self.roles else [],
            "scopes": sorted(set(self.scopes)) if self.scopes else [],
        }


@dataclass
class ABTestBucket:
    experiment: Optional[str] = None
    bucket: Optional[str] = None  # e.g., "A" / "B" / "control" / "treatment"


@dataclass
class UserContext:
    # Identity / tenancy
    tenant_id: Optional[str] = None
    user_id: Optional[str] = None
    session_id: str = field(default_factory=lambda: f"ses-{uuid.uuid4()}")

    # Correlation / tracing
    request_id: str = field(default_factory=lambda: f"req-{uuid.uuid4()}")
    correlation_id: Optional[str] = None  # may come from gateway headers

    # Query scoping (mirrors your retrieval filters)
    project_id: Optional[int] = None
    document_content_type: Optional[str] = None

    # Locale / UX
    locale: str = DEFAULT_LOCALE
    timezone: str = DEFAULT_TZ

    # Flags & prefs
    flags: FeatureFlags = field(default_factory=FeatureFlags)
    prefs: RetrievalPrefs = field(default_factory=RetrievalPrefs)

    # Security & experiments
    security: SecurityContext = field(default_factory=SecurityContext)
    abtest: ABTestBucket = field(default_factory=ABTestBucket)

    # Arbitrary metadata carried through the pipeline
    extra: Dict[str, Any] = field(default_factory=dict)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def __post_init__(self) -> None:
        # Normalize numeric prefs to valid ranges
        if self.prefs:
            self.prefs.normalize()
        # Generate correlation id if absent
        if not self.correlation_id:
            self.correlation_id = f"corr-{uuid.uuid4()}"

    # Context manager to auto-bind structlog context
    def __enter__(self) -> "UserContext":
        self.bind_log_context()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.clear_log_context()

    # ------------------------------------------------------------------
    # Builders / Views
    # ------------------------------------------------------------------
    def to_llamaindex_filters(self) -> Optional[MetadataFilters]:
        """Translate scoping to LlamaIndex filters."""
        filters: List[MetadataFilter] = []
        if self.project_id is not None:
            filters.append(MetadataFilter(key="project_id", value=str(self.project_id)))
        if self.document_content_type:
            filters.append(MetadataFilter(key="document_content_type", value=self.document_content_type))
        return MetadataFilters(filters=filters) if filters else None

    def to_logging_dict(self, *, include_pii: Optional[bool] = None) -> Dict[str, Any]:
        """Safe dict for logs; respects include_user_ids_in_logs."""
        include = self.flags.include_user_ids_in_logs if include_pii is None else include_pii
        payload = {
            "tenant_id": self.tenant_id if include else _redact(self.tenant_id),
            "user_id": self.user_id if include else _redact(self.user_id),
            "session_id": self.session_id,
            "request_id": self.request_id,
            "correlation_id": self.correlation_id,
            "project_id": self.project_id,
            "document_content_type": self.document_content_type,
            "locale": self.locale,
            "timezone": self.timezone,
            "flags": asdict(self.flags),
            "prefs": asdict(self.prefs),
            "security": self.security.as_logging_dict(),
            "abtest": asdict(self.abtest),
        }
        if self.extra:
            # Avoid dumping large payloads; record only keys
            payload["extra_keys"] = list(self.extra.keys())
        return payload

    def to_prompt_context(self) -> Dict[str, Any]:
        """Small, helpful context for system/instruction prompts."""
        return {
            "tenant_id": self.tenant_id,
            "project_id": self.project_id,
            "document_content_type": self.document_content_type,
            "locale": self.locale,
            "timezone": self.timezone,
            "abtest_bucket": self.abtest.bucket,
        }

    def cache_key_seed(self) -> str:
        """Stable, non-PII seed for caches/metrics bucketing."""
        material = f"{self.tenant_id}|{self.project_id}|{self.document_content_type}"
        return hashlib.sha256(material.encode("utf-8")).hexdigest()

    # ------------------------------------------------------------------
    # Structlog integration
    # ------------------------------------------------------------------
    def bind_log_context(self) -> None:
        payload = self.to_logging_dict()
        structlog.contextvars.bind_contextvars(**payload)

    @staticmethod
    def clear_log_context() -> None:
        structlog.contextvars.clear_contextvars()

    # ------------------------------------------------------------------
    # Constructors
    # ------------------------------------------------------------------
    @staticmethod
    def from_headers_and_body(headers: Dict[str, Any] | None, body: Dict[str, Any] | None) -> "UserContext":
        headers = headers or {}
        body = body or {}

        flags = FeatureFlags(
            enable_cache=bool(_coerce_int(body.get("enable_cache", 1), 1)),
            enable_rerank=bool(_coerce_int(body.get("enable_rerank", 1), 1)),
            enable_debug_logs=bool(_coerce_int(body.get("enable_debug_logs", 0), 0)),
            include_user_ids_in_logs=bool(_coerce_int(body.get("include_user_ids_in_logs", 0), 0)),
            trace_headers_to_log=True,
        )
        prefs = RetrievalPrefs(
            top_k=_coerce_int(body.get("top_k", 6), 6),
            similarity_threshold=_coerce_float(body.get("threshold", 0.15), 0.15),
            min_results=_coerce_int(body.get("min_results", 3), 3),
        )

        ctx = UserContext(
            tenant_id=headers.get("X-Tenant") or body.get("tenant_id"),
            user_id=headers.get("X-User") or body.get("user_id"),
            session_id=headers.get("X-Session-Id") or body.get("session_id") or f"ses-{uuid.uuid4()}",
            request_id=headers.get("X-Request-Id") or f"req-{uuid.uuid4()}",
            correlation_id=headers.get("X-Correlation-Id") or body.get("correlation_id"),
            project_id=_coerce_int(body.get("project_id"), None) if body.get("project_id") is not None else None,
            document_content_type=body.get("document_content_type"),
            locale=body.get("locale") or DEFAULT_LOCALE,
            timezone=body.get("timezone") or DEFAULT_TZ,
            flags=flags,
            prefs=prefs,
            security=SecurityContext(
                roles=body.get("roles", []) or [],
                scopes=body.get("scopes", []) or [],
            ),
            abtest=ABTestBucket(
                experiment=body.get("experiment"),
                bucket=body.get("bucket"),
            ),
            extra=body.get("extra", {}) or {},
        )
        return ctx

    @staticmethod
    def from_azure_functions_http(req) -> "UserContext":  # type: ignore[override]
        """Lightweight adapter for Azure Functions HttpRequest.
        Expects methods: headers.get, get_json(), route_params, etc.
        """
        try:
            body = req.get_json() or {}
        except Exception:
            body = {}
        headers = {k: v for k, v in (req.headers or {}).items()}
        return UserContext.from_headers_and_body(headers, body)

    @staticmethod
    def from_fastapi(request) -> "UserContext":  # type: ignore[override]
        """Adapter for FastAPI Request."""
        headers = dict(request.headers)
        try:
            # If called in sync context, caller should pass body separately.
            body = request.json()
        except Exception:
            body = {}
        return UserContext.from_headers_and_body(headers, body)


# --------------------------------------------------------------------------------------
# Convenience context manager for ad-hoc usage
# --------------------------------------------------------------------------------------
class bind_user_context:
    """with bind_user_context(ctx): ... -> binds structlog context for the block"""

    def __init__(self, ctx: UserContext):
        self.ctx = ctx

    def __enter__(self):
        self.ctx.bind_log_context()
        return self.ctx

    def __exit__(self, exc_type, exc, tb):
        UserContext.clear_log_context()
        return False
