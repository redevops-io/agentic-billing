"""Dunning Manager agent.

# import reference: github.com/redevops-io/agent-harness
"""
class DunningManager:
    """Handles dunning sequences and high-value escalations."""

    def process(self, account: dict) -> dict:
        if account.get("balance", 0) > 1000:
            return {"action": "escalate_human"}
        return {"action": "send_notice"}
