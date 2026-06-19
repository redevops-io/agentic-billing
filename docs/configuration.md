# Configuration

## Environment Variables
- OPENAI_BASE_URL: base URL for the OpenAI-compatible endpoint
- OPENAI_API_KEY: API key for authentication
- MODEL: model identifier to use

Core service configuration for Hyperswitch, Lago, MedusaJS, PostgreSQL, and Redis is provided via their respective standard environment variables.

## Using an OpenAI-Compatible Endpoint
Set OPENAI_BASE_URL to point at any compatible server (e.g. a local or alternative provider). Authentication uses OPENAI_API_KEY and the chosen MODEL.

## Guardrail Thresholds
Guardrail thresholds are configured via the service environment and control agent behavior limits.