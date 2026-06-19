"""Guardrails for sensitive data and approval thresholds."""
from typing import Any, Dict


APPROVAL_THRESHOLD = 1000  # USD
DISCREPANCY_PCT = 0.05     # 5%


def sanitize_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Remove or mask sensitive fields. Never store raw PII."""
    safe = payload.copy()
    safe.pop("ssn", None)
    safe.pop("card_number", None)
    return safe
