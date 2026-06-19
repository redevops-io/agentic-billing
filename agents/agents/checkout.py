"""Checkout Orchestrator agent.

# import reference: github.com/redevops-io/agent-harness
"""
from agents.tools import needs_approval


class CheckoutOrchestrator:
    """Coordinates checkout workflows with human-in-the-loop for high value."""

    def run(self, payload: dict) -> dict:
        if needs_approval(payload):
            return {"status": "pending_approval", "reason": "high_value"}
        return {"status": "completed"}
