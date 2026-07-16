# How AI Is Used in GDC KubeInsight

> A concise overview of how Google Gemini AI is integrated into the platform.

---

## Overview

GDC KubeInsight uses **Google Gemini 2.5 Flash** (via Vertex AI API) as a pre-trained language model — no custom training or fine-tuning is involved. The AI acts as an intelligent operations assistant that reads, correlates, and interprets Kubernetes cluster data that would otherwise require senior SRE expertise and significant manual effort.

---

## Two AI Integration Patterns

### 1. Direct Prompt Pattern

The backend collects live Kubernetes data (pod logs, events, deployment specs, resource metrics), assembles it into a structured prompt, and sends it to Gemini in a single API call. Gemini returns structured JSON that the dashboard renders as actionable insights.

**This pattern powers 13+ features, including:**

| Feature | What AI Does |
|---------|-------------|
| **Root Cause Analysis** | Reads pod logs, events, and specs to identify why a workload is failing and suggests kubectl fix commands |
| **Log Summarization** | Distills hundreds of log lines into the few that matter, highlighting errors and anomalies |
| **Security Audit** | Scans deployment configs for security risks (privileged containers, missing network policies, etc.) |
| **Resource Optimization** | Analyzes resource requests/limits vs. actual usage and recommends right-sizing to reduce cost |
| **Config Review** | Evaluates ConfigMaps and deployment specs for best-practice violations |
| **Cross-Container Correlation** | Connects events across sidecar proxies, app containers, and init containers to build a unified timeline |
| **Workload Description** | Generates a plain-English summary of what a deployment does based on its spec and image |

### 2. Agentic Function Calling Pattern

A conversational AI chat where users ask questions in natural language (e.g., *"Why is billing-service slow?"* or *"Show me all crashing pods"*). Gemini is provided with **10 read-only Kubernetes tools** (list pods, get logs, get events, describe deployments, etc.) and autonomously decides:

- Which tools to call
- In what order
- How to interpret the results

It executes up to **5 investigation rounds**, chaining tool calls together to build a complete picture before delivering a data-backed answer — behaving like a virtual SRE with live cluster access.

---

## Key Design Principles

- **No custom models** — We use Gemini as-is via API. No GPUs, training pipelines, or ML ops to maintain.
- **Deterministic fallbacks** — Every AI feature has a rule-based fallback. The dashboard works fully without Gemini if the API is unavailable or not yet approved.
- **Response caching** — Gemini responses are cached for 5 minutes to avoid redundant API calls on repeated clicks.
- **Retry with backoff** — Transient errors (SSL, 429 quota) are retried automatically before falling back.
- **Structured output** — All prompts request JSON responses, parsed with robust error handling for Gemini's occasional formatting quirks.
- **Namespace-scoped** — AI analysis is limited to the namespace the instance is deployed in, respecting RBAC boundaries.

---

## Cost

Gemini 2.5 Flash is extremely cost-effective at approximately **$0.001 per AI call**, translating to roughly **$3–5/month per team** at heavy usage — a fraction of the engineering time it saves.

---

*For full architectural details, see [ARCHITECTURE.md](ARCHITECTURE.md). For a complete feature list, see [GEMINI-AI-FEATURES.md](GEMINI-AI-FEATURES.md).*
