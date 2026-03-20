# AI Use Case Submission — GDC KubeInsight

> *AI-Powered Kubernetes Operations Platform on Google Distributed Cloud*

---

## Use Case Description

The GDC KubeInsight is an AI-powered Kubernetes operations platform that integrates Google Gemini into day-to-day cluster management on Google Distributed Cloud (GDC). It enables developers, SREs, and team leads to monitor, troubleshoot, and manage production workloads through a single web-based interface — with AI performing the expert-level analysis that traditionally requires senior SRE knowledge, multiple CLI tools, and significant manual effort. The platform uses Gemini as a pre-trained model via Vertex AI API calls (no custom model training or fine-tuning) to deliver 15+ AI-powered features including one-click root cause analysis, intelligent log correlation across containers, natural language cluster queries, resource cost optimization, automated security auditing, and a conversational AI agent with live Kubernetes tool-calling capabilities.

---

## Problem / Opportunity

### Context

Our operations teams manage dozens of microservices deployed across GDC clusters. When incidents occur — pods crash-looping, services timing out, containers running out of memory — the current troubleshooting workflow is time-consuming and expertise-dependent. Engineers must VPN into the cluster, run 10+ kubectl commands to gather pod status, events, and logs, then switch to Splunk to search and filter through hundreds of log lines, manually correlate findings across containers and services, and finally Google error messages to understand root causes. This process takes 30–60 minutes per incident, requires deep Kubernetes CLI expertise that not every developer possesses, and creates a bottleneck where only a few senior engineers can effectively triage production issues. Additionally, proactive tasks like security auditing, resource right-sizing, and configuration review are rarely performed because they demand even more manual effort and specialized knowledge.

### Problem / Opportunity

The core problem is the gap between the data that Kubernetes already exposes (logs, events, pod specs, resource metrics) and the human expertise needed to interpret it quickly and accurately. Every piece of information needed to diagnose most incidents already exists within the cluster — it just takes too long for humans to collect, read, correlate, and act on it. This is a perfect opportunity for AI: Gemini can read 500 log lines in milliseconds, cross-reference events with pod specs, identify error patterns from its pre-trained knowledge of Kubernetes failure modes, and deliver a structured diagnosis with actionable fix recommendations — reducing incident triage from 30+ minutes to under 10 seconds. Beyond incident response, the same AI capability unlocks opportunities that teams rarely have bandwidth for: continuous security posture assessment, resource cost optimization (identifying over-provisioned workloads), configuration drift detection, and making Kubernetes accessible to developers who don't know kubectl. The opportunity at scale is significant — every team running workloads on GDC faces the same operational challenges, and a single platform can serve all of them.

---

## Solution

### What We Built

We have a **fully working solution** that is already deployed and demonstrated. The GDC KubeInsight is a lightweight Flask web application (single pod, ~200MB container) that connects to the Kubernetes API for real-time cluster data and to Google Gemini (via Vertex AI) for AI-powered analysis. The application uses two AI integration patterns:

1. **Direct Prompt Pattern** — For features like Diagnose, Root Cause Analysis, Log Summarization, and Security Audit, the backend collects relevant Kubernetes data (pod logs, events, deployment specs, resource metrics), assembles it into a structured prompt, and sends it to Gemini in a single API call. Gemini returns structured JSON that the dashboard renders as actionable insights with health scores, risk assessments, and kubectl fix commands. This pattern powers 13 distinct AI features.

2. **Agentic Function Calling Pattern** — For the conversational AI Chat, users ask questions in natural language (e.g., "Why is billing-service slow?"). Gemini is given 10 read-only Kubernetes tools (list pods, get logs, get events, etc.) and autonomously decides which tools to call, executes up to 5 investigation rounds, and delivers a data-backed answer — behaving like a virtual SRE with live cluster access.

### Why AI/ML Is the Key Differentiator

Without AI, a dashboard can only show raw data — tables of pods, walls of log text, lists of events. The engineer still needs to do the hard part: reading, correlating, and interpreting. AI transforms this from a **data display tool** into an **intelligent operations assistant** that:

- **Reads and summarizes** 500 log lines in milliseconds, surfacing the 3 lines that matter
- **Correlates across containers** — connects a sidecar proxy timeout at 14:03 to the app's database failure at 14:04, something that takes humans 15+ minutes in Splunk
- **Applies pre-trained Kubernetes knowledge** — recognizes CrashLoopBackOff patterns, OOMKill signatures, and ImagePullBackOff causes without needing a runbook
- **Generates actionable output** — not just "something is wrong" but "here's the root cause and here's the exact kubectl command to fix it"
- **Understands natural language** — engineers type "show me crashing pods" instead of learning `kubectl get pods --field-selector=status.phase!=Running -o json | jq ...`

No amount of traditional dashboard UI can replicate this — it fundamentally requires language understanding and reasoning capabilities that only LLMs provide.

### Scalability Across the Organisation

The solution is designed for org-wide adoption:

- **Per-namespace deployment** — each team deploys their own instance via ArgoCD, same as any microservice. No shared infrastructure to manage.
- **Namespace-scoped RBAC** — no cluster-admin. Each instance only accesses its own namespace, maintaining security isolation.
- **Zero ML infrastructure** — we consume Gemini via API, so there are no GPUs, training pipelines, or ML ops to maintain.
- **Negligible cost** — Gemini 2.5 Flash costs ~$0.001 per AI call (~$3–5/month at heavy usage per team).
- **Graceful degradation** — every AI feature has a deterministic fallback. The dashboard works fully without Gemini, making it safe to deploy even where AI isn't yet approved.
- **Future platform capabilities** — planned initiatives include an MCP Server (centralized K8s data access for any AI agent), Gemini API Gateway (governed access with rate limiting and cost tracking), and Teams/Email bot integration (self-service AI via chat without opening the dashboard).

### Key Benefits

| Benefit | Impact |
|---------|--------|
| **Reduced MTTR** | Incident triage from 30–60 minutes → under 1 minute |
| **Democratized K8s access** | Developers troubleshoot without learning kubectl |
| **Proactive security** | Automated security audits that teams rarely do manually |
| **Cost optimization** | AI identifies over-provisioned workloads and estimates savings |
| **Knowledge multiplication** | One AI assistant replaces the need for senior SRE availability 24/7 |
| **Consistent quality** | AI applies the same thorough analysis every time, no human fatigue |
| **Extremely low cost** | ~$3–5/month per team in Gemini API costs vs. hours of engineer time saved |
| **No ML expertise needed** | Teams deploy and use it like any other app — no data science skills required |

---

*Submitted for AI use case approval. Supporting documentation available: [ARCHITECTURE.md], [GEMINI-AI-FEATURES.md], [AI-INITIATIVES-PLAN.md], [DEMO-PRESENTATION.md], [DEMO-QA.md].*
