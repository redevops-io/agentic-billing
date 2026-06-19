"""Reconciliation Bot agent.

# import reference: github.com/redevops-io/agent-harness
"""
class ReconciliationBot:
    """Detects discrepancies and escalates when thresholds exceeded."""

    def reconcile(self, expected: float, actual: float) -> dict:
        diff = abs(expected - actual)
        pct = diff / expected if expected else 0
        if diff > 1000 or pct > 0.05:
            return {"status": "escalate", "diff": diff}
        return {"status": "ok", "diff": diff}
