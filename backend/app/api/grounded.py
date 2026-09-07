"""Source-grounded evidence surfaces: extraction, normalized records, relations and review.

Every route is case-scoped through `require_case_access`, paginated, and returns only derived data
— never a storage key, signed URL or credential.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import func, select

from app.api.deps import CurrentUser, DbSession
from app.models.entities import (
    EvidenceFile,
    ModelInferenceRun,
    NormalizedRecord,
    ProcessingRun,
    RawExtractionArtifact,
    RecordRelation,
    RecordReview,
)
from app.schemas.grounded import (
    EvidenceStagesResponse,
    ModelRunResponse,
    NormalizedRecordPage,
    NormalizedRecordResponse,
    ProcessingStageResponse,
    RawArtifactResponse,
    RecordReviewRequest,
    RecordReviewResponse,
    RelationPage,
    RelationResponse,
    RelationReviewRequest,
    ReviewQueueItem,
    ReviewQueuePage,
)
from app.services import record_review
from app.services.audit import audit
from app.services.cases import require_case_access
from app.services.grounded_pipeline import GROUNDED_PIPELINE_VERSION, UI_STAGE_ORDER

router = APIRouter(prefix="/cases/{case_id}/grounded", tags=["grounded-evidence"])

STAGE_LABELS = {
    "grounded.received": "File received",
    "grounded.type_detected": "Format detected",
    "grounded.extracting": "Parser extraction",
    "grounded.ocr_completed": "OCR completed",
    "grounded.local_model_completed": "Local model analysis",
    "grounded.groq_escalated": "Escalated for second opinion",
    "grounded.validated": "Validation completed",
    "grounded.review_required": "Review required",
    "grounded.ready": "Ready",
}


def _evidence(db: DbSession, case_id: str, evidence_id: str) -> EvidenceFile:
    evidence = db.scalar(select(EvidenceFile).where(EvidenceFile.id == evidence_id, EvidenceFile.case_id == case_id))
    if not evidence:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Evidence record not found")
    return evidence


def _record_response(record: NormalizedRecord) -> NormalizedRecordResponse:
    return NormalizedRecordResponse(
        id=record.id,
        evidence_id=record.evidence_id,
        case_id=record.case_id,
        workspace_id=record.workspace_id,
        record_key=record.record_key,
        source_file_name=record.source_file_name,
        source_type=record.source_type,
        observed_text=record.observed_text,
        normalized_summary=record.normalized_summary,
        event_type=record.event_type,
        event_time=record.event_time,
        event_time_raw=record.event_time_raw,
        event_time_precision=record.event_time_precision,
        participant_a=record.participant_a,
        participant_b=record.participant_b,
        sender=record.sender,
        receiver=record.receiver,
        message_direction=record.message_direction,
        chat_participant_identifier=record.chat_participant_identifier,
        phone_numbers=list(record.phone_numbers or []),
        email_addresses=list(record.email_addresses or []),
        account_identifiers=list(record.account_identifiers or []),
        transaction_reference=record.transaction_reference,
        amount={"value": float(record.amount_value) if record.amount_value is not None else None, "currency": record.amount_currency},
        location=record.location,
        device_identifier=record.device_identifier,
        event_attributes=dict(record.event_attributes or {}),
        observation_basis=record.observation_basis,
        field_provenance=dict(record.field_provenance or {}),
        model_confidence=float(record.model_confidence) if record.model_confidence is not None else None,
        validation_confidence=float(record.validation_confidence) if record.validation_confidence is not None else None,
        final_confidence_band=record.final_confidence_band,
        validation_status=record.validation_status,
        requires_human_review=record.requires_human_review,
        review_reason=record.review_reason,
        review_state=record.review_state,
        conflict_fields=list(record.conflict_fields or []),
        escalated=record.escalated,
        raw_extraction_version=record.raw_extraction_version,
        raw_model_output_version=record.raw_model_output_version,
        extraction_model_name=record.extraction_model_name,
        prompt_version=record.prompt_version,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def _relation_response(relation: RecordRelation) -> RelationResponse:
    return RelationResponse(
        id=relation.id,
        relation_type=relation.relation_type,
        status=relation.status,
        detection_method=relation.detection_method,
        evidence_ids=list(relation.evidence_ids or []),
        record_ids=list(relation.record_ids or []),
        matching_or_conflicting_fields=list(relation.matching_or_conflicting_fields or []),
        reason=relation.reason,
        source_references=list(relation.source_references or []),
        confidence=float(relation.confidence),
        requires_human_review=relation.requires_human_review,
        review_decision=relation.review_decision,
        reviewed_at=relation.reviewed_at,
        created_at=relation.created_at,
    )


def _review_response(review: RecordReview) -> RecordReviewResponse:
    return RecordReviewResponse(
        id=review.id,
        record_id=review.record_id,
        relation_id=review.relation_id,
        action=review.action,
        field_name=review.field_name,
        previous_value=review.previous_value,
        new_value=review.new_value,
        reason=review.reason,
        reviewer_id=review.reviewer_id,
        created_at=review.created_at,
    )


@router.get("/evidence/{evidence_id}/stages", response_model=EvidenceStagesResponse)
def evidence_stages(case_id: str, evidence_id: str, current_user: CurrentUser, db: DbSession) -> EvidenceStagesResponse:
    """Report the grounded processing lifecycle. This endpoint never queues or retries work."""
    require_case_access(db, case_id, current_user)
    _evidence(db, case_id, evidence_id)

    runs = {
        run.pipeline_stage: run
        for run in db.scalars(
            select(ProcessingRun).where(
                ProcessingRun.evidence_id == evidence_id,
                ProcessingRun.pipeline_version == GROUNDED_PIPELINE_VERSION,
            )
        ).all()
    }
    stages = [
        ProcessingStageResponse(
            stage=stage,
            label=STAGE_LABELS.get(stage, stage),
            state=runs[stage].state.value if stage in runs else "pending",
            attempt=runs[stage].attempt if stage in runs else 0,
            reached=stage in runs,
            failure_reason=runs[stage].failure_reason if stage in runs else None,
            started_at=runs[stage].started_at if stage in runs else None,
            completed_at=runs[stage].completed_at if stage in runs else None,
        )
        for stage in UI_STAGE_ORDER
    ]
    reached = [stage for stage in stages if stage.reached]
    return EvidenceStagesResponse(
        evidence_id=evidence_id,
        pipeline_version=GROUNDED_PIPELINE_VERSION,
        current_stage=reached[-1].stage if reached else None,
        stages=stages,
    )


@router.get("/evidence/{evidence_id}/extraction", response_model=list[RawArtifactResponse])
def raw_extraction(
    case_id: str,
    evidence_id: str,
    current_user: CurrentUser,
    db: DbSession,
    layer: str | None = Query(default=None, max_length=48),
) -> list[RawArtifactResponse]:
    """Return the immutable deterministic extraction layers, independent of any model output."""
    require_case_access(db, case_id, current_user)
    _evidence(db, case_id, evidence_id)

    query = select(RawExtractionArtifact).where(RawExtractionArtifact.evidence_id == evidence_id)
    if layer:
        query = query.where(RawExtractionArtifact.layer == layer)
    return [
        RawArtifactResponse(
            id=item.id,
            layer=item.layer,
            extractor_name=item.extractor_name,
            source_type=item.source_type,
            artifact_version=item.artifact_version,
            quality_flags=list(item.quality_flags or []),
            payload=dict(item.payload_json or {}),
            created_at=item.created_at,
        )
        for item in db.scalars(query.order_by(RawExtractionArtifact.layer)).all()
    ]


@router.get("/evidence/{evidence_id}/model-runs", response_model=list[ModelRunResponse])
def model_runs(case_id: str, evidence_id: str, current_user: CurrentUser, db: DbSession) -> list[ModelRunResponse]:
    """Every provider call for this evidence, including both outputs when models disagreed."""
    require_case_access(db, case_id, current_user)
    _evidence(db, case_id, evidence_id)
    return [
        ModelRunResponse(
            id=item.id,
            record_key=item.record_key,
            provider=item.provider,
            model_name=item.model_name,
            prompt_version=item.prompt_version,
            role=item.role,
            status=item.status,
            raw_output=item.raw_output,
            parsed_payload=item.parsed_payload,
            grounding_report=item.grounding_report,
            error=item.error_json,
            latency_ms=item.latency_ms,
            created_at=item.created_at,
        )
        for item in db.scalars(
            select(ModelInferenceRun)
            .where(ModelInferenceRun.evidence_id == evidence_id)
            .order_by(ModelInferenceRun.created_at)
        ).all()
    ]


@router.get("/records", response_model=NormalizedRecordPage)
def list_records(
    case_id: str,
    current_user: CurrentUser,
    db: DbSession,
    evidence_id: str | None = Query(default=None),
    band: str | None = Query(default=None, pattern="^(high|medium|low|unknown)$"),
    requires_review: bool | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> NormalizedRecordPage:
    require_case_access(db, case_id, current_user)

    filters = [NormalizedRecord.case_id == case_id]
    if evidence_id:
        filters.append(NormalizedRecord.evidence_id == evidence_id)
    if band:
        filters.append(NormalizedRecord.final_confidence_band == band)
    if requires_review is not None:
        filters.append(NormalizedRecord.requires_human_review.is_(requires_review))

    total = db.scalar(select(func.count(NormalizedRecord.id)).where(*filters)) or 0
    rows = db.scalars(
        select(NormalizedRecord).where(*filters).order_by(NormalizedRecord.created_at.desc()).limit(limit).offset(offset)
    ).all()
    return NormalizedRecordPage(items=[_record_response(row) for row in rows], total=total, limit=limit, offset=offset)


@router.get("/review-queue", response_model=ReviewQueuePage)
def review_queue(
    case_id: str,
    current_user: CurrentUser,
    db: DbSession,
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> ReviewQueuePage:
    """Records the system will not stand behind on its own."""
    require_case_access(db, case_id, current_user)

    filters = [NormalizedRecord.case_id == case_id, NormalizedRecord.requires_human_review.is_(True)]
    total = db.scalar(select(func.count(NormalizedRecord.id)).where(*filters)) or 0
    rows = db.scalars(
        select(NormalizedRecord)
        .where(*filters)
        .order_by(NormalizedRecord.final_confidence_band.desc(), NormalizedRecord.created_at.desc())
        .limit(limit)
        .offset(offset)
    ).all()

    names = dict(
        db.execute(select(EvidenceFile.id, EvidenceFile.original_name).where(EvidenceFile.case_id == case_id)).all()
    )
    relations = db.scalars(select(RecordRelation).where(RecordRelation.case_id == case_id)).all()

    items = [
        ReviewQueueItem(
            record=_record_response(row),
            evidence_name=names.get(row.evidence_id, "Unknown evidence"),
            relations=[_relation_response(relation) for relation in relations if row.id in (relation.record_ids or [])],
        )
        for row in rows
    ]
    return ReviewQueuePage(items=items, total=total, limit=limit, offset=offset)


@router.post("/records/{record_id}/review", response_model=RecordReviewResponse)
def review_record(
    case_id: str,
    record_id: str,
    payload: RecordReviewRequest,
    current_user: CurrentUser,
    db: DbSession,
) -> RecordReviewResponse:
    require_case_access(db, case_id, current_user)
    review = record_review.review_record(
        db,
        case_id=case_id,
        record_id=record_id,
        action=payload.action,
        reviewer_id=current_user.id,
        field_name=payload.field_name,
        new_value=payload.new_value,
        reason=payload.reason,
    )
    audit(
        db,
        action="grounded.record_review",
        object_type="normalized_record",
        object_id=record_id,
        case_id=case_id,
        outcome="success",
        actor_id=current_user.id,
        details={"review_action": payload.action.value, "field": payload.field_name},
    )
    db.commit()
    return _review_response(review)


@router.get("/records/{record_id}/history", response_model=list[RecordReviewResponse])
def record_history(case_id: str, record_id: str, current_user: CurrentUser, db: DbSession) -> list[RecordReviewResponse]:
    require_case_access(db, case_id, current_user)
    return [_review_response(item) for item in record_review.history_for_record(db, case_id=case_id, record_id=record_id)]


@router.get("/relations", response_model=RelationPage)
def list_relations(
    case_id: str,
    current_user: CurrentUser,
    db: DbSession,
    relation_type: str | None = Query(default=None, pattern="^(corroboration|contradiction)$"),
    relation_status: str | None = Query(default=None, pattern="^(candidate|confirmed|rejected)$", alias="status"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> RelationPage:
    """Candidate corroborations and contradictions. Nothing here is a settled finding."""
    require_case_access(db, case_id, current_user)

    filters = [RecordRelation.case_id == case_id]
    if relation_type:
        filters.append(RecordRelation.relation_type == relation_type)
    if relation_status:
        filters.append(RecordRelation.status == relation_status)

    total = db.scalar(select(func.count(RecordRelation.id)).where(*filters)) or 0
    rows = db.scalars(
        select(RecordRelation).where(*filters).order_by(RecordRelation.confidence.desc()).limit(limit).offset(offset)
    ).all()
    return RelationPage(items=[_relation_response(row) for row in rows], total=total, limit=limit, offset=offset)


@router.post("/relations/{relation_id}/review", response_model=RecordReviewResponse)
def review_relation(
    case_id: str,
    relation_id: str,
    payload: RelationReviewRequest,
    current_user: CurrentUser,
    db: DbSession,
) -> RecordReviewResponse:
    require_case_access(db, case_id, current_user)
    review = record_review.review_relation(
        db,
        case_id=case_id,
        relation_id=relation_id,
        action=payload.action,
        reviewer_id=current_user.id,
        reason=payload.reason,
    )
    audit(
        db,
        action="grounded.relation_review",
        object_type="record_relation",
        object_id=relation_id,
        case_id=case_id,
        outcome="success",
        actor_id=current_user.id,
        details={"review_action": payload.action.value},
    )
    db.commit()
    return _review_response(review)


@router.post("/evidence/{evidence_id}/reanalyze", status_code=status.HTTP_202_ACCEPTED)
def reanalyze(case_id: str, evidence_id: str, current_user: CurrentUser, db: DbSession) -> dict:
    """Queue a reviewer-requested re-analysis, which forces escalation for this evidence."""
    require_case_access(db, case_id, current_user)
    evidence = _evidence(db, case_id, evidence_id)
    audit(
        db,
        action="grounded.reanalyze",
        object_type="evidence_file",
        object_id=evidence.id,
        case_id=case_id,
        outcome="queued",
        actor_id=current_user.id,
    )
    db.commit()

    from app.workers.tasks import reanalyze_evidence_task

    reanalyze_evidence_task.delay(evidence.id)
    return {"evidence_id": evidence.id, "status": "queued", "forced_escalation": True}
