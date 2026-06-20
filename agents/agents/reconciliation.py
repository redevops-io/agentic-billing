"""Reconciliation Bot agent.

# import reference: github.com/redevops-io/agent-harness
"""
from decimal import Decimal


class ReconciliationBot:
    """Detects discrepancies and escalates when thresholds exceeded."""

    def reconcile(self, expected: float, actual: float) -> dict:
        expected = Decimal(str(expected))
        actual = Decimal(str(actual))
        diff = abs(expected - actual)
        pct = diff / abs(expected) if expected else Decimal(0)
        if diff > Decimal("1000") or pct > Decimal("0.05"):
            return {"status": "escalate", "diff": diff}
        return {"status": "ok", "diff": diff}
