"""Render the step-by-step execution plan for the agreed roadmap."""

from __future__ import annotations

from datetime import datetime, timezone

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

BURGUNDY = colors.HexColor("#7F1D1D")
SLATE = colors.HexColor("#3d4952")
INK = colors.HexColor("#1d1a17")
MUTED = colors.HexColor("#5f574e")
RULE = colors.HexColor("#dcd2c5")
PAPER = colors.HexColor("#faf6ef")

OUT = "/app/generated_reports/DRISHYAM_SIH26189_Execution_Plan.pdf"

styles = getSampleStyleSheet()
body = styles["BodyText"]
body.fontName = "Times-Roman"
body.fontSize = 9.4
body.leading = 13.4
body.textColor = INK
body.spaceAfter = 2

H1 = ParagraphStyle("H1", parent=styles["Heading1"], fontName="Times-Bold", fontSize=15, leading=18,
                    textColor=BURGUNDY, spaceBefore=9, spaceAfter=4)
ITEM = ParagraphStyle("ITEM", parent=styles["Heading2"], fontName="Helvetica-Bold", fontSize=10, leading=13,
                      textColor=INK, spaceBefore=7, spaceAfter=2)
STEP = ParagraphStyle("STEP", parent=body, fontSize=9, leading=12.8, leftIndent=6 * mm, spaceAfter=1.2)
META = ParagraphStyle("META", parent=body, fontName="Courier", fontSize=7.6, leading=10.6,
                      textColor=colors.HexColor("#4a4038"), leftIndent=6 * mm, spaceAfter=1)
SMALL = ParagraphStyle("Small", parent=body, fontSize=8.2, leading=11.4, textColor=MUTED)
COVER = ParagraphStyle("Cover", parent=styles["Title"], fontName="Times-Bold", fontSize=26, leading=30,
                       textColor=BURGUNDY, alignment=TA_CENTER)
SUB = ParagraphStyle("Sub", parent=body, alignment=TA_CENTER, fontSize=10, textColor=MUTED)


def frame(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica-Bold", 6.4)
    canvas.setFillColor(colors.HexColor("#8f857a"))
    canvas.drawString(15 * mm, A4[1] - 9 * mm, "DRISHYAM  /  SIH26189  /  EXECUTION PLAN")
    canvas.drawRightString(A4[0] - 15 * mm, 9 * mm, f"Page {doc.page}")
    canvas.setStrokeColor(RULE)
    canvas.setLineWidth(0.4)
    canvas.line(15 * mm, A4[1] - 12 * mm, A4[0] - 15 * mm, A4[1] - 12 * mm)
    canvas.restoreState()


def item(code, title, effort, depends, steps, files, tests, done):
    block = [
        Paragraph(f"{code} &nbsp;·&nbsp; {title} "
                  f"<font size=8 color='#7f6d5f'>[{effort}"
                  + (f", after {depends}" if depends else "")
                  + "]</font>", ITEM),
    ]
    block += [Paragraph(f"{n}. {text}", STEP) for n, text in enumerate(steps, start=1)]
    block.append(Paragraph(f"<b>files</b>  {files}", META))
    block.append(Paragraph(f"<b>tests</b>  {tests}", META))
    block.append(Paragraph(f"<font color='#1f5e3a'><b>done when</b></font>  {done}", META))
    block.append(Spacer(1, 1.5 * mm))
    return KeepTogether(block)


story: list = []

story += [
    Spacer(1, 44 * mm),
    Paragraph("DRISHYAM", COVER),
    Paragraph("Execution Plan", ParagraphStyle("cs", parent=COVER, fontSize=15, leading=19, textColor=INK)),
    Spacer(1, 5 * mm),
    Paragraph("SIH26189 — step by step, per item<br/>Ministry of Home Affairs · NCRB Women Safety Division", SUB),
    Spacer(1, 4 * mm),
    Paragraph(f"Generated {datetime.now(timezone.utc).strftime('%d %B %Y')}", SMALL),
    Spacer(1, 12 * mm),
    Paragraph(
        "The companion to the build roadmap. That document says what will be built and why; this one says how each "
        "item is done, which files it touches, what holds it in place afterwards, and what has to be true before it "
        "can be called finished. Read the roadmap first for the reasoning; work from this one.",
        ParagraphStyle("intro", parent=body, fontSize=10, leading=15, textColor=MUTED, alignment=TA_CENTER,
                       leftIndent=14 * mm, rightIndent=14 * mm)),
    PageBreak(),
]

# --------------------------------------------------------------------------- how to read
story += [
    Paragraph("How to work from this", H1),
    Paragraph(
        "Every item carries four lines. <b>files</b> names what changes. <b>tests</b> names what must be written "
        "alongside it — not afterwards, and not optional: every behaviour here is one somebody will later assume is "
        "still true. <b>done when</b> is a statement that can be checked on the benchmark case rather than a feeling "
        "of completeness.", body),
    Spacer(1, 2 * mm),
    Paragraph(
        "Two standing rules apply to every item without being repeated. Nothing sends case content to a hosted model. "
        "Nothing states intent, identity or culpability — the system reports what a source states and marks anything "
        "it could not establish as unestablished.", body),
    Spacer(1, 4 * mm),
]

# --------------------------------------------------------------------------- PHASE A
story.append(Paragraph("Phase A — The investigator can understand what they are looking at", H1))

story.append(item(
    "A1", "Capture the stated role", "0.5 day", None,
    [
        "Name the role group in the two patterns that already match it. <font face='Courier' size='8'>PERSON_LABEL_PATTERN</font> and "
        "<font face='Courier' size='8'>PERSON_INLINE_ROLE_PATTERN</font> both wrap the role in a non-capturing group today, so the match is made "
        "and discarded.",
        "Add a readings map that reduces the label to the word a case turns on: complainant and informant to "
        "complainant; accused and suspect to accused; victim and deceased to victim; witness, driver, owner as "
        "themselves. <b>“Name:” is not a case role</b> — it becomes <i>named</i> — and “S/o Mohan Lal” names a parent, "
        "which becomes <i>relative</i>, not a role in the case.",
        "Label the weaker basis honestly: “identifying himself as” becomes <i>self-identified</i>. That is how a name "
        "enters a surveillance note and it is not the same as a report assigning a role.",
        "Add <font face='Courier' size='8'>find_person_roles(text)</font> returning name to role. Where one passage gives two readings the "
        "stronger wins — an assigned role outranks a self-given name.",
        "Record the roles in extraction with the same provenance the names already carry, and store them: a "
        "<font face='Courier' size='8'>person_roles</font> column on the record, and <font face='Courier' size='8'>stated_role</font> on the entity occurrence. "
        "The role belongs to the place it was read, never to the person: the same individual can be a witness in one "
        "file and a suspect in another.",
    ],
    "patterns.py · extraction.py · schema.py · models/entities.py · entity_resolution.py · one migration",
    "role read from an FIR header and from narrative prose · “Name:” yields no case role · S/o names the parent as a "
    "relative · self-identified is labelled as such · a name with no stated role gets none",
    "the benchmark case reads Suresh Yadav as accused, Priya Sharma as complainant, and Suresh Yadava as "
    "self-identified — each with the line it came from",
))

story.append(item(
    "A2", "Entity summary card", "1 day", "A1",
    [
        "A service that assembles four sentences from stored rows: the role as stated and where; how many files it "
        "was found in; what it connects to and on whose evidence; and what it does <b>not</b> connect to in this case.",
        "Every sentence carries its citation. No sentence is generated by a model — the facts are structured, so a "
        "template-built summary is quotable line by line where a written one is not.",
        "Endpoint under the existing grounded routes, authorised the same way.",
        "Surface it on the network page: clicking a node opens the summary above the source panel that already exists.",
        "Carry the standing caveat, and state absence explicitly rather than leaving a gap.",
    ],
    "services/entity_summary.py (new) · api/grounded.py · NetworkIntelligence.tsx · new frontend component",
    "every sentence carries a source · no sentence asserts guilt · an entity with no relationships says so plainly · "
    "an entity with no stated role says the role was not stated",
    "clicking Ravi Kumar on the network answers who he is, where he came from and what he is connected to, without "
    "leaving the page",
))

story.append(item(
    "A3", "Confidence as a sentence", "0.5 day", None,
    [
        "Map the stored basis and confidence onto a phrase an officer can weigh: “stated directly in a call record”, "
        "“read from a screenshot”, “inferred from context”.",
        "Show the phrase everywhere the number is shown today; keep the number on hover so the record is unchanged.",
        "Leave the report's numeric columns alone — a court document should carry the figure.",
    ],
    "frontend shared formatter · NetworkIntelligence.tsx · EvidenceSourceViewer.tsx",
    "each basis maps to exactly one phrase · the numeric value remains reachable",
    "no bare 0.92 appears in the workspace without words beside it",
))

story.append(item(
    "A4", "Every page opens with the work", "1 day", None,
    [
        "One line at the top of each view stating what to do next, derived from what is already on the page.",
        "Network: which links to verify first. Alerts: which cluster to read first. Review: what is unreviewed. "
        "Evidence: what failed or is unprocessed.",
        "Where there is nothing to do, say that — an empty instruction line is worse than an honest one.",
    ],
    "each workspace view · one shared component",
    "the line changes when the underlying data changes · it never states a conclusion about a person",
    "each view answers “what do I do here” before it shows a table",
))

story.append(PageBreak())

# --------------------------------------------------------------------------- PHASE B
story.append(Paragraph("Phase B — The questions an investigator actually asks", H1))

story.append(item(
    "B1", "Entity profile page", "2 days", "A1",
    [
        "A page per entity: every way the identity was written and which file wrote it that way; every occurrence "
        "with its exact place; every relationship with the record stating it; that entity's own timeline; and its "
        "appearances in other cases where the viewer is authorised to know.",
        "Reuse what exists — the source panel, the relation drawer, the summary from A2 — rather than building new "
        "surfaces for the same data.",
        "Reachable from the network node, the observation table, the findings list and search.",
        "An alias is a lead, not a merge: the page states the different spellings and never quietly joins them.",
    ],
    "api/grounded.py (entity routes) · services/entity_profile.py (new) · new workspace view · routing",
    "authorisation scoped to the case · aliases listed without merging · every row opens at its source · an entity "
    "with one occurrence renders correctly",
    "a name can be clicked from anywhere in the workspace and answers itself",
))

story.append(item(
    "B2", "Incident date at case creation", "2 hours", None,
    [
        "Add the incident window to the case intake form, writing the fields the case record already has.",
        "Allow it to be set later from case settings for cases already open.",
        "Where it is absent, keep saying so — the temporal sections already word this correctly.",
    ],
    "case intake form · cases API · settings view",
    "a case created with a window produces before/during/after counts · one created without still renders",
    "the benchmark case reports contact placed around the incident instead of “no incident window declared”",
))

story.append(item(
    "B3", "Cross-case identity check", "2 days", "E3",
    [
        "Given an identity in this case, report which other cases hold the same identity — the case reference and the "
        "officer to contact, never the other case's content.",
        "Match on the canonical value the resolver already produces, so a number written four ways still matches.",
        "Show it on the entity profile as its own section, with the disclosure limit stated on screen.",
        "Audit every check: asking whether an identifier appears elsewhere is itself an access event.",
    ],
    "services/cross_case.py · entity profile page · audit",
    "no field of another case leaks into the response · an unauthorised viewer gets nothing · the check is audited",
    "“this number appears in two other cases” is answerable without either officer seeing the other's file",
))

story.append(PageBreak())

# --------------------------------------------------------------------------- PHASE C
story.append(Paragraph("Phase C — Alerts that tell a story", H1))

story.append(item(
    "C1", "Narrative pattern alerts", "2 days", None,
    [
        "Assemble the sourced facts behind a pattern in time order and render them as a sequence: time, what the "
        "source states, and the file and place it is written.",
        "Close every sequence with the same line — the sequence is recorded, the meaning is the reader's.",
        "State the gaps inside the sequence too: “between these, no recorded contact” is part of the story.",
        "No sentence may contain a because, a motive, or a relationship the source did not state.",
    ],
    "alerts/network_rules.py · alert rendering in the workspace · report alert section",
    "every line carries a file and a place · no rendered sequence contains a causal clause · a pattern with one fact "
    "still renders",
    "an alert reads as a story an officer can act on and states nothing about why",
))

story.append(item(
    "C2", "Five new pattern rules", "2 days", None,
    [
        "<b>Relay</b> — A contacts B and B contacts C inside a short window.",
        "<b>Converging location</b> — several distinct entities placed at one location inside a window.",
        "<b>Late-arriving identity</b> — an identity that first appears well after the case opened.",
        "<b>Vehicle corridor</b> — one vehicle recorded at several places in time order.",
        "<b>Sudden silence</b> — a pair in regular recorded contact that stops. Nothing reports this today and it is "
        "often the strongest signal in a case.",
        "Each rule states what it observed and what it does not establish, and is idempotent on reprocessing.",
    ],
    "alerts/network_rules.py · temporal.py",
    "each rule fires on the benchmark case where expected and stays silent where not · reprocessing raises no "
    "duplicates · no rule discloses another case",
    "five new patterns appear on the benchmark case, each opening at its evidence",
))

story.append(item(
    "C3", "Alerts page states the work", "0.5 day", "C1",
    [
        "A line above the list: how many patterns, which cluster in time, and which links to verify first.",
        "Derive it from the bridge relationships and the temporal data already computed.",
    ],
    "alerts view",
    "the line reflects the current filters · it names links rather than people",
    "the page opens with an instruction, not a count",
))

story.append(PageBreak())

# --------------------------------------------------------------------------- PHASE D
story.append(Paragraph("Phase D — The report as a working surface", H1))

story.append(item(
    "D1", "In-app report viewer with search", "2 days", None,
    [
        "Render report pages through the endpoint that already renders evidence pages, and page through them in a panel.",
        "Search inside the document. The renderer returns the rectangle of every match, so results are marked in place "
        "rather than counted.",
        "Reuse the mark styling from the evidence viewer so a highlight means the same thing everywhere.",
    ],
    "api/reports (page render) · new report viewer component · reuse of the source panel styling",
    "search marks every occurrence and reports the count honestly · a report that fails to render says so · access is "
    "authorised and audited",
    "a nineteen-page report can be read and searched without downloading it",
))

story.append(item(
    "D2", "A finding opens its evidence", "0.5 day", "D1",
    [
        "Findings already carry a number, a file and an exact place. Make each one a control that opens the existing "
        "source panel at that place.",
        "Do the same for the source crops already printed in the report.",
    ],
    "report viewer · EvidenceSourceViewer.tsx",
    "every numbered finding resolves to a source · a finding whose evidence is gone says so rather than failing",
    "F-07 in the report opens the row it was read from",
))

story.append(item(
    "D3", "Report questions, answered offline", "1 day", "D1",
    [
        "Questions of fact — where did this come from, what supports it, what connects these two — go to the existing "
        "case assistant, which has no model behind it.",
        "Questions of wording surface the explanation the report already stores rather than writing a new one.",
        "Anything else is declined with a plain sentence saying why, and the scope is stated on screen.",
    ],
    "report viewer · services/case_assistant.py",
    "no report content reaches a hosted provider · a question outside scope is declined rather than guessed",
    "a reader can ask about a finding and get an answer with its source, offline",
))

story.append(PageBreak())

# --------------------------------------------------------------------------- PHASE E
story.append(Paragraph("Phase E — Integrity, and where blockchain genuinely belongs", H1))

story.append(item(
    "E1", "Chain verification", "1 day", None,
    [
        "Walk the audit chain for a case from its first entry, recompute each hash from the stored payload, and "
        "confirm each entry carries the previous one's hash.",
        "Report the count and the outcome — intact, or the exact entry where it breaks and what differs.",
        "Surface it three ways: an endpoint, a badge in the workspace, and a line in the court annexure.",
        "Today <font face='Courier' size='8'>trustify/verify</font> checks the report and manifest hashes — that part works — and only echoes "
        "the chain head. A chain nobody walks is a table that looks like tamper-evidence.",
    ],
    "services/trustify.py · api · integrity view · reporting.py",
    "an intact chain verifies · a tampered entry is located exactly · a case with no entries reports that honestly",
    "“prove the chain holds” has an answer, on screen and in the annexure",
))

story.append(item(
    "E2", "Merkle root per case", "1 day", "E1",
    [
        "Build a Merkle tree over the evidence hashes of a case; print the root in the report and store it with the receipt.",
        "Provide an inclusion proof for any single file: the short path proving that file was in the set, without "
        "revealing the others.",
        "State plainly what the root proves and what it does not — it fixes the set at a moment, it does not "
        "authenticate the contents.",
    ],
    "services/trustify.py · reporting.py · api",
    "a proof verifies against the root · a file not in the set fails · adding a file changes the root",
    "a court can be shown that one file was in the case at report time without seeing the rest",
))

story.append(item(
    "E3", "Shared hash ledger for cross-case matching", "3 days", "E1",
    [
        "Publish only <font face='Courier' size='8'>sha256(canonical identifier)</font> with a case reference and a contact — never the "
        "identifier, never any case content. A hash cannot be reversed and discloses nothing on its own.",
        "Append-only and chained, so an entry cannot be removed or backdated by whoever holds the store.",
        "Off by default, with the same double gate the external-model switch uses, and every publish audited.",
        "This is the one place in this product where the parties do not trust each other, which is the only place a "
        "shared ledger earns its cost. Everywhere else a local hash chain is the honest answer.",
    ],
    "services/ledger.py (new) · settings gate · audit · cross_case.py",
    "nothing but a hash and a reference leaves · the gate defaults closed · a publish is audited · matching works "
    "across differently written forms of the same identifier",
    "two districts can discover a shared identifier without either seeing the other's case",
))

story.append(PageBreak())

# --------------------------------------------------------------------------- PHASE F + G
story.append(Paragraph("Phase F — Fewer places to look", H1))

story.append(item(
    "F1", "Seventeen views to eight", "2 days", None,
    [
        "Entities &amp; Graph and Network Intelligence become one <b>Network</b>. Corroboration, Contradictions and "
        "Review Queue become one <b>Review</b>. Integrity, Custody/Audit and Processing become one <b>Integrity</b>. "
        "Reports and Report Versions become one <b>Reports</b>.",
        "Nothing is deleted. Each merged view keeps the sections it absorbed, as tabs or as sections within the page.",
        "Update the sidebar, the routing and any deep links that name the old views.",
    ],
    "Workspace.tsx · sidebar · routing · view components",
    "every feature reachable before is reachable after · no route 404s · deep links still resolve",
    "the sidebar holds eight destinations and the demo can show all of them",
))

story.append(Paragraph("Phase G — Finishing the workflow", H1))

for code, title, effort, depends, steps, files, tests, done in [
    ("G1", "Notes on entities and relations", "1 day", "B1",
     ["A note belongs to a case object, an author and a time, and is never mixed into extracted facts.",
      "Show notes on the entity profile and the relation drawer; include them in the case file report, marked as "
      "investigator commentary rather than evidence."],
     "models · api · entity profile · relation drawer · reporting.py",
     "a note is attributed and timestamped · notes never appear as findings · deleting is recorded, not silent",
     "an investigator can write down what they know beside what the system read"),
    ("G2", "Export", "1 day", None,
     ["CSV and JSON for entities, relationships and numbered findings, carrying the source columns.",
      "Exporting is a disclosure: audit it, and apply the same protected-identity rule the reports use."],
     "api · workspace export controls",
     "the export carries the source of every row · protection is applied · the action is audited",
     "a case can be handed to another system without anybody retyping it"),
    ("G3", "Requisition draft", "1 day", "C2",
     ["From the network and the temporal data, draft what to request next: which numbers, which date ranges, and why "
      "each is being asked for.",
      "Produce it as text the officer edits and sends. The system drafts; it does not submit."],
     "services/requisition.py (new) · workspace",
     "every number in a draft traces to a stated relationship · the draft states its own basis",
     "the page that shows the network can produce the next request from it"),
    ("G4", "What changed since you were last here", "1 day", None,
     ["Record when each user last opened a case; summarise what arrived since — new evidence, new relationships, new "
      "patterns, new review decisions.",
      "Show it on opening the case, dismissible, never blocking."],
     "models · api · overview view",
     "the digest is per user · it reports nothing the user cannot access · an unchanged case says so",
     "opening a case answers “what is new” before anything else"),
]:
    story.append(item(code, title, effort, depends, steps, files, tests, done))

story.append(PageBreak())

# --------------------------------------------------------------------------- order + rules
story.append(Paragraph("Order of work", H1))


def cell(t, s=None):
    return Paragraph(t, s or ParagraphStyle("c", parent=body, fontSize=8.6, leading=11.6, spaceAfter=0))


def head(t):
    return Paragraph(f"<b>{t}</b>", ParagraphStyle("h", parent=body, fontSize=8, leading=11,
                                                   textColor=colors.white, spaceAfter=0))


rows = [
    ["Step", "Items", "Effort", "Why here"],
    ["1", "A1 + A2", "1.5 d", "Half a day unblocks four items. The investigator's first question, answered."],
    ["2", "B1", "2 d", "The largest missing surface in the product."],
    ["3", "E1", "1 d", "The theme is Blockchain &amp; Cybersecurity and the chain is currently unproven."],
    ["4", "B2", "2 h", "One field wakes an entire dormant feature."],
    ["5", "C1 + C2", "4 d", "The largest readability gain after A2."],
    ["6", "D1 + D2", "2.5 d", "Closes the loop from report back to evidence."],
    ["7", "F1", "2 d", "Worth as much to the demo as any new feature."],
    ["8", "E3", "3 d", "The blockchain story, told where it is true."],
    ["9", "A3, A4, C3, D3, E2, G1–G4", "7 d", "Polish, in whatever order time allows."],
]
t = Table([[head(c) for c in rows[0]]] + [[cell(c) for c in r] for r in rows[1:]],
          colWidths=[12 * mm, 44 * mm, 14 * mm, 110 * mm], repeatRows=1)
t.setStyle(TableStyle([
    ("BACKGROUND", (0, 0), (-1, 0), BURGUNDY),
    ("GRID", (0, 0), (-1, -1), 0.25, RULE),
    ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, PAPER]),
    ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 5),
    ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
]))
story += [t, Spacer(1, 3 * mm)]
story.append(Paragraph(
    "<b>About twenty-five working days for one person.</b> Phases C, D and F depend on nothing in Phase B, so three "
    "people can run them in parallel once step 2 is done.", body))

story.append(Spacer(1, 5 * mm))
story.append(Paragraph("Rules that apply to every item", H1))
rows = [
    ["Rule", "Why"],
    ["No case content reaches a hosted model.",
     "It is the strongest claim this product makes and one careless feature ends it. Where a summary is needed, the "
     "facts are structured and a template-built sentence is citable where a written one is not."],
    ["Nothing states intent, identity or culpability.",
     "A confident wrong lead costs an investigation more than a missing one. The system reports what a source states."],
    ["Every new statement carries its source.",
     "A relationship with no source cannot be written at all; the same standard applies to anything added here."],
    ["Absence is reported, never left blank.",
     "A silent gap reads as “nothing there”. Say that nothing was recorded, and that this is not the same as nothing "
     "having happened."],
    ["Tests are written with the item, not after it.",
     "Every behaviour in this plan is one somebody will later assume is still true."],
]
t = Table([[head(c) for c in rows[0]]] + [[cell(c) for c in r] for r in rows[1:]],
          colWidths=[62 * mm, 118 * mm], repeatRows=1)
t.setStyle(TableStyle([
    ("BACKGROUND", (0, 0), (-1, 0), SLATE),
    ("GRID", (0, 0), (-1, -1), 0.25, RULE),
    ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, PAPER]),
    ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 5),
    ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
]))
story += [t, Spacer(1, 6 * mm)]
story.append(Paragraph(
    "Nothing in this plan claims a capability is already implemented. Where an item says a thing does not work today, "
    "that was verified in the running system.", SMALL))

SimpleDocTemplate(OUT, pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm, topMargin=16 * mm,
                  bottomMargin=14 * mm, title="DRISHYAM SIH26189 Execution Plan").build(
    story, onFirstPage=frame, onLaterPages=frame)
print("written:", OUT)
