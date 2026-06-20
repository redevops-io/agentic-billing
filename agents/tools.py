"""Shared agent tools and utilities."""
from decimal import Decimal
from typing import Any, Dict

THRESHOLD = Decimal("1000")


def needs_approval(payload: Dict[str, Any]) -> bool:
    """Return True if the payload requires human approval."""
    amount = payload.get("amount", 0)
    return abs(Decimal(str(amount))) > THRESHOLD
