"""Shared agent tools and utilities."""
from typing import Any, Dict


def needs_approval(payload: Dict[str, Any]) -> bool:
    """Return True if the payload requires human approval."""
    amount = payload.get("amount", 0)
    return amount > 1000
