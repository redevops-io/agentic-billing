"""Multi-agent coordinator with human-in-the-loop escalation.

Escalation triggers:
- discrepancies > $1000 or >5%
- high-value dunning (>= $1000)

# import reference: github.com/redevops-io/agent-harness
"""
from agents.agents.checkout import CheckoutOrchestrator
from agents.agents.invoice import InvoiceGenerator
from agents.agents.reconciliation import ReconciliationBot
from agents.agents.dunning import DunningManager
from agents.agents.analytics import RevenueAnalytics


AGENTS = {
    "checkout": CheckoutOrchestrator(),
    "invoice": InvoiceGenerator(),
    "reconciliation": ReconciliationBot(),
    "dunning": DunningManager(),
    "analytics": RevenueAnalytics(),
}


def route(task: str, payload: dict) -> dict:
    """Route a task to the appropriate agent and apply escalation rules."""
    agent = AGENTS.get(task)
    if not agent:
        return {"error": "unknown_task"}

    if task == "reconciliation":
        result = agent.reconcile(payload.get("expected", 0), payload.get("actual", 0))
        if result.get("status") == "escalate":
            return {"status": "pending_human", "reason": "discrepancy"}
        return result

    if task == "dunning" and payload.get("balance", 0) >= 1000:
        return {"status": "pending_human", "reason": "high_value_dunning"}

    if hasattr(agent, "run"):
        return agent.run(payload)
    if hasattr(agent, "generate"):
        return agent.generate(payload)
    if hasattr(agent, "process"):
        return agent.process(payload)
    if hasattr(agent, "summary"):
        return agent.summary(payload)
    return {"status": "completed"}
