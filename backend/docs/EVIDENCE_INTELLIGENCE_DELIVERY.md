# DRISHYAM — Evidence Intelligence Upgrade: Delivery Notes

Companion to [`EVIDENCE_INTELLIGENCE_AUDIT.md`](EVIDENCE_INTELLIGENCE_AUDIT.md) (Phase 1) and
[`EVIDENCE_INTELLIGENCE_DESIGN.md`](EVIDENCE_INTELLIGENCE_DESIGN.md) (architecture and routing).

---

## 1. Changed files

### New (nothing pre-existing was moved or renamed)

| Path | Purpose |
|---|---|
| `app/evidence_intelligence/references.py` | `SourceReference` — one provenance address for file, page, line range, OCR block, bbox, email header, CSV row/column, chat message index, reviewer decision |
| `app/evidence_intelligence/schema.py` | Canonical record schema, `FieldProvenance`, observation basis, relation candidates |
| `app/evidence_intelligence/patterns.py` | Identifier/amount/date regexes with identifier masking |
| `app/evidence_intelligence/detection.py` | `FileTypeDetector` — content-based type detection |
| `app/evidence_intelligence/ocr.py` | `OCRAdapter` + `LayoutAnalysisAdapter` — blocks with bbox/page/block-id |
| `app/evidence_intelligence/extraction.py` | `NativeExtractionAdapter` — per-format deterministic extraction |
| `app/evidence_intelligence/grounding.py` | `StructuredOutputValidator` — quote and citation verification |
| `app/evidence_intelligence/confidence.py` | `ConfidenceScorer` — bands + mandatory-review rules |
| `app/evidence_intelligence/correlation.py` | `CorrelationEngine` — exact rules, then optional semantic |
| `app/evidence_intelligence/providers/base.py` | `VLMAdapter` protocol, error taxonomy, cache keys |
| `app/evidence_intelligence/providers/ollama.py` | `OllamaVLMAdapter` — local first pass |
| `app/evidence_intelligence/providers/groq.py` | `GroqVLMAdapter` — escalation only |
| `app/evidence_intelligence/providers/router.py` | `ModelRouter` — routing, escalation, reconciliation |
| `app/evidence_intelligence/providers/prompts.py` | Versioned system prompt + strict JSON schema |
| `app/evidence_intelligence/providers/mock.py` | Scripted adapters for tests and `mock` routing mode |
| `app/services/grounded_pipeline.py` | Pipeline orchestration and persistence |
| `app/services/record_review.py` | `ReviewService` for records and relations |
| `app/api/grounded.py` | 10 new case-scoped endpoints |
| `app/schemas/grounded.py` | Request/response contracts |
| `migrations/versions/d1c8f4e7a930_*.py` | Additive migration |
| `tests/fixtures/synthetic.py` | Synthetic-only evidence builders |
| `tests/unit/*` | 65 unit tests |
| `.env.example` | Configuration template with placeholders only |
| `docs/*.md` | Audit, design, this document |

### Modified (5 files, all additive)

| Path | Change |
|---|---|
| `app/core/config.py` | Added the `EVIDENCE_*` / `OLLAMA_*` / `GROQ_*` settings block and `groq_transmission_allowed` |
| `app/models/entities.py` | 9 new `EvidenceStatus` members + 5 new table classes |
| `app/api/router.py` | Registered the grounded router (2 lines) |
| `app/workers/tasks.py` | Added `reanalyze_evidence_task` |
| `app/services/pipeline.py` | `db.commit()` after parsing (bug fix, see below) + `_run_grounded()` hook |

**Bug fixed in existing code.** `process_evidence` added `ExtractedText` to the session but its
`except` branch called `db.rollback()` before recording failure, so a crash during event extraction
discarded parser output that had already succeeded. Raw extraction is now committed first.

---

## 2. Database migration notes

Revision **`d1c8f4e7a930`**, chained from the previous head `c4f2d9a8b7e6`.

**Creates:** `raw_extraction_artifacts`, `model_inference_runs`, `normalized_records`,
`record_relations`, `record_reviews`.

**Alters:** adds 9 members to the `evidence_status` enum. These use the **member name**
(`REVIEW_REQUIRED`, not `review_required`) because SQLAlchemy's `Enum` persists names — the
existing members are stored as `UPLOADED`, `COMPLETED` and so on.

No existing table, column, index, constraint or row is modified. Historic cases, evidence,
reports, Trustify receipts and the audit chain are untouched.

```bash
alembic upgrade head        # apply
alembic downgrade -1        # roll back
```

**Verified on a clean PostgreSQL 16 database:** full chain applies from empty, all 5 tables and 22
enum members present, new members round-trip through SQLAlchemy, and `downgrade -1` drops all 5
tables (0 remaining). The added enum members are deliberately **not** removed on downgrade —
PostgreSQL cannot drop an enum value, and recreating the type would require rewriting every
`evidence_files` row. Unused members are inert.

---

## 3. Provider setup

### Ollama (local first pass)

```bash
# 1. Install from https://ollama.com/download
# 2. Pull the vision model
ollama pull qwen2.5vl:7b     # or qwen2.5vl:3b on a weaker machine
# 3. Confirm it is serving
curl http://localhost:11434/api/tags
```

Then in `.env`:

```
LLM_ROUTING_MODE=local_first
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_VISION_MODEL=qwen2.5vl:7b
```

### Groq (escalation only)

1. Create an API key in the Groq console.
2. Put it in `.env` — **never** in source, fixtures, logs or this document.
3. Sending evidence off the machine needs **both** switches plus the key:

```
GROQ_ENABLED=true
EXTERNAL_EVIDENCE_TRANSMISSION=enabled
GROQ_API_KEY=<your key, in .env only>
GROQ_MODEL=qwen/qwen3.8-27b
GROQ_ESCALATE_BELOW_CONFIDENCE=0.85
```

`.env` is already covered by `.gitignore`. `GROQ_MODEL` is carried from the specification as the
documented default — **verify the exact model id against Groq's live model list before enabling.**
An unknown model is classified as `model_not_found`, which falls back to the local result rather
than failing the evidence.

---

## 4. Automated test results

Command:

```bash
pytest tests/unit -q                 # no database, no network, no provider
pytest tests -q                      # full suite, needs PostgreSQL
alembic upgrade head                 # migration check
```

| Suite | Result |
|---|---|
| `tests/unit` (new) | **71 passed, 0 skipped** — including 3 real-Tesseract OCR tests |
| Migration apply + downgrade on clean PG 16 | **passed** |
| `tests/` full suite | 13 passed, **4 pre-existing failures** |
| Live Ollama run (`qwen2.5vl:7b`) | **5/5 acceptance checks passed** — see §5b |

Tesseract 5.4.0 is installed, so the real-OCR tests run rather than skip. Running the suite
requires `C:\Program Files\Tesseract-OCR` on `PATH` (added to the user PATH during setup; a new
terminal picks it up automatically).

### The 4 failures are pre-existing, not regressions

Each was reproduced with `EVIDENCE_INTELLIGENCE_ENABLED=false` — i.e. with the new pipeline fully
disabled — and fails identically:

| Test | Cause | Related to this work? |
|---|---|---|
| `test_cross_case_intelligence` (×2) | Test helper creates a case without `description`; the API has required it since migration `c4f2d9a8b7e6`. Fails with `{"detail":"Case description is required."}` | No |
| `test_end_to_end` | Uploads a PNG; the **legacy** `app/parsers/registry.py` OCR path raises `TesseractNotFoundError`, so that evidence item ends `failed` | No |
| `test_report_preview` | Hardcoded Linux path `/home/ubuntu/drishyam_local_runtime/...`; cannot pass on Windows | No |

They were left untouched: fixing them is outside the scope of this upgrade.

---

## 5. WhatsApp screenshot walkthrough

Synthetic screenshot: header `+91 9876543210`, left bubble
`bhai is number pe 25000 bhej de`, right bubble `theek hai bhej raha hu`.

| Stage | Result |
|---|---|
| Detection | `source_type = screenshot` (content + declared category) |
| OCR | Blocks with bbox and ids: `block-1` header, `block-2` message, … |
| Layout | Header band isolated; left bubble → `incoming` (`direct_visual`); centre-band bubbles → unresolved |
| Extraction | `amount = {value: 25000.0, currency: null}`, quote `"25000"`, ref `image:block-2` |
| Identity | `chat_participant_identifier = "+91 9876543210"` (direct). `sender = null`, `receiver = null` |
| Model | `event_type = possible_payment_request`, basis **inferred**, confidence 0.78 |
| Grounding | `observed_text` matched against source; every direct claim's quote verified |
| Scoring | Band from model + validation confidence; `requires_human_review = true` |
| Reason | "Record carries key findings that affect case conclusions: amount, event_time; Record meaning is contextual rather than directly represented in the source." |

Against the specification's 10 mandatory expectations — all covered by
`tests/unit/test_whatsapp_acceptance.py`:

1. Exact Hinglish text preserved ✓
2. OCR block + bbox references present ✓
3. Header number stored **only** as `chat_participant_identifier` ✓
4. `25000` extracted and grounded ✓ — currency stays `null` because no symbol is visible
5. Payment intent marked `inferred` ✓
6. Missing sender/receiver stay `null` — a model naming "Amit Sharma" is dropped as ungrounded ✓
7. Direction set only where the bubble clearly hugs one side ✓
8. Blurry/cropped forces review ✓
9. Model disagreement preserves both raw outputs and records a conflict ✓
10. Original bytes and SHA-256 unchanged after processing ✓

---

## 5b. Live local-model run (verified)

Ollama 0.33.3 with `qwen2.5vl:7b` (Q4_K_M, 5.97 GB, vision) against the synthetic screenshot:

| Check | Result |
|---|---|
| Model returned parseable JSON | pass |
| `sender` stayed `null` (not visible in source) | pass |
| `receiver` stayed `null` (not visible in source) | pass |
| Parser amount `25000` preserved | pass |
| Record flagged for human review | pass |

Two integration defects surfaced only under a real model and were fixed:

1. **Cold-start 500.** Ollama answers `5xx` while loading a model — over a minute for a cold 7B
   vision model. The adapter classified that as a dead host and tripped the circuit breaker,
   silently costing the evidence item its entire model pass. It now retries a bounded number of
   times before giving up.
2. **Flat output instead of the field-object shape.** The model returned
   `"chat_participant_identifier": "+91..."` rather than the `{value, basis, quote,
   source_reference}` object the validator expects, so its output was being silently discarded. A
   worked example was added to the system prompt (`PROMPT_VERSION` bumped to
   `grounded-normalize-v2`) and the model now emits the correct shape.

**Operational note — VLM and OCR will disagree on screenshots.** In the live run, Tesseract read
the header as `4919878543210` while the vision model read the pixels correctly as `+919876543210`.
The system did not silently pick a winner: it recorded a `chat_participant_identifier` conflict,
kept both readings, set `validation_status = mismatch` and forced review. Expect this often — the
vision model usually reads screenshot text better than Tesseract, and reviewers will usually side
with it. The deterministic value still wins by default because the alternative is letting a model
overwrite extraction, which the evidence rules forbid.

## 5c. Live escalation run (verified in the deployed stack)

Run inside `backend-api-1` against the live configuration, with `force_escalation=True`:

```
ollama qwen2.5vl:7b       succeeded
groq   qwen/qwen3.8-27b   succeeded
elapsed 101.6s

event_type       possible_payment_request
amount           25000.0  (currency null — none visible)
sender/receiver  None / None
escalated        True
conflicts        []
band / status    high / validated
review required  True
```

`GROQ_MODEL=qwen/qwen3.8-27b` was confirmed present in Groq's live catalogue (14 models on this
account) and accepts image content. Both providers agreed, so no conflict was recorded; the record
still requires review because it carries a key amount and its meaning is inferred.

## 6. Provider failure / fallback walkthrough

| Scenario | Behaviour |
|---|---|
| Ollama not installed | `unavailable` recorded; deterministic record still produced with full provenance; escalation reason logged |
| Ollama returns invalid JSON | Attempt marked `rejected`; parser values untouched; escalation triggered |
| Model contradicts a parser value | Parser wins; field added to `conflict_fields`; `validation_status = mismatch`; review forced |
| Model quotes text not in the source | Field dropped as `ungrounded`; value stays `null` |
| Local confidence < 0.85 | Escalation attempted, with the numeric reason recorded |
| Groq disabled | `ProviderError(disabled)` — evidence never leaves the machine |
| Both providers down | Deterministic extraction, provenance, confidence, correlation and review all still work |
| Provider unreachable, 300-row file | Circuit breaker trips after the **first** failure; not dialled again for that evidence item |

Upload, storage, evidence access and report generation are unaffected in every case.

---

## 7. Supported vs inferred vs review-required

- **`direct` / `direct_visual`** — visible in the source or deterministically parsed. Carries a
  verbatim quote and a source reference. Example: a CSV `Amount` cell, an email `From` header, a
  bubble's left/right placement.
- **`inferred`** — suggested by layout, language or context but not proven. Never validated, never
  presented as fact. Example: `possible_payment_request`.
- **`unknown`** — the source does not establish it. Stored as `null` **with a reason**, never
  guessed.

Review is mandatory when confidence is below 0.85, a model conflicts with the parser, identity or
role is inferred, a key amount/ID/timestamp is present, the content is sensitive or threatening, a
relation is semantic-only, or the source is blurry/cropped/incomplete.

---

## 8. Known limitations

1. **Host-side DNS interception (Proxifier).** Every hostname resolves to a fake `127.110.0.0/16`
   address over UDP:53 on this machine. `docker-compose.yml` already works around it for the
   containers (`dns: 8.8.8.8` + `use-vc`, i.e. DNS over TCP, which is not intercepted). Host-side
   Python processes and the `ollama` CLI are still affected — the Ollama *server* downloads fine,
   the CLI does not.
2. **OCR fidelity is imperfect and is preserved as-is.** Against the synthetic fixture, real
   Tesseract reads `bhai is number pe 25000 bhej de` as `bhatisnumber pe 25000 bhe} de` and the
   header `+91 9876543210` as `4919878543210`. The digits that matter survived, and the garbled
   text is stored exactly as observed — never silently "corrected". Downstream, a misread
   identifier simply fails to correlate rather than producing a false match.
3. **Light-on-dark headers need a second OCR pass.** Tesseract does not read white text on the dark
   WhatsApp header bar. The adapter retries that band inverted when the first pass returns nothing
   there. Full dark-mode screenshots (dark throughout, not just the header) are **not** handled and
   will yield fewer blocks.
4. **Layout analysis is heuristic**, tuned to a standard chat layout. It infers side from which
   margin a text block hugs, because OCR returns the extent of the text rather than of the bubble
   drawn around it. Unusual themes, RTL layouts, very narrow crops or group chats with inline
   avatars may leave direction unresolved — which is the intended failure mode, not a silent wrong
   answer.
5. **Semantic correlation is deliberately weak** and off by default.
6. **`EvidenceFile.status` still uses only the legacy 13 values.** The granular stage vocabulary is
   served from `GET .../grounded/evidence/{id}/stages` — see the assumption recorded in the design
   document.
7. **No frontend work was done.** The endpoints exist and are documented; the UI does not consume
   them yet.
8. **Accuracy is not claimed.** The system combines format-specific extraction, multimodal
   understanding, source-linked validation, confidence scoring, correlation and human review.

---

## 9. Rollback and migration safety

**To disable the feature without touching the database** — the fastest, safest rollback:

```
EVIDENCE_INTELLIGENCE_ENABLED=false
```

The grounded pass returns immediately; the legacy pipeline is unchanged. The new tables simply stop
receiving rows.

**To disable only the models**, keeping deterministic grounding, provenance and correlation:

```
LLM_ROUTING_MODE=disabled
```

**To roll back the schema:**

```bash
alembic downgrade c4f2d9a8b7e6
```

Drops the 5 new tables. Legacy tables and data are untouched; the enum members remain (see §2).

**Safety properties**

- New data lives in new tables under a new `raw_extraction_version` (`grounded-v1`). Legacy
  `mvp-v1` rows are never read-modified.
- Raw artifacts are committed before any model runs.
- A grounded-pass failure is caught and never rolls back the legacy result.
- Reviewed records are not overwritten by reprocessing.
- Processing is idempotent through unique constraints and provider cache keys.
