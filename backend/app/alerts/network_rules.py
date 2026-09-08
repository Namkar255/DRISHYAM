"""Criminal-network pattern rules, over the grounded relationship graph.

`rules.py` reads the legacy transaction and event tables and its rules are shaped for payment
fraud. These read the typed relationships instead, which is where a call, a vehicle and a place
actually live, and they are the patterns SIH26189 names.

Every rule here is transparent arithmetic with a stated threshold. None of them predicts anything.
An alert is a reason to look at named evidence, and its wording has to survive being read out in a
courtroom -- so each one says what was counted, over what span, and from which sources.

One rule is deliberately absent. A cross-case alert ("this phone also appears in case B") would
tell everyone who can see case A that case B exists, which is a disclosure the case-level
authorisation model exists to prevent. Cross-case links stay behind the authorisation-scoped
endpoint in `services/cross_case.py`, where the asking user's own access decides what they see.
"""

from __future__ import annotations

import logging
from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import Alert, Entity, NormalizedRecord, Severity
from app.services import temporal

logger = logging.getLogger(__name__)

NETWORK_RULES_VERSION = "network-rules-v1"

# A vehicle recorded at the same place this many times is worth a look. Twice is a coincidence
# often enough; three times is a pattern the investigator should see.
RECURRING_SIGHTING_MIN = 3


def _label(entities: dict[str, Entity], entity_id: str) -> str:
    entity = entities.get(entity_id)
    return entity.value if entity else entity_id


def _raise(
    db: Session,
    *,
    case_id: str,
    rule_code: str,
    key: str,
    severity: Severity,
    explanation: str,
    evidence_ids: list[str],
) -> bool:
    """Record one alert, once. Returns whether it was new."""
    idempotency_key = f"{case_id}:{rule_code}:{NETWORK_RULES_VERSION}:{key}"
    if db.scalar(select(Alert).where(Alert.idempotency_key == idempotency_key)):
        return False
    db.add(
        Alert(
            case_id=case_id,
            rule_code=rule_code,
            severity=severity,
            explanation=explanation,
            affected_evidence_ids=evidence_ids,
            idempotency_key=idempotency_key,
        )
    )
    return True


def _pre_incident_communication(db: Session, case_id: str, entities: dict[str, Entity]) -> int:
    raised = 0
    for finding in temporal.pre_incident_contacts(db, case_id):
        left, right = finding["pair"]
        raised += _raise(
            db,
            case_id=case_id,
            rule_code="PRE_INCIDENT_COMMUNICATION",
            key=f"{left}:{right}",
            severity=Severity.HIGH,
            explanation=(
                f"Review lead: {_label(entities, left)} and {_label(entities, right)} are recorded in contact "
                f"{finding['contacts']} times in the {int(temporal.PRE_INCIDENT_LOOKBACK.total_seconds() // 3600)} hours "
                f"before the declared incident window, the last of them {finding['hours_before']} hours before it opens. "
                "Contact before an incident is not evidence of involvement in it; open the call records and read them."
            ),
            evidence_ids=finding["evidence_ids"],
        )
    return raised


def _communication_burst(db: Session, case_id: str, entities: dict[str, Entity]) -> int:
    raised = 0
    for finding in temporal.communication_bursts(db, case_id):
        left, right = finding["pair"]
        raised += _raise(
            db,
            case_id=case_id,
            rule_code="COMMUNICATION_BURST",
            key=f"{left}:{right}",
            severity=Severity.MEDIUM,
            explanation=(
                f"Review lead: {_label(entities, left)} and {_label(entities, right)} are recorded in contact "
                f"{finding['contacts']} times within {finding['minutes']} minutes. "
                "A burst of contact can have an ordinary explanation; the records themselves are the evidence."
            ),
            evidence_ids=finding["evidence_ids"],
        )
    return raised


def _recurring_vehicle_at_location(db: Session, case_id: str) -> int:
    """The same registration and the same place recorded together, repeatedly.

    Read from records that name both, which states that the source recorded them together -- not
    that the vehicle was at the place at any particular time. The wording keeps that distinction.
    """
    sightings: dict[tuple[str, str], list[NormalizedRecord]] = defaultdict(list)
    records = db.scalars(select(NormalizedRecord).where(NormalizedRecord.case_id == case_id)).all()
    for record in records:
        for vehicle in record.vehicle_identifiers or []:
            for place in record.location_names or []:
                sightings[(str(vehicle), str(place))].append(record)

    raised = 0
    for (vehicle, place), matches in sightings.items():
        if len(matches) < RECURRING_SIGHTING_MIN:
            continue
        evidence_ids = sorted({item.evidence_id for item in matches})
        raised += _raise(
            db,
            case_id=case_id,
            rule_code="RECURRING_VEHICLE_AT_LOCATION",
            key=f"{vehicle}:{place}",
            severity=Severity.MEDIUM,
            explanation=(
                f"Review lead: vehicle {vehicle} and the location {place} are recorded together in "
                f"{len(matches)} records across {len(evidence_ids)} evidence files. "
                "The sources record them together; they do not establish that the vehicle was there at a stated time."
            ),
            evidence_ids=evidence_ids,
        )
    return raised


def _bridge_entity(db: Session, case_id: str) -> int:
    """Entities whose removal would disconnect the network.

    These are where the case is most fragile: if the relationship through such an entity is wrong,
    the connection between two parts of the network does not exist. That makes them the first thing
    worth verifying, which is what the alert says -- not that they are important people.
    """
    from app.graph import analytics  # imported here; analytics reads relations this module writes about

    raised = 0
    for entry in analytics.important_entities(db, case_id, limit=20):
        if not entry["is_bridge"] or entry["supporting_evidence_count"] < 2:
            continue
        raised += _raise(
            db,
            case_id=case_id,
            rule_code="BRIDGE_ENTITY",
            key=entry["entity_id"],
            severity=Severity.MEDIUM,
            explanation=(
                f"Review lead: {entry['label']} holds two parts of this network together. {entry['why']} "
                "Verify the relationships through it first: if one of them is wrong, the connection between "
                "those groups does not exist. Network position is review priority, not an indication of guilt."
            ),
            evidence_ids=[],
        )
    return raised


def evaluate_network_alerts(db: Session, case_id: str) -> dict[str, int]:
    """Run every criminal-network rule for one case. Safe to run repeatedly."""
    entities = {item.id: item for item in db.scalars(select(Entity).where(Entity.case_id == case_id)).all()}
    counts = {
        "pre_incident_communication": _pre_incident_communication(db, case_id, entities),
        "communication_burst": _communication_burst(db, case_id, entities),
        "recurring_vehicle_at_location": _recurring_vehicle_at_location(db, case_id),
        "bridge_entity": _bridge_entity(db, case_id),
    }
    counts["total_new"] = sum(counts.values())
    counts["rules_version"] = NETWORK_RULES_VERSION  # type: ignore[assignment]
    return counts
