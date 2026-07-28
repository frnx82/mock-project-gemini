# AI Knowledge Assistant — Implementation Plan (v2)
# Regulatory & Trade Surveillance Platform

> **Adapted for:** Python microservices on GDC | Spark/PySpark | Impala | BigQuery | Dataproc | Cloud Composer | CloudSQL
> **Building on:** [AI-ORCHESTRATION-OBSERVABILITY-PLAN.md](AI-ORCHESTRATION-OBSERVABILITY-PLAN.md)

---

## 1. Problem Statement

In a **regulatory and trade surveillance** platform, teams constantly need to:

- Look up surveillance rules and alert-handling procedures during investigations
- Reference regulatory policies (SEC, FINRA, MiFID II, etc.) when reviewing flagged trades
- Find runbook steps for data pipeline issues (Spark jobs, Impala queries, Cloud Composer DAGs)
- Understand how ingestion flows work across the stack (PySpark → Impala → BigQuery)
- Answer audit questions with traceable, cited sources

An AI Knowledge Assistant that understands the **domain** and can cross-reference **live surveillance data** with **compliance documentation** would save significant time per investigation.

---

## 2. Architecture Decisions

| Requirement | Decision | Rationale |
|---|---|---|
| Chat interface | **Dashboard Web Widget + Google Chat** | Fits GDC ecosystem. Widget accessible during investigations |
| LLM | **Gemini API** (`google-genai`) | Already in use. Stays within Google ecosystem for GDC |
| Vector store | **ChromaDB** (self-hosted) | On-prem in GDC K8s. No external SaaS. Regulatory data stays internal |
| Embeddings | **Gemini `text-embedding-004`** | Same vendor, no additional API keys |
| Orchestration | **LangGraph** (new agent in existing graph) | Extends multi-agent plan. Knowledge Agent + Compliance Agent |
| Deployment | **GDC Kubernetes** | Same cluster as existing microservices |

> [!IMPORTANT]
> **Data security:** All document content and embeddings stay within the GDC cluster. No external vector DB SaaS. ChromaDB runs as a sidecar container with persistent volume — regulatory-sensitive content never leaves the environment.

### High-Level Architecture

```
   ┌──────────────────────────────────────────────────────┐
   │              Chat Interfaces                          │
   │  ┌──────────────┐  ┌─────────────────────────────┐   │
   │  │ Google Chat   │  │ Surveillance Dashboard      │   │
   │  │ Bot           │  │ (Knowledge Widget)          │   │
   │  └──────┬────────┘  └─────────────┬───────────────┘   │
   └─────────┼─────────────────────────┼───────────────────┘
             │                         │
   ┌─────────▼─────────────────────────▼───────────────────┐
   │            Flask API Gateway (existing)                │
   │  POST /api/ai/knowledge                                │
   │  POST /api/ai/converse  (enhanced)                     │
   └────────────────────────┬──────────────────────────────┘
                            │
   ┌────────────────────────▼──────────────────────────────┐
   │           LangGraph Supervisor                         │
   │  ┌──────────┬──────────┬──────────────┬────────────┐  │
   │  │ K8s      │ Data     │ Knowledge    │ Compliance │  │
   │  │ Agent    │ Agent    │ Agent (NEW)  │ Agent(NEW) │  │
   │  └──────────┴────┬─────┴──────┬───────┴─────┬──────┘  │
   └──────────────────┼────────────┼─────────────┼─────────┘
                      │            │             │
          ┌───────────▼──┐  ┌─────▼──────┐  ┌───▼─────────────┐
          │ Live Data     │  │ ChromaDB   │  │ Regulatory      │
          │ ┌───────────┐ │  │ (Vectors)  │  │ Knowledge Base  │
          │ │ Impala    │ │  │            │  │ ┌─────────────┐ │
          │ │ BigQuery  │ │  │ Org docs,  │  │ │ SEC rules   │ │
          │ │ CloudSQL  │ │  │ runbooks,  │  │ │ FINRA regs  │ │
          │ │ Dataproc  │ │  │ SOPs       │  │ │ MiFID II    │ │
          │ └───────────┘ │  └────────────┘  │ │ Alert SOPs  │ │
          └───────────────┘                  │ └─────────────┘ │
                                             └─────────────────┘
                      ▲
        ┌─────────────┘
        │  Document Ingestion Pipeline
        │  ┌──────┬───────┬───────┬───────┬────────────┐
        │  │ PDF  │ Word  │ Excel │ Text  │ Loom/Video │
        │  │      │       │       │       │ Transcripts│
        │  └──────┴───────┴───────┴───────┴────────────┘
```

---

## 3. Domain-Specific Document Categories

> [!NOTE]
> The ingestion pipeline organizes documents by category, which enables filtered searches (e.g., "search only regulatory policies" vs "search runbooks").

| Category | Examples | Typical Format |
|---|---|---|
| **Regulatory Policies** | SEC Rule 15c3-5, FINRA 3110, MiFID II RTS 25 | PDF, Word |
| **Surveillance Rules** | Alert logic definitions, threshold configs, model documentation | Word, Excel, Text |
| **Alert Handling SOPs** | How to investigate wash trades, layering, spoofing alerts | Word, PDF |
| **Data Pipeline Runbooks** | Spark job failure recovery, Impala table maintenance, DAG troubleshooting | Text, Word |
| **Architecture Docs** | Microservice interaction maps, data flow diagrams, schema docs | PDF, Word |
| **Audit & Compliance** | Exam prep materials, regulatory exam transcripts, remediation plans | PDF, Text |
| **Meeting Transcripts** | Loom recordings, investigation notes, compliance meeting notes | Text |
| **Ingestion Specs** | PySpark job configs, Cloud Composer DAG docs, Dataproc cluster specs | Text, Excel |

---

## 4. Proposed Changes

### Component 1: Document Ingestion Pipeline

#### [NEW] `knowledge/ingest.py`

```python
# Domain-aware ingestion pipeline

Pipeline:
  1. Upload via API or bulk directory scan
  2. Format detection & text extraction:
     - PDF  → PyMuPDF (regulatory filings, policies)
     - DOCX → python-docx (SOPs, runbooks)
     - XLSX → openpyxl (surveillance rule configs, threshold tables)
     - TXT  → direct read (Loom transcripts, meeting notes)
     - CSV  → pandas (alert definitions, rule mappings)
  3. Domain-aware chunking:
     - Regulatory docs → chunk by section/article number
     - SOPs → chunk by step/procedure
     - Runbooks → chunk by scenario/troubleshooting step
     - Transcripts → chunk by time window or topic
  4. Embedding: Gemini text-embedding-004
  5. Store: ChromaDB with rich metadata
```

**Metadata per chunk:**
```json
{
  "source": "policies/SEC-Rule-15c3-5.pdf",
  "category": "regulatory_policy",
  "regulator": "SEC",
  "section": "Rule 15c3-5(c)(1)(ii) — Erroneous Order Prevention",
  "page": 12,
  "last_updated": "2026-01-15",
  "classification": "internal",
  "chunk_index": 8,
  "tags": ["market-access", "pre-trade-risk", "erroneous-orders"]
}
```

#### [NEW] `knowledge/ingest_api.py`

| Endpoint | Method | Description |
|---|---|---|
| `/api/knowledge/upload` | POST | Upload & ingest a document with category tag |
| `/api/knowledge/bulk_ingest` | POST | Ingest all files from a directory path |
| `/api/knowledge/documents` | GET | List all ingested documents (filterable by category) |
| `/api/knowledge/documents/<id>` | DELETE | Remove a document & its embeddings |
| `/api/knowledge/reindex` | POST | Re-ingest all documents (after schema changes) |
| `/api/knowledge/status` | GET | Pipeline health + document counts by category |

---

### Component 2: Vector Store (ChromaDB)

#### [NEW] `knowledge/vectorstore.py`

```python
# Two ChromaDB collections for different purposes:

Collection: "org_knowledge"
  - General org docs, runbooks, SOPs, architecture
  - Searched by Knowledge Agent

Collection: "regulatory_compliance"
  - Regulatory policies, rules, exam materials
  - Searched by Compliance Agent
  - Tagged by regulator (SEC, FINRA, MiFID, etc.)

Both collections:
  - Embedding: Gemini text-embedding-004
  - Distance: cosine similarity
  - Storage: PVC at /data/chromadb
  - Top-K: 5 results, threshold: 0.72
```

---

### Component 3: Two Specialized Agents

#### [NEW] `knowledge/knowledge_agent.py` — General Knowledge Agent

Handles: runbooks, SOPs, architecture docs, pipeline documentation

```python
Knowledge Agent Tools:
  - search_docs(query, category=None)
      → Semantic search across org docs
  - search_runbook(query, pipeline=None)
      → Filtered search: Spark, Impala, Composer, Dataproc runbooks
  - get_pipeline_doc(pipeline_name)
      → Return full documentation for a specific pipeline/DAG
  - list_documents(category=None)
      → Show available documents

Example queries:
  "How do I restart the trade ingestion Spark job?"
  "What's the SOP for Impala table compaction?"
  "Show me the Cloud Composer DAG for EOD processing"
  "What microservice handles alert enrichment?"
```

#### [NEW] `knowledge/compliance_agent.py` — Compliance Agent

Handles: regulatory policies, surveillance rules, alert procedures

```python
Compliance Agent Tools:
  - search_regulation(query, regulator=None)
      → Search SEC/FINRA/MiFID policies
  - search_alert_procedure(alert_type)
      → How to investigate a specific alert type
  - get_surveillance_rule(rule_id)
      → Full rule definition + thresholds
  - cite_regulation(topic)
      → Return specific regulatory citations

Example queries:
  "What does FINRA 3110 say about supervisory review?"
  "How do I investigate a layering alert?"
  "What are the wash trade detection thresholds?"
  "Cite the SEC rule for market access risk controls"
```

---

### Component 4: Cross-Domain Power Queries

This is where it gets powerful — combining **live surveillance data** with **compliance knowledge**:

```
SCENARIO 1: Investigation Assistance
─────────────────────────────────────
Analyst: "I have a spoofing alert for account XYZ.
          What's the investigation procedure and pull
          the recent order activity?"

  → Compliance Agent: searches alert SOPs for "spoofing investigation"
     Returns: step-by-step procedure with citations
  → Data Agent: queries Impala/BigQuery for account XYZ order history
     Returns: recent orders with cancel rates
  → Supervisor: combined response with procedure + live data


SCENARIO 2: Pipeline Troubleshooting
─────────────────────────────────────
Analyst: "The EOD trade ingestion job failed.
          What does the runbook say and check the
          Spark job status?"

  → Knowledge Agent: searches runbooks for "EOD trade ingestion failure"
     Returns: troubleshooting steps from runbook
  → K8s Agent: checks Spark driver pod status, gets logs
     Returns: OOM error in executor
  → Supervisor: "The runbook says to increase executor memory
     (Step 3.2). The Spark job shows OOM — this matches."


SCENARIO 3: Regulatory Exam Prep
─────────────────────────────────
Compliance: "Summarize our wash trade surveillance
             coverage and cite the relevant FINRA rules"

  → Compliance Agent: searches "wash trade" across regulatory docs
     Returns: FINRA Rule 5210, relevant sections with citations
  → Knowledge Agent: searches "wash trade" across surveillance rules
     Returns: internal rule definitions, thresholds, model docs
  → Supervisor: combined compliance coverage summary with citations


SCENARIO 4: Data Lineage Questions
──────────────────────────────────
Analyst: "How does trade data flow from ingestion to
          the surveillance alerts table?"

  → Knowledge Agent: searches architecture docs + pipeline docs
     Returns: PySpark ingestion → Impala staging → enrichment
              microservice → BigQuery alerts table
  → Cites: architecture-doc.pdf Section 3, data-flow-spec.docx
```

---

### Component 5: Chat Integration

#### Option A: Dashboard Widget (Build First)

```
Surveillance Dashboard additions:
  - "Knowledge" tab or floating widget (bottom-right)
  - Category filter dropdown (Regulatory, Runbooks, SOPs, All)
  - Source citation links (clickable → opens original doc)
  - Uses existing Socket.IO + marked.js infrastructure
  - File upload drag-and-drop for document ingestion
```

#### Option B: Google Chat Bot (Phase 2)

```
For analysts who work in Google Chat:
  - @KnowledgeBot "how do I investigate a layering alert?"
  - @KnowledgeBot "what's the FINRA rule for trade reporting?"
  - Formatted responses with citations
  - Links back to Dashboard for detailed investigation
```

---

## 5. File Structure

```
mock-project-gemini/
├── app.py                              # [MODIFY] Add knowledge routes
├── knowledge/                          # [NEW] Knowledge Assistant module
│   ├── __init__.py
│   ├── ingest.py                       # Document ingestion pipeline
│   ├── ingest_api.py                   # Upload/manage endpoints
│   ├── vectorstore.py                  # ChromaDB wrapper (2 collections)
│   ├── knowledge_agent.py              # General docs/runbooks agent
│   ├── compliance_agent.py             # Regulatory/surveillance agent
│   ├── gchat_bot.py                    # Google Chat integration
│   ├── prompts.py                      # Domain-specific RAG prompts
│   └── parsers/                        # Format-specific parsers
│       ├── pdf_parser.py
│       ├── docx_parser.py
│       ├── xlsx_parser.py
│       └── text_parser.py
├── documents/                          # [NEW] Document storage
│   ├── regulatory/                     # SEC, FINRA, MiFID policies
│   ├── surveillance_rules/             # Alert logic, thresholds
│   ├── sops/                           # Investigation procedures
│   ├── runbooks/                       # Pipeline troubleshooting
│   ├── architecture/                   # System design docs
│   └── transcripts/                    # Meeting notes, Loom exports
├── templates/index.html                # [MODIFY] Add Knowledge widget
└── requirements.txt                    # [MODIFY] Add new deps
```

**New dependencies:**
```
chromadb>=0.5.0
PyMuPDF>=1.24.0
python-docx>=1.1.0
openpyxl>=3.1.0
langchain-text-splitters>=0.3.0
pandas>=2.0.0
```

---

## 6. Implementation Phases

| Phase | What | Effort | Priority |
|---|---|---|---|
| **Phase 1** | Document parsers (PDF, DOCX, XLSX, TXT) + chunking | 2 days | 🔴 Must |
| **Phase 2** | ChromaDB setup + Gemini embeddings + ingestion API | 1 day | 🔴 Must |
| **Phase 3** | Knowledge Agent (runbooks, SOPs, architecture) | 2 days | 🔴 Must |
| **Phase 4** | Compliance Agent (regulatory, surveillance rules) | 1 day | 🔴 Must |
| **Phase 5** | Dashboard web widget with citations | 1 day | 🔴 Must |
| **Phase 6** | Cross-domain queries (Knowledge + Data Agent) | 2 days | 🟡 High |
| **Phase 7** | Google Chat bot integration | 1-2 days | 🟢 Nice |

**Total: ~10-12 days**

---

## 7. Open Questions

> [!IMPORTANT]
> Need your input before building:

1. **Sample documents** — Can you provide 2-3 sample docs (redacted/mock is fine) in any format? Or should I create mock regulatory policies and surveillance SOPs for testing?

2. **Priority agent** — Should I build the **Compliance Agent** (regulatory focus) or **Knowledge Agent** (runbooks/pipelines focus) first? Which would get more daily use?

3. **Existing docs location** — Are docs currently in a shared drive, Confluence, or local folders? This affects whether we build a directory watcher vs upload-only.

4. **Phase scope** — Should I start with Phases 1-5 (standalone RAG assistant) and add cross-domain/Google Chat later? Or go all-in?

---

## 8. Verification Plan

### Automated Tests
- Parser tests: 1 sample file per format (PDF, DOCX, XLSX, TXT)
- Embedding test: verify chunk → embed → retrieve roundtrip
- RAG quality: 10 curated Q&A pairs per agent, measure accuracy
- Citation test: every answer must include at least 1 source citation

### Manual Verification
- Ingest 5+ documents across categories
- Ask 10 regulatory questions → verify citations match source
- Ask 5 pipeline/runbook questions → verify accuracy
- Test cross-domain: "check if alert thresholds match FINRA guidance"
- Demo to team for feedback
