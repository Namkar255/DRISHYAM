# DRISHYAM

**Evidence intelligence for criminal investigation — where every line can be walked back to the page it came from.**

Built for **Smart India Hackathon 2026**, problem statement **SIH26189 — AI-Powered Criminal Network Analysis System**, proposed by the **Ministry of Home Affairs (NCRB, Women Safety Division)**.

---

## The problem, and the half of it that usually gets skipped

An investigating officer opens a case with nine files: an FIR, a supplementary report, three WhatsApp screenshots, a call record, a bank statement, a surveillance note, and one file that is corrupt. The people in them are connected, but no single file shows the connection.

Finding that network is the easy half. A whiteboard does it in an afternoon.

The hard half comes months later, when a defence lawyer asks **"where does it say that?"** If nobody can put a finger on the exact line, that point is not weak evidence. It is not evidence at all.

DRISHYAM is built for the second half. It assembles the network *and* keeps every claim attached to the file, page and position it was read from.

---

## The one thing worth knowing

Every relationship in this system carries a reference to the evidence that produced it — and that is enforced by the database, not by discipline.

```
RawExtractionArtifact → ModelInferenceRun → NormalizedRecord → RecordRelation → EntityRelation
                                                                     ↑              ↑
                                                          NOT NULL source reference
```

A relationship row **cannot be saved** without naming its source. So "every finding is traceable" is not a promise the team makes; it is a constraint the schema enforces.

On PDFs this goes further: PyMuPDF gives back text *and its coordinates*, so clicking a finding opens the source page with the exact line boxed — not the filename, not the page number, the line.

---

## What it does

| | |
|---|---|
| **Evidence Vault** | Ingests PDFs, images, CSV/XLSX and text. Originals are preserved and never edited. Each file is SHA-256 hashed on arrival, and each is processed as its own queued job — one bad file cannot take the case down. |
| **Extraction** | PyMuPDF for PDFs (with coordinates), Tesseract for images, column mapping for tabular sources. Whatever the reader physically produced is stored *before* anything interprets it. |
| **Entity resolution** | Identifiers are canonicalised so one phone number written four ways resolves to one node. Names are **never** fuzzy-matched — see *What it refuses to do*. |
| **Network** | A relationship graph over NetworkX 3.4: degree, betweenness and eigenvector centrality, Louvain communities, articulation points and bridges. Five layouts, an ego-scoped subject view, and every edge opens its source. |
| **Timeline** | Events placed against an incident window the officer declares. Until that window is declared, no temporal reading is offered — "contact before the incident" has no meaning until somebody says when the incident was. |
| **Alerts** | 15 detection rules over the graph, timeline, evidence and transactions. Each alert shows its working: the rule, the files it was built from, and the steps in order. |
| **Review** | Everything waiting on a person. Extraction output arrives as a *candidate*, not a fact. Decisions are kept as history — a reversal is a new entry, never an edit over the old one. |
| **Integrity** | A hash-chained audit log that the product **recomputes in front of you**, a Merkle tree over the evidence set with inclusion proofs, and Trustify receipts that travel with the report. |
| **Cross-district ledger** | Two districts holding the same phone number can learn that fact without either seeing the other's case. Only an HMAC digest, a case reference and a contact are published. |
| **Prior record** | Looks up the national record of registered cases by identifier. Every disposal is shown — including acquittals. |
| **Reports** | Read in place rather than downloaded, searchable with hit positions, and every line clicks through to its evidence. Versions are never silently replaced. |
| **Trace Orb** | Two scopes with a wall between them. HELP explains the product and reaches a hosted model, so no case content may enter it. CASE answers about the open case from its own rows, with **no model behind it at all**. The scope in use is always on screen, and the operator chooses it. |

---

## What it refuses to do

These are pass-or-fail checks in the test suite, run on every build. They exist because the failure modes they guard against are the ones that put the wrong person in a chargesheet.

**1. It will not complete a value it could not read.**
A handwritten field that scans as `97?4?8821?` stays that way. Completing it would make the number the system's, not the evidence's. No phone number in the benchmark case begins `97`, so a fabricated one is unambiguous.

**2. It will not merge two names that differ.**
`Yash Kumar Gupta` and `Yash Kumar Gupt` are two people in two sources. They stay two nodes. Names are never fuzzy-matched at all, because any threshold loose enough to merge spelling variants is loose enough to merge two different men. Inventing a person is worse than missing a link.

**3. It will not resolve a contradiction by choosing.**
The FIR says the call came at 21:15. The call record says 21:45. Both readings survive, each attached to the source that made it. Quietly picking one hides exactly what the investigating officer most needs to see.

**4. A malformed file fails alone.**
It is rejected, it is recorded as rejected, and the case keeps standing.

**And a fifth, which is architectural rather than a test:** nothing in this system scores a person. There is no risk level, no threat score, no ranking of who matters. Network position is stated as *review priority* with the caveat attached, because a number beside a name invites exactly the reading this product exists to refuse.

---

## Architecture

```
React 19 · Vite 7 · TypeScript · Tailwind 4 · wouter
                    │
                    ▼
        FastAPI 0.115  (Python 3.12)
                    │
        ┌───────────┼───────────────┐
        ▼           ▼               ▼
   PostgreSQL    Redis          Ollama
   36 tables   ┌─ 5 queues ─┐   qwen2.5vl:7b
   23 migrations│ Celery 5.4 │   (on the unit's own hardware)
                └────────────┘
                              optional escalation ↓
                              Groq, administrator-gated
```

**Reading:** PyMuPDF 1.24 · Tesseract OCR · Pillow 11 · pandas / openpyxl
**Analysis:** NetworkX 3.4
**Integrity:** SHA-256 hash chain · Merkle tree with inclusion proofs · HMAC-SHA256 ledger

### On the AI, plainly

The vision model runs **locally**. A hosted model exists as an escalation path for pages the local model reads with low confidence, and it sits behind two separate switches (`GROQ_ENABLED`, `EXTERNAL_EVIDENCE_TRANSMISSION`) that an administrator must set. With those off, evidence does not leave the deployment.

### On the ledger, plainly

The cross-district ledger is an **append-only hash-chained store with a shared key**. There is no consensus, no mining and no distributed agreement, and this project does not call it a blockchain — that would be a claim about Byzantine fault tolerance which nothing here provides.

The digest is HMAC and not a plain hash for a specific reason: a plain SHA-256 of a ten-digit phone number is the phone number with extra steps, and a laptop enumerates that space in an afternoon. Without the shared key, publishing is refused rather than falling back to something that looks like protection and is not.

---

## Getting started

**Requirements:** Docker and Docker Compose. For local inference, [Ollama](https://ollama.com) with `qwen2.5vl:7b` pulled.

```bash
git clone https://github.com/Namkar255/DRISHYAM.git
cd DRISHYAM/backend

cp .env.example .env        # then fill in DATABASE_URL, REDIS_URL, SECRET_KEY
docker compose up -d        # runs migrations, then API on :8000 and the worker
```

Frontend:

```bash
cd frontend
npm install
npm run dev                 # Vite dev server
```

Generate the synthetic benchmark case and seed the national record:

```bash
cd backend
python -c "from scripts import benchmark_case; benchmark_case.generate()"
python -m scripts.seed_prior_records
```

Tests:

```bash
cd backend && pytest
```

> **Note on hardware.** The vision model is ~6 GB. On a GPU with 6 GB of VRAM it partially offloads to CPU and a text-heavy PDF can take tens of minutes. Lowering `OLLAMA_NUM_CTX` leaves more room on the card.

---

## Measured, not asserted

Everything below is regenerated from `backend/scripts/` against a synthetic case whose correct answers are written down beside it, so the claim is a measurement anyone can re-run rather than an assertion.

| | |
|---|---|
| People, vehicles, organisations, accounts, phone numbers | **100%** recall and precision |
| Place names | 2 of 3 |
| **Cross-source identity resolution** | **72%** — the weakest number, and the next piece of work |
| Identifiers corroborated outside a single image | 92.3% |
| The four refusal checks above | 4 / 4 |
| Test suite | 36 files, 464 test functions |

The dataset behind the prior-record feature is deliberately mixed: of six registered cases, one is a conviction, two are open, one ended in acquittal, one was closed without a chargesheet and one was quashed. A demo dataset of six convictions would look more impressive and would teach every viewer the exact inference this product exists to refuse.

---

## Known limits

Stated here rather than discovered by a reviewer.

- **Cross-source identity resolution is at 72%.** It is a recall problem, not a precision one — every link it did make was correct.
- **OCR on degraded images can misread an identifier**, and because names and values are never auto-merged, a misread arrives as a *separate* entity for a human to reject. Honest, but it means a blurred source can add noise to the entity list.
- **The shared-device finding is an alert, not a graph edge.** The IMEI is a node; the "these two numbers ran on one handset" conclusion lives in the alert with its working, not as a drawn line.
- **Contradictions are recorded by a reviewer**, not raised automatically. The conflicting readings both survive in the timeline; turning that into a filed contradiction is a human act.
- **No disaster-recovery story yet.** Per-file queueing means one bad file cannot sink a case, but backup and restore are not built.
- **Cross-district key distribution is unsolved.** The ledger works; agreeing the shared key between real forces is an operational problem this prototype does not answer.
- **No formal security audit has been performed.**

---

## Legal context

DRISHYAM is a prototype for controlled evaluation. It is not a deployed crime database and it does not decide guilt.

- **BSA §63** — electronic records and the conditions for their admissibility shape the provenance and integrity design.
- **BSA §46** — previous bad character is generally not relevant. The prior-record lookup exists so an investigator can reach the officer who handled an earlier case, **not** so the present case can lean on it. Every disposal is shown, nothing is scored, and the caveat travels with the record wherever it appears.

Every name, number, vehicle, account and place in this repository is invented, and the generated files say so inside themselves.

---

## Layout

```
backend/
  app/
    api/                    FastAPI routers
    alerts/                 15 detection rules
    evidence_intelligence/  extraction, grounding, model providers
    graph/                  NetworkX analytics, projections, connections
    parsers/                PDF, image, CSV, XLSX readers
    services/               pipeline, ledger, prior_record, temporal, reporting
    models/                 SQLAlchemy — 36 tables
  migrations/               Alembic — 23 revisions
  scripts/                  benchmark case generator, seeds, benchmark runner
  tests/                    36 files
frontend/client/src/
  pages/workspace/          the investigator workspace
  components/               evidence viewer, chain verification, entity profile
  api/                      typed API clients
demo-evidence/              synthetic evidence pack
```

---

## Team

**Ctrl Freaks_97322** · Team ID 157473 · MNNIT Allahabad
Smart India Hackathon 2026 · SIH26189 · Ministry of Home Affairs · Blockchain & Cybersecurity

> *See the truth. Prove the truth.*
