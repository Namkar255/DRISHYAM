# REPORT_TIMESTAMP_SEPARATOR_20260828: Use a plain readable date-time separator that cannot render as a garbled glyph in the PDF.
# SOURCE_EVENT_TIME_DISPLAY_20260828: Date-only midnight event values may display an explicitly labelled evidence time without changing stored records.
# REPORT_TIMESTAMP_READABILITY_20260828: All human-facing PDF dates and times use readable day-month-year and 12-hour AM/PM formatting.
# EVIDENCE_ANALYTICS_PAGE_REMOVED_20260828: The redundant blank-prone category chart page is intentionally excluded from new PDFs.
# REPORT_COPY_CLEANUP_20260828: Human-facing report copy avoids internal hash, manifest, and processing jargon.
"""Dynamic, case-scoped PDF report creation from database-backed reviewed and unreviewed evidence leads."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from collections import Counter

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import networkx as nx
from matplotlib.patches import Patch
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Image, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import utcnow
from app.models.entities import Alert, AuditLog, Case, Claim, Contradiction, Entity, EntityOccurrence, EntityRelation, Event, EvidenceFile, NormalizedRecord, ProcessingRun, ProcessingState, RecordRelation, Report, ReviewDecision, Transaction
from app.graph.projection import build_case_graph
from app.graph.connections import build_connection_graph, describe_connections
from app.services.storage import get_report_artifact_path, publish_private_file, report_storage_key
from app.services.trustify import create_receipt


settings = get_settings()
PAPER = colors.HexColor("#fbf8f2")
PAPER_ALT = colors.HexColor("#fffaf3")
BURGUNDY = colors.HexColor("#7b1e2b")
CHARCOAL = colors.HexColor("#394a54")
INK = colors.HexColor("#2d2926")
RULE = colors.HexColor("#cbc3b7")
CELL_STYLE = ParagraphStyle("ReportCell", fontName="Helvetica", fontSize=7.2, leading=9.3, textColor=INK)
HEADER_CELL_STYLE = ParagraphStyle(
    "ReportHeaderCell",
    parent=CELL_STYLE,
    fontName="Helvetica-Bold",
    fontSize=8.0,
    leading=10.0,
    textColor=colors.white,
)
META_STYLE = ParagraphStyle("ReportMeta", fontName="Courier", fontSize=6.7, leading=8.4, textColor=colors.HexColor("#5d5852"))


# Two extraction generations name the same thing differently ("upi_id" then "upi", "person" then
# "party"). Charting the raw column showed both, so one UPI handle counted twice. An amount is not
# an identity at all and is excluded rather than renamed.
ENTITY_DISPLAY = {
    "phone": "Phone",
    "email": "Email",
    "upi": "UPI handle",
    "upi_id": "UPI handle",
    "account": "Account",
    "account_number": "Account",
    "ifsc": "Bank branch code",
    "reference": "Transaction reference",
    "utr": "Transaction reference",
    "party": "Named party",
    "person": "Named party",
    "device": "Device",
    "url": "Web address",
    "ip_address": "IP address",
}
NON_IDENTITY_ENTITY_TYPES = {"amount"}


def _entity_display(entity_type: str) -> str | None:
    """The label a reader sees, or None when the row is not an identity at all."""
    if entity_type in NON_IDENTITY_ENTITY_TYPES:
        return None
    return ENTITY_DISPLAY.get(entity_type, entity_type.replace("_", " ").title())


def _unique_relations(relations: list) -> list:
    """Collapse relation rows that say the same thing.

    Correlation writes one row per pair of records, so an identifier shared by four records
    produced six identical "corroboration / account_identifiers / 0.85" lines. A reader needs the
    finding once.
    """
    seen: set[tuple] = set()
    unique = []
    for item in relations:
        key = (
            item.relation_type,
            item.detection_method,
            tuple(sorted(item.matching_or_conflicting_fields or [])),
            tuple(sorted(item.evidence_ids or [])),
            round(float(item.confidence), 2),
        )
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique


# The entity classes SIH26189 names, in the order a reader thinks about them: who, then what they
# moved in, then where, then under whose name.
# Plural and singular both, because a briefing states these in a sentence and "1 organisations"
# is the kind of detail a reader notices instead of the finding beside it.
NETWORK_ENTITY_CLASSES = (
    ("person", "People named", "person named"),
    ("vehicle", "Vehicles", "vehicle"),
    ("location", "Places", "place"),
    ("organisation", "Organisations", "organisation"),
    ("phone", "Phone numbers", "phone number"),
    ("upi", "UPI handles", "UPI handle"),
    ("account", "Accounts", "account"),
    ("email", "Email addresses", "email address"),
    ("reference", "Transaction references", "transaction reference"),
)


# The wider report calls both a person and an unclassified counterparty a "Named party", which is
# the cautious reading it wants elsewhere. Inside the network sections that reads as a contradiction
# against a class table saying "People named", so these sections use one vocabulary throughout.
NETWORK_CLASS_LABELS = {
    "person": "Person",
    "party": "Named counterparty",
    "vehicle": "Vehicle",
    "location": "Place",
    "organisation": "Organisation",
    "phone": "Phone",
    "upi": "UPI handle",
    "account": "Account",
    "email": "Email",
    "reference": "Transaction reference",
}


def _network_label(entity_type: object) -> str:
    key = str(entity_type or "")
    return NETWORK_CLASS_LABELS.get(key) or _entity_display(key) or key.replace("_", " ").title()


def _network_snapshot(db: Session, case_id: str) -> dict:
    """What the criminal-network layer knows about this case.

    The report was written before this layer existed and still described a cyber-fraud case: it
    could name the files that shared an identifier but not the people, vehicles and places the
    problem statement is actually about, nor who sits where in the network between them.

    Every figure here is read back from the same functions the live views use, so a printed report
    and the screen it was printed from cannot disagree.
    """
    from app.graph import analytics
    from app.services import temporal

    entities = db.scalars(select(Entity).where(Entity.case_id == case_id)).all()
    relations = db.scalars(select(EntityRelation).where(EntityRelation.case_id == case_id)).all()

    classes = Counter(item.entity_type for item in entities)
    # Distinct evidence files, not occurrence rows. One file can record the same identity in
    # several fields, and counting those made a number appear in more files than the case holds.
    occurrences = Counter(
        row[0]
        for row in db.execute(
            select(EntityOccurrence.entity_id, EntityOccurrence.evidence_id)
            .where(EntityOccurrence.case_id == case_id)
            .distinct()
        )
    )
    labels = {item.id: item.value for item in entities}
    types = {item.id: item.entity_type for item in entities}

    # An identity written in several files and resolved to one node is the thing this product
    # exists to do, so it is reported as a figure rather than left for a reader to infer.
    across_sources = sorted(
        (
            {"label": labels.get(entity_id, "?"), "type": types.get(entity_id, "?"), "sources": count}
            for entity_id, count in occurrences.items()
            if count > 1
        ),
        key=lambda item: (-item["sources"], item["label"]),
    )

    traced = sum(1 for item in relations if item.source_evidence_id and item.source_reference)
    chronology = temporal.case_chronology(db, case_id)

    return {
        "overview": analytics.network_overview(db, case_id),
        "ranked": analytics.important_entities(db, case_id, limit=8),
        "bridges": analytics.bridge_relationships(db, case_id),
        "communities": analytics.communities(db, case_id),
        "classes": [
            (plural, singular, classes.get(key, 0))
            for key, plural, singular in NETWORK_ENTITY_CLASSES
            if classes.get(key)
        ],
        "entity_total": len(entities),
        "relation_total": len(relations),
        "across_sources": across_sources[:10],
        "traceability": {
            "traced": traced,
            "total": len(relations),
            "percent": round((traced / len(relations)) * 100, 1) if relations else 100.0,
        },
        "chronology": chronology,
        "pre_incident": temporal.pre_incident_contacts(db, case_id)[:6],
        "bursts": temporal.communication_bursts(db, case_id)[:6],
        "labels": labels,
    }


def _snapshot(db: Session, case_id: str) -> dict:
    case = db.get(Case, case_id)
    if not case:
        raise ValueError("Case not found")
    evidence = db.scalars(select(EvidenceFile).where(EvidenceFile.case_id == case_id).order_by(EvidenceFile.uploaded_at)).all()
    # Same rule as the live timeline: a raw OCR event whose file the grounded pass has already read
    # is a duplicate of that record's quoted source text, so it is not listed twice.
    from app.api.analysis import _visible_timeline_events

    events = _visible_timeline_events(db, case_id)
    transactions = db.scalars(select(Transaction).where(Transaction.case_id == case_id).order_by(Transaction.occurred_at)).all()
    alerts = db.scalars(select(Alert).where(Alert.case_id == case_id).order_by(Alert.generated_at)).all()
    claims = db.scalars(select(Claim).where(Claim.case_id == case_id).order_by(Claim.created_at)).all()
    contradictions = db.scalars(select(Contradiction).where(Contradiction.case_id == case_id).order_by(Contradiction.created_at)).all()
    reviews = db.scalars(select(ReviewDecision).where(ReviewDecision.case_id == case_id).order_by(ReviewDecision.created_at)).all()
    grounded = db.scalars(select(NormalizedRecord).where(NormalizedRecord.case_id == case_id).order_by(NormalizedRecord.created_at)).all()
    relations = db.scalars(select(RecordRelation).where(RecordRelation.case_id == case_id).order_by(RecordRelation.confidence.desc())).all()
    return {
        "case": {
            "number": case.case_number,
            "title": case.title,
            "crime_type": case.crime_type,
            "fir_number": case.fir_number,
            "victim_alias": case.victim_alias,
            "date_range_start": case.date_range_start.isoformat() if case.date_range_start else None,
            "date_range_end": case.date_range_end.isoformat() if case.date_range_end else None,
            "description": case.description,
            "status": case.status.value,
            "priority": case.priority.value,
        },
        "evidence": [{"id": item.id, "name": item.original_name, "hash": item.sha256, "status": item.status.value} for item in evidence],
        "events": [{"time": item.occurred_at.isoformat() if item.occurred_at else None, "original_time": item.original_time, "precision": item.time_precision, "type": item.event_type, "description": item.description, "review": item.review_status.value} for item in events],
        "transactions": [{"time": item.occurred_at.isoformat() if item.occurred_at else None, "amount": float(item.amount), "currency": item.currency or "INR", "sender": item.sender_value, "receiver": item.receiver_value, "reference": item.reference_id, "review": item.review_status.value} for item in transactions],
        "alerts": [{"rule": item.rule_code, "severity": item.severity.value, "status": item.status.value, "explanation": item.explanation} for item in alerts],
        "claims": [{"id": item.id, "statement": item.statement, "type": item.claim_type, "status": item.status.value} for item in claims],
        "contradictions": [{"id": item.id, "subject": item.subject, "description": item.description, "status": item.status.value} for item in contradictions],
        "reviews": [{"subject_type": item.subject_type, "subject_id": item.subject_id, "decision": item.decision.value, "note": item.note} for item in reviews],
        "grounded_records": [
            {
                "source": item.source_file_name,
                "source_type": item.source_type,
                "summary": item.normalized_summary,
                "observed_text": item.observed_text,
                "event_type": item.event_type,
                "time": item.event_time.isoformat() if item.event_time else None,
                "sender": item.sender,
                "receiver": item.receiver,
                "chat_participant_identifier": item.chat_participant_identifier,
                "amount": float(item.amount_value) if item.amount_value is not None else None,
                "currency": item.amount_currency,
                "amount_role": item.amount_role,
                "basis": item.observation_basis,
                "band": item.final_confidence_band,
                "validation_status": item.validation_status,
                "requires_review": item.requires_human_review,
                "review_reason": item.review_reason,
                "model": item.extraction_model_name,
                "conflicts": list(item.conflict_fields or []),
                "provenance_fields": sorted((item.field_provenance or {}).keys()),
            }
            for item in grounded
        ],
        "network": _network_snapshot(db, case_id),
        "connections": describe_connections(db, case_id),
        "connection_summary": build_connection_graph(db, case_id)["summary"],
        "candidate_relations": [
            {
                "type": item.relation_type,
                "status": item.status,
                "method": item.detection_method,
                "fields": list(item.matching_or_conflicting_fields or []),
                "reason": item.reason,
                "confidence": float(item.confidence),
                "requires_review": item.requires_human_review,
            }
            for item in _unique_relations(relations)
        ],
    }


def create_report_record(db: Session, *, case_id: str, generated_by_id: str, redaction_profile: str = "standard", profile: str = "case_file") -> Report:
    highest = db.scalar(select(func.max(Report.version)).where(Report.case_id == case_id)) or 0
    snapshot_hash = hashlib.sha256(json.dumps(_snapshot(db, case_id), sort_keys=True, default=str).encode("utf-8")).hexdigest()
    report = Report(case_id=case_id, version=highest + 1, review_snapshot_hash=snapshot_hash, redaction_profile=redaction_profile, profile=profile, generated_by_id=generated_by_id)
    db.add(report)
    db.flush()
    return report


# ReportLab's built-in fonts are Type-1 with WinAnsi encoding. A character outside that set is not
# refused — it is emitted as its raw UTF-8 bytes, which the viewer then reads as Latin-1, so a
# downward arrow arrived on the page as "→". Report body text is one thing; quoted OCR
# text is another, and a screenshot can contain any character at all. Everything printed therefore
# passes through this mapping first.
_FONT_SUBSTITUTIONS = {
    "→": ">", "←": "<", "↓": "v", "↑": "^", "⇒": "=>", "⇐": "<=",
    "≠": "!=", "≤": "<=", "≥": ">=", "×": "x", "−": "-",
    "‘": "'", "’": "'", "‚": ",", "‹": "<", "›": ">",
    "′": "'", "″": '"', " ": " ", "​": "", "﻿": "",
    # Currency marks appear inside quoted evidence. Turning them into "?" would destroy the very
    # part of the quote a reviewer is checking, so each keeps its conventional written form.
    "₹": "Rs", "₨": "Rs", "₩": "W", "₪": "NIS", "฿": "THB", "₫": "d",
}


def _renderable(text: str) -> str:
    """Reduce text to what the report font can actually draw.

    Anything with no WinAnsi equivalent becomes "?" rather than being dropped, so a reader can see
    that the source held a character this document could not reproduce.
    """
    if text.isascii():
        return text
    out: list[str] = []
    for character in text:
        character = _FONT_SUBSTITUTIONS.get(character, character)
        try:
            character.encode("cp1252")
        except UnicodeEncodeError:
            character = "?"
        out.append(character)
    return "".join(out)


def _safe(value: object) -> str:
    # `value or ""` swallowed every zero, so a count of 0 rendered as an empty cell rather than
    # as the fact that there are none.
    text = "" if value is None else str(value)
    text = _renderable(text)
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _timestamp_parts(value: object) -> tuple[str, str] | None:
    """Return a date and 12-hour time for PDF display without changing the stored source value."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        moment = value
    else:
        try:
            moment = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return None
    return moment.strftime("%d %b %Y"), moment.strftime("%I:%M %p").lstrip("0")


def _display_timestamp(value: object) -> str:
    parts = _timestamp_parts(value)
    return " at ".join(parts) if parts else str(value or "Not recorded")


def _cell(value: str) -> Paragraph:
    return Paragraph(_safe(value), CELL_STYLE)


def _cell_lines(*values: object) -> Paragraph:
    return Paragraph("<br/>".join(_safe(value) for value in values if value is not None), CELL_STYLE)


def _timestamp_cell(value: object) -> Paragraph:
    parts = _timestamp_parts(value)
    return _cell_lines(*parts) if parts else _cell(str(value or "Not recorded"))


def _source_time_from_description(description: object) -> str | None:
    """Read an explicitly labelled source time without modifying the stored event timestamp."""
    match = re.search(
        r"\btime\s*[:=]\s*(?P<hour>[01]?\d|2[0-3]):(?P<minute>[0-5]\d)(?:\s*(?P<meridiem>am|pm))?\b",
        str(description or ""),
        flags=re.IGNORECASE,
    )
    if not match:
        return None
    hour = int(match.group("hour"))
    minute = int(match.group("minute"))
    meridiem = match.group("meridiem")
    if meridiem:
        return f"{hour}:{minute:02d} {meridiem.upper()}"
    return datetime(2000, 1, 1, hour, minute).strftime("%I:%M %p").lstrip("0")


def _event_timestamp_parts(event: dict) -> tuple[str | None, str | None] | None:
    """Prefer the stored event time; use a labelled source time only for a date-only placeholder."""
    parts = _timestamp_parts(event.get("time"))
    if not parts:
        # No datetime was established. The source may still have shown a clock reading — a chat
        # bubble stamped "5:45 pm" under a "Today" divider states a time but never a date — and
        # printing that reading is honest where inventing a date would not be.
        observed = event.get("original_time") or _source_time_from_description(event.get("description"))
        return (None, str(observed)) if observed else None
    date_label, time_label = parts
    source_time = _source_time_from_description(event.get("description"))
    if time_label == "12:00 AM" and source_time:
        return date_label, source_time
    return parts


def _format_event_time(parts: tuple[str | None, str | None] | None) -> str:
    if not parts:
        return "Time not established"
    date_label, time_label = parts
    if date_label and time_label:
        return f"{date_label} at {time_label}"
    if time_label:
        return f"{time_label} (date not established)"
    return date_label or "Time not established"


def _event_timestamp_cell(event: dict) -> Paragraph:
    parts = _event_timestamp_parts(event)
    if not parts:
        return _cell("Time not established")
    date_label, time_label = parts
    if date_label is None:
        return _cell_lines(time_label, "date not established")
    return _cell_lines(date_label, time_label)


def _display_event_timestamp(event: dict) -> str:
    return _format_event_time(_event_timestamp_parts(event))


def _report_table_style(*, header: str = "burgundy", padded: float = 4.0, alternate: bool = True) -> TableStyle:
    """Apply the formal register treatment with accessible, high-contrast headers."""
    header_color = BURGUNDY if header == "burgundy" else CHARCOAL
    commands = [
        ("BACKGROUND", (0, 0), (-1, 0), header_color),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 8.0),
        ("LEADING", (0, 0), (-1, 0), 10.0),
        ("GRID", (0, 0), (-1, -1), 0.35, RULE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 1), (-1, -1), padded),
        ("RIGHTPADDING", (0, 1), (-1, -1), padded),
        ("TOPPADDING", (0, 1), (-1, -1), max(3.0, padded - 1)),
        ("BOTTOMPADDING", (0, 1), (-1, -1), max(3.0, padded - 1)),
        ("LEFTPADDING", (0, 0), (-1, 0), max(5.25, padded)),
        ("RIGHTPADDING", (0, 0), (-1, 0), max(5.25, padded)),
        ("TOPPADDING", (0, 0), (-1, 0), 5.0),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 5.0),
        ("LINEBELOW", (0, 0), (-1, 0), 0.55, colors.HexColor("#e3c9c9")),
    ]
    if alternate:
        commands.append(("ROWBACKGROUNDS", (0, 1), (-1, -1), [PAPER_ALT, PAPER]))
    return TableStyle(commands)

def _apply_reference_table_rhythm(story: list[object]) -> None:
    """Make every report table header readable while retaining its established colors and body rhythm."""
    for flowable in story:
        if not isinstance(flowable, Table) or not flowable._cellvalues:
            continue
        has_dark_semantic_header = any(
            command[0] == "BACKGROUND"
            and command[1] == (0, 0)
            and command[2] == (-1, 0)
            and command[3] in (BURGUNDY, CHARCOAL)
            for command in getattr(flowable, "_bkgrndcmds", [])
        )
        if not has_dark_semantic_header:
            continue
        # HEADER_CELL_MARKUP_FORCED: table text commands do not override Paragraph fragments.
        for column_index, header_cell in enumerate(flowable._cellvalues[0]):
            if isinstance(header_cell, Paragraph):
                visible_text = _safe(header_cell.getPlainText()).replace("\n", "<br/>")
                flowable._cellvalues[0][column_index] = Paragraph(
                    f'<font color="#FFFFFF"><b>{visible_text}</b></font>',
                    HEADER_CELL_STYLE,
                )
        flowable.setStyle(TableStyle([
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, 0), 8.0),
            ("LEADING", (0, 0), (-1, 0), 10.0),
            ("GRID", (0, 0), (-1, -1), 0.35, RULE),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, 0), 5.25),
            ("RIGHTPADDING", (0, 0), (-1, 0), 5.25),
            ("TOPPADDING", (0, 0), (-1, 0), 5.0),
            ("BOTTOMPADDING", (0, 0), (-1, 0), 5.0),
            ("LINEBELOW", (0, 0), (-1, 0), 0.55, colors.HexColor("#e3c9c9")),
            ("LEFTPADDING", (0, 1), (-1, -1), 4),
            ("RIGHTPADDING", (0, 1), (-1, -1), 4),
            ("TOPPADDING", (0, 1), (-1, -1), 3.5),
            ("BOTTOMPADDING", (0, 1), (-1, -1), 3.5),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [PAPER_ALT, PAPER]),
        ]))

def _draw_report_frame(canvas, doc) -> None:
    canvas.saveState()
    width, height = A4
    canvas.setStrokeColor(RULE)
    canvas.setLineWidth(0.35)
    canvas.line(14 * mm, height - 10 * mm, width - 14 * mm, height - 10 * mm)
    canvas.line(14 * mm, 12 * mm, width - 14 * mm, 12 * mm)
    if canvas.getPageNumber() > 1:
        canvas.setFont("Helvetica-Bold", 6.2)
        canvas.setFillColor(BURGUNDY)
        canvas.drawString(14 * mm, height - 8 * mm, "DRISHYAM  /  CRIMINAL NETWORK ANALYSIS REPORT")
    canvas.setFont("Helvetica", 6.1)
    canvas.setFillColor(colors.HexColor("#756f68"))
    canvas.drawString(14 * mm, 8.3 * mm, "DRISHYAM — CRIMINAL NETWORK ANALYSIS REPORT")
    canvas.drawRightString(width - 14 * mm, 8.3 * mm, f"Page {canvas.getPageNumber()}")
    canvas.restoreState()


def _case_synopsis(case: Case) -> str:
    """Return the stored investigator-entered Case Description without rewriting it."""
    if (case.description or "").strip():
        return case.description
    return "Case synopsis not available."

def _controlled_conclusion(case: Case, *, evidence_count: int, event_count: int, relationship_count: int, alert_count: int, review_count: int) -> str:
    return (
        f"This case record currently includes {evidence_count} evidence item(s), {event_count} timeline event(s), "
        f"{relationship_count} linked record(s), {alert_count} alert(s), and {review_count} review decision(s). "
        "The information is presented for review and should be checked against its sources. It does not by itself decide identity, intent, responsibility, or a legal outcome."
    )
def _render_bar_chart(path: Path, title: str, labels: list[str], values: list[float], color: str, y_label: str) -> Path | None:
    if len(labels) < 2:
        return None
    figure, axis = plt.subplots(figsize=(11.5, 5.7), dpi=320)
    figure.patch.set_facecolor("#fbf5ec")
    axis.set_facecolor("#fbf5ec")
    bars = axis.bar(range(len(labels)), values, color=color, width=.62)
    axis.set_xticks(range(len(labels)), labels, rotation=22, ha="right", fontsize=9)
    axis.set_ylabel(y_label, color="#3d4952")
    axis.set_title(title, color="#4b1821", fontsize=15, fontweight="bold", pad=15)
    axis.grid(axis="y", color="#d9cfc1", linewidth=.6, alpha=.75)
    axis.spines[["top", "right"]].set_visible(False)
    for bar, value in zip(bars, values):
        axis.text(bar.get_x() + bar.get_width() / 2, bar.get_height(), f"{value:,.0f}", ha="center", va="bottom", fontsize=9, color="#3d4952")
    figure.tight_layout()
    figure.savefig(path, dpi=320, facecolor=figure.get_facecolor())
    plt.close(figure)
    return path


def _render_donut(path: Path, title: str, values: Counter[str]) -> Path | None:
    if not values:
        return None
    labels, counts = list(values.keys()), list(values.values())
    palette = {"critical": "#9d3932", "high": "#7b1e2b", "medium": "#c68a34", "low": "#78858b"}
    figure, axis = plt.subplots(figsize=(7.2, 6.2), dpi=320)
    figure.patch.set_facecolor("#fbf5ec")
    axis.set_facecolor("#fbf5ec")
    wedges, _ = axis.pie(counts, colors=[palette.get(label.lower(), "#78858b") for label in labels], startangle=90, wedgeprops={"width": .36, "edgecolor": "#fbf5ec"})
    total = sum(counts)
    axis.text(0, .07, str(total), ha="center", va="center", fontsize=27, fontweight="bold", color="#4b1821")
    axis.text(0, -.14, "ALERTS", ha="center", va="center", fontsize=9, color="#3d4952")
    legend = [f"{label.title()} · {count} ({count / total:.0%})" for label, count in zip(labels, counts)]
    axis.legend(wedges, legend, loc="lower center", bbox_to_anchor=(.5, -.17), frameon=False, fontsize=9, ncol=1)
    axis.set_title(title, color="#4b1821", fontsize=15, fontweight="bold", pad=14)
    figure.tight_layout()
    figure.savefig(path, dpi=320, facecolor=figure.get_facecolor())
    plt.close(figure)
    return path


def _render_connection_graph(db: Session, case_id: str, output: Path) -> tuple[Path | None, dict]:
    """Draw what links the evidence: files on the left, shared identifiers on the right.

    The previous drawing was a four-lane provenance flow — evidence, event, transaction,
    identifier — which rendered a hundred nodes and answered a question nobody asks. Only an
    identifier found in more than one file can connect anything, so only those are drawn, and the
    line weight carries how specific the shared value is.
    """
    projection = build_connection_graph(db, case_id)
    identifiers = [node for node in projection["nodes"] if node["kind"] == "identifier"]
    evidence_nodes = [node for node in projection["nodes"] if node["kind"] == "evidence"]
    summary = projection["summary"]

    metrics = {
        "evidence_count": summary["evidence_count"],
        "connected_evidence": summary["connected_evidence"],
        "bridge_count": summary["bridge_count"],
        "isolated_count": len(summary["isolated_evidence"]),
        "connections": describe_connections(db, case_id),
    }
    if not identifiers:
        return None, metrics

    # Keep the picture legible: a page can carry about a dozen bridges before it turns to soup.
    identifiers = identifiers[:12]
    shown = {node["id"] for node in identifiers}
    edges = [edge for edge in projection["edges"] if edge["source"] in shown]
    linked_evidence = {edge["target"] for edge in edges}
    evidence_nodes = [node for node in evidence_nodes if node["id"] in linked_evidence]

    band_colour = {"strong": "#7b1e2b", "moderate": "#b17a2d", "weak": "#8b8175"}
    height = max(5.2, 0.62 * max(len(identifiers), len(evidence_nodes)) + 2.0)
    figure, axis = plt.subplots(figsize=(13.5, height), dpi=220)
    figure.patch.set_facecolor("#fbf5ec")
    axis.set_facecolor("#fbf5ec")

    def _lane(items: list[dict], x: float) -> dict[str, tuple[float, float]]:
        spacing = 1.0
        offset = (len(items) - 1) / 2
        return {item["id"]: (x, (offset - index) * spacing) for index, item in enumerate(items)}

    left = _lane(evidence_nodes, 0.0)
    right = _lane(identifiers, 1.0)
    position = {**left, **right}

    for edge in edges:
        start, end = position.get(edge["target"]), position.get(edge["source"])
        if not start or not end:
            continue
        axis.annotate(
            "",
            xy=end,
            xytext=start,
            arrowprops={
                "arrowstyle": "-",
                "color": band_colour.get(edge.get("strength_band", "weak"), "#8b8175"),
                "alpha": 0.55,
                "linewidth": 1.0 + 1.8 * float(edge.get("strength", 0.5)),
                "connectionstyle": "arc3,rad=0.12",
                "linestyle": "--" if edge.get("link_style") == "dashed" else "-",
            },
        )

    for node in evidence_nodes:
        x, y = position[node["id"]]
        axis.scatter([x], [y], s=520, c="#e6d7bd", edgecolors="#4b1821", linewidths=1.1, zorder=3)
        axis.text(x - 0.045, y, _shorten(node["label"], 34), ha="right", va="center", fontsize=8.5, color="#3a2f28")
        axis.text(x - 0.045, y - 0.26, f"{node['bridge_count']} shared", ha="right", va="center", fontsize=7, color="#8a7c6f")

    for node in identifiers:
        x, y = position[node["id"]]
        colour = band_colour.get(node["strength_band"], "#8b8175")
        axis.scatter([x], [y], s=560, c=colour, edgecolors="#4b1821", linewidths=1.1, zorder=3)
        axis.text(x + 0.045, y, _shorten(node["label"], 32), ha="left", va="center", fontsize=8.5, fontweight="bold", color="#3a2f28")
        axis.text(
            x + 0.045,
            y - 0.26,
            f"{node['identifier_type']} · in {node['evidence_count']} files · {node['strength_band']}",
            ha="left", va="center", fontsize=7, color="#8a7c6f",
        )

    axis.text(0.0, max(len(evidence_nodes), len(identifiers)) / 2 + 0.75, "EVIDENCE FILES",
              ha="center", fontsize=8.5, fontweight="bold", color="#4b1821")
    axis.text(1.0, max(len(evidence_nodes), len(identifiers)) / 2 + 0.75, "SHARED IDENTIFIERS",
              ha="center", fontsize=8.5, fontweight="bold", color="#4b1821")

    # Anchored to the figure, not the axes: inside the axes it printed over the lowest node row.
    figure.legend(
        handles=[
            Patch(facecolor="#e6d7bd", edgecolor="#4b1821", label="Evidence file"),
            Patch(facecolor="#7b1e2b", edgecolor="#4b1821", label="Strong link"),
            Patch(facecolor="#b17a2d", edgecolor="#4b1821", label="Moderate link"),
            Patch(facecolor="#8b8175", edgecolor="#4b1821", label="Weak link"),
        ],
        loc="lower center", ncol=4, frameon=False, fontsize=8,
    )
    axis.set_xlim(-0.55, 1.55)
    span = max(len(evidence_nodes), len(identifiers)) / 2
    axis.set_ylim(-span - 1.0, span + 1.1)
    axis.axis("off")

    path = output.parent / f"{output.stem}-connection-graph.png"
    figure.tight_layout(pad=1.1, rect=(0, 0.07, 1, 1))
    figure.savefig(path, dpi=220, bbox_inches="tight", facecolor=figure.get_facecolor())
    plt.close(figure)
    return path, metrics


def _shorten(text: object, limit: int) -> str:
    value = str(text)
    return value if len(value) <= limit else value[: limit - 1] + "…"


def _render_relationship_graph(db: Session, case_id: str, output: Path) -> tuple[Path | None, dict]:
    """Render a focused, source-derived graph while retaining raw graph counts and relation rows."""
    projection = build_case_graph(db, case_id)
    if not projection["nodes"]:
        return None, projection["metrics"]
    graph = nx.DiGraph()
    for node in projection["nodes"]:
        graph.add_node(node["id"], label=node.get("label", "record"), kind=node.get("kind", "entity"))
    for edge in projection["edges"]:
        graph.add_edge(edge["source"], edge["target"], relationship=edge.get("relationship", "source-linked"))
    palette = {"evidence": "#d9c7a6", "event": "#59636a", "transaction": "#b17a2d", "phone": "#7b1e2b", "upi": "#7b1e2b", "upi_id": "#7b1e2b", "account": "#b17a2d", "reference": "#8a7a5c", "vehicle": "#4a6350", "person": "#6b4f7a", "email": "#657b87", "url": "#657b87"}
    degrees = dict(graph.degree())
    ranked = sorted(graph.nodes, key=lambda node: (-degrees[node], str(graph.nodes[node].get("label"))))
    evidence_nodes = {node for node in graph.nodes if graph.nodes[node].get("kind") == "evidence"}
    transaction_nodes = {node for node in graph.nodes if graph.nodes[node].get("kind") == "transaction"}
    identifier_nodes = [node for node in ranked if graph.nodes[node].get("kind") not in {"evidence", "event", "transaction"}]
    selected_identifiers = set(identifier_nodes[:4])
    event_candidates = [node for node in ranked if graph.nodes[node].get("kind") == "event" and degrees[node] >= 2]
    selected_events = set(event_candidates[:3])
    selected_transactions = set(sorted(transaction_nodes, key=lambda node: (-degrees[node], str(graph.nodes[node].get("label"))))[:6])
    focus_nodes = evidence_nodes | selected_transactions | selected_identifiers | selected_events
    focus_graph = graph.subgraph(focus_nodes).copy()
    if not focus_graph.nodes:
        focus_graph = graph.copy()
        focus_nodes = set(graph.nodes)
    compacted_nodes = set(graph.nodes) - set(focus_graph.nodes)
    compacted_by_kind = Counter(str(graph.nodes[node].get("kind", "record")).replace("_", " ") for node in compacted_nodes)
    lanes = {"evidence": -1.5, "event": -0.5, "transaction": 0.5}
    grouped: dict[float, list[str]] = {}
    for node in sorted(focus_graph.nodes, key=lambda item: (str(focus_graph.nodes[item].get("kind")), str(focus_graph.nodes[item].get("label")))):
        grouped.setdefault(lanes.get(str(focus_graph.nodes[node].get("kind")), 1.5), []).append(node)
    position: dict[str, tuple[float, float]] = {}
    for lane_x, nodes in grouped.items():
        for index, node in enumerate(nodes):
            position[node] = (lane_x, ((len(nodes) - 1) / 2 - index) * .84)
    figure = plt.figure(figsize=(16.5, 8.7), dpi=320)
    axis = figure.add_subplot(111)
    axis.set_facecolor("#fbf5ec")
    figure.patch.set_facecolor("#fbf5ec")
    nx.draw_networkx_edges(focus_graph, position, ax=axis, edge_color="#8b8175", arrows=True, arrowsize=10, alpha=.58, width=1.0, connectionstyle="arc3,rad=.10")
    colors_by_node = [palette.get(str(focus_graph.nodes[node].get("kind")), "#3d4952") for node in focus_graph.nodes]
    node_sizes = [510 + min(degrees[node], 8) * 130 for node in focus_graph.nodes]
    nx.draw_networkx_nodes(focus_graph, position, ax=axis, node_color=colors_by_node, node_size=node_sizes, edgecolors="#4b1821", linewidths=[1.5 if degrees[node] >= 3 else .7 for node in focus_graph.nodes])
    labels = {node: str(focus_graph.nodes[node]["label"])[:24] for node in focus_graph.nodes}
    nx.draw_networkx_labels(focus_graph, position, labels=labels, ax=axis, font_size=9.4, font_color="#201b18", font_weight="bold")
    relationship_examples: dict[str, tuple[str, str]] = {}
    for source, target, data in focus_graph.edges(data=True):
        relationship_examples.setdefault(str(data.get("relationship", "source-linked")), (source, target))
    edge_labels = {pair: relationship for relationship, pair in relationship_examples.items()}
    nx.draw_networkx_edge_labels(focus_graph, position, edge_labels=edge_labels, ax=axis, font_size=7.2, font_color="#66594f", rotate=False, label_pos=.52)
    top = max((point[1] for point in position.values()), default=0) + 1.0
    for lane_x, heading in [(-1.5, "EVIDENCE"), (-.5, "EVENTS"), (.5, "TRANSACTIONS"), (1.5, "IDENTIFIERS")]:
        axis.text(lane_x, top, heading, ha="center", va="center", fontsize=9, fontweight="bold", color="#4b1821")
    axis.legend(handles=[Patch(facecolor="#d9c7a6", edgecolor="#4b1821", label="Evidence"), Patch(facecolor="#59636a", edgecolor="#4b1821", label="Event"), Patch(facecolor="#b17a2d", edgecolor="#4b1821", label="Transaction"), Patch(facecolor="#7b1e2b", edgecolor="#4b1821", label="Key identifier"), Patch(facecolor="#657b87", edgecolor="#4b1821", label="Email / URL")], loc="lower center", bbox_to_anchor=(.5, -.08), ncol=5, frameon=False, fontsize=8)
    compacted_summary = ", ".join(f"{count} {kind}" for kind, count in compacted_by_kind.most_common()) or "none"
    axis.text(.5, -.17, f"Focus graph: {focus_graph.number_of_nodes()} of {graph.number_of_nodes()} source-derived nodes · {focus_graph.number_of_edges()} of {graph.number_of_edges()} relationships. Compacted supporting nodes: {compacted_summary}.", transform=axis.transAxes, ha="center", va="center", fontsize=8, color="#66594f")
    axis.set_title("Primary evidence links · Source-linked backend projection", color="#4b1821", fontsize=14, fontweight="bold", pad=12)
    axis.margins(.045)
    axis.axis("off")
    path = output.parent / f"{output.stem}-relationship-graph.png"
    figure.tight_layout(pad=1.2)
    figure.savefig(path, dpi=220, bbox_inches="tight", facecolor=figure.get_facecolor())
    plt.close(figure)
    metrics = projection["metrics"] | {
        "evidence_sources": sum(1 for node in projection["nodes"] if node.get("kind") == "evidence"),
        "repeated_identifiers": sum(1 for node in graph.nodes if degrees[node] >= 2 and graph.nodes[node].get("kind") not in {"evidence", "event", "transaction"}),
        "high_connectivity": sum(1 for node in graph.nodes if degrees[node] >= 3),
        "ranked_nodes": ranked,
        "labels": {node: graph.nodes[node]["label"] for node in graph.nodes},
        "degrees": degrees,
        "edges": projection["edges"],
        "focus_node_count": focus_graph.number_of_nodes(),
        "focus_edge_count": focus_graph.number_of_edges(),
        "compacted_node_count": len(compacted_nodes),
        "compacted_by_kind": dict(compacted_by_kind),
    }
    return path, metrics


def _append_connection_section(story: list[object], styles, snapshot: dict) -> None:
    """Say, in words, what ties the evidence together — before drawing anything.

    A reader should learn which files are connected and by what without having to interpret a
    diagram, so the sentences come first and the graph illustrates them afterwards.
    """
    connections = snapshot.get("connections") or []
    summary = snapshot.get("connection_summary") or {}

    story.extend([PageBreak(), Paragraph("How this evidence connects", styles["Heading1"])])

    total = summary.get("evidence_count", 0)
    connected = summary.get("connected_evidence", 0)
    isolated = summary.get("isolated_evidence") or []

    if not connections:
        story.append(
            Paragraph(
                f"No identifier is shared between any two of the {total} evidence items in this case. "
                "That is a finding in itself: on the material available, these files do not link to one another.",
                styles["BodyText"],
            )
        )
        return

    story.append(
        Paragraph(
            f"<b>{connected} of {total}</b> evidence items are connected to at least one other, through "
            f"<b>{summary.get('bridge_count', 0)}</b> shared identifier(s). Each link below is an exact match on a "
            "value that appears in more than one file. A shared identifier links the <b>files</b>; it does not by "
            "itself establish that the same person is behind them.",
            styles["BodyText"],
        )
    )
    story.append(Spacer(1, 4 * mm))

    for item in connections:
        story.append(Paragraph("• " + _safe(item["sentence"]), styles["BodyText"]))
        story.append(Paragraph("<font size=7 color='#6b6258'>" + _safe(item["caveat"]) + "</font>", styles["BodyText"]))
        story.append(Spacer(1, 2.5 * mm))

    rows = [[_cell("Shared value"), _cell("Type"), _cell("Appears in"), _cell("Evidence items"), _cell("Link strength")]]
    for item in connections:
        rows.append([
            _cell(item["identifier"]),
            _cell(item["identifier_label"]),
            _cell(str(item["evidence_count"]) + " files"),
            _cell(", ".join(item["evidence_names"])),
            _cell(item["strength_band"]),
        ])
    table = Table(rows, colWidths=[42 * mm, 26 * mm, 20 * mm, 68 * mm, 22 * mm], repeatRows=1)
    table.setStyle(_report_table_style(header="burgundy"))
    story.extend([Spacer(1, 2 * mm), table, Spacer(1, 4 * mm)])

    if isolated:
        story.append(
            Paragraph(
                "<b>Not connected to anything:</b> "
                + _safe(", ".join(item["label"] for item in isolated))
                + ". No identifier from these files was found elsewhere in the case.",
                styles["BodyText"],
            )
        )

    story.append(Spacer(1, 2 * mm))
    story.append(
        Paragraph(
            "<font size=7 color='#6b6258'>Link strength reflects how specific the shared value is and how many "
            "separate files carry it. A transaction reference shared across three files is strong; a shared first "
            "name is weak. Strength is not a probability, and no link here has been confirmed by a reviewer.</font>",
            styles["BodyText"],
        )
    )


_BASIS_LABEL = {
    "direct": "Directly observed",
    "direct_visual": "Directly observed (layout)",
    "inferred": "Contextual inference",
    "unknown": "Not established",
}


def _describe_reference(reference: object) -> str:
    """Where a statement was read, in the words somebody would use to go and look."""
    if not isinstance(reference, dict):
        return ""
    parts: list[str] = []
    if reference.get("page"):
        parts.append(f"page {reference['page']}")
    if reference.get("row"):
        parts.append(f"row {reference['row']}")
    if reference.get("column"):
        parts.append(f'column "{reference["column"]}"')
    if not parts and reference.get("line_start"):
        start, end = reference["line_start"], reference.get("line_end") or reference["line_start"]
        parts.append(f"line {start}" if start == end else f"lines {start}-{end}")
    if not parts and reference.get("kind"):
        parts.append(str(reference["kind"]).replace("_", " "))
    return ", ".join(parts)


def _numbered_findings(db: Session, case_id: str, snapshot: dict) -> list[dict]:
    """The case's findings, each with a number that can be cited elsewhere.

    A finding written only as prose cannot be referred to. An FIR, a case diary or a chargesheet
    needs to be able to say "DRISHYAM finding F-07" and have that mean one specific statement with
    one specific source, stable across the whole document.

    Ordered by how much of the case rests on each: a relationship that is the only link between two
    parts of the network comes before one of many parallel observations, because that is the order
    in which being wrong matters.
    """
    from app.graph import analytics

    relations = db.scalars(select(EntityRelation).where(EntityRelation.case_id == case_id)).all()
    if not relations:
        return []

    labels = {item.id: item.value for item in db.scalars(select(Entity).where(Entity.case_id == case_id))}
    files = {item.id: item.original_name for item in db.scalars(select(EvidenceFile).where(EvidenceFile.case_id == case_id))}

    # The pairs the network cannot do without. Their observations are listed first.
    load_bearing = set()
    for bridge in analytics.bridge_relationships(db, case_id):
        pair = ((bridge.get("subject") or {}).get("id"), (bridge.get("object") or {}).get("id"))
        load_bearing.add(frozenset(pair))

    ordered = sorted(
        relations,
        key=lambda item: (
            0 if frozenset((item.subject_entity_id, item.object_entity_id)) in load_bearing else 1,
            -float(item.confidence or 0),
            item.created_at or 0,
        ),
    )

    findings: list[dict] = []
    for number, relation in enumerate(ordered, start=1):
        subject = labels.get(relation.subject_entity_id, "an unresolved identity")
        target = labels.get(relation.object_entity_id, "an unresolved identity")
        meaning = str(relation.relation_type).replace("_", " ").lower()
        place = _describe_reference(relation.source_reference)
        findings.append({
            "id": f"F-{number:02d}",
            "statement": f"{subject} {meaning} {target}.",
            "file": files.get(relation.source_evidence_id, "an evidence file no longer in this case"),
            "place": place,
            "confidence": float(relation.confidence or 0),
            "verification": str(relation.verification_status or "machine_extracted").replace("_", " "),
            "load_bearing": frozenset((relation.subject_entity_id, relation.object_entity_id)) in load_bearing,
        })
    return findings


def _append_numbered_findings(story: list[object], styles, findings: list[dict], *, limit: int = 40) -> None:
    """Print the findings so each one can be cited by number and opened at its source."""
    if not findings:
        story.append(
            Paragraph(
                "This case records no relationship between two resolved identities, so there is no numbered finding "
                "to state. That is an absence of recorded evidence, not a finding that no relationship exists.",
                styles["BodyText"],
            )
        )
        return

    story.append(
        Paragraph(
            "Each finding below is one statement read from one source. The reference is the exact place inside that "
            "file, so a finding can be cited by its number and checked at its origin. A finding is what the evidence "
            "records, not a conclusion about what it means.",
            styles["BodyText"],
        )
    )
    story.append(Spacer(1, 3 * mm))

    rows = [[_cell("No."), _cell("Finding"), _cell("Read from"), _cell("Confidence"), _cell("Verification")]]
    for item in findings[:limit]:
        marker = f"{item['id']}*" if item["load_bearing"] else item["id"]
        source = item["file"] + (f" — {item['place']}" if item["place"] else "")
        rows.append([
            _cell(marker),
            _cell(item["statement"]),
            _cell(_shorten(source, 60)),
            _cell(f"{item['confidence']:.2f}"),
            _cell(item["verification"]),
        ])
    table = Table(rows, colWidths=[15 * mm, 68 * mm, 58 * mm, 20 * mm, 21 * mm], repeatRows=1)
    table.setStyle(_report_table_style())
    story.extend([table, Spacer(1, 3 * mm)])

    if any(item["load_bearing"] for item in findings[:limit]):
        story.append(
            Paragraph(
                "<font size=7 color='#6b6258'>* This finding is the only link between two parts of the network. If it "
                "is a misreading, the connection it carries does not exist. Verify these first.</font>",
                styles["BodyText"],
            )
        )
    if len(findings) > limit:
        story.append(
            Paragraph(
                f"<font size=7 color='#6b6258'>{len(findings) - limit} further finding(s) are recorded in the case and "
                "omitted here for length. They remain in the record and in the full case file.</font>",
                styles["BodyText"],
            )
        )


def _append_network_sections(story: list[object], styles, snapshot: dict) -> None:
    """The criminal network: who is in it, who holds it together, and what it does not establish.

    House rule, the same one the live view follows: a centrality score is never printed on its own.
    Every ranked entity carries the sentence explaining why it ranked and the caveat saying what the
    ranking is not. A number beside a person's name, alone on a page that will be read by somebody
    deciding whether to act on it, invites exactly the reading this system must not support.
    """
    network = snapshot.get("network") or {}
    overview = network.get("overview") or {}
    ranked = network.get("ranked") or []

    story.extend([PageBreak(), Paragraph("Criminal network analysis", styles["Heading1"])])

    entity_total = network.get("entity_total", 0)
    relation_total = network.get("relation_total", 0)

    if not relation_total:
        story.append(
            Paragraph(
                f"This case records {entity_total} resolved identit{'y' if entity_total == 1 else 'ies'} but no stated "
                "relationship between any two of them, so no network can be described. That is an absence of recorded "
                "evidence, not evidence that no network exists.",
                styles["BodyText"],
            )
        )
        return

    bridges = network.get("bridges") or []
    story.append(
        Paragraph(
            f"The evidence in this case states <b>{relation_total}</b> relationship observation(s) between "
            f"<b>{overview.get('entities', 0)}</b> identities, forming <b>{overview.get('communities', 0)}</b> connected "
            f"group(s). <b>{len(bridges)}</b> of those relationships are the only link between two parts of the network: "
            "if one of them is wrong, the connection it carries does not exist. Everything below was read from a source "
            "and can be opened at the row, line or image region it came from.",
            styles["BodyText"],
        )
    )
    story.append(Spacer(1, 4 * mm))

    # ----------------------------------------------------------------- what was found, by class
    classes = network.get("classes") or []
    if classes:
        story.append(Paragraph("Entities recorded, by class", styles["Heading2"]))
        rows = [[_cell("Class"), _cell("Recorded")]] + [[_cell(plural), _cell(str(count))] for plural, _singular, count in classes]
        table = Table(rows, colWidths=[95 * mm, 40 * mm], hAlign="LEFT")
        table.setStyle(_report_table_style())
        story.extend([table, Spacer(1, 3 * mm)])
        story.append(
            Paragraph(
                "<font size=7 color='#6b6258'>A name, a place or an organisation is recorded because a source wrote it "
                "down. Recording it does not establish that the person, place or body behind the name is the one named "
                "elsewhere.</font>",
                styles["BodyText"],
            )
        )
        story.append(Spacer(1, 4 * mm))

    # ----------------------------------------------------------------- one identity, several files
    across = network.get("across_sources") or []
    if across:
        story.append(Paragraph("Identities appearing in more than one source", styles["Heading2"]))
        story.append(
            Paragraph(
                "Each of these was written in several files and resolved to a single identity. This is what allows the "
                "files to be read together at all; it is not, by itself, proof that one person is behind them.",
                styles["BodyText"],
            )
        )
        rows = [[_cell("Identity"), _cell("Type"), _cell("Evidence files")]]
        rows += [[_cell(_shorten(item["label"], 46)), _cell(_network_label(item["type"])), _cell(str(item["sources"]))] for item in across]
        table = Table(rows, colWidths=[80 * mm, 45 * mm, 30 * mm], hAlign="LEFT")
        table.setStyle(_report_table_style())
        story.extend([table, Spacer(1, 4 * mm)])

    # ----------------------------------------------------------------- network position
    if ranked:
        story.append(Paragraph("Network position / review priority, not guilt", styles["Heading2"]))
        story.append(
            Paragraph(
                f"Ranked by {str(ranked[0].get('metric', 'betweenness_centrality')).replace('_', ' ')}, which answers "
                "who connects parts of the network that would otherwise be separate — the investigative question — "
                "rather than who simply appears most often.",
                styles["BodyText"],
            )
        )
        story.append(Spacer(1, 2 * mm))
        for entry in ranked:
            story.append(
                Paragraph(
                    f"<b>#{entry.get('rank')} &nbsp; {_safe(_shorten(entry.get('label'), 52))}</b> "
                    f"<font size=7 color='#8a7d71'>({_network_label(entry.get('entity_type'))} · "
                    f"score {float(entry.get('score', 0)):.3f} · {entry.get('supporting_evidence_count', 0)} evidence file(s))</font>",
                    styles["BodyText"],
                )
            )
            story.append(Paragraph(_safe(entry.get("why")), styles["BodyText"]))
            story.append(Paragraph("<font size=7 color='#6b6258'>" + _safe(entry.get("caveat")) + "</font>", styles["BodyText"]))
            story.append(Spacer(1, 2 * mm))

    # ----------------------------------------------------------------- the fragile links
    if bridges:
        story.append(PageBreak())
        story.append(Paragraph("Relationships to verify first", styles["Heading2"]))
        story.append(
            Paragraph(
                "Each of these is the only path between two parts of this network. They are listed first not because "
                "they are the most incriminating but because they are the most load-bearing: if one is a misreading, "
                "everything it joins comes apart.",
                styles["BodyText"],
            )
        )
        rows = [[_cell("Relationship"), _cell("Stated as"), _cell("Records"), _cell("Sources")]]
        for item in bridges[:12]:
            subject = _shorten((item.get("subject") or {}).get("label"), 30)
            target = _shorten((item.get("object") or {}).get("label"), 30)
            rows.append([
                _cell(f"{subject} — {target}"),
                _cell(", ".join(str(value).replace("_", " ").title() for value in item.get("relation_types") or [])),
                _cell(str(item.get("observations", 0))),
                _cell(str(item.get("supporting_evidence_count", 0))),
            ])
        table = Table(rows, colWidths=[70 * mm, 45 * mm, 20 * mm, 20 * mm], hAlign="LEFT")
        table.setStyle(_report_table_style())
        story.extend([table, Spacer(1, 4 * mm)])

    # ----------------------------------------------------------------- groups
    communities = network.get("communities") or []
    if communities:
        story.append(Paragraph("Connected groups / a pattern, not an organisation", styles["Heading2"]))
        story.append(
            Paragraph(
                "A group below is a set of identities more connected to each other than to the rest of the case. It is "
                "a shape in the evidence gathered so far. It is not a finding that an organisation exists.",
                styles["BodyText"],
            )
        )
        for item in communities:
            members = ", ".join(_shorten((member or {}).get("label"), 28) for member in (item.get("members") or [])[:8])
            story.append(
                Paragraph(
                    f"<b>Group {item.get('community_id')}</b> <font size=7 color='#8a7d71'>({item.get('size', 0)} identities · "
                    f"{item.get('supporting_evidence_count', 0)} evidence file(s))</font><br/>{_safe(members)}",
                    styles["BodyText"],
                )
            )
        story.append(Spacer(1, 4 * mm))

    # ----------------------------------------------------------------- around the incident
    chronology = network.get("chronology") or {}
    story.append(Paragraph("Contact around the declared incident", styles["Heading2"]))
    if not chronology.get("incident_window_declared"):
        story.append(
            Paragraph(
                "No incident window is declared on this case, so recorded contact cannot be placed before or after it. "
                "Setting the incident date on the case enables this reading.",
                styles["BodyText"],
            )
        )
    else:
        placed = chronology.get("contacts_placed") or {}
        story.append(
            Paragraph(
                f"Of the contact this case records, <b>{placed.get('before', 0)}</b> occurred before the declared "
                f"incident window, <b>{placed.get('during', 0)}</b> during it and <b>{placed.get('after', 0)}</b> after."
                + (
                    " Some recorded contact could not be placed at all, because the source never established a time; "
                    "a chronology with that much missing should not be leaned on."
                    if chronology.get("contacts_without_established_time")
                    else ""
                )
                + " Contact before an incident is not evidence of involvement in it.",
                styles["BodyText"],
            )
        )
        pre = network.get("pre_incident") or []
        if pre:
            story.append(Spacer(1, 3 * mm))
            rows = [[_cell("Between"), _cell("Contacts"), _cell("Hours before")]]
            for item in pre:
                pair = item.get("pair") or []
                rows.append([
                    _cell(" — ".join(_shorten(name, 26) for name in pair)),
                    _cell(str(item.get("contacts", 0))),
                    _cell(f"{float(item.get('hours_before', 0)):.1f}"),
                ])
            table = Table(rows, colWidths=[85 * mm, 25 * mm, 30 * mm], hAlign="LEFT")
            table.setStyle(_report_table_style())
            story.extend([table, Spacer(1, 3 * mm)])

    bursts = network.get("bursts") or []
    if bursts:
        story.append(Paragraph("Concentrated communication", styles["Heading2"]))
        rows = [[_cell("Between"), _cell("Contacts"), _cell("Within (minutes)")]]
        for item in bursts:
            pair = item.get("pair") or []
            rows.append([
                _cell(" — ".join(_shorten(name, 26) for name in pair)),
                _cell(str(item.get("contacts", 0))),
                _cell(str(int(item.get("minutes", 0)))),
            ])
        table = Table(rows, colWidths=[85 * mm, 25 * mm, 30 * mm], hAlign="LEFT")
        table.setStyle(_report_table_style())
        story.extend([table, Spacer(1, 3 * mm)])
        story.append(
            Paragraph(
                "<font size=7 color='#6b6258'>A concentration of contact is a pattern worth asking about. It is not a "
                "finding about what was discussed.</font>",
                styles["BodyText"],
            )
        )

    # ----------------------------------------------------------------- the headline claim, measured
    traceability = network.get("traceability") or {}
    story.append(Spacer(1, 4 * mm))
    story.append(Paragraph("Traceability of this network", styles["Heading2"]))
    story.append(
        Paragraph(
            f"<b>{traceability.get('percent', 0)}%</b> of the {traceability.get('total', 0)} relationship observation(s) "
            f"above name both the evidence file they were read from and the exact place inside it "
            f"({traceability.get('traced', 0)} of {traceability.get('total', 0)}). This is enforced when the record is "
            "written, not audited afterwards: a relationship with no source cannot be stored, so this figure is a "
            "property of the system rather than a claim about this case.",
            styles["BodyText"],
        )
    )


def _grounded_field(value: object, basis: str) -> str:
    """Render a field so an inference can never be mistaken for an observation."""
    if value in (None, "", []):
        return "Not established by this source"
    if basis in {"inferred", "unknown"}:
        return f"{value} (inferred — requires verification)"
    return str(value)


def _append_grounded_sections(story: list[object], styles, snapshot: dict) -> None:
    """Render the model-assisted layer separately from deterministic observations."""
    records = snapshot.get("grounded_records") or []
    relations = snapshot.get("candidate_relations") or []
    if not records and not relations:
        return

    bands = Counter(item["band"] for item in records)
    models = sorted({item["model"] for item in records if item["model"]})
    review_count = sum(1 for item in records if item["requires_review"])

    story.extend(
        [
            PageBreak(),
            Paragraph("Source-grounded evidence intelligence", styles["Heading1"]),
            Paragraph(
                "Each row below was read from one evidence item and carries its own basis, confidence "
                "and review state. Values marked <b>inferred</b> are contextual readings, not established "
                "facts; values marked <b>not established</b> were deliberately left empty because the "
                "source does not support them. Nothing here asserts identity, intent or culpability.",
                styles["BodyText"],
            ),
            Spacer(1, 3 * mm),
        ]
    )

    summary = [[
        _cell_lines(len(records), "Grounded records"),
        _cell_lines(bands.get("high", 0), "High confidence"),
        _cell_lines(bands.get("medium", 0) + bands.get("low", 0) + bands.get("unknown", 0), "Medium / low / unknown"),
        _cell_lines(review_count, "Awaiting review"),
    ]]
    summary_table = Table(summary, colWidths=[45 * mm] * 4)
    summary_table.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), PAPER_ALT), ("BOX", (0, 0), (-1, -1), .5, BURGUNDY), ("INNERGRID", (0, 0), (-1, -1), .25, RULE), ("PADDING", (0, 0), (-1, -1), 6)]))
    story.extend([summary_table, Spacer(1, 4 * mm)])

    if models:
        story.extend([
            Paragraph(f"Model-assisted normalization performed by: <b>{_safe(', '.join(models))}</b>. "
                      "Deterministic parser values were never replaced by model output.", styles["BodyText"]),
            Spacer(1, 3 * mm),
        ])

    rows = [[_cell("Source"), _cell("What the source shows"), _cell("Event"), _cell("Sender"), _cell("Receiver"), _cell("Amount"), _cell("Confidence")]]
    for item in records:
        amount = f"{item['currency'] or ''} {item['amount']:,.2f}".strip() if item["amount"] is not None else "Not established"
        confidence = f"{_safe(item['band'])} / {_safe(item['validation_status'])}"
        if item["requires_review"]:
            confidence += " · review required"
        rows.append([
            _cell(item["source"]),
            _cell(item["summary"] or (item["observed_text"] or "")[:300] or "—"),
            _cell(_grounded_field(item["event_type"], item["basis"])),
            _cell(_grounded_field(item["sender"], item["basis"])),
            _cell(_grounded_field(item["receiver"], item["basis"])),
            _cell(amount),
            _cell(confidence),
        ])
    table = Table(rows, colWidths=[26 * mm, 52 * mm, 26 * mm, 26 * mm, 26 * mm, 22 * mm, 24 * mm], repeatRows=1)
    table.setStyle(_report_table_style(header="charcoal"))
    story.extend([table, Spacer(1, 4 * mm)])

    conflicted = [item for item in records if item["conflicts"]]
    if conflicted:
        story.append(Paragraph("Preserved conflicts", styles["Heading2"]))
        story.append(Paragraph(
            "Two readings of the same field disagreed. Both were kept and no automatic resolution was applied.",
            styles["BodyText"],
        ))
        for item in conflicted:
            story.append(Paragraph(f"<b>{_safe(item['source'])}</b> — conflicting: {_safe(', '.join(item['conflicts']))}", styles["BodyText"]))
        story.append(Spacer(1, 3 * mm))

    if relations:
        story.extend([
            Paragraph("Candidate corroborations and contradictions", styles["Heading2"]),
            Paragraph(
                "These are candidate links produced by identifier matching. They remain candidates until a "
                "reviewer confirms them, and they do not establish a relationship between people.",
                styles["BodyText"],
            ),
            Spacer(1, 2 * mm),
        ])
        relation_rows = [[_cell("Type"), _cell("Matched on"), _cell("Basis"), _cell("Confidence"), _cell("Status")]]
        for item in relations[:40]:
            relation_rows.append([
                _cell(item["type"]),
                _cell(", ".join(item["fields"]) or "—"),
                _cell(item["method"]),
                _cell(f"{item['confidence']:.2f}"),
                _cell(item["status"] + (" · review required" if item["requires_review"] else "")),
            ])
        relation_table = Table(relation_rows, colWidths=[30 * mm, 48 * mm, 30 * mm, 26 * mm, 48 * mm], repeatRows=1)
        relation_table.setStyle(_report_table_style(header="burgundy"))
        story.extend([relation_table, Spacer(1, 4 * mm)])

    unresolved = [item for item in records if not item["sender"] or not item["receiver"]]
    if unresolved:
        story.append(Paragraph(
            f"<b>{len(unresolved)} of {len(records)}</b> grounded records do not establish both parties. "
            "Recipient or sender identity was left unset rather than inferred.",
            styles["BodyText"],
        ))


# Four readers, four documents. One report serving all of them served none of them well: the
# briefing a station officer needs was buried on page nine, and a court was handed network rankings
# mixed in with the evidence register as though both were the same kind of statement.
REPORT_PROFILES = ("case_file", "briefing", "court_annexure", "handover")

PROFILE_TITLES = {
    "case_file": "Criminal Network Analysis Report",
    "briefing": "Investigation Briefing",
    "court_annexure": "Evidence Annexure and Integrity Record",
    "handover": "Case Handover Pack",
}


def _finalise(db: Session, report: Report, output: Path, story: list[object], case: dict) -> dict:
    """Render the story, seal it, and record where it went. Every profile ends here."""
    _apply_reference_table_rhythm(story)
    SimpleDocTemplate(
        str(output),
        pagesize=A4,
        rightMargin=14 * mm,
        leftMargin=14 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
        title=f"DRISHYAM report {case['number']}",
    ).build(story, onFirstPage=_draw_report_frame, onLaterPages=_draw_report_frame)

    report.status = ProcessingState.SUCCEEDED
    report.storage_key = report_storage_key(str(output.relative_to(settings.generated_reports_root)))
    report.generated_at = utcnow()
    report.failure_reason = None
    receipt = create_receipt(db, report, output)
    publish_private_file(output, report.storage_key, content_type="application/pdf")
    publish_private_file(
        output.parent / "trustify" / f"report-v{report.version}-manifest.json",
        receipt.manifest_storage_key,
        content_type="application/json",
    )
    db.commit()
    return {
        "report_id": report.id,
        "path": str(output),
        "status": report.status.value,
        "trustify": {"verification_id": receipt.verification_id, "manifest_hash": receipt.manifest_hash},
    }


def _profile_cover(styles, snapshot: dict, profile: str) -> list[object]:
    case = snapshot["case"]
    return [
        Spacer(1, 38 * mm),
        Paragraph("DRISHYAM", styles["Cover"]),
        Paragraph(
            PROFILE_TITLES.get(profile, "Report"),
            ParagraphStyle(name="ProfileSub", parent=styles["Heading2"], alignment=TA_CENTER, textColor=INK),
        ),
        Spacer(1, 4 * mm),
        Paragraph(
            f"<para alignment='center'>{_safe(case['number'])} &nbsp;·&nbsp; {_safe(case['title'])}<br/>"
            f"<font size=7 color='#6b6258'>Generated {_display_timestamp(utcnow())}</font></para>",
            styles["BodyText"],
        ),
        PageBreak(),
    ]


def _build_briefing(db: Session, report: Report, styles, snapshot: dict, findings: list[dict]) -> list[object]:
    """What a station officer needs before deciding where to put people.

    Short on purpose. Everything here is in the full case file too; the value of this document is
    what it leaves out.
    """
    network = snapshot.get("network") or {}
    overview = network.get("overview") or {}
    ranked = (network.get("ranked") or [])[:3]
    bridges = network.get("bridges") or []

    story = _profile_cover(styles, snapshot, "briefing")
    story.append(Paragraph("What this case records", styles["Heading1"]))
    story.append(
        Paragraph(
            f"{len(snapshot['evidence'])} evidence file(s) have been read. They state "
            f"<b>{network.get('relation_total', 0)}</b> relationship observation(s) between "
            f"<b>{overview.get('entities', 0)}</b> resolved identities, in "
            f"<b>{overview.get('communities', 0)}</b> connected group(s). "
            f"<b>{len(bridges)}</b> of those relationships are the only link between two parts of the network.",
            styles["BodyText"],
        )
    )
    classes = network.get("classes") or []
    if classes:
        story.append(Spacer(1, 2 * mm))
        story.append(
            Paragraph(
                ", ".join(
                    f"<b>{count}</b> {(singular if count == 1 else plural).lower()}"
                    for plural, singular, count in classes
                )
                + ".",
                styles["BodyText"],
            )
        )

    if ranked:
        story.append(Spacer(1, 4 * mm))
        story.append(Paragraph("Where to look first", styles["Heading2"]))
        for entry in ranked:
            story.append(
                Paragraph(
                    f"<b>{_safe(_shorten(entry.get('label'), 46))}</b> "
                    f"<font size=7 color='#8a7d71'>({_network_label(entry.get('entity_type'))} · "
                    f"{entry.get('supporting_evidence_count', 0)} evidence file(s))</font><br/>{_safe(entry.get('why'))}",
                    styles["BodyText"],
                )
            )
            story.append(Spacer(1, 2 * mm))
        story.append(
            Paragraph(
                "<font size=7 color='#6b6258'>Network position indicates review priority. It is not an indication of "
                "guilt, and it describes the evidence gathered so far rather than the world.</font>",
                styles["BodyText"],
            )
        )

    fragile = [item for item in findings if item["load_bearing"]][:5]
    if fragile:
        story.append(Spacer(1, 4 * mm))
        story.append(Paragraph("Verify these before acting on anything", styles["Heading2"]))
        for item in fragile:
            source = item["file"] + (f" — {item['place']}" if item["place"] else "")
            story.append(Paragraph(f"<b>{item['id']}</b> &nbsp; {_safe(item['statement'])} <font size=7 color='#8a7d71'>({_safe(_shorten(source, 50))})</font>", styles["BodyText"]))
        story.append(
            Paragraph(
                "<font size=7 color='#6b6258'>Each is the only link between two parts of the network. If one is a "
                "misreading, everything it joins comes apart.</font>",
                styles["BodyText"],
            )
        )

    story.append(Spacer(1, 4 * mm))
    story.append(Paragraph("What this case does not establish", styles["Heading2"]))
    gaps = []
    chronology = network.get("chronology") or {}
    if not chronology.get("incident_window_declared"):
        gaps.append("No incident window is declared, so contact cannot be placed before or after the incident.")
    unreviewed = [item for item in findings if "machine" in item["verification"]]
    if unreviewed:
        gaps.append(f"{len(unreviewed)} of {len(findings)} finding(s) have not yet been confirmed by a person.")
    if snapshot.get("alerts"):
        gaps.append(f"{len(snapshot['alerts'])} review lead(s) are open and are reasons to read evidence, not findings.")
    gaps.append("Nothing in this document establishes identity, intent or responsibility.")
    for gap in gaps:
        story.append(Paragraph("• " + gap, styles["BodyText"]))
    return story


def _build_court_annexure(db: Session, report: Report, styles, snapshot: dict, evidence_records: list) -> list[object]:
    """The evidence and how it was handled. No interpretation, by design.

    A ranking, an alert and a network position are readings this system produced. They belong in an
    investigator's file and not in an annexure, where their presence beside a hash invites them to
    be read as the same kind of statement. What is here is what can be attested to: which files
    exist, what they hash to, when they arrived, what was run over them, and who touched them.
    """
    story = _profile_cover(styles, snapshot, "court_annexure")
    story.append(Paragraph("Scope of this annexure", styles["Heading1"]))
    story.append(
        Paragraph(
            "This annexure records the electronic evidence held in this case and the handling of it. It contains no "
            "analysis, no ranking and no finding. Statements about what the evidence means are made in the case file "
            "and are not repeated here, so that nothing in this document can be read as an assertion by the system "
            "about any person.",
            styles["BodyText"],
        )
    )

    story.append(Spacer(1, 4 * mm))
    story.append(Paragraph("Evidence register", styles["Heading2"]))
    rows = [[_cell("#"), _cell("File"), _cell("SHA-256"), _cell("Received"), _cell("State")]]
    for index, item in enumerate(evidence_records, start=1):
        rows.append([
            _cell(str(index)),
            _cell(_shorten(item.original_name, 40)),
            _cell(_shorten(item.sha256 or "not recorded", 34)),
            _cell(_display_timestamp(item.uploaded_at)),
            _cell(str(item.status.value).replace("_", " ")),
        ])
    if len(rows) == 1:
        rows.append([_cell("—"), _cell("No evidence is held in this case."), _cell("—"), _cell("—"), _cell("—")])
    table = Table(rows, colWidths=[10 * mm, 55 * mm, 58 * mm, 32 * mm, 27 * mm], repeatRows=1)
    table.setStyle(_report_table_style())
    story.extend([table, Spacer(1, 3 * mm)])
    story.append(
        Paragraph(
            "<font size=7 color='#6b6258'>Each hash is of the file exactly as received. A file whose hash differs from "
            "the value recorded here is not the file this case was built on.</font>",
            styles["BodyText"],
        )
    )

    # A processing run belongs to a file, not to a case, so the register above is what scopes it.
    evidence_ids = [item.id for item in evidence_records]
    runs = (
        db.scalars(
            select(ProcessingRun).where(ProcessingRun.evidence_id.in_(evidence_ids)).order_by(ProcessingRun.created_at)
        ).all()
        if evidence_ids
        else []
    )
    named = {item.id: item.original_name for item in evidence_records}
    if runs:
        story.append(PageBreak())
        story.append(Paragraph("Processing record", styles["Heading2"]))
        story.append(
            Paragraph(
                "What was run over this evidence, when, and with what outcome. Listed so that the handling of the "
                "material can be examined independently of any conclusion drawn from it.",
                styles["BodyText"],
            )
        )
        rows = [[_cell("File"), _cell("Stage"), _cell("Started"), _cell("Completed"), _cell("Outcome")]]
        for item in runs[:60]:
            rows.append([
                _cell(_shorten(named.get(item.evidence_id, "—"), 26)),
                _cell(str(item.pipeline_stage)),
                _cell(_display_timestamp(item.started_at)),
                _cell(_display_timestamp(item.completed_at)),
                _cell(str(item.state.value)),
            ])
        table = Table(rows, colWidths=[46 * mm, 38 * mm, 34 * mm, 34 * mm, 30 * mm], repeatRows=1)
        table.setStyle(_report_table_style(header="slate"))
        story.extend([table, Spacer(1, 3 * mm)])

    entries = db.scalars(
        select(AuditLog).where(AuditLog.case_id == report.case_id).order_by(AuditLog.created_at.desc())
    ).all()
    story.append(PageBreak())
    story.append(Paragraph("Access and handling record", styles["Heading2"]))
    story.append(
        Paragraph(
            f"{len(entries)} recorded action(s) against this case. The most recent are listed. The record is "
            "append-only: an action taken cannot be removed from it.",
            styles["BodyText"],
        )
    )
    rows = [[_cell("When"), _cell("Action"), _cell("Object"), _cell("Outcome")]]
    for item in entries[:60]:
        rows.append([
            _cell(_display_timestamp(item.created_at)),
            _cell(str(item.action)),
            _cell(_shorten(f"{item.object_type or ''} {item.object_id or ''}".strip(), 34)),
            _cell(str(item.outcome or "")),
        ])
    if len(rows) == 1:
        rows.append([_cell("—"), _cell("No action has been recorded against this case."), _cell("—"), _cell("—")])
    table = Table(rows, colWidths=[36 * mm, 58 * mm, 56 * mm, 32 * mm], repeatRows=1)
    table.setStyle(_report_table_style(header="slate"))
    story.extend([table, Spacer(1, 4 * mm)])
    story.append(
        Paragraph(
            "This annexure and its manifest are sealed together. The verification identifier issued with this document "
            "can be used to confirm that neither has been altered since it was generated.",
            styles["BodyText"],
        )
    )
    return story


def _build_handover(db: Session, report: Report, styles, snapshot: dict, findings: list[dict]) -> list[object]:
    """What the next officer needs in order to pick this case up.

    The question this answers is not "what does the case say" but "where was it left" -- what has
    been checked, what has not, and what the last person had not got to.
    """
    network = snapshot.get("network") or {}
    story = _profile_cover(styles, snapshot, "handover")

    story.append(Paragraph("State of this case", styles["Heading1"]))
    confirmed = [item for item in findings if "machine" not in item["verification"]]
    story.append(
        Paragraph(
            f"{len(snapshot['evidence'])} evidence file(s) read. {len(findings)} numbered finding(s) recorded, of which "
            f"<b>{len(confirmed)}</b> have been confirmed by a person and <b>{len(findings) - len(confirmed)}</b> have "
            f"not. {len(snapshot.get('alerts') or [])} review lead(s) are open. Case status: "
            f"{_safe(snapshot['case']['status'])}.",
            styles["BodyText"],
        )
    )

    story.append(Spacer(1, 4 * mm))
    story.append(Paragraph("Not yet checked by a person", styles["Heading2"]))
    outstanding = [item for item in findings if "machine" in item["verification"]]
    if not outstanding:
        story.append(Paragraph("Every recorded finding has been reviewed.", styles["BodyText"]))
    else:
        story.append(
            Paragraph(
                "These are machine readings that no reviewer has confirmed or rejected. They are the work in front of "
                "you, in the order in which being wrong matters most.",
                styles["BodyText"],
            )
        )
        _append_numbered_findings(story, styles, outstanding, limit=25)

    story.append(Spacer(1, 4 * mm))
    story.append(Paragraph("Open review leads", styles["Heading2"]))
    alerts = snapshot.get("alerts") or []
    if not alerts:
        story.append(Paragraph("No review lead is open against this case.", styles["BodyText"]))
    else:
        rows = [[_cell("Severity"), _cell("Lead"), _cell("Status")]]
        for item in alerts[:25]:
            rows.append([_cell(str(item["severity"]).upper()), _cell(_shorten(item["explanation"], 120)), _cell(str(item["status"]))])
        table = Table(rows, colWidths=[24 * mm, 128 * mm, 30 * mm], repeatRows=1)
        table.setStyle(_report_table_style(header="slate"))
        story.extend([table, Spacer(1, 2 * mm)])
        story.append(
            Paragraph(
                "<font size=7 color='#6b6258'>A lead is a reason to read the named evidence. It is never a finding.</font>",
                styles["BodyText"],
            )
        )

    story.append(Spacer(1, 4 * mm))
    story.append(Paragraph("What is missing", styles["Heading2"]))
    chronology = network.get("chronology") or {}
    missing = []
    if not chronology.get("incident_window_declared"):
        missing.append("No incident window is set on this case, so no contact can be placed relative to the incident. Setting the incident date enables that reading.")
    isolated = (network.get("overview") or {}).get("isolated_entities", 0)
    if isolated:
        missing.append(f"{isolated} resolved identit(ies) are connected to nothing else in the case. Either the evidence linking them has not arrived, or they are incidental.")
    if not missing:
        missing.append("Nothing structural is missing from this case as it stands.")
    for item in missing:
        story.append(Paragraph("• " + item, styles["BodyText"]))
    return story


def generate_report(report_id: str) -> dict:
    """Render a fresh PDF from the report’s current snapshot—never from a static document template alone."""
    from app.core.db import SessionLocal

    db = SessionLocal()
    try:
        report = db.get(Report, report_id)
        if not report:
            raise ValueError("Report record not found")
        report.status = ProcessingState.RUNNING
        db.commit()
        snapshot = _snapshot(db, report.case_id)
        report.review_snapshot_hash = hashlib.sha256(json.dumps(snapshot, sort_keys=True, default=str).encode("utf-8")).hexdigest()
        case_record = db.get(Case, report.case_id)
        if not case_record:
            raise ValueError("Case not found")
        report_dir = settings.generated_reports_root / report.case_id
        report_dir.mkdir(parents=True, exist_ok=True)
        output = report_dir / f"report-v{report.version}.pdf"
        styles = getSampleStyleSheet()
        styles["BodyText"].fontName = "Helvetica"
        styles["BodyText"].fontSize = 8.5
        styles["BodyText"].leading = 12.2
        styles["BodyText"].textColor = INK
        styles["Heading1"].fontName = "Times-Bold"
        styles["Heading1"].fontSize = 15
        styles["Heading1"].leading = 18
        styles["Heading1"].textColor = BURGUNDY
        styles["Heading1"].spaceBefore = 3 * mm
        styles["Heading1"].spaceAfter = 3 * mm
        styles["Heading2"].fontName = "Helvetica-Bold"
        styles["Heading2"].fontSize = 10.5
        styles["Heading2"].leading = 13
        styles["Heading2"].textColor = BURGUNDY
        styles["Heading2"].spaceBefore = 3 * mm
        styles["Heading2"].spaceAfter = 2.2 * mm
        styles.add(ParagraphStyle(name="Cover", parent=styles["Title"], fontName="Times-Bold", fontSize=24, leading=28, textColor=BURGUNDY, alignment=TA_CENTER, spaceAfter=3 * mm))
        styles.add(ParagraphStyle(name="Meta", parent=styles["BodyText"], fontName="Courier", fontSize=6.7, leading=8.4, textColor=colors.HexColor("#5d5852")))
        styles.add(ParagraphStyle(name="Callout", parent=styles["BodyText"], fontSize=8.7, leading=12.5, textColor=INK, borderColor=BURGUNDY, borderWidth=.55, borderPadding=8, backColor=PAPER_ALT))
        styles.add(ParagraphStyle(name="SynopsisHeading", parent=styles["Heading1"], leftIndent=4 * mm, rightIndent=4 * mm, spaceBefore=4 * mm, spaceAfter=2.4 * mm, keepWithNext=True))
        styles.add(ParagraphStyle(name="NarrativeHeading", parent=styles["Heading2"], leftIndent=4 * mm, rightIndent=4 * mm, spaceBefore=4 * mm, spaceAfter=2.4 * mm, keepWithNext=True))
        styles.add(ParagraphStyle(name="NarrativeCallout", parent=styles["Callout"], leftIndent=4 * mm, rightIndent=4 * mm, borderPadding=9.5, spaceAfter=5.5 * mm))
        evidence_records = db.scalars(select(EvidenceFile).where(EvidenceFile.case_id == report.case_id).order_by(EvidenceFile.uploaded_at)).all()
        entity_records = db.scalars(select(Entity).where(Entity.case_id == report.case_id)).all()
        transaction_records = db.scalars(select(Transaction).where(Transaction.case_id == report.case_id).order_by(Transaction.occurred_at)).all()
        alert_records = db.scalars(select(Alert).where(Alert.case_id == report.case_id)).all()
        claim_records = db.scalars(select(Claim).where(Claim.case_id == report.case_id).order_by(Claim.created_at)).all()
        contradiction_records = db.scalars(select(Contradiction).where(Contradiction.case_id == report.case_id).order_by(Contradiction.created_at)).all()
        # A profile other than the full case file is a different document for a different reader,
        # not a filtered version of this one, so it is written rather than trimmed.
        if report.profile in {"briefing", "court_annexure", "handover"}:
            findings = _numbered_findings(db, report.case_id, snapshot)
            if report.profile == "briefing":
                profile_story = _build_briefing(db, report, styles, snapshot, findings)
            elif report.profile == "handover":
                profile_story = _build_handover(db, report, styles, snapshot, findings)
            else:
                profile_story = _build_court_annexure(db, report, styles, snapshot, evidence_records)
            return _finalise(db, report, output, profile_story, snapshot["case"])

        entities_by_type = Counter(label for item in entity_records if (label := _entity_display(item.entity_type)))
        alerts_by_severity = Counter(item.severity.value for item in alert_records)
        entity_chart = _render_bar_chart(output.parent / f"{output.stem}-entities.png", "Extracted entities by type", list(entities_by_type), list(entities_by_type.values()), "#59636a", "Entities")
        alert_donut = _render_donut(output.parent / f"{output.stem}-alerts.png", "Alert severity distribution", alerts_by_severity)
        transaction_chart = _render_bar_chart(output.parent / f"{output.stem}-transactions.png", "Transaction amount by event / time", [(item.reference_id or (_display_timestamp(item.occurred_at) if item.occurred_at else "Unknown"))[-18:] for item in transaction_records], [float(item.amount) for item in transaction_records], "#b17a2d", "INR")
        story = [Spacer(1, 42 * mm), Paragraph("DRISHYAM", styles["Cover"]), Paragraph("Criminal Network Analysis Report", ParagraphStyle(name="CoverSub", parent=styles["Heading2"], alignment=TA_CENTER, textColor=CHARCOAL, spaceAfter=10 * mm)), Spacer(1, 7 * mm)]
        case = snapshot["case"]
        cover = Table([
            [_cell("Case ID"), _cell("Crime type"), _cell("Priority"), _cell("Investigation status")],
            [_cell(case["number"]), _cell(case["crime_type"].replace("_", " ")), _cell(case["priority"].upper()), _cell(case["status"].replace("_", " "))],
            [_cell("Case title"), _cell("FIR / record reference"), _cell("Report version"), _cell("Review workflow")],
            [_cell(case["title"]), _cell(case["fir_number"] or "Not recorded"), _cell(f"v{report.version}"), _cell("Investigator review workflow")],
        ], colWidths=[45.5 * mm] * 4)
        cover.setStyle(_report_table_style(header="charcoal", padded=4.5, alternate=False))
        story.extend([cover, Spacer(1, 8 * mm), Paragraph("Case synopsis", styles["SynopsisHeading"]), Spacer(1, 3.5 * mm), Paragraph(_safe(_case_synopsis(db.get(Case, report.case_id))), styles["NarrativeCallout"]), Paragraph("Investigation summary", styles["Heading2"]), Paragraph("The following pages present the evidence, timeline, transactions, alerts, and review notes for this case. Each finding should be checked against its listed source before a decision is made.", styles["BodyText"]), Spacer(1, 8 * mm), Paragraph("TRACEABLE · VERIFIABLE · REVIEWABLE", ParagraphStyle(name="Tagline", parent=styles["BodyText"], alignment=TA_CENTER, textColor=CHARCOAL, fontName="Helvetica-Bold", fontSize=7.5)), PageBreak()])
        report_identification = [[_cell("Field"), _cell("Value"), _cell("Field"), _cell("Value")], [_cell("Report ID"), _cell(report.id), _cell("Case ID"), _cell(case["number"])], [_cell("Report version"), _cell(f"v{report.version}"), _cell("Snapshot record"), _cell("Current case-scoped backend snapshot")], [_cell("Generated timestamp"), _cell(_display_timestamp(utcnow())), _cell("Processing version"), _cell("DRISHYAM evidence pipeline")], [_cell("Reviewer / owner"), _cell("Authorized investigator workflow"), _cell("Report integrity"), _cell("Verification receipt generated on completion")]]
        identification_table = Table(report_identification, colWidths=[32 * mm, 59 * mm, 34 * mm, 57 * mm], repeatRows=1)
        identification_table.setStyle(_report_table_style(header="burgundy", padded=3.5))
        story.extend([Paragraph("Report identification", styles["Heading1"]), identification_table, Spacer(1, 6 * mm), Paragraph("Executive summary", styles["Heading1"]), Paragraph("This summary shows the evidence, timeline, transactions, alerts, and review decisions currently recorded for the case.", styles["BodyText"]), Spacer(1, 3 * mm)])
        metrics = [
            [_cell("Evidence\n" + str(len(snapshot["evidence"]))), _cell("Entities\n" + str(db.scalar(select(func.count(Entity.id)).where(Entity.case_id == report.case_id)) or 0)), _cell("Timeline events\n" + str(len(snapshot["events"]))), _cell("Transactions\n" + str(len(snapshot["transactions"]))), _cell("Reviewable alerts\n" + str(len(snapshot["alerts"])))],
            [_cell("Claims\n" + str(len(claim_records))), _cell("Contradictions\n" + str(len(contradiction_records))), _cell("Review decisions\n" + str(len(snapshot["reviews"]))), _cell("Open alerts\n" + str(sum(1 for item in alert_records if item.status.value != "reviewed"))), _cell("Report version\n" + str(report.version))],
        ]
        metric_table = Table(metrics, colWidths=[36 * mm] * 5)
        metric_table.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f7efe5")), ("BOX", (0, 0), (-1, -1), .5, colors.HexColor("#7b1e2b")), ("INNERGRID", (0, 0), (-1, -1), .25, colors.HexColor("#d7c7b7")), ("PADDING", (0, 0), (-1, -1), 6)]))
        story.extend([Paragraph("Integrity and executive summary", styles["Heading1"]), Paragraph(f"Case { _safe(case['number']) } — { _safe(case['title']) }", styles["Heading2"]), metric_table, Spacer(1, 5 * mm), Paragraph("Report snapshot and verification", styles["Heading2"]), Paragraph(f"Snapshot SHA-256: {report.review_snapshot_hash}<br/>Report version: {report.version} · Generator: DRISHYAM Trustify v1 · This record presents source-linked leads and review state; it does not determine guilt or legal admissibility.", styles["Meta"]), Spacer(1, 5 * mm)])
        story.append(Paragraph("Report scope", styles["Heading2"]))
        evidence_table = [[_cell("Evidence"), _cell("Record reference"), _cell("Pipeline state")]] + [[_cell(item["name"]), _cell(item["hash"]), _cell(item["status"])] for item in snapshot["evidence"]]
        table = Table(evidence_table, colWidths=[52 * mm, 100 * mm, 30 * mm], repeatRows=1)
        table.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#7b1e2b")), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white), ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#c9c9c9")), ("VALIGN", (0, 0), (-1, -1), "TOP"), ("PADDING", (0, 0), (-1, -1), 5)]))
        story.extend([table])
        story.extend([PageBreak(), Paragraph("Entity and alert analytics", styles["Heading1"])])
        if entity_chart:
            story.append(Image(str(entity_chart), width=178 * mm, height=84 * mm))
        if alert_donut:
            story.extend([Spacer(1, 3 * mm), Image(str(alert_donut), width=100 * mm, height=86 * mm)])
        known_events = [item for item in snapshot["events"] if item["time"]]
        # An event with a clock reading but no date cannot be placed in the chronology, yet the
        # reading itself is real and belongs in the report rather than being flattened into
        # "Time not established" alongside records that carry no time at all.
        undated = [item for item in snapshot["events"] if not item["time"]]
        partial_events = [item for item in undated if _event_timestamp_parts(item)]
        unknown_events = [item for item in undated if not _event_timestamp_parts(item)]
        story.extend([PageBreak(), Paragraph("Investigation timeline", styles["Heading1"]), Paragraph("Chronology established", styles["Heading2"])])
        overview = [[_cell("Time"), _cell("Event type"), _cell("Review state")]] + [[_event_timestamp_cell(item), _cell(item["type"]), _cell(item["review"])] for item in known_events[:10]]
        overview_table = Table(overview, colWidths=[42 * mm, 94 * mm, 46 * mm], repeatRows=1)
        overview_table.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#7b1e2b")), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white), ("GRID", (0, 0), (-1, -1), .25, colors.HexColor("#c9c9c9")), ("PADDING", (0, 0), (-1, -1), 4)]))
        story.extend([overview_table, Spacer(1, 5 * mm), Paragraph("Detailed source-linked chronology", styles["Heading2"])])
        for item in known_events[:80]:
            time_label = _display_event_timestamp(item)
            story.append(Paragraph(f"<b>{_safe(time_label)}</b> — {_safe(item['type'])} ({_safe(item['review'])}): {_safe(item['description'])}", styles["BodyText"]))
            story.append(Spacer(1, 1.5 * mm))
        if partial_events:
            story.extend([Spacer(1, 4 * mm), Paragraph("Time of day observed, date not established", styles["Heading2"]), Paragraph("The source shows a clock reading but never states which day it belongs to, so these records are not placed in the chronology above.", styles["BodyText"])])
            for item in partial_events:
                story.append(Paragraph(f"<b>{_safe(_display_event_timestamp(item))}</b> — {_safe(item['type'])} ({_safe(item['review'])}): {_safe(_shorten(item['description'], 400))}", styles["BodyText"]))
                story.append(Spacer(1, 1.5 * mm))
        if unknown_events:
            story.extend([PageBreak(), Paragraph("Time not established", styles["Heading1"]), Paragraph("The following source-linked records are retained but are not presented as exact chronology.", styles["BodyText"])])
            for item in unknown_events:
                story.append(Paragraph(f"<b>{_safe(item['type'])}</b> ({_safe(item['review'])}): {_safe(_shorten(item['description'], 400))}", styles["BodyText"]))
                story.append(Spacer(1, 1.5 * mm))
        graph_image, graph_metrics = _render_connection_graph(db, report.case_id, output)
        lineage_metrics = build_case_graph(db, report.case_id)["metrics"]
        graph_metrics = {**lineage_metrics, **graph_metrics}
        if graph_image:
            graph_strip = [[_cell_lines(f"{graph_metrics['connected_evidence']} of {graph_metrics['evidence_count']}", "Files connected"), _cell_lines(graph_metrics["bridge_count"], "Shared identifiers"), _cell_lines(graph_metrics["isolated_count"], "Files linked to nothing")]]
            graph_strip_table = Table(graph_strip, colWidths=[59 * mm] * 3)
            graph_strip_table.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f7efe5")), ("BOX", (0, 0), (-1, -1), .5, colors.HexColor("#7b1e2b")), ("INNERGRID", (0, 0), (-1, -1), .25, colors.HexColor("#d7c7b7")), ("PADDING", (0, 0), (-1, -1), 6)]))
            story.extend([PageBreak(), Paragraph("Entity relationship graph", styles["Heading1"]), Paragraph("Each line joins an evidence file to a value found inside it. Only values that appear in more than one file are drawn, because only those connect anything. A shared identifier links the files; it does not by itself establish that the same person is behind them.", styles["BodyText"]), Spacer(1, 3 * mm), graph_strip_table, Spacer(1, 3 * mm), Image(str(graph_image), width=178 * mm, height=104 * mm), Paragraph("Line weight and colour show how specific the shared value is: a transaction reference carried by three files is strong, a shared name is weak. Dashed lines are inferred candidates, not exact matches. The register that follows lists the underlying source-linked relationships in full.", styles["BodyText"])])
        # The graph shows the links; this says what they are in words. Separating them meant the
        # picture arrived on one page and its explanation on another.
        _append_connection_section(story, styles, snapshot)

        # The connection section says which files share a value. This says what network those
        # shared values describe -- who is in it, who holds it together, and what none of it
        # establishes. It was written after this report was, and until now the report described a
        # cyber-fraud case that this product had stopped being.
        _append_network_sections(story, styles, snapshot)

        # "Documented amount" read as a loss figure, which is not what the arithmetic produces. The
        # sum counts a balance quoted in a message beside a payment recorded on a receipt, and counts
        # the same payment twice when two files describe it. The figure is still worth showing — it
        # bounds what the evidence talks about — but it is labelled as what it is, and the caveat
        # below the strip says so in words rather than leaving the reader to assume.
        #
        # Totalling across currencies would state a sum nobody can act on, so the strip names the
        # currency only when the case has exactly one.
        currencies = {(item.currency or "INR") for item in transaction_records}
        total_currency = currencies.pop() if len(currencies) == 1 else None
        currencies.clear()
        total_amount = sum(float(item.amount) for item in transaction_records)
        sender_count = len({item.sender_value for item in transaction_records if item.sender_value})
        receiver_count = len({item.receiver_value for item in transaction_records if item.receiver_value})
        unresolved = sum(1 for item in transaction_records if not item.sender_value or not item.receiver_value)
        txn_strip = [[_cell_lines(len(transaction_records), "Transactions"), _cell_lines(f"{total_currency} {total_amount:,.0f}" if total_currency else "Mixed currencies", "Sum of figures read"), _cell_lines(sender_count, "Distinct senders"), _cell_lines(receiver_count, "Distinct receivers"), _cell_lines(unresolved, "Unresolved parties")]]
        story.extend([PageBreak(), Paragraph("Transaction trail", styles["Heading1"]), Table(txn_strip, colWidths=[36 * mm] * 5, style=[("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f7efe5")), ("BOX", (0, 0), (-1, -1), .5, colors.HexColor("#7b1e2b")), ("INNERGRID", (0, 0), (-1, -1), .25, colors.HexColor("#d7c7b7")), ("PADDING", (0, 0), (-1, -1), 6)]), Spacer(1, 5 * mm)])
        balances = [item for item in snapshot["grounded_records"] if item.get("amount_role") == "balance" and item["amount"] is not None]
        story.append(
            Paragraph(
                "The sum above adds the figures in this trail exactly as they were read. Balances are "
                "excluded and listed separately below, but a sum demanded and the payment that answered "
                "it are both counted, and one payment described in two files is counted twice. This is "
                "not a loss total; each row should be checked against its source before it is relied on.",
                styles["BodyText"],
            )
        )
        story.append(Spacer(1, 3 * mm))
        txn_table = [[_cell("Time"), _cell("Amount"), _cell("Sender"), _cell("Receiver"), _cell("Reference")]] + [[(_timestamp_cell(item["time"]) if item["time"] else _cell("Unknown")), _cell(f"{item['currency']} {item['amount']:,.2f}"), _cell(item["sender"] or "Not extracted"), _cell(item["receiver"] or "Not extracted"), _cell(item["reference"] or "Not extracted")] for item in snapshot["transactions"]]
        txn = Table(txn_table, colWidths=[38 * mm, 30 * mm, 40 * mm, 40 * mm, 35 * mm], repeatRows=1)
        txn.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#3d4952")), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white), ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#c9c9c9")), ("VALIGN", (0, 0), (-1, -1), "TOP"), ("PADDING", (0, 0), (-1, -1), 4)]))
        story.append(txn)
        story.append(Spacer(1, 5 * mm))
        if balances:
            # These figures were read from the evidence but describe a position, not a transfer, so
            # they are listed apart from the trail rather than dropped or counted as payments.
            balance_rows = [[_cell("Source"), _cell("Figure"), _cell("Quoted as")]]
            balance_rows += [
                [
                    _cell(item["source"]),
                    _cell(f"{item['currency'] or ''} {item['amount']:,.2f}".strip()),
                    _cell(_shorten(item["summary"] or item["observed_text"], 150)),
                ]
                for item in balances
            ]
            balance_table = Table(balance_rows, colWidths=[52 * mm, 32 * mm, 99 * mm], repeatRows=1)
            balance_table.setStyle(_report_table_style(header="charcoal"))
            story.extend([
                Paragraph("Balances quoted in the evidence", styles["Heading2"]),
                Paragraph(
                    "A balance states what an account was said to hold. It is not a payment and is not "
                    "included in the transaction trail above, because nothing in the evidence shows this "
                    "money moving.",
                    styles["BodyText"],
                ),
                Spacer(1, 2 * mm),
                balance_table,
                Spacer(1, 5 * mm),
            ])
        if transaction_chart:
            story.append(Image(str(transaction_chart), width=178 * mm, height=78 * mm))
        # Where every figure above came from, with its quote, basis and confidence. This is the part
        # a reviewer checks the rest of the report against, so it comes before the housekeeping.
        _append_grounded_sections(story, styles, snapshot)

        # An empty finding is still a finding, but it does not need a page of zeros and a table of
        # em-dashes to say so. Alerts, claims and contradictions now share one page, and each part
        # shrinks to a sentence when the case has nothing of that kind recorded.
        story.extend([PageBreak(), Paragraph("Alerts, claims and contradictions", styles["Heading1"])])
        if alert_records:
            story.extend([Paragraph("Rule-based alerts", styles["Heading2"]), Paragraph("Alerts are reviewable rule-based leads, not a conclusion about intent, identity, truthfulness or culpability.", styles["BodyText"])])
            alert_summary = [[_cell_lines(len(alert_records), "Total alerts"), _cell_lines(sum(1 for item in alert_records if item.status.value == "reviewed"), "Reviewed"), _cell_lines(sum(1 for item in alert_records if item.status.value == "open"), "Open"), _cell_lines(sum(1 for item in alert_records if item.severity.value in {"high", "critical"}), "High / critical")]]
            alert_summary_table = Table(alert_summary, colWidths=[45 * mm] * 4)
            alert_summary_table.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f7efe5")), ("BOX", (0, 0), (-1, -1), .5, colors.HexColor("#7b1e2b")), ("INNERGRID", (0, 0), (-1, -1), .25, colors.HexColor("#d7c7b7")), ("PADDING", (0, 0), (-1, -1), 6)]))
            story.extend([alert_summary_table, Spacer(1, 5 * mm)])
            for item in snapshot["alerts"]:
                story.append(Paragraph(f"<b>{_safe(item['severity']).upper()} · {_safe(item['rule'])} · {_safe(item['status'])}</b><br/>{_safe(item['explanation'])}", styles["BodyText"]))
                story.append(Spacer(1, 2 * mm))
        else:
            story.append(Paragraph("No rule-based alert was raised against this case snapshot.", styles["BodyText"]))
        if claim_records or contradiction_records:
            story.extend([Spacer(1, 4 * mm), Paragraph("Claims and contradictions", styles["Heading2"]), Paragraph("This report preserves source-linked patterns and review states. Multiple files are not automatically treated as independent sources; no corroboration or contradiction is asserted unless the backend has explicitly produced that relationship.", styles["BodyText"])])
            claim_rows = [[_cell("Claim type"), _cell("Statement"), _cell("Evidence state")]] + [[_cell(item.claim_type), _cell(item.statement), _cell(item.status.value)] for item in claim_records]
            if len(claim_rows) == 1:
                claim_rows.append([_cell("—"), _cell("No structured claim has been recorded for this case snapshot."), _cell("—")])
            claim_table = Table(claim_rows, colWidths=[34 * mm, 112 * mm, 36 * mm], repeatRows=1)
            claim_table.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#7b1e2b")), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white), ("GRID", (0, 0), (-1, -1), .25, colors.HexColor("#c9c9c9")), ("VALIGN", (0, 0), (-1, -1), "TOP"), ("PADDING", (0, 0), (-1, -1), 4), ("BACKGROUND", (0, 1), (-1, -1), colors.HexColor("#fbf5ec"))]))
            contradiction_rows = [[_cell("Subject"), _cell("Documented difference"), _cell("Status")]] + [[_cell(item.subject), _cell(item.description), _cell(item.status.value)] for item in contradiction_records]
            if len(contradiction_rows) == 1:
                contradiction_rows.append([_cell("—"), _cell("No structured contradiction has been recorded by the current comparison workflow."), _cell("—")])
            contradiction_table = Table(contradiction_rows, colWidths=[42 * mm, 104 * mm, 36 * mm], repeatRows=1)
            contradiction_table.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#3d4952")), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white), ("GRID", (0, 0), (-1, -1), .25, colors.HexColor("#c9c9c9")), ("VALIGN", (0, 0), (-1, -1), "TOP"), ("PADDING", (0, 0), (-1, -1), 4), ("BACKGROUND", (0, 1), (-1, -1), colors.HexColor("#fbf5ec"))]))
            story.extend([Spacer(1, 4 * mm), Paragraph("Claim support and source posture", styles["Heading2"]), claim_table, Spacer(1, 4 * mm), Paragraph("Structured contradictions", styles["Heading2"]), contradiction_table])
        else:
            story.append(
                Paragraph(
                    "No structured claim or contradiction has been recorded for this case snapshot. "
                    "Multiple files are not automatically treated as independent sources; corroboration "
                    "and contradiction are asserted only when the backend has explicitly produced that "
                    "relationship.",
                    styles["BodyText"],
                )
            )
        audit_rows = db.scalars(select(AuditLog).where(AuditLog.case_id == report.case_id).order_by(AuditLog.created_at)).all()
        reviews = db.scalars(select(ReviewDecision).where(ReviewDecision.case_id == report.case_id).order_by(ReviewDecision.created_at)).all()
        runs = db.scalars(select(ProcessingRun).join(EvidenceFile).where(EvidenceFile.case_id == report.case_id).order_by(ProcessingRun.created_at)).all()
        story.extend([PageBreak(), Paragraph("Evidence register", styles["Heading1"])])
        evidence_register = [[_cell("Evidence ID"), _cell("Original filename / type"), _cell("Uploaded"), _cell("Processing"), _cell("Review readiness")]]
        evidence_register += [[_cell(item.id[:8]), _cell_lines(item.original_name, item.source_category.replace("_", " ").title()), _timestamp_cell(item.uploaded_at), _cell(item.status.value), _cell("Ready for review" if item.status.value == "completed" else item.status.value)] for item in db.scalars(select(EvidenceFile).where(EvidenceFile.case_id == report.case_id).order_by(EvidenceFile.uploaded_at)).all()]
        register_table = Table(evidence_register, colWidths=[25 * mm, 62 * mm, 30 * mm, 30 * mm, 35 * mm], repeatRows=1)
        register_table.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#7b1e2b")), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white), ("GRID", (0, 0), (-1, -1), .25, colors.HexColor("#c9c9c9")), ("VALIGN", (0, 0), (-1, -1), "TOP"), ("PADDING", (0, 0), (-1, -1), 4)]))
        story.extend([register_table, Spacer(1, 6 * mm), Paragraph("Evidence record history", styles["Heading2"])])
        hashes = [[_cell("Evidence ID"), _cell("Record reference"), _cell("Stored"), _cell("Record status")]]
        hashes += [[_cell(item.id[:8]), _cell("Recorded"), _timestamp_cell(item.uploaded_at), _cell("Recorded" if item.sha256 else "Needs attention")] for item in db.scalars(select(EvidenceFile).where(EvidenceFile.case_id == report.case_id).order_by(EvidenceFile.uploaded_at)).all()]
        hash_table = Table(hashes, colWidths=[25 * mm, 88 * mm, 36 * mm, 33 * mm], repeatRows=1)
        hash_table.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#7b1e2b")), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white), ("GRID", (0, 0), (-1, -1), .25, colors.HexColor("#c9c9c9")), ("VALIGN", (0, 0), (-1, -1), "TOP"), ("PADDING", (0, 0), (-1, -1), 4), ("BACKGROUND", (0, 1), (-1, -1), colors.HexColor("#fbf5ec"))]))
        story.extend([hash_table, PageBreak(), Paragraph("Evidence and review history", styles["Heading1"]), Paragraph("EVIDENCE RECEIVED   →   CASE RECORD UPDATED   →   REVIEWED   →   REPORT INCLUDED", ParagraphStyle(name="Lifecycle", parent=styles["BodyText"], alignment=TA_CENTER, textColor=colors.HexColor("#7b1e2b"), fontName="Helvetica-Bold")), Spacer(1, 5 * mm)])
        story.extend([Paragraph("Investigator review", styles["Heading2"])])
        if reviews:
            review_table = [[_cell("Time"), _cell("Reviewer"), _cell("Subject"), _cell("Decision"), _cell("Note")]]
            review_table += [[_timestamp_cell(item.created_at), _cell(item.reviewer_id), _cell(f"{item.subject_type} · {item.subject_id[:8]}"), _cell(item.decision.value), _cell(item.note or "—")] for item in reviews] or [[_cell("—"), _cell("—"), _cell("No review record"), _cell("—"), _cell("—")]]
            review_render = Table(review_table, colWidths=[28 * mm, 35 * mm, 42 * mm, 28 * mm, 49 * mm], repeatRows=1)
            review_render.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#7b1e2b")), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white), ("GRID", (0, 0), (-1, -1), .25, colors.HexColor("#c9c9c9")), ("VALIGN", (0, 0), (-1, -1), "TOP"), ("PADDING", (0, 0), (-1, -1), 4)]))
            story.append(review_render)
        else:
            story.append(Paragraph("No investigator review decision has been recorded against this case yet.", styles["BodyText"]))
        custody = [[_cell("Time"), _cell("Actor"), _cell("Action"), _cell("Result")]]
        custody += [[_timestamp_cell(item.created_at), _cell(item.actor_id or "System"), _cell(item.action), _cell(item.outcome)] for item in audit_rows]
        custody_table = Table(custody, colWidths=[32 * mm, 38 * mm, 58 * mm, 54 * mm], repeatRows=1)
        custody_table.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#7b1e2b")), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white), ("GRID", (0, 0), (-1, -1), .25, colors.HexColor("#c9c9c9")), ("VALIGN", (0, 0), (-1, -1), "TOP"), ("PADDING", (0, 0), (-1, -1), 4)]))
        story.extend([Spacer(1, 6 * mm), Paragraph("Evidence and review log", styles["Heading2"]), custody_table])
        # The processing manifest continues on the same page. Removing "Case record overview" left a
        # page break with nothing behind it, which rendered as a blank sheet.
        story.append(Spacer(1, 6 * mm))
        manifest = [[_cell("Stage"), _cell("Version"), _cell("State"), _cell("Attempt"), _cell("Completed / note")]]
        manifest += [[_cell(item.pipeline_stage), _cell(item.pipeline_version), _cell(item.state.value), _cell(str(item.attempt)), _cell((item.completed_at or item.created_at).isoformat(timespec="minutes"))] for item in runs]
        manifest_table = Table(manifest, colWidths=[37 * mm, 32 * mm, 30 * mm, 24 * mm, 59 * mm], repeatRows=1)
        manifest_table.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#7b1e2b")), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white), ("GRID", (0, 0), (-1, -1), .25, colors.HexColor("#c9c9c9")), ("VALIGN", (0, 0), (-1, -1), "TOP"), ("PADDING", (0, 0), (-1, -1), 4)]))
        story.extend([PageBreak(), Paragraph("Key findings and review", styles["Heading1"]), Paragraph("The following observations should be considered with their listed source and review state.", styles["BodyText"]), Paragraph("Evidence-linked findings", styles["Heading2"])])
        story.append(Paragraph("Numbered findings", styles["Heading2"]))
        _append_numbered_findings(story, styles, _numbered_findings(db, report.case_id, snapshot))
        story.append(Spacer(1, 5 * mm))
        findings = [event for event in snapshot["events"] if event["review"] == "confirmed"][:5]
        finding_rows = [[_cell("Finding / event"), _cell("Supporting source"), _cell("Review state")]]
        if findings:
            for item in findings:
                finding_rows.append([_cell(item["description"]), _cell("Case-scoped event record"), _cell(item["review"])])
        else:
            finding_rows.append([_cell("No event is presented as a final finding until a human review decision confirms it."), _cell("—"), _cell("Review required")])
        finding_table = Table(finding_rows, colWidths=[102 * mm, 42 * mm, 38 * mm], repeatRows=1)
        finding_table.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#7b1e2b")), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white), ("GRID", (0, 0), (-1, -1), .25, colors.HexColor("#c9c9c9")), ("VALIGN", (0, 0), (-1, -1), "TOP"), ("PADDING", (0, 0), (-1, -1), 4), ("BACKGROUND", (0, 1), (-1, -1), colors.HexColor("#fbf5ec"))]))
        gap_rows = [[_cell("Severity"), _cell("Reviewable lead"), _cell("Status")]] + [[_cell(item.severity.value.upper()), _cell(item.explanation), _cell(item.status.value)] for item in alert_records]
        if len(gap_rows) == 1:
            gap_rows.append([_cell("—"), _cell("No alert record is currently present in this case snapshot."), _cell("—")])
        gap_table = Table(gap_rows, colWidths=[25 * mm, 125 * mm, 32 * mm], repeatRows=1)
        gap_table.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#3d4952")), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white), ("GRID", (0, 0), (-1, -1), .25, colors.HexColor("#c9c9c9")), ("VALIGN", (0, 0), (-1, -1), "TOP"), ("PADDING", (0, 0), (-1, -1), 4), ("BACKGROUND", (0, 1), (-1, -1), colors.HexColor("#fbf5ec"))]))
        recommendations = []
        if any(item.status.value != "reviewed" for item in alert_records):
            recommendations.append([_cell("High"), _cell("Review each open alert alongside its linked evidence object."), _cell("Open alert records require source-level verification.")])
        if any(not item.sender_value or not item.receiver_value for item in transaction_records):
            recommendations.append([_cell("High"), _cell("Validate transaction counterparties and references against original financial evidence."), _cell("One or more transaction records have incomplete parties or references.")])
        if any(item["time"] is None for item in snapshot["events"]):
            recommendations.append([_cell("Medium"), _cell("Cross-check time-not-established events against original metadata before using chronology."), _cell("No confirmed time has been recorded for one or more events.")])
        if contradiction_records:
            recommendations.append([_cell("Medium"), _cell("Review documented contradictions against their linked source records."), _cell("Structured contradiction records remain in the case review workflow.")])
        if not recommendations:
            recommendations.append([_cell("Routine"), _cell("Continue case-scoped human review and retain verification records with the next report version."), _cell("No additional action is indicated by the current case record.")])
        recommendation_table = Table([[_cell("Priority"), _cell("Recommended action"), _cell("Reason")]] + recommendations, colWidths=[25 * mm, 92 * mm, 65 * mm], repeatRows=1)
        recommendation_table.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#3d4952")), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white), ("GRID", (0, 0), (-1, -1), .25, colors.HexColor("#c9c9c9")), ("VALIGN", (0, 0), (-1, -1), "TOP"), ("PADDING", (0, 0), (-1, -1), 4), ("BACKGROUND", (0, 1), (-1, -1), colors.HexColor("#fbf5ec"))]))
        conclusion_rows = [[_cell("Conclusion field"), _cell("Current case-scoped presentation")], [_cell("Case status"), _cell(case_record.status.value)], [_cell("Evidence status"), _cell(f"{len(evidence_records)} evidence object(s); {sum(1 for item in evidence_records if item.status.value == 'completed')} completed")], [_cell("Graph relationships"), _cell(f"{graph_metrics.get('edge_count', 0)} source-linked relationship(s)")], [_cell("Review status"), _cell(f"{len(reviews)} recorded decision(s); {sum(1 for item in alert_records if item.status.value != 'reviewed')} open alert(s)")], [_cell("Report record"), _cell("Case evidence and review information is retained with this report.")]]
        conclusion_table = Table(conclusion_rows, colWidths=[55 * mm, 127 * mm], repeatRows=1)
        conclusion_table.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#7b1e2b")), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white), ("GRID", (0, 0), (-1, -1), .25, colors.HexColor("#c9c9c9")), ("VALIGN", (0, 0), (-1, -1), "TOP"), ("PADDING", (0, 0), (-1, -1), 5), ("BACKGROUND", (0, 1), (-1, -1), colors.HexColor("#fbf5ec"))]))
        story.extend([finding_table, Spacer(1, 5 * mm), Paragraph("Conflicting information / reviewable gaps", styles["Heading2"]), gap_table, Spacer(1, 5 * mm), Paragraph("Recommended next investigator actions", styles["Heading2"]), Paragraph("These prompts are derived from current evidence and review state. They are not legal conclusions or mandatory instructions.", styles["BodyText"]), recommendation_table, PageBreak(), Paragraph("Report conclusion", styles["Heading1"]), conclusion_table, Spacer(1, 7 * mm), Paragraph("Conclusion narrative", styles["NarrativeHeading"]), Spacer(1, 3.5 * mm), Paragraph(_controlled_conclusion(db.get(Case, report.case_id), evidence_count=len(evidence_records), event_count=len(snapshot["events"]), relationship_count=graph_metrics.get("edge_count", 0), alert_count=len(alert_records), review_count=len(reviews)), styles["NarrativeCallout"]), Paragraph("Important note", styles["Heading2"]), Paragraph("Use this report together with its listed evidence and review notes. Check important findings against the original source material before taking further action.", styles["BodyText"]), Spacer(1, 5 * mm), Paragraph("Caution", styles["Heading2"]), Paragraph("This report records source-linked evidence, machine-derived leads, and human-review states. It does not determine guilt, identity, truthfulness, legal admissibility, or a legal outcome, and it does not replace independent evidentiary verification.", styles["BodyText"]), ])
        return _finalise(db, report, output, story, case)
    except Exception as exc:
        db.rollback()
        report = db.get(Report, report_id)
        if report:
            report.status, report.failure_reason = ProcessingState.FAILED, str(exc)[:1000]
            db.commit()
        raise
    finally:
        db.close()


def get_report_path(storage_key: str) -> Path:
    return get_report_artifact_path(storage_key)
