# OpenAPI and Backend Contract

The running backend exposes interactive Swagger UI at [`/docs`](http://localhost:8000/docs), ReDoc at [`/redoc`](http://localhost:8000/redoc), and machine-readable OpenAPI at [`/openapi.json`](http://localhost:8000/openapi.json). Every resource below is case-scoped and protected by bearer authentication except account registration, verification, login, health, and OpenAPI documentation.

| Area | Primary endpoint | Contract outcome |
|---|---|---|
| Account verification | `POST /api/v1/auth/signup`, `POST /verify`, `POST /login` | Verified JWT account session with server-side logout revocation. |
| Cases | `POST /api/v1/cases`, `GET /cases/{case_id}` | Owner or membership authorization applies before a case is read or changed. |
| Evidence intake | `POST /cases/{case_id}/evidence` | Multipart file is validated, privately stored, hashed with SHA-256, audited, and queued. |
| Derived intelligence | `GET /timeline`, `/graph`, `/transactions`, `/alerts` | Database-derived canonical records, not static sample payloads. |
| Review and reports | `POST /review/{type}/{id}`, `POST /reports` | Review decision is audited; generated PDF can be downloaded only by authorized users. |
| Trustify integrity | `GET /trustify/summary`, `GET /trustify/reports/{report_id}/verify` | Case-scoped technical integrity summary plus report/manifest hash verification. |
| Developer preview | `GET /preview/cases/{case_id}` | Backend-only protected HTML summary with integrity receipts and counts. |

> The API returns **reviewable leads**, not a conclusion of guilt. Consumers should present source-file linkage, confidence, and review state alongside any derived event, entity, transaction, or alert.

> Trustify provides technical integrity and traceability signals, including SHA-256 report receipts, evidence-manifest hashes and audit-chain heads. It does not establish truth, guilt, source authenticity, legal admissibility or a final investigative conclusion.
