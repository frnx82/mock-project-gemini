# GDC Dashboard — Demo Q&A Cheat Sheet

> *Anticipated questions from team leads, developers, and security reviewers during the demo.*

---

## 🏗️ Architecture & Design

### Q1: "Why not use a commercially available dashboard like Lens, Rancher, or Headlamp?"

**A:** Those tools are general-purpose K8s dashboards. They show you raw data — but none of them have **AI-powered diagnosis, root cause analysis, or natural language search**. Our dashboard is purpose-built for GDC with features tailored to our operations workflow:
- AI Diagnose with one click (no other dashboard does this)
- Gemini-powered conversational agent with live K8s tool-calling
- Built-in CVE scanning
- Natural language search ("show me crashing pods")
- Resource optimizer with cost estimates

Also, most commercial dashboards require **cluster-admin** privileges. Ours runs with **namespace-level RBAC** only.

---

### Q2: "Why Flask? Why not Go, Node.js, or a proper SPA framework?"

**A:** Three reasons:
1. **Speed of development** — Python lets us iterate fast and the `kubernetes` Python SDK is mature
2. **Gemini SDK** — Google's `google-genai` SDK is Python-first; no equivalent Go SDK with the same feature set
3. **Simple deployment** — single file, no build step, no webpack, no node_modules. The container image is ~200MB

If this grows into a platform with multiple services, it can be split later. Right now, simplicity is a feature.

---

### Q3: "Why is everything in one large app.py file?"

**A:** It started as a quick prototype and grew organically. The single-file approach actually has advantages for deployment: one container, one process, no microservice coordination. However, if we productionize this, we'd split into modules (`routes/`, `ai/`, `k8s/`, etc.). The mock_app.py already demonstrates that the API shape is modular and testable.

---

### Q4: "How does it handle multiple namespaces / clusters?"

**A:** Currently, each dashboard instance monitors **one namespace**. Each team deploys their own instance in their namespace — this is intentional:
- **Security**: No cross-namespace data access
- **RBAC**: Minimal permissions needed
- **Isolation**: One team's dashboard can't affect another's

For a multi-namespace view, we could add namespace switching (dropdown), but each namespace would still need its own ServiceAccount.

---

## 🤖 AI Integration

### Q5: "What exactly gets sent to Gemini? Can you show us?"

**A:** Here's exactly what goes to Gemini for a typical "Diagnose" call:

```
Sent:
- Pod logs (last 200 lines of stdout/stderr)
- K8s events (Warning/Error events for the resource)
- Deployment spec (replicas, image tags, resource limits, labels)
- Container status (running, waiting, terminated, restart count)
- ConfigMap key names (NOT values)

NEVER sent:
- Secret values (always redacted before sending)
- Container image binaries
- Cluster credentials or tokens
- User/developer credentials
- Raw network traffic
```

The prompt is structured like: *"You are a Kubernetes SRE. Analyze this deployment. Here are the logs: [logs]. Here are the events: [events]. Return a JSON with health_score, risks, and fixes."*

---

### Q6: "Does Google train on our data?"

**A:** **No.** Vertex AI explicitly states that customer data is:
- **Not used for model training** — your prompts and responses are not used to improve Gemini
- **Not stored** — data is processed and discarded after the API response
- **Covered by your GCP Terms of Service** — same data processing agreements as other GCP services

This is documented in Google's Vertex AI data governance page.

---

### Q7: "What if Gemini gives wrong advice?"

**A:** Gemini can hallucinate, but we mitigate this in several ways:
1. **Real data, not imagination** — we always send actual K8s data (logs, events). Gemini analyzes real facts, not hypothetical scenarios
2. **Structured output** — we request JSON with specific fields, not free-form text. This constrains the output to things that can be verified
3. **Low temperature (0.2)** — reduces creative/random responses
4. **Source data included** — the AI response references actual container names, log lines, and events from YOUR cluster. You can verify
5. **No auto-execution** — AI never modifies the cluster. Scale, restart, delete all require human confirmation

**Bottom line:** Treat AI output like a **senior engineer's recommendation** — usually accurate, but always verify before acting.

---

### Q8: "How much does the Gemini API cost?"

**A:** Very little.

| Model | Input | Output | Cost per AI call |
|-------|-------|--------|-----------------|
| Gemini 2.5 Flash | $0.15/1M tokens | $0.60/1M tokens | ~$0.001 (one-tenth of a cent) |

**Monthly estimates:**

| Usage Level | Daily AI Calls | Monthly Cost |
|-------------|---------------|-------------|
| Light | 20/day | ~$0.60/month |
| Medium | 50/day | ~$1.50/month |
| Heavy | 200/day | ~$6.00/month |

Compare this to Splunk license costs or the engineer-hours saved — it's negligible.

---

### Q9: "What if Gemini is down or rate-limited?"

**A:** Every AI feature has a **deterministic fallback**:
- **Diagnose** → basic health score from replica counts
- **Security Audit** → heuristic scan (pattern matching for known risks)
- **Config Explainer** → pattern matching for obvious issues
- **AI Chat** → message explaining Gemini is unavailable

The core dashboard (workloads, scaling, logs, terminal) works **100% without Gemini**. AI is an enhancement, not a dependency.

---

## 🔐 Security & Data Residency

### Q10: "We have data residency requirements. Is this compliant?"

**A:** It depends on your specific policy. Here's the data flow:

- **All K8s data stays on the GDC cluster** — the dashboard reads from the local K8s API, data never leaves unless you trigger an AI feature
- **When AI is triggered**, a subset of data (logs, events, specs) is sent to **Vertex AI over HTTPS**
- Vertex AI processes in the **region you configure** (e.g., `us-central1`, `europe-west1`)
- **No data is stored** by Vertex AI after processing

**If your policy forbids any external API calls:**
- You can run the dashboard **without Gemini** — just don't set the GCP env vars
- All AI features gracefully degrade to deterministic mode
- You lose AI analysis but keep all operational features

---

### Q11: "Logs might contain sensitive information. Isn't that a risk?"

**A:** Yes, this is a valid concern. Logs can contain:
- Database connection strings
- Debug-mode output with user data
- Stack traces with file paths

**Current mitigations:**
- Only the last 200 lines are sent (not full log history)
- Secret values from K8s Secrets are always redacted
- Gemini doesn't store the data after processing

**Recommended additional mitigations:**
1. **Log sanitizer** — add a pre-processing step that strips PII/credentials before sending to Gemini
2. **Content filter** — regex-based filter to strip patterns like `password=`, email addresses, etc.
3. **Opt-in AI** — make AI features opt-in per namespace (some teams may not want it)

---

### Q12: "Can someone use the AI Chat to delete pods or run destructive commands?"

**A:** **No. Absolutely not.** The AI Chat agent has access to **10 read-only tools only**:
- List pods, get logs, get events, describe pods, list deployments, etc.
- **No write/delete/scale/restart tools** are registered with the chat agent

Destructive actions (scale, restart, delete) go through **separate API endpoints** with a mandatory **confirmation dialog** in the UI. The AI cannot bypass these controls.

---

### Q13: "What K8s permissions does it need? Can it access other namespaces?"

**A:** It uses a **ServiceAccount with namespace-scoped RBAC** only:

| Permission | Resources | Purpose |
|-----------|-----------|---------|
| `get, list, watch` | pods, deployments, services, configmaps, secrets, events | Read operations |
| `create, patch` | deployments/scale | Scaling |
| `patch` | deployments | Rolling restart |
| `create` | pods/exec | Terminal access |

**No ClusterRole.** It cannot access other namespaces, cluster-level resources, or node-level data.

---

## ⚖️ Comparison Questions

### Q14: "Why not just use Splunk for log analysis?"

**A:** Splunk and GDC Dashboard AI serve different purposes:

| | Splunk | GDC Dashboard AI |
|---|---|---|
| **Best for** | Historical log search, alerting, dashboards | Real-time incident response |
| **How it works** | You write SPL queries, filter, correlate manually | AI reads logs and tells you the answer |
| **Cross-container** | Search each container separately | AI correlates ALL containers together |
| **Time to answer** | Minutes (build query → run → read → think) | Seconds (one click → AI delivers RCA) |
| **Retention** | Weeks/months ✅ | Live logs only ❌ |
| **Alerting** | ✅ Custom alerts | ❌ No built-in alerting |

**They work best together:** GDC Dashboard AI for immediate triage, Splunk for deep historical analysis.

---

### Q15: "Why not just use ArgoCD's built-in health checks?"

**A:** ArgoCD health checks are limited to sync status:
- ✅ "Is the deployment synced with Git?" → Yes/No
- ❌ "WHY is the pod crashing?" → No answer
- ❌ "What log errors are causing this?" → No visibility
- ❌ "How do I fix it?" → No recommendations

ArgoCD tells you **something is wrong**. GDC Dashboard tells you **what's wrong, why, and how to fix it**.

---

### Q16: "We already have kubectl access. Why do we need a dashboard?"

**A:** kubectl is powerful but:
1. **Requires CLI expertise** — not every developer knows `kubectl get pods -o json | jq '.items[] | select(.status.phase != "Running")'`
2. **No AI analysis** — kubectl shows raw data; you still need to interpret it
3. **Context switching** — jump between terminal, Splunk, documentation, Stack Overflow
4. **No correlation** — you manually connect logs from different containers

The dashboard wraps kubectl's power in a visual interface and adds AI on top. Think of it as **kubectl + Splunk + AI analyst, combined**.

---

## 🚀 Deployment & Operations

### Q17: "How do we deploy this?"

**A:** Same as any other app:

```bash
# Build the container
docker build -t your-registry/gdc-dashboard:latest .

# Push to registry
docker push your-registry/gdc-dashboard:latest

# Deploy via ArgoCD or kubectl
kubectl apply -f manifests/deploy.yaml -n your-namespace
```

The manifests include: Deployment + Service + ServiceAccount + RBAC RoleBinding.

---

### Q18: "What happens if the dashboard pod crashes?"

**A:** It restarts normally (standard K8s restart policy). There's no persistent state — the board reads from K8s API on every request. If it's down for a few seconds, users just see a brief disconnection. Nothing is lost.

---

### Q19: "Can multiple teams share one instance?"

**A:** Not recommended. Each team should deploy their own instance because:
- RBAC is namespace-scoped — one instance per namespace
- AI context is namespace-specific
- Isolation prevents cross-team interference
- Each team can customize their settings independently

---

### Q20: "What's the resource footprint?"

**A:**

| Resource | Value |
|----------|-------|
| **CPU request** | 100m |
| **CPU limit** | 500m |
| **Memory request** | 128Mi |
| **Memory limit** | 512Mi |
| **Image size** | ~200MB |
| **Pods** | 1 (single replica) |

Very lightweight — less resource usage than most microservices it monitors.

---

## 🔮 Future / Roadmap

### Q21: "What's next for this project?"

**A:** Five planned initiatives:

| # | Initiative | What It Adds |
|---|-----------|-------------|
| 1 | **AI Metrics & Observability** | Track every Gemini call: cost, latency, usage |
| 2 | **MCP Server** | Centralized K8s data access for AI agents |
| 3 | **Gemini API Gateway** | Governed, audited Gemini access for all apps |
| 4 | **Log Analytics Expansion** | Cross-namespace correlation, anomaly detection |
| 5 | **Teams/Email Bot** | Ask your cluster questions via Teams/email |

These transform the dashboard from a **team tool** into an **AI Operations Platform**.

---

### Q22: "Can other teams contribute features?"

**A:** Absolutely. The codebase is structured for contribution:
- **Mock mode** (`mock_app.py`) lets you develop without a cluster
- API endpoints are straightforward Flask routes
- AI features follow a documented pattern (collect data → build prompt → call Gemini → return JSON)
- PR process through standard Git workflow

---

*Keep this document handy during the demo. Most questions will fall into one of these categories.*
