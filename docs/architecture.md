# Architecture

## OSS Core
- Hyperswitch: payment routing and card vault
- Lago: usage-based billing
- MedusaJS: commerce backend
- PostgreSQL and Redis for state and caching

## Agent Layer
- 5 specialized agents coordinated by an orchestrator
- Human-in-the-loop triggers for sensitive actions
- Agents perform scoped operations only; they do not execute financial transactions or modify production billing without explicit human approval.