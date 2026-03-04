# GDC Dashboard — AI-Powered Kubernetes Operations Platform

## What Is This?

The GDC Dashboard is a **real-time Kubernetes operations dashboard** enhanced with **Google Gemini AI**. It gives your team a single pane of glass to monitor, troubleshoot, and manage workloads — with AI doing the heavy lifting that normally requires SRE-level expertise.

Think of it this way: **ArgoCD deploys your apps. This dashboard keeps them running.**

---

## The 30-Second Pitch

> "When a pod crashes at 2am, your team shouldn't have to SSH into a cluster, run 15 kubectl commands, read 500 log lines, and Google error messages. They should click one button and get an AI-generated root cause analysis with the exact fix."

That's what this tool does.

---

## "We Already Have ArgoCD — Why Do We Need This?"

This is the most common question, so let's address it head-on. **ArgoCD and GDC Dashboard solve completely different problems.** They are complementary, not competing.

### What ArgoCD Does (Deployment Pipeline)
- ✅ Sync Git repos to the cluster (GitOps)
- ✅ Detect drift between desired and actual state
- ✅ Roll back to previous deployments
- ✅ Manage Helm charts and Kustomize overlays

### What ArgoCD Does NOT Do (Day-2 Operations)
- ❌ Tell you WHY a pod is crashing
- ❌ Analyze logs across multiple containers
- ❌ Diagnose OOM kills, ImagePullBackOff, or CrashLoopBackOff
- ❌ Suggest resource optimization (CPU/memory right-sizing)
- ❌ Scan for CVEs in container images
- ❌ Provide a terminal/console into running pods
- ❌ Explain what a ConfigMap or Secret actually does
- ❌ Answer natural language questions about your cluster

### Side-by-Side Comparison

| Scenario | ArgoCD | GDC Dashboard |
|---|---|---|
| "Deploy v2.4 of billing-service" | ✅ Sync from Git | ❌ Not its job |
| "billing-service is crash-looping — why?" | ❌ Just shows ❌ sync status | ✅ **AI Diagnose**: reads logs, events, pod spec → gives root cause + fix |
| "What CVEs are in our container images?" | ❌ No scanning | ✅ **Trivy Scan**: CVE-level vulnerability report with AI summary |
| "Are we wasting money on over-provisioned pods?" | ❌ No visibility | ✅ **AI Optimizer**: analyzes real CPU/memory usage → savings estimate |
| "Scale backend-api to 5 replicas" | ❌ Requires Git commit | ✅ One click (or type it in the AI search bar) |
| "Explain what db-creds secret contains" | ❌ No analysis | ✅ **AI Explain**: security-aware key-by-key breakdown |
| "Show me logs from all containers in this pod" | ❌ Not available | ✅ Multi-container log viewer with AI correlation |

### The Bottom Line

```
ArgoCD = "How do I DEPLOY my application?"       → CI/CD Pipeline
GDC Dashboard = "How do I OPERATE my application?"  → Day-2 Operations
```

They work together:
1. **ArgoCD** deploys your app from Git
2. **GDC Dashboard** monitors it, diagnoses issues, and helps your team fix problems in real-time

---

## Key Features

### 🤖 AI-Powered Intelligence (Gemini)

| Feature | What It Does |
|---|---|
| **AI Diagnose** | One-click full health analysis of any Deployment, StatefulSet, or Pod. Reads logs, events, and spec, then returns a structured diagnosis with root cause and fix. |
| **AI Root Cause Analysis** | Deep-dive RCA for failing pods — analyzes all container logs, correlates events, identifies the exact failure chain. |
| **AI Log Analysis** | Summarizes hundreds of log lines into key errors, patterns, and recommendations. |
| **Multi-Container Log Correlation** | Correlates logs across init containers, sidecars, and app containers to find cross-container issues. |
| **AI Resource Optimizer** | Compares actual CPU/memory usage against limits, calculates wasted spend, suggests right-sized values. |
| **Natural Language Search** | Type "show me crashing pods" or "scale frontend to 3" — the AI understands and executes. |
| **Conversational AI Agent** | Multi-turn chat with live K8s tool-calling. Ask "why is billing slow?" and the AI fetches real data to answer. |
| **AI Config Explainer** | Explains what ConfigMaps, Secrets, and environment variables actually configure — with security flagging. |

### 🔒 Security

| Feature | What It Does |
|---|---|
| **Security Audit** | Scans all workloads for security risks: privileged containers, missing network policies, service account misuse, host path mounts. |
| **Vulnerability Scan** | Uses Trivy to scan container images for known CVEs. Falls back to metadata checks (unpinned tags, Docker Hub images) if Trivy is unavailable. |
| **Secret Risk Scan** | Identifies secrets with weak access controls or missing rotation policies. |

### 📊 Operations

| Feature | What It Does |
|---|---|
| **Workloads Dashboard** | Real-time view of all Deployments, StatefulSets, DaemonSets, Jobs, Pods, ConfigMaps, and Secrets — with status, ready count, and age. |
| **Scale Up/Down** | One-click replica scaling with confirmation dialog. |
| **Rolling Restart** | Trigger rolling restarts without touching Git or kubectl. |
| **Pod Console** | Terminal into any running pod container directly from the browser (xterm.js + WebSocket). |
| **Deployment Labels** | Shows image tags, Helm chart versions, and team labels at a glance. |
| **Networking Tab** | Services and Istio VirtualServices with AI-powered route analysis, traffic policy review, and dependency mapping. |

---

## Who Is This For?

| Role | How They Use It |
|---|---|
| **Application Developers** | Check if their deployment is healthy, read logs, understand why a pod crashed — without learning kubectl. |
| **SREs / DevOps Engineers** | Faster triage: AI reads 500 log lines and hands you the root cause in 3 seconds. |
| **Team Leads / Managers** | Namespace-wide health pulse, cost optimization reports, security posture overview. |
| **On-Call Engineers** | 2am incidents: click AI Diagnose → get the fix → done. No context-switching to terminals. |

---

## How It Integrates with Your Existing Stack

```
┌──────────────────────────────────────────────────┐
│                Your Workflow                     │
│                                                  │
│  Developer commits code                          │
│        ↓                                         │
│  CI/CD builds image, pushes to registry          │
│        ↓                                         │
│  ArgoCD syncs deployment to cluster         ← DEPLOY
│        ↓                                         │
│  GDC Dashboard monitors, diagnoses, optimizes  ← OPERATE
│        ↓                                         │
│  Issue found? AI gives root cause + fix          │
│        ↓                                         │
│  Developer fixes code, commits...               │
│        (cycle repeats)                           │
└──────────────────────────────────────────────────┘
```

---

## Requirements

- **Namespace-level admin access** (no cluster admin needed)
- **Google Cloud project** with Gemini API enabled (for AI features)
- Runs as a single pod in your namespace — no DaemonSets, no cluster-level permissions
- Optional: Trivy installed in the container image for CVE scanning

---

## Summary

| Question | Answer |
|---|---|
| Does it replace ArgoCD? | **No.** It complements ArgoCD by handling Day-2 operations. |
| Does it need cluster admin? | **No.** Namespace admin is sufficient. |
| Is it safe to run in production? | **Yes.** Read-only operations by default. Scale/restart require confirmation. |
| Does it depend on Gemini? | AI features need Gemini. The dashboard itself works without it (basic mode). |
| How is it deployed? | Single pod. Same as any other app ArgoCD deploys. |
