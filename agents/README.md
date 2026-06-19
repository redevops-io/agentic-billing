# Agentic Billing Layer

Implements five agents:
- Checkout Orchestrator
- Invoice Generator
- Reconciliation Bot
- Dunning Manager
- Revenue Analytics

Human-in-the-loop triggers on discrepancies >$1000 or >5%, high-value dunning.
Uses shared harness from github.com/redevops-io/agent-harness.
