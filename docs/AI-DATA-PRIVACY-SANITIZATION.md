# AI Log Analysis — Data Privacy & Sensitive Data Sanitization

> **Status:** 📋 Planning — implementation pending
> **Context:** Our applications handle sensitive data and are deployed on-prem. The AI features (log analysis, AI chat, AI diagnostics) send pod log content to Vertex AI / Gemini for analysis. This document captures the security implications and planned mitigations.

---

## Problem Statement

Our application runs on on-prem infrastructure because it processes sensitive data. When the AI features (log analysis, AI chatbot, AI diagnostics) are used, the raw pod logs — which may contain sensitive traces — are sent to Google's Vertex AI / Gemini API for analysis.

### Data Flow Today

```
Pod logs (contain sensitive data)
    │
    ▼
GDC Dashboard (mock-project-gemini)
    │
    │  HTTP POST to Vertex AI / Gemini API
    │  Body includes: raw log lines, pod names, error messages
    │
    ▼
Google Cloud (Vertex AI or Gemini API)
    │
    │  LLM processes the text → generates summary
    │
    ▼
Response back to our app
```

### What's at Risk

Sensitive data in our logs that gets sent as plaintext in the Gemini prompt:

- **PII**: customer names, emails, account numbers in log messages
- **Financial data**: transaction amounts, card tokens, routing numbers
- **Security tokens**: API keys, session IDs, JWTs accidentally logged
- **Internal infra**: hostnames, DB connection strings, internal IPs

---

## Vertex AI vs Gemini API — Risk Comparison

| | Vertex AI (`GCP_PROJECT_ID`) | Gemini API (`GEMINI_API_KEY`) |
|---|---|---|
| **Where data goes** | Our own GCP project | Google's public API endpoint |
| **Data residency** | Our chosen region (us-central1, etc.) | Google's choice |
| **Training on our data** | ❌ **No** — Google does NOT use Vertex AI customer data for model training | ❌ **No** — as of current terms (but terms can change) |
| **Data retention** | Logs retained per our GCP project settings | Google may retain inputs for up to 30 days for abuse monitoring |
| **SOC2/HIPAA** | ✅ Vertex AI is covered under GCP compliance (BAA available) | ❌ Consumer API — not covered |
| **Network path** | Can use VPC Service Controls + Private Google Access | Goes over public internet |
| **Who can see it** | Only our GCP project's IAM principals | Google's API infrastructure |

---

## Mitigation Options (Ranked: Most → Least Secure)

### Option 1: On-Prem LLM (Zero Data Leakage)

Run an open-source LLM (Llama 3, Mistral, Gemma) inside our own infrastructure. Logs never leave our network.

```
Pod → Our App → On-Prem LLM (e.g., vLLM/Ollama on GPU node)
                 ↑ Data stays here
```

- **Pro**: Zero external exposure
- **Con**: Needs GPU hardware, smaller models = lower quality responses

### Option 2: Log Sanitization Before AI (Recommended Pragmatic Approach)

Scrub sensitive data **before** sending to Gemini. The sanitizer redacts known-sensitive patterns so the LLM only sees `[REDACTED]` placeholders.

```
Pod logs → Sanitizer (redact PII, tokens, etc.) → Gemini
                                                    ↑ Only sees [REDACTED]
```

What to scrub:
- Email addresses → `[EMAIL_REDACTED]`
- Account/card numbers → `[ACCOUNT_REDACTED]`
- JWT/Bearer tokens → `[TOKEN_REDACTED]`
- SSN/ID numbers → `[PII_REDACTED]`
- IP addresses → `[IP_REDACTED]`
- Domain-specific patterns → defined by our compliance team

### Option 3: Vertex AI with VPC Service Controls

Use Vertex AI inside a VPC-SC perimeter. Data stays within our GCP org's security boundary.

```
Pod → VPN/Interconnect → Our GCP Project (VPC-SC) → Vertex AI
      ↑ Encrypted, private path                      ↑ Our project only
```

- **Pro**: Enterprise-grade, Google doesn't use data for training
- **Con**: Data still reaches Google-managed infrastructure

### Option 4: Limit What Gets Sent

Instead of sending raw logs, pre-process and send only structured metadata:

```python
# ❌ Dangerous — sends raw logs with potential PII
prompt = f"Here are the logs:\n{raw_logs}"

# ✅ Safe — sends only structured, non-sensitive metadata
prompt = f"""Analyze this pod health:
- Pod: billing-service-abc123
- Status: CrashLoopBackOff
- Restart count: 5
- Last error type: OOMKilled
- Memory limit: 512Mi
- No PII included."""
```

---

## The Sanitizer Challenge: Knowing What's Sensitive

### What a Generic Sanitizer CAN Detect (Universal Patterns)

| Pattern | Regex-Detectable? | Example |
|---------|-------------------|---------|
| Email addresses | ✅ Yes | `user@company.com` |
| Credit card numbers | ✅ Yes | `4111-1111-1111-1111` |
| SSN | ✅ Yes | `123-45-6789` |
| JWT tokens | ✅ Yes | `eyJhbG...` (starts with `eyJ`) |
| Bearer/API tokens | ✅ Mostly | `Bearer ghp_abc123...` |
| IP addresses | ✅ Yes | `10.245.12.98` |
| UUID/session IDs | ⚠️ Partially | Could be over-aggressive |

### What ONLY Our Team Knows (Domain-Specific)

| Our Sensitive Data | Why Generic Detection Fails |
|--------------------|-----------------------------|
| Account numbers in OUR format | Is `ACC-78291034` sensitive? Only we know our format |
| Customer IDs | Is `CUST_4829` PII? Depends on our business |
| Internal hostnames | Is `db-prod-oracle-fin.internal` sensitive? Our infosec decides |
| Transaction amounts | Is `$45,892.31` in a log sensitive? Context-dependent |
| Routing numbers | Is `021000021` a routing number or a random integer? |
| Domain-specific codes | Billing codes, trade IDs, policy numbers unique to our org |
| Custom PII fields | Patient IDs, loan numbers, portfolio IDs |

### How to Define Our Rules

```
Our infosec/compliance team defines:
  "These patterns are sensitive in OUR logs"
         │
         ▼
We encode those as regex rules or keyword lists
         │
         ▼
The sanitizer applies OUR rules before sending to AI
```

### Proposed Sanitizer Architecture

```python
# Config file or env var — OUR team defines these rules
SANITIZE_RULES = [
    # ── Universal patterns (provided by default) ──
    {"pattern": r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b", "replace": "[EMAIL]"},
    {"pattern": r"\b\d{3}-\d{2}-\d{4}\b", "replace": "[SSN]"},
    {"pattern": r"eyJ[A-Za-z0-9_-]+\.eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+", "replace": "[JWT]"},
    {"pattern": r"Bearer\s+[A-Za-z0-9._~+/=-]+", "replace": "Bearer [TOKEN]"},
    {"pattern": r"\b\d{4}[- ]?\d{4}[- ]?\d{4}[- ]?\d{4}\b", "replace": "[CARD_NUMBER]"},
    {"pattern": r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b", "replace": "[IP_ADDR]"},

    # ── OUR domain-specific patterns (compliance team provides) ──
    {"pattern": r"ACC-\d{8,12}", "replace": "[ACCOUNT_ID]"},
    {"pattern": r"CUST_\d{4,8}", "replace": "[CUSTOMER_ID]"},
    {"pattern": r"TXN-[A-Z0-9]{10,}", "replace": "[TRANSACTION_ID]"},
    # ... add more based on our data classification policy
]
```

### Important: A generic sanitizer provides a FALSE sense of security

It catches emails and SSNs but will miss `ACC-78291034` because nobody told it that's an account number. **Our compliance team must provide the domain-specific rules.**

---

## Recommended Implementation Plan

| Phase | Action | Owner |
|-------|--------|-------|
| 1. **Immediate** | Switch to **Vertex AI** (not API key) — our GCP project, covered by compliance controls | Dev team |
| 2. **Short-term** | Build a configurable **log sanitizer** function with universal patterns | Dev team |
| 3. **Short-term** | Get **domain-specific sensitive patterns** from compliance/infosec team | Compliance + Dev |
| 4. **Medium-term** | Evaluate **VPC Service Controls** for a GCP security perimeter | Infra + Security |
| 5. **Long-term** | Evaluate **on-prem LLM** (Gemma / Llama) for most sensitive operations | Platform team |

---

## Action Items

- [ ] Confirm we are using **Vertex AI** (not Gemini API key) in production
- [ ] Meet with compliance/infosec to get **domain-specific sensitive data patterns**
- [ ] Implement sanitizer function in `app.py` — all AI calls route through it
- [ ] Add sanitizer config as **environment variable or ConfigMap** so rules can be updated without code changes
- [ ] Add **logging** to track how many redactions the sanitizer makes per AI call
- [ ] Evaluate VPC Service Controls for our GCP project
- [ ] Document the sanitizer in the Help tab
