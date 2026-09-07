"""Response and request contracts for the source-grounded evidence surfaces."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.evidence_intelligence.schema import RelationReviewAction, ReviewAction


class ProcessingStageResponse(BaseModel):
    stage: str
    label: str
    state: str
    attempt: int
    reached: bool
    failure_reason: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None


class EvidenceStagesResponse(BaseModel):
    evidence_id: str
    pipeline_version: str
    current_stage: str | None
    stages: list[ProcessingStageResponse]


class RawArtifactResponse(BaseModel):
    id: str
    layer: str
    extractor_name: str
    source_type: str
    artifact_version: str
    quality_flags: list[str]
    payload: dict[str, Any]
    created_at: datetime


class NormalizedRecordResponse(BaseModel):
    id: str
    evidence_id: str
    case_id: str
    workspace_id: str | None
    record_key: str
    source_file_name: str
    source_type: str
    observed_text: str | None
    normalized_summary: str | None
    event_type: str | None
    event_time: datetime | None
    event_time_raw: str | None
    event_time_precision: str
    participant_a: str | None
    participant_b: str | None
    sender: str | None
    receiver: str | None
    message_direction: str | None
    chat_participant_identifier: str | None
    phone_numbers: list[str]
    email_addresses: list[str]
    account_identifiers: list[str]
    transaction_reference: str | None
    amount: dict[str, Any]
    location: str | None
    device_identifier: str | None
    event_attributes: dict[str, Any]
    observation_basis: str
    field_provenance: dict[str, Any]
    model_confidence: float | None
    validation_confidence: float | None
    final_confidence_band: str
    validation_status: str
    requires_human_review: bool
    review_reason: str | None
    review_state: str
    conflict_fields: list[str]
    escalated: bool
    raw_extraction_version: str
    raw_model_output_version: str | None
    extraction_model_name: str | None
    prompt_version: str | None
    created_at: datetime
    updated_at: datetime


class NormalizedRecordPage(BaseModel):
    items: list[NormalizedRecordResponse]
    total: int
    limit: int
    offset: int


class ModelRunResponse(BaseModel):
    id: str
    record_key: str
    provider: str
    model_name: str
    prompt_version: str
    role: str
    status: str
    raw_output: str | None
    parsed_payload: dict[str, Any] | None
    grounding_report: dict[str, Any] | None
    error: dict[str, Any] | None
    latency_ms: int | None
    created_at: datetime


class RelationResponse(BaseModel):
    id: str
    relation_type: str
    status: str
    detection_method: str
    evidence_ids: list[str]
    record_ids: list[str]
    matching_or_conflicting_fields: list[str]
    reason: str
    source_references: list[dict[str, Any]]
    confidence: float
    requires_human_review: bool
    review_decision: str | None
    reviewed_at: datetime | None
    created_at: datetime


class RelationPage(BaseModel):
    items: list[RelationResponse]
    total: int
    limit: int
    offset: int


class RecordReviewRequest(BaseModel):
    action: ReviewAction
    field_name: str | None = Field(default=None, max_length=96)
    new_value: Any = None
    reason: str | None = Field(default=None, max_length=2000)


class RelationReviewRequest(BaseModel):
    action: RelationReviewAction
    reason: str | None = Field(default=None, max_length=2000)


class RecordReviewResponse(BaseModel):
    id: str
    record_id: str | None
    relation_id: str | None
    action: str
    field_name: str | None
    previous_value: Any
    new_value: Any
    reason: str | None
    reviewer_id: str
    created_at: datetime


class ReviewQueueItem(BaseModel):
    record: NormalizedRecordResponse
    evidence_name: str
    relations: list[RelationResponse]


class ReviewQueuePage(BaseModel):
    items: list[ReviewQueueItem]
    total: int
    limit: int
    offset: int
