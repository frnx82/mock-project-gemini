# GDC Dashboard - AI Features & Usage Guide

This dashboard includes several AI-powered features designed to simplify Kubernetes operations, troubleshooting, and optimization.

## 🤖 AI Features Overview

### 1. Interactive AI Search Bar
Location: **Top Header**
A natural language interface that allows you to filter resources, perform actions, and navigate the dashboard using plain English.

### 2. Smart Log Summarizer
Location: **Logs Modal** (Click "View Logs" on a pod)
Automatically analyzes raw logs to detect patterns, critical errors, and root causes.
-   **Detects**: Stack traces, repeated error patterns, timeout issues.
-   **Output**: A concise summary with recommended actions (e.g., "Increase DB pool size").
-   *(Demo Note: This is currently mocked to trigger specific summaries for pods like `backend-pod-multi`)*

### 3. Smart Resource Optimizer
Location: **"💰 Smart Optimizer" Tab**
Continuously analyzes workload usage metrics against requests/limits to identify efficiency improvements.
-   **Cost Saving 📉**: Identifies over-provisioned resources (wasted CPU/Memory).
-   **Performance Risk 📈**: Identifies under-provisioned resources (risk of OOMKilled/CPU Throttling).
-   **Zombie Resources 🧟**: Identifies resources with no traffic/usage for 7+ days.

### 4. AI Security Guardian
Location: **"🛡️ Security Guardian" Tab** (Sub-tab under Networking or Workloads depending on layout, or accessible via Search)
Scans workloads for security best practice violations.
-   **Checks**: Privileged containers, Root user usage, Host PID/IPC/Network namespace usage, Missing resource limits.

### 5. Automated Root Cause Analysis (RCA)
Location: **Pod Status / AI Search**
When a pod crashes or fails, the AI analyzes the events and logs to determine *why*.
-   *(Demo Note: Try searching "analyze" or "why is payment-service broken")*

---

## 🔍 AI Search Bar: Supported Queries

You can type these queries into the search bar to see the AI in action.

### 🛑 Filtering & Troubleshooting
*   `"Show me failed pods"`
*   `"List crashed pods"`
*   `"Find broken resources"`
*   `"Show errors"`
    *   **Action**: Filters the Workload view to show only pods with status `Failed`, `Error`, or `CrashLoopBackOff`.

### ⚖️ Scaling Workloads
*   `"Scale up billing-service"`
*   `"Increase replicas for frontend"`
*   `"Scale backend to 3 replicas"`
    *   **Action**: parses the intent and target (`billing-service`), then triggers a scaling action (simulated in demo).

### 📊 Log Analysis
*   `"Show logs for checkout-pod"`
*   `"Get logs"`
    *   **Action**: Opens the logs modal for the target pod and auto-runs the **Smart Log Summarizer**.

### 🗑️ Cleanup
*   `"Delete unused-pod"`
*   `"Remove zombie resources"`
    *   **Action**: Triggers a deletion flow for the specified resource.

### 🧠 Root Cause Analysis (RCA)
*   `"Analyze payment-service"`
*   `"Why is the payment pod crashing?"`
*   `"Run RCA on frontend"`
    *   **Action**: Runs a deep-dive analysis simulation, checking events, logs, and metrics to provide a diagnosis (e.g., "OOMKilled due to memory spike").

### 🔄 Navigation & Reset
*   `"Reset view"`
*   `"Clear filters"`
*   `"Help"`
    *   **Action**: Resets the dashboard to its default state or shows a help tooltip.

---

## 🛠️ Technical Details

-   **Backend**: Flask (Python) with `kubernetes` client.
-   **Updates**: Real-time updates via `flask-socketio`.
-   **Terminal**: Real interaction via `xterm.js` and Kubernetes Exec API (websocket stream).
-   **AI Logic**: Currently acts as a "Mock AI" with heuristic-based pattern matching for demonstration purposes. In a production version, `app.py` would connect to an LLM API (Gemini/OpenAI) for dynamic analysis.

---

## 📚 All Actions Reference

A complete reference of every action the dashboard supports, organized by category.

### 🖥️ Resource Viewing (Read)

| Action | Endpoint | Description |
|---|---|---|
| **List Workloads** | `GET /api/workloads` | Lists Pods, Deployments, StatefulSets, DaemonSets, Secrets by namespace |
| **List Services** | `GET /api/services` | Lists all Kubernetes Services (ClusterIP, LoadBalancer, etc.) |
| **List VirtualServices** | `GET /api/virtualservices` | Lists Istio VirtualServices |
| **Pod Stats** | `GET /api/pods/stats` | CPU & memory usage per pod (via metrics server) |
| **Pod Logs** | `GET /api/pods/<name>/logs` | Fetch logs for a specific pod/container |
| **Pod Events** | `GET /api/events/<name>` | List Kubernetes events for a resource |
| **Resource YAML** | `GET /api/yaml/<name>` | Show full YAML/describe output for any resource |
| **Env Variables** | `GET /api/workloads/env` | Shows env vars, ConfigMaps, and Secrets mounted on a workload |
| **View Secret** | `GET /api/secrets/<name>` | Decode and display secret values |
| **View ConfigMap** | `GET /api/configmaps/<name>` | Display ConfigMap data |

---

### ⚙️ Resource Management (Write)

| Action | Endpoint | Description |
|---|---|---|
| **Scale Workload** | `POST /api/scale` | Scale a Deployment/StatefulSet to a desired replica count |
| **Restart Workload** | `POST /api/restart` | Trigger a rolling restart of a Deployment |
| **Delete Resource** | `POST /api/delete` | Delete a Pod, Deployment, or other resource |

---

### 🤖 AI / Gemini API Actions

| Action | Endpoint | Description |
|---|---|---|
| **Natural Language Query** | `POST /api/ai/query` | Parse plain-English commands → dashboard actions (filter, scale, restart, logs, etc.) |
| **Log Analysis (Gemini)** | `POST /api/ai/analyze_logs` | Send aggregated pod logs to Gemini for deep root-cause analysis |
| **Log Summarize** | `POST /api/ai/summarize_logs` | Pattern-match logs for OOM, crashes, timeouts, 4xx/5xx errors |
| **AI Optimize** | `GET /api/ai/optimize` | Analyze resource requests vs. actual usage → cost-saving & right-sizing recommendations |
| **Root Cause Analysis (RCA)** | `POST /api/ai/rca` | Diagnose a specific failing pod (CrashLoopBackOff, OOMKilled, ImagePullBackOff, Pending) |
| **Security Scan** | `GET /api/ai/security_scan` | Scan workloads for misconfigurations (missing limits, root containers, etc.) |
| **AI Chat Agent** | `POST /api/ai/chat` | General freeform Q&A about the cluster state powered by Gemini |

---

### 💬 Natural Language Commands (via AI Search Bar)

These are the intents the AI query parser understands when typed into the search bar:

| What You Type | Action Triggered |
|---|---|
| `"show failed pods"` / `"crash"` / `"error"` | Filter Pod list by failed/errored status |
| `"show running pods"` | Filter for `Running` pods |
| `"show pending pods"` | Filter for `Pending` pods |
| `"show all pods"` | Show all pods (clear status filter) |
| `"restart frontend"` | Rolling restart of named deployment |
| `"scale billing-service to 5"` | Scale deployment to N replicas |
| `"get yaml for frontend"` / `"describe frontend"` | Show YAML for a resource |
| `"show events for backend"` | List Kubernetes events for a resource |
| `"show logs for payment-pod"` | Open log viewer for a pod |
| `"delete unused-pod"` | Delete a resource |
| `"analyze payment-service"` / `"rca"` | Trigger Root Cause Analysis |
| `"reset"` / `"clear"` | Clear all active filters |
| `"help"` | Show available commands |

---

### 🖥️ Terminal (WebSocket)

| Action | Event | Description |
|---|---|---|
| **Open Terminal** | `connect_terminal` (WS) | Open an interactive shell (`kubectl exec`) into any pod/container |
| **Send Input** | `terminal_input` (WS) | Send keystrokes to the running shell session |
| **Disconnect** | `disconnect` (WS) | Clean up and close the terminal session |
