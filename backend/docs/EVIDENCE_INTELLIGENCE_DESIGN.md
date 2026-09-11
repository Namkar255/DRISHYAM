# DRISHYAM — Phase B Design (local-first, Ollama → Groq escalation)

Design for the source-grounded multimodal evidence-understanding upgrade. Every item here is
**additive**: no existing table, column, endpoint, response shape or status value is removed or
repurposed.

## B1. Module boundaries and required interfaces

```
app/evidence_intelligence/
    references.py    SourceReference — the single provenance address abstraction
    schema.py        ObservationBasis, FieldProvenance, NormalizedRecordDraft, RelationCandidate
    confidence.py    ConfidenceScorer — band arithmetic + mandatory-review classification
    detection.py     FileTypeDetector
    ocr.py           OCRAdapter + LayoutAnalysisAdapter (blocks with bbox/page/block-id)
    extraction.py    NativeExtractionAdapter — deterministic, per format.
                     Also the ProvenanceBuilder: every fact it emits is a FieldProvenance
                     carrying value, basis, quote and SourceReference.
    grounding.py     StructuredOutputValidator — every model quote must exist in the source
    correlation.py   CorrelationEngine — exact rules first, semantic candidates second
    providers/
        base.py      VLMAdapter protocol, VLMRequest/VLMResponse, error taxonomy
        ollama.py    OllamaVLMAdapter   (local first pass)
        groq.py      GroqVLMAdapter     (escalation only)
        router.py    ModelRouter — routing + escalation + field-by-field reconciliation
        prompts.py   versioned system prompt + strict JSON schema
```

`ReviewService` and `AuditService` already exist (`app/services/review.py`, `app/services/audit.py`)
and are **extended**, not replaced. `EvidenceStorageAdapter` already exists as
`app/services/storage.py` and is reused unchanged.

Business logic depends only on the protocol in `providers/base.py`. Nothing outside
`providers/ollama.py` and `providers/groq.py` knows either vendor exists.

## B2. Data flow (new pipeline version `grounded-v1`)

```
original upload (unchanged path, unchanged 409-on-duplicate behaviour)
  -> immutable registration + SHA-256              existing storage.py, reused as-is
  -> file/content type detection                   detection.py
  -> deterministic native extraction                extraction.py
  -> local OCR with coordinates                     ocr.py -> blocks[{id,page,bbox,text,conf}]
  -> raw artifacts persisted, versioned             raw_extraction_artifacts, COMMITTED HERE
  ------------- everything above is provider-free and always runs -------------
  -> Ollama local VLM first pass        [opt-in]    providers/ollama.py
  -> schema / provenance / validation gate          grounding.py + schema.py
  -> if difficult: Groq escalation      [opt-in]    providers/groq.py
  -> compare and reconcile field by field           router.py — conflicts are preserved, not resolved
  -> confidence and review classification           confidence.py
  -> normalized_records persisted                   null-preserving, field-level provenance
  -> exact-match correlation                        correlation.py
  -> optional semantic candidate correlation
  -> record_relations persisted as candidates
  -> human review + audit trail                     record_reviews (append-only)
  -> timeline, graph, alerts, reports
```

Raw artifacts are committed **before** any model runs, so a provider outage can never destroy
extraction that already succeeded — this fixes audit finding A4.11.

## B3. Routing policy

| Evidence class | Route |
|---|---|
| `bank_record`, `call_log`, `csv`, `spreadsheet`, email **headers**, native PDF | Deterministic parser is authoritative. A model may only add `normalized_summary` / `event_type`. Parser-derived amount, timestamp, account id, reference id and row values are **immutable** — `router.py` drops any model attempt to change them and records a conflict. |
| `screenshot`, `image`, scanned PDF | OCR with coordinates → Ollama VLM with image + OCR blocks → validate against OCR regions → keep local if `validation_confidence >= GROQ_ESCALATE_BELOW_CONFIDENCE`. |
| Difficult | Escalate to Groq when confidence is below threshold, OCR/VLM disagree, a key field (amount/UTR/account/phone/timestamp) conflicts, identity is ambiguous, the image is blurry/cropped/incomplete, the local model returned invalid JSON, or a reviewer re-requests analysis. |

**Disagreement policy.** Groq never wins by virtue of being the cloud model. `router.py` compares
both outputs against OCR and the deterministic parser. Where they disagree the field is marked
conflicting, **both raw outputs are preserved** in `model_inference_runs`, and the record is forced
to human review.

**Idempotency.** The cache key is
`sha256(evidence_hash | parser_version | provider | model | prompt_version)`, stored on
`model_inference_runs`, so re-processing the same evidence with the same versions reuses the stored
output instead of re-calling a provider.

## B4. Migration plan

One migration, `d1c8f4e7a930`, chained from head `c4f2d9a8b7e6`:

1. `CREATE TABLE raw_extraction_artifacts` — versioned raw layers with geometry.
2. `CREATE TABLE model_inference_runs` — one row per provider call; preserves raw model output.
3. `CREATE TABLE normalized_records` — the canonical §10 schema.
4. `CREATE TABLE record_relations` — corroboration/contradiction candidates.
5. `CREATE TABLE record_reviews` — append-only reviewer decision layer.
6. `ALTER TYPE evidence_status ADD VALUE IF NOT EXISTS` × 9 for the new stage vocabulary
   (`received, type_detected, ocr_completed, local_model_completed, groq_escalated, validated,
   review_required, ready`).

Downgrade drops only the five new tables. PostgreSQL cannot remove enum members, so added values
stay on downgrade — documented, harmless, and the reason enum members are added last.

### Assumption recorded (§20 "do not invent repository facts")

`frontend/client/src/api/evidence.ts` pins `EvidenceStatus` as a **closed** TypeScript union of the
existing 13 values. Emitting `groq_escalated` on `EvidenceFile.status` would break that client at
compile time. Therefore the new stage names are added to the database enum so the vocabulary
exists, while `EvidenceFile.status` keeps moving only through legacy values. The §14 eight-stage
lifecycle is served from the new `GET .../stages` endpoint, computed from `ProcessingRun`
(`pipeline_stage` is free text, so no enum pressure). This is the smallest change that satisfies
§14 without breaking §19.16.

`workspace_id` is nullable: this deployment has no workspace entity separate from a case — `Case`
*is* the authorization boundary — so the column exists for schema parity and stays null rather than
inventing a fact.

## B5. Provider configuration

```
LLM_ROUTING_MODE=local_first
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_VISION_MODEL=qwen2.5vl:7b
GROQ_ENABLED=false
GROQ_API_KEY=
GROQ_MODEL=qwen/qwen3.8-27b
GROQ_ESCALATE_BELOW_CONFIDENCE=0.85
GROQ_MAX_RETRIES=1
EXTERNAL_EVIDENCE_TRANSMISSION=disabled
```

Evidence leaves the machine only when `GROQ_ENABLED=true` **and**
`EXTERNAL_EVIDENCE_TRANSMISSION=enabled`. Two independent switches, both off by default.

These are **separate** from the existing `ASSISTANT_LLM_*` variables. Trace Orb is scoped to
website help and is explicitly forbidden from touching case data; sharing one credential knob
between the help chat and the evidence pipeline would erase that boundary.

### Environment limitation on this machine

Ollama is **not installed** and no local model is present, so live local inference cannot be
exercised here. Per §20 the adapters ship with a deterministic **mock mode**
(`LLM_ROUTING_MODE=mock`) used by the test suite, and every provider path is covered by
failure-injection tests. Raw extraction, provenance, confidence, correlation and human review are
fully functional with both providers unavailable. Setup instructions for a real Ollama host are in
the delivery notes.

`GROQ_MODEL=qwen/qwen3.8-27b` is carried through from the specification as the documented default.
It is configuration, not a hardcoded constant — the exact id must be checked against Groq's live
model list before enabling, and an unknown-model error is classified as a provider error that falls
back to the local result rather than failing the evidence.

## B6. Canonical schema and confidence

`normalized_records` mirrors §10 field-for-field. `field_provenance` is a JSON object keyed by
field name; each entry is `{value, basis, quote, source_reference, confidence, validation_status}`.
`source_reference` is the serialized `SourceReference` and can address a file+hash, PDF page, line
range, OCR block, image bbox, CSV row/column, email header/body, chat message index or a reviewer
decision id.

Four confidence values are stored, never one: `model_confidence`, `validation_confidence`,
`final_confidence_band` (high ≥0.85 / medium ≥0.60 / low / unknown) and `validation_status`
(validated|mismatch|unvalidated|rejected).

## B7. Compatibility plan

| Existing surface | Treatment |
|---|---|
| `POST/GET /cases/{id}/evidence*` | Unchanged. Response models untouched. |
| `GET /review-queue` | Unchanged. New rich queue lives at `/review-queue/records`. |
| `POST /review/{subject_type}/{subject_id}` | Unchanged. Record reviews use a new path. |
| timeline / graph / transactions / alerts | Unchanged. Grounded data is exposed additively. |
| `ExtractedText` `mvp-v1` rows | Never read-modified; new work writes `grounded-v1` rows. |
| Trace Orb (`/assistant/help`) | Untouched, keeps its own `ASSISTANT_LLM_*` config. |
| Reports, Trustify receipts, audit chain | Untouched. |
