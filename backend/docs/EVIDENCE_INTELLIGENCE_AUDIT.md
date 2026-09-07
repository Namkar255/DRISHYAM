# DRISHYAM — Phase A Architecture Audit

Audit of the local repository **before** the source-grounded multimodal evidence-understanding
upgrade. Nothing in this document is a proposal; it records what exists today.

## A1. Runtime and module boundaries

| Concern | Location | Notes |
|---|---|---|
| App entry point | `app/main.py` | FastAPI, CORS from `ALLOWED_ORIGINS`, router mounted at `/api/v1`. No frontend mounted. |
| Config | `app/core/config.py` | `pydantic-settings`, `.env` + `.env.trace-orb`, `extra="ignore"`. Secrets are `SecretStr`. |
| DB | `app/core/db.py`, `app/models/entities.py` | SQLAlchemy 2.x, PostgreSQL, Alembic. `create_all()` is **not** run at startup (tests excepted). |
| Routes | `app/api/*.py` via `app/api/router.py` | auth, assistant, account, gmail_oauth, cases, evidence, analysis, claims, notifications, review, preview. |
| Jobs | `app/workers/celery_app.py`, `app/workers/tasks.py` | Celery + Redis. Queues: `evidence_fast, evidence_ocr, evidence_parse, evidence_enrich, reports`. `CELERY_TASK_ALWAYS_EAGER` supported. |
| Storage | `app/services/storage.py` | Filesystem authority by default; Supabase object store optional with a local `.remote-cache`. Path traversal is blocked by `_safe_storage_key`. |
| Pipeline | `app/services/pipeline.py` | Stages: `parse → extract → normalize → graph → alerts`. |
| Parsers | `app/parsers/registry.py` | txt, eml, csv, xlsx, pdf, png/jpg/jpeg. |
| Deterministic extraction | `app/extraction/normalizer.py` | Regex indicators, timestamp, transaction fields. |
| Derived surfaces | `app/graph/projection.py`, `app/alerts/rules.py` | Graph projection and 5 idempotent alert rules. |
| Reports | `app/services/reporting.py`, `app/services/trustify.py` | ReportLab PDF + hash receipt/manifest. |
| Audit | `app/services/audit.py` | Hash-chained `audit_logs` (`previous_hash`/`event_hash`). |

## A2. Current data flow

```
POST /api/v1/cases/{case_id}/evidence   (multipart: file, source_category)
  -> require_case_access(...)                        authorization
  -> persist_upload(...)                             stream to .incoming, SHA-256, size cap,
                                                     magic-byte MIME sniff, move to cases/<case>/<id><ext>
  -> duplicate check on (case_id, sha256)            409 CONFLICT on repeat
  -> EvidenceFile row, status = QUEUED
  -> audit("evidence.upload") + commit
  -> process_evidence_task.delay(evidence_id)        request returns immediately

worker: process_evidence(evidence_id)
  -> _records()   parse_evidence(path)  -> ExtractedText(evidence_id, pipeline_version="mvp-v1")
  -> _events()    regex over each record -> Event, Entity, EventEntity, Transaction
  -> normalize/graph                     status-only stages, no work performed
  -> alerts       evaluate_alerts(case)  -> Alert rows
  -> status COMPLETED, audit("evidence.process"), commit
```

Reads: `GET /cases/{id}/timeline|graph|transactions|alerts|processing-runs|audit|cross-case-links|search`,
`GET /cases/{id}/review-queue`, `POST /cases/{id}/review/{subject_type}/{subject_id}`,
report create/list/download, Trustify verify/summary.

## A3. Supported formats today

| Extension | Path | Provenance captured |
|---|---|---|
| `.txt` | `_parse_text` → line records | line number |
| `.eml` | `_parse_text` → flattens `From/To/Subject` + text body into one string | line number only |
| `.csv` | `_parse_csv` → `DictReader`, dialect sniffing | row number + column map |
| `.xlsx` | `_parse_xlsx` → pandas | row number + column map |
| `.pdf` | `_parse_pdf` → PyMuPDF text, falls back to render+OCR under 20 chars | none (page number is lost) |
| `.png/.jpg/.jpeg` | `_parse_image` → `pytesseract.image_to_string` | none (no coordinates) |

## A4. Gaps against the target system

1. **No LLM/VLM contextual layer.** The only model call in the repo is `app/api/assistant.py`
   (Trace Orb website help; explicitly forbidden from touching case data). There is no provider
   adapter, no schema-constrained output, no prompt versioning.
2. **OCR has no geometry.** `image_to_string` returns a flat string. No blocks, no bounding boxes,
   no page/block ids — so no source reference can point at an image region.
3. **PDF loses page numbers.** Pages are joined with `\n` before records are cut by line.
4. **No field-level provenance.** `Event.raw_text_reference` is a single opaque string such as
   `bank_transaction:12`. There is no `{value, basis, quote, source_reference, confidence,
   validation_status}` structure anywhere.
5. **One unexplained confidence number.** `Event.confidence` is a hardcoded 0.91/0.78;
   `Entity.confidence` a hardcoded 0.93/0.86. No `model_confidence`, `validation_confidence`,
   `final_confidence_band` or `validation_status`.
6. **No observation basis.** Nothing distinguishes *directly observed* from *inferred* from
   *unknown*, so the UI cannot label them differently.
7. **No normalized-record layer.** `Event` is the closest analogue but is a display row, not a
   source-grounded record, and it has no null-preserving participant/sender/receiver fields.
8. **No in-case corroboration/contradiction engine.** `app/services/cross_case.py` does exact
   identifier matching **across** cases only. `Claim`/`Contradiction` tables exist but are
   populated manually by users through `app/api/claims.py`.
9. **Review queue is thin.** `GET /review-queue` returns flat id/type/status lists. It cannot show
   original vs raw vs normalized side by side, has no source highlight, no confidence reason, and
   `ReviewStatus` has no `mark_unknown` equivalent.
10. **Status vocabulary is incomplete.** `EvidenceStatus` lacks `received, type_detected,
    ocr_completed, parsed, llm_analyzing, validated, review_required, ready, partially_processed`.
11. **Failure discards raw extraction.** In `process_evidence`, `_records()` adds `ExtractedText`
    to the session, but the `except` branch calls `db.rollback()` before recording the failure —
    so a crash during `_events()` throws away extraction that had already succeeded. This directly
    violates "raw extraction should remain available when enrichment fails".
12. **Email parsing is lossy.** No `Cc`, `Bcc`, `Date`, `Message-ID`, `Reply-To`, no attachment
    names/MIME types, no header/body separation for provenance.
13. **No WhatsApp/chat awareness.** A chat `.txt` export is treated as generic lines; a chat
    screenshot is treated as generic OCR. No timestamp/sender/message parsing, no bubble direction,
    no header participant identifier, no `<Media omitted>` handling.
14. **No image metadata layer.** EXIF is never read.
15. **No `.env.example`** exists anywhere in the repository.
16. **No redaction hooks** for logs or model inputs.

## A5. Compatibility constraints (must not break)

- **Frontend contracts.** `frontend/client/src/api/*.ts` pins response shapes.
  `EvidenceRecord` in `api/evidence.ts` enumerates the 13 current `EvidenceStatus` values as a
  TypeScript union; a *new* status value reaching that client widens the union and would not
  type-check on the frontend. New statuses must therefore be opt-in, not emitted on the existing
  default path.
- **Enum storage.** `EvidenceStatus` is a PostgreSQL `ENUM`. Adding members requires
  `ALTER TYPE ... ADD VALUE` (additive, non-destructive, irreversible in-place).
- **`ExtractedText` uniqueness** is `(evidence_id, pipeline_version)` — a new pipeline version
  writes a **new row** and leaves `mvp-v1` intact. This is the safe versioning seam.
- **Duplicate uploads** currently return `409 CONFLICT` on `(case_id, sha256)`. Existing tests and
  the frontend rely on this; it must stay.
- **Historic records.** 7 cases already have generated reports under `generated_reports/`, and
  `demo_run.json` records a prior demo run. Reports, audit chain and Trustify receipts must remain
  readable and byte-identical.
- **Alembic head is `c4f2d9a8b7e6`** (`add_case_description`). New migrations must chain from it.

## A6. Test suite and environment

- 8 test modules under `tests/`; `conftest.py` sets `CELERY_TASK_ALWAYS_EAGER=true` and points
  storage at `.test_data`.
- **Every existing test needs a live PostgreSQL** at `DATABASE_URL` — `conftest.py` calls
  `Base.metadata.create_all(bind=engine)` at fixture time. There is no SQLite fallback.
- No virtualenv and no installed dependencies were present in this checkout; `.venv` was created
  during this audit from Python 3.12.10 to make the suite runnable.
- Consequence: new **unit** tests (parsers, schemas, provenance, confidence, correlation) must be
  written so they run **without** a database, or the acceptance criteria cannot be demonstrated on
  this machine.

## A7. Smallest safe migration path

1. Additive tables only — no column drops, no type changes, no backfill rewrites of existing rows.
2. `ALTER TYPE evidence_status ADD VALUE IF NOT EXISTS ...` for the new status vocabulary.
3. New derived data written under a **new** `pipeline_version`, leaving `mvp-v1` rows untouched.
4. The LLM/VLM layer defaults to **disabled**; with it disabled the pipeline must behave exactly as
   it does today.
