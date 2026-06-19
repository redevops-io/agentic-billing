# Agentic Billing

## The Triplet: Pain → Legacy → Redevops

Modern billing systems suffer from fragmented pain points in payments, subscriptions, and commerce. Legacy monoliths lock teams into inflexible infrastructure. Agentic Billing enables redevops: autonomous, AI-orchestrated modernization of billing workflows on open foundations.

## Headline Value Props
- Unified OSS core for payments, usage billing, and storefronts
- Agent layer automates reconciliation, retries, and compliance
- Rapid integration via install script or Docker Compose
- AGPL-3.0 licensed for full transparency and extensibility
- Orchestrator-driven 5-agent architecture for reliable operations

## What It Does
Agentic Billing provides an autonomous billing platform that integrates payments, metering, and e-commerce, powered by intelligent agents that handle the full lifecycle of subscriptions and invoices with minimal human intervention.

## Architecture
### OSS Core
- Hyperswitch: payments orchestration
- Lago: usage-based billing and metering
- MedusaJS: commerce and storefront capabilities

### Agent Layer
- 5 specialized agents + central orchestrator for end-to-end automation

## Quickstart
1. Clone the repo and ensure `.env` is configured with required keys (see `.env.example`).
2. Run either:
   - `./install.sh`
   - `docker compose up`

## License
AGPL-3.0

See LICENSE for details.