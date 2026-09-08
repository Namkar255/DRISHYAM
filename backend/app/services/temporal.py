"""Temporal reading of a case: what happened before the incident, and what clustered in time.

The incident window is `Case.date_range_start` / `date_range_end`. Those columns already exist and
the workspace already fills the first from a field it calls "incident date", so this reads them
rather than adding a second pair of near-identical columns for the same idea.

Everything here is arithmetic over observed timestamps. It answers "these records fall before that
moment" and "these contacts cluster inside that span". It never says the clustering was planned, or
that the parties intended anything -- an investigator reads that, from the sources the finding
points at.

Records whose time was never established are excluded rather than assumed. A record with no
timestamp is not evidence of anything happening at any particular moment, and letting it default
into a window is how a made-up sequence gets built.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import Case, EntityRelation

TEMPORAL_VERSION = "temporal-v1"

# How far before the incident a contact still counts as leading up to it. Long enough to catch the
# arrangements, short enough that ordinary prior contact does not qualify.
PRE_INCIDENT_LOOKBACK = timedelta(hours=48)
PRE_INCIDENT_MIN_CONTACTS = 2

# A burst is contact repeated inside a short span. Two calls in an hour is a conversation; several
# is a pattern worth a look.
BURST_WINDOW = timedelta(hours=2)
BURST_MIN_CONTACTS = 3

# Relations that record one party contacting another. A transfer is not contact.
CONTACT_RELATIONS = {"CALLED", "MESSAGED", "COMMUNICATED_WITH"}


@dataclass(frozen=True)
class IncidentWindow:
    """The span an investigator has declared to be the incident, if they declared one."""

    start: datetime | None
    end: datetime | None

    @property
    def is_set(self) -> bool:
        return self.start is not None or self.end is not None

    def position(self, moment: datetime | None) -> str:
        """Where a moment sits relative to the window, or that it cannot be placed."""
        if moment is None:
            return "time_not_established"
        if self.start is not None and moment < self.start:
            return "before"
        if self.end is not None and moment > self.end:
            return "after"
        if not self.is_set:
            return "no_window_declared"
        return "during"


def incident_window(db: Session, case_id: str) -> IncidentWindow:
    case = db.get(Case, case_id)
    if case is None:
        return IncidentWindow(None, None)
    return IncidentWindow(case.date_range_start, case.date_range_end)


def _contact_relations(db: Session, case_id: str) -> list[EntityRelation]:
    """Contact edges with an established time, in order.

    Rejected edges are excluded: a reviewer saying the source does not support a contact must stop
    that contact from driving a temporal finding too.
    """
    rows = db.scalars(
        select(EntityRelation)
        .where(EntityRelation.case_id == case_id, EntityRelation.relation_type.in_(CONTACT_RELATIONS))
        .order_by(EntityRelation.observed_at)
    ).all()
    return [row for row in rows if row.observed_at is not None and row.verification_status != "rejected"]


def _pair(relation: EntityRelation) -> tuple[str, str]:
    """The unordered pair, so contact in either direction groups together."""
    return tuple(sorted((relation.subject_entity_id, relation.object_entity_id)))  # type: ignore[return-value]


def pre_incident_contacts(db: Session, case_id: str) -> list[dict]:
    """Pairs that were repeatedly in contact in the hours before the declared incident.

    Returns nothing when no incident window has been declared. Choosing a moment on the case's
    behalf would manufacture the very sequence this is supposed to find.
    """
    window = incident_window(db, case_id)
    if window.start is None:
        return []

    opens = window.start - PRE_INCIDENT_LOOKBACK
    grouped: dict[tuple[str, str], list[EntityRelation]] = defaultdict(list)
    for relation in _contact_relations(db, case_id):
        if opens <= relation.observed_at < window.start:
            grouped[_pair(relation)].append(relation)

    findings = []
    for pair, relations in grouped.items():
        if len(relations) < PRE_INCIDENT_MIN_CONTACTS:
            continue
        findings.append(
            {
                "pair": pair,
                "contacts": len(relations),
                "first": relations[0].observed_at,
                "last": relations[-1].observed_at,
                "evidence_ids": sorted({item.source_evidence_id for item in relations}),
                "relation_ids": [item.id for item in relations],
                "hours_before": round((window.start - relations[-1].observed_at).total_seconds() / 3600, 1),
            }
        )
    findings.sort(key=lambda item: -item["contacts"])
    return findings


def communication_bursts(db: Session, case_id: str) -> list[dict]:
    """Contact between one pair repeated inside a short span, wherever it falls in the case."""
    grouped: dict[tuple[str, str], list[EntityRelation]] = defaultdict(list)
    for relation in _contact_relations(db, case_id):
        grouped[_pair(relation)].append(relation)

    findings = []
    for pair, relations in grouped.items():
        relations.sort(key=lambda item: item.observed_at)
        start = 0
        for end in range(len(relations)):
            while relations[end].observed_at - relations[start].observed_at > BURST_WINDOW:
                start += 1
            span = relations[start : end + 1]
            if len(span) >= BURST_MIN_CONTACTS:
                findings.append(
                    {
                        "pair": pair,
                        "contacts": len(span),
                        "first": span[0].observed_at,
                        "last": span[-1].observed_at,
                        "minutes": round((span[-1].observed_at - span[0].observed_at).total_seconds() / 60),
                        "evidence_ids": sorted({item.source_evidence_id for item in span}),
                        "relation_ids": [item.id for item in span],
                    }
                )
                break  # one finding per pair; the densest span is enough to prompt a look
    findings.sort(key=lambda item: -item["contacts"])
    return findings


def case_chronology(db: Session, case_id: str) -> dict:
    """How the case's contact record sits around the declared incident."""
    window = incident_window(db, case_id)
    relations = _contact_relations(db, case_id)
    counts = {"before": 0, "during": 0, "after": 0, "no_window_declared": 0}
    for relation in relations:
        counts[window.position(relation.observed_at)] = counts.get(window.position(relation.observed_at), 0) + 1

    undated = db.scalar(
        select(EntityRelation)
        .where(
            EntityRelation.case_id == case_id,
            EntityRelation.relation_type.in_(CONTACT_RELATIONS),
            EntityRelation.observed_at.is_(None),
        )
        .limit(1)
    )
    return {
        "incident_window_declared": window.is_set,
        "incident_start": window.start,
        "incident_end": window.end,
        "contacts_placed": counts,
        # Reported rather than hidden: a case where most contact has no established time is a case
        # whose chronology should not be leaned on.
        "contacts_without_established_time": bool(undated),
        "temporal_version": TEMPORAL_VERSION,
    }
