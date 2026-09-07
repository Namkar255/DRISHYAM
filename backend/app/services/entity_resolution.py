"""Turn grounded records into shared identity nodes.

Two ideas do the work here.

**Identity vs attribute.** Only things that identify a party — a phone, an address, an account, a
reference — become graph nodes. An amount does not identify anyone: making `25,000` a node linked
eleven unrelated files together purely because they mention the same figure.

**One identifier, one node, many sightings.** The same handle read out of a chat, a receipt and a
bank statement is one node with three occurrences, not three nodes. That is what makes a link
between two files visible at all.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.evidence_intelligence import patterns
from app.models.entities import Entity, EntityOccurrence, NormalizedRecord

logger = logging.getLogger(__name__)

RESOLVER_VERSION = "entity-resolution-v1"

# Identity-bearing fields only. `amount`, `event_time` and free text are attributes of an event, not
# identities, and are deliberately excluded — see the module docstring.
IDENTITY_FIELDS: dict[str, str] = {
    "phone_numbers": "phone",
    "email_addresses": "email",
    "account_identifiers": "account",
    "transaction_reference": "reference",
    "device_identifier": "device",
    "sender": "party",
    "receiver": "party",
    "chat_participant_identifier": "party",
    # SIH26189 entity classes. A vehicle is an identifier and behaves like one.
    # A person and an organisation are named things whose identity the source
    # rarely proves, and a place identifies nobody at all -- so all three stay
    # weak and are never merged on similarity alone.
    "vehicle_identifiers": "vehicle",
    "organisation_names": "organisation",
    "person_names": "person",
    "location_names": "location",
}

# A name read off a screen is a label, not a proof of identity, so party nodes stay weak.
PARTY_FIELDS = {"sender", "receiver", "chat_participant_identifier", "person_names", "organisation_names", "location_names"}

_NON_ALNUM = re.compile(r"[^a-z0-9]+")


@dataclass(frozen=True)
class ResolvedIdentity:
    entity_type: str
    display_value: str
    canonical_value: str


def _classify_account(value: str) -> str:
    """UPI handles and email addresses look alike; the same string must not become two nodes."""
    if patterns.EMAIL_PATTERN.fullmatch(value):
        return "email"
    if "@" in value:
        return "upi"
    if patterns.IFSC_PATTERN.fullmatch(value.upper()):
        return "ifsc"
    return "account"


def canonicalize(field_name: str, raw: str) -> ResolvedIdentity | None:
    """Reduce one observed value to the node it belongs to, or None if it identifies nothing."""
    value = str(raw).strip()
    if not value or len(value) > 320:
        return None

    kind = IDENTITY_FIELDS.get(field_name)
    if kind is None:
        return None

    if kind == "phone":
        canonical = patterns.normalize_phone(value)
        digits = re.sub(r"\D", "", canonical)
        return ResolvedIdentity("phone", canonical, digits[-10:]) if len(digits) >= 10 else None

    if kind in {"email", "account"}:
        resolved = _classify_account(value)
        return ResolvedIdentity(resolved, value, value.casefold())

    if kind == "reference":
        # OCR reads O/0 and I/1/l interchangeably, so references are folded before comparison.
        folded = _NON_ALNUM.sub("", value.casefold()).translate(str.maketrans("oil", "011"))
        return ResolvedIdentity("reference", value, folded) if len(folded) >= 6 else None

    if kind == "device":
        return ResolvedIdentity("device", value, _NON_ALNUM.sub("", value.casefold()))

    if kind == "vehicle":
        canonical = patterns.normalize_vehicle(value)
        # A plate is at least a state code, an RTO code and a serial. Anything
        # shorter is a fragment, and a fragment links files that share nothing.
        return ResolvedIdentity("vehicle", value.upper(), canonical) if len(canonical) >= 8 else None

    if kind == "organisation":
        folded = patterns.normalize_organisation(value)
        return ResolvedIdentity("organisation", value, folded) if len(folded) >= 3 else None

    if kind == "person":
        folded = patterns.normalize_person(value)
        # Two people share a name far more often than they share an account.
        # This node records that the same name was written down twice; whether
        # it is the same person is a review decision, never an extraction one.
        return ResolvedIdentity("person", value, folded) if len(folded) >= 3 else None

    if kind == "location":
        folded = patterns.normalize_location(value)
        return ResolvedIdentity("location", value, folded) if len(folded) >= 3 else None

    if kind == "party":
        if patterns.EMAIL_PATTERN.fullmatch(value):
            return ResolvedIdentity("email", value, value.casefold())
        digits = re.sub(r"\D", "", value)
        if len(digits) >= 10:
            return ResolvedIdentity("phone", patterns.normalize_phone(value), digits[-10:])
        folded = _NON_ALNUM.sub(" ", value.casefold()).strip()
        return ResolvedIdentity("party", value, folded) if len(folded) >= 3 else None

    return None


def _values_for(record: NormalizedRecord, field_name: str) -> list[str]:
    value = getattr(record, field_name, None)
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    return [str(value)] if str(value).strip() else []


def _confidence_for(record: NormalizedRecord, field_name: str) -> float:
    provenance = (record.field_provenance or {}).get(field_name) or {}
    raw = provenance.get("confidence")
    if isinstance(raw, (int, float)):
        return float(raw)
    if record.validation_confidence is not None:
        return float(record.validation_confidence)
    return 0.6 if field_name in PARTY_FIELDS else 0.75


def _source_reference(record: NormalizedRecord, field_name: str) -> dict:
    provenance = (record.field_provenance or {}).get(field_name) or {}
    reference = provenance.get("source_reference")
    return reference if isinstance(reference, dict) else {}


def _entity_for(db: Session, record: NormalizedRecord, identity: ResolvedIdentity) -> Entity:
    entity = db.scalar(
        select(Entity).where(
            Entity.case_id == record.case_id,
            Entity.entity_type == identity.entity_type,
            Entity.normalized_value == identity.canonical_value,
        )
    )
    if entity is None:
        entity = Entity(
            case_id=record.case_id,
            source_evidence_id=record.evidence_id,
            entity_type=identity.entity_type,
            value=identity.display_value[:512],
            normalized_value=identity.canonical_value[:512],
            source_reference=f"grounded:{record.record_key}"[:512],
            extraction_method=RESOLVER_VERSION,
            confidence=0.8,
        )
        db.add(entity)
        db.flush()
    return entity


def resolve_record(db: Session, record: NormalizedRecord) -> int:
    """Register every identity this record observed. Returns how many new sightings were stored."""
    stored = 0
    for field_name in IDENTITY_FIELDS:
        for raw in _values_for(record, field_name):
            identity = canonicalize(field_name, raw)
            if identity is None:
                continue

            entity = _entity_for(db, record, identity)
            existing = db.scalar(
                select(EntityOccurrence).where(
                    EntityOccurrence.entity_id == entity.id,
                    EntityOccurrence.evidence_id == record.evidence_id,
                    EntityOccurrence.field_name == field_name,
                )
            )
            if existing is not None:
                continue

            db.add(
                EntityOccurrence(
                    case_id=record.case_id,
                    entity_id=entity.id,
                    evidence_id=record.evidence_id,
                    record_id=record.id,
                    field_name=field_name,
                    observed_value=str(raw)[:512],
                    source_reference=_source_reference(record, field_name),
                    detection_method=RESOLVER_VERSION,
                    confidence=_confidence_for(record, field_name),
                )
            )
            stored += 1
    return stored


def resolve_case(db: Session, case_id: str) -> dict[str, int]:
    """Rebuild identity sightings for a whole case. Safe to run repeatedly."""
    records = db.scalars(
        select(NormalizedRecord).where(NormalizedRecord.case_id == case_id).order_by(NormalizedRecord.created_at)
    ).all()
    stored = sum(resolve_record(db, record) for record in records)
    return {"records": len(records), "occurrences_added": stored}
