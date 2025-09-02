from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass, asdict
from typing import List, Dict, Any, Optional

import structlog
from prometheus_client import Histogram, Counter

# --------------------------------------------------------------------------
# Logging (structured) & Metrics
# --------------------------------------------------------------------------
structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer(),
    ],
    wrapper_class=structlog.stdlib.BoundLogger,
    logger_factory=structlog.stdlib.LoggerFactory(),
    cache_logger_on_first_use=True,
)
logger = structlog.get_logger(__name__)

ANSWER_VERIFICATION_DURATION = Histogram(
    "answer_verification_duration_seconds",
    "Time spent verifying answers",
    ["project_id"],
)

ANSWER_VERIFICATION_TOTAL = Counter(
    "answer_verification_total",
    "Number of answers verified",
    ["project_id", "status"],
)

ANSWER_VERIFICATION_FAILURES = Counter(
    "answer_verification_failures_total",
    "Number of verification failures by reason",
    ["project_id", "reason"],
)

# --------------------------------------------------------------------------
# NLI model loading (optional)
# --------------------------------------------------------------------------
try:
    from transformers import AutoTokenizer, AutoModelForSequenceClassification
    import torch

    _tok = AutoTokenizer.from_pretrained("cross-encoder/nli-deberta-v3-base")
    _nli = AutoModelForSequenceClassification.from_pretrained("cross-encoder/nli-deberta-v3-base")
    _use_nli = True
except Exception as e:
    _tok = _nli = None
    _use_nli = False
    logger.warning("NLI model not available; entailment verification disabled", error=str(e))

# --------------------------------------------------------------------------
# Numeric regex + helpers
# --------------------------------------------------------------------------
# Matches: 1,200 or 1200 or 12.5% or $1,200.00 etc.
NUM = re.compile(r"\d{1,3}(?:,\d{3})*(?:\.\d+)?%?|\d+(?:\.\d+)?%?")

def _to_floats(num: str) -> List[float]:
    """Turn a matched numeric string into float(s). Handles commas & %."""
    s = num.replace(",", "").strip()
    is_pct = s.endswith("%")
    if is_pct:
        s = s[:-1].strip()
    try:
        v = float(s)
        return [v / 100.0] if is_pct else [v]
    except Exception:
        return []

def numbers_supported(answer: str, sources: List[str], tol: float = 0.01) -> bool:
    """
    Check numeric consistency between answer and sources.

    - Accepts formats with commas and percents.
    - Uses relative tolerance `tol` (e.g. 0.01 = ±1%) to tolerate minor rounding.
    - Returns True if every numeric value in the answer is matched by at least one
      numeric value in sources within tolerance.
    """
    answer_nums = NUM.findall(answer or "")
    if not answer_nums:
        return True

    src_nums = NUM.findall(" ".join(sources or []))
    src_vals: List[float] = []
    for s in src_nums:
        src_vals.extend(_to_floats(s))

    if not src_vals:
        # answer included numbers but sources do not
        return False

    for a in answer_nums:
        target_vals = _to_floats(a)
        if not target_vals:
            # if we can't parse the target numeric, conservatively mark as unsupported
            return False
        ok = any(
            any(abs(tv - sv) <= max(tol * max(1.0, abs(tv)), 1e-6) for sv in src_vals)
            for tv in target_vals
        )
        if not ok:
            return False
    return True

# --------------------------------------------------------------------------
# Config dataclass
# --------------------------------------------------------------------------
@dataclass
class AnswerVerifierConfig:
    min_entailment_threshold: float = float(os.getenv("ANSWER_MIN_ENTAILMENT", "0.55"))
    enable_number_check: bool = True
    enable_entailment_check: bool = True
    max_premise_chars: int = 4000
    project_id: Optional[str] = None

# --------------------------------------------------------------------------
# NLI entailment wrapper
# --------------------------------------------------------------------------
def nli_entails(premise: str, hypothesis: str) -> float:
    """Return entailment probability (0..1). Fallback 0.5 if model not available."""
    if not _use_nli:
        return 0.5
    inputs = _tok.encode_plus(f"{premise} </s></s> {hypothesis}", return_tensors="pt", truncation=True, max_length=384)
    with torch.no_grad():
        logits = _nli(**inputs).logits.softmax(-1).tolist()[0]
    # logits order: [contradiction, neutral, entailment]
    return logits[2]

# --------------------------------------------------------------------------
# Main API
# --------------------------------------------------------------------------
def verify_answer(answer: str, source_nodes: List[Any], config: Optional[AnswerVerifierConfig] = None) -> Dict[str, Any]:
    cfg = config or AnswerVerifierConfig()
    proj_label = str(cfg.project_id or "unknown")

    start = time.time()
    verdict = {"numbers_supported": True, "entailment": None, "ok": True, "notes": []}

    logger.info("Answer verification started", project_id=proj_label, answer_preview=(answer or "")[:120], config=asdict(cfg), sources_count=len(source_nodes or []))

    try:
        # extract plain text from nodes defensively
        texts = []
        for n in (source_nodes or []):
            try:
                txt = getattr(n, "get_content", lambda: str(n))() or ""
            except Exception:
                # If node.get_content raises, fallback to string conversion
                try:
                    txt = str(n)
                except Exception:
                    txt = ""
            texts.append(txt)

        # 1) numeric check
        if cfg.enable_number_check:
            verdict["numbers_supported"] = numbers_supported(answer or "", texts)
            if not verdict["numbers_supported"]:
                verdict["ok"] = False
                note = "Some numbers in the answer were not supported by retrieved sources."
                verdict["notes"].append(note)
                ANSWER_VERIFICATION_FAILURES.labels(proj_label, "numbers_mismatch").inc()
                logger.warning(note, project_id=proj_label)

        # 2) entailment check (sentence-level average)
        if cfg.enable_entailment_check and _use_nli and (answer or "").strip():
            import re as _re
            sentences = _re.split(r"(?<=[\.\!\?])\s+", (answer or "").strip())
            premise = " ".join(texts)[: cfg.max_premise_chars]
            scores = [nli_entails(premise, s) for s in sentences if s]
            if scores:
                avg_entail = sum(scores) / len(scores)
                verdict["entailment"] = avg_entail
                if avg_entail < cfg.min_entailment_threshold:
                    verdict["ok"] = False
                    note = f"Low entailment between answer and sources ({avg_entail:.2f} < {cfg.min_entailment_threshold})."
                    verdict["notes"].append(note)
                    ANSWER_VERIFICATION_FAILURES.labels(proj_label, "low_entailment").inc()
                    logger.warning(note, project_id=proj_label)

        duration = time.time() - start
        status_label = "success" if verdict["ok"] else "fail"
        ANSWER_VERIFICATION_TOTAL.labels(proj_label, status_label).inc()
        ANSWER_VERIFICATION_DURATION.labels(proj_label).observe(duration)

        logger.info("Answer verification completed", project_id=proj_label, duration_seconds=round(duration, 3), verdict=verdict)

    except Exception as e:
        ANSWER_VERIFICATION_FAILURES.labels(proj_label, type(e).__name__).inc()
        verdict["ok"] = False
        verdict["notes"].append(f"Verification failed: {str(e)}")
        logger.error("Answer verification error", project_id=proj_label, error=str(e), error_type=type(e).__name__)

    return verdict

__all__ = ["AnswerVerifierConfig", "verify_answer", "numbers_supported", "nli_entails"]
