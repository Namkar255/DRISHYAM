"""Render the build roadmap agreed in this session to a PDF."""

from __future__ import annotations

from datetime import datetime, timezone

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

BURGUNDY = colors.HexColor("#7F1D1D")
INK = colors.HexColor("#1d1a17")
MUTED = colors.HexColor("#5f574e")
RULE = colors.HexColor("#d9cec1")
PAPER = colors.HexColor("#faf6ef")

OUT = "/app/generated_reports/DRISHYAM_SIH26189_Build_Roadmap.pdf"

styles = getSampleStyleSheet()
styles["BodyText"].fontName = "Times-Roman"
styles["BodyText"].fontSize = 9.6
styles["BodyText"].leading = 14
styles["BodyText"].textColor = INK
styles["BodyText"].spaceAfter = 3

H1 = ParagraphStyle("H1", parent=styles["Heading1"], fontName="Times-Bold", fontSize=16, leading=19,
                    textColor=BURGUNDY, spaceBefore=10, spaceAfter=5)
H2 = ParagraphStyle("H2", parent=styles["Heading2"], fontName="Helvetica-Bold", fontSize=10.5, leading=13,
                    textColor=BURGUNDY, spaceBefore=8, spaceAfter=3)
COVER = ParagraphStyle("Cover", parent=styles["Title"], fontName="Times-Bold", fontSize=26, leading=30,
                       textColor=BURGUNDY, alignment=TA_CENTER)
SUB = ParagraphStyle("Sub", parent=styles["BodyText"], alignment=TA_CENTER, fontSize=10, textColor=MUTED)
SMALL = ParagraphStyle("Small", parent=styles["BodyText"], fontSize=8.2, leading=11.5, textColor=MUTED)
MONO = ParagraphStyle("Mono", parent=styles["BodyText"], fontName="Courier", fontSize=8, leading=11,
                      textColor=colors.HexColor("#4a4038"))

body = styles["BodyText"]


def cell(text, style=None):
    return Paragraph(text, style or ParagraphStyle("c", parent=body, fontSize=8.6, leading=11.8, spaceAfter=0))


def head(text):
    return Paragraph(f"<b>{text}</b>", ParagraphStyle("h", parent=body, fontSize=8, leading=11,
                                                      textColor=colors.white, spaceAfter=0))


def table(rows, widths, header_colour=BURGUNDY):
    data = [[head(c) for c in rows[0]]] + [[cell(c) for c in row] for row in rows[1:]]
    t = Table(data, colWidths=widths, repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), header_colour),
        ("GRID", (0, 0), (-1, -1), 0.25, RULE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, PAPER]),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    return t


def phase(story, title, intro, rows):
    block = [Paragraph(title, H1), Paragraph(intro, body), Spacer(1, 2 * mm),
             table(rows, [16 * mm, 62 * mm, 20 * mm, 24 * mm, 56 * mm])]
    story.append(KeepTogether(block) if len(rows) <= 4 else block[0])
    if len(rows) > 4:
        story.extend(block[1:])
    story.append(Spacer(1, 4 * mm))


def frame(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica-Bold", 6.4)
    canvas.setFillColor(colors.HexColor("#8f857a"))
    canvas.drawString(16 * mm, A4[1] - 9 * mm, "DRISHYAM  /  SIH26189  /  BUILD ROADMAP")
    canvas.drawRightString(A4[0] - 16 * mm, 9 * mm, f"Page {doc.page}")
    canvas.setStrokeColor(RULE)
    canvas.setLineWidth(0.4)
    canvas.line(16 * mm, A4[1] - 12 * mm, A4[0] - 16 * mm, A4[1] - 12 * mm)
    canvas.restoreState()


story: list = []

# --------------------------------------------------------------------------- cover
story += [
    Spacer(1, 46 * mm),
    Paragraph("DRISHYAM", COVER),
    Paragraph("Build Roadmap", ParagraphStyle("cs", parent=COVER, fontSize=15, leading=19, textColor=INK)),
    Spacer(1, 5 * mm),
    Paragraph("SIH26189 — AI-Powered Criminal Network Analysis System<br/>"
              "Ministry of Home Affairs · NCRB Women Safety Division", SUB),
    Spacer(1, 4 * mm),
    Paragraph(f"Generated {datetime.now(timezone.utc).strftime('%d %B %Y')}", SMALL),
    Spacer(1, 14 * mm),
    Paragraph(
        "This is the work agreed after a walkthrough of the running product as an investigator would use it. "
        "Everything here is additive: the provenance chain, the network layer, the source viewer, the four report "
        "profiles and the benchmark already exist and are not revisited. What follows is what an investigator still "
        "cannot do, what they cannot understand, and what the system claims but does not yet prove.",
        ParagraphStyle("intro", parent=body, fontSize=10, leading=15, textColor=MUTED, alignment=TA_CENTER,
                       leftIndent=14 * mm, rightIndent=14 * mm)),
    PageBreak(),
]

# --------------------------------------------------------------------------- where this stands
story += [
    Paragraph("Where this stands", H1),
    Paragraph(
        "Phases 0 to 9 of the original change roadmap are complete: the criminal-network vocabulary, entity-to-entity "
        "relationships, network analytics, source adapters, temporal rules, image preprocessing, the workspace surface, "
        "the case assistant and the benchmark. Since then the report was rewritten around the network, split into four "
        "audience profiles, given numbered findings and source crops, and a §63 certificate form. The landing page was "
        "rebuilt to argue the criminal-network case. 372 backend tests pass.",
        body),
    Spacer(1, 2 * mm),
    Paragraph("Three findings from the walkthrough drive most of this roadmap:", H2),
]

story.append(table([
    ["#", "Finding", "Where"],
    ["1",
     "The stated role — <b>Complainant, Accused, Victim, Witness, Driver, Owner</b> — is matched by the person "
     "extractor and then thrown away. Only the name is kept. The first question any investigator asks is the one "
     "piece of information the system deliberately discards.",
     "patterns.find_person_names()"],
    ["2",
     "There is no entity endpoint at all. An investigator cannot click a name and see who it is, where it came from, "
     "or whether it is known to another case. The data exists; nothing surfaces it.",
     "no /entities/{id}"],
    ["3",
     "The audit hash chain is written on every action but never verified. trustify/verify checks the report and "
     "manifest hashes — which works — and only echoes the chain head. A hash chain nobody walks is not "
     "tamper-evidence; it is a table that looks like one.",
     "trustify.verify_receipt()"],
], [8 * mm, 118 * mm, 52 * mm]))

story += [Spacer(1, 5 * mm), PageBreak()]

# --------------------------------------------------------------------------- phases
PHASES = [
    ("Phase A — The investigator can understand what they are looking at",
     "The product is accurate and hard to read. These four items change nothing about what it finds and everything "
     "about whether a working officer can act on it.",
     [
         ["ID", "Work", "Effort", "Depends on", "What it solves"],
         ["A1", "<b>Capture the stated role.</b> Keep the label the person pattern already matches, and store it on "
                "the entity as an observation with its own source.", "0.5 day", "—",
          "Unlocks every summary below. Without it the system cannot say whether a person is the complainant or the accused."],
         ["A2", "<b>Entity summary card.</b> Click a node, get four sentences: role as stated, where it was found, what "
                "it connects to, what it does not connect to. Template-driven from stored facts.", "1 day", "A1",
          "The investigator's first question, answered where they ask it. Every clause is citable."],
         ["A3", "<b>Confidence as a sentence.</b> Replace 0.92 with “stated directly in a call record”. Keep the number "
                "available on hover for the record.", "0.5 day", "—",
          "A number no officer can calibrate becomes a fact they can weigh."],
         ["A4", "<b>Every page opens with the work.</b> One line at the top of each view saying what to do, derived "
                "from the data already on it.", "1 day", "—",
          "Turns a set of dashboards into a set of instructions."],
     ]),
    ("Phase B — The questions an investigator actually asks",
     "Three gaps that stop the product being usable on a real case rather than a demo one.",
     [
         ["ID", "Work", "Effort", "Depends on", "What it solves"],
         ["B1", "<b>Entity profile page.</b> Aliases and how each was written, every occurrence with its source, every "
                "relationship, that entity's own timeline, and its appearances in other cases.", "2 days", "A1",
          "“Who is Ravi Kumar and what is his record.” The single largest missing surface."],
         ["B2", "<b>Incident date at case creation.</b> One field on the case form.", "2 hours", "—",
          "The entire temporal layer — contact before, during and after the incident, communication bursts — is built "
          "and dormant because no case declares a window."],
         ["B3", "<b>Cross-case identity check.</b> “This number appears in two other cases; here is the officer to "
                "contact,” without disclosing the other case's content.", "2 days", "E3",
          "Siloed districts are the problem MHA actually has. Cross-case links today are case-to-case, not identity-to-identity."],
     ]),
    ("Phase C — Alerts that tell a story",
     "The alert layer states facts correctly and reads like a log. An investigator needs the sequence. It must remain "
     "a sequence: the system states what happened and where it is written, and never why.",
     [
         ["ID", "Work", "Effort", "Depends on", "What it solves"],
         ["C1", "<b>Narrative pattern alerts.</b> Order the sourced facts by time and render them as a sequence, with "
                "each line carrying its file and place, and a closing line stating that the meaning is the reader's.",
          "2 days", "—",
          "Reads as a story, cites every clause, asserts no intent."],
         ["C2", "<b>Five new pattern rules:</b> relay (A→B→C inside a window), converging location, late-arriving "
                "identity, vehicle corridor, and sudden silence between a pair that had been in regular contact.",
          "2 days", "—",
          "All computable from data already stored. Silence in particular is a strong signal nothing currently reports."],
         ["C3", "<b>Alerts page states the work.</b> “Four patterns. Two cluster around one evening. Verify these two "
                "links first — if either is wrong the other three fall.”", "0.5 day", "C1",
          "Priority instead of a list."],
     ]),
    ("Phase D — The report as a working surface",
     "The report is generated, downloaded and then leaves the system. It should be readable, searchable and "
     "answerable inside the product first.",
     [
         ["ID", "Work", "Effort", "Depends on", "What it solves"],
         ["D1", "<b>In-app report viewer.</b> Render pages, search inside them, highlight matches at their exact "
                "rectangles. PyMuPDF already provides both.", "2 days", "—",
          "Review before download, and find a line in a nineteen-page document."],
         ["D2", "<b>F-xx opens its evidence.</b> Findings are already numbered and carry their file and exact place; "
                "wire each to the existing source panel.", "0.5 day", "D1",
          "“Which evidence was this from” becomes a click rather than a question."],
         ["D3", "<b>Report Q&amp;A through the offline assistant.</b> Questions of fact answered exactly from case rows. "
                "Questions of wording surface the explanation the report already stores.", "1 day", "D1",
          "Answers without putting report content — victim names, numbers — into a hosted model."],
     ]),
    ("Phase E — Integrity, and where blockchain genuinely belongs",
     "A hash chain already exists and is real. What is missing is proof that it holds, and the one situation where a "
     "shared ledger is the right tool rather than decoration: two districts that cannot show each other their data.",
     [
         ["ID", "Work", "Effort", "Depends on", "What it solves"],
         ["E1", "<b>Chain verification.</b> Walk the audit chain from the first entry, recompute every hash, and report "
                "“142 entries, chain intact” or the exact entry where it breaks. Surface as a badge and a report line.",
          "1 day", "—",
          "Converts a claim into a demonstration. Today there is no way to answer “prove the chain holds”."],
         ["E2", "<b>Merkle root per case.</b> A root over the evidence hashes, printed in the report, with an inclusion "
                "proof for any single file.", "1 day", "E1",
          "Proves a file was in the case at report time without disclosing the other files."],
         ["E3", "<b>Shared hash ledger for cross-case matching.</b> Districts publish sha256(identifier) with a case "
                "reference — never the identifier, never case content. A hash discloses nothing and cannot be reversed.",
          "3 days", "E1",
          "The one place in this product where no party trusts another, which is the only place a distributed ledger "
          "earns its cost."],
     ]),
    ("Phase F — Fewer places to look",
     "The workspace has seventeen views. No investigator holds seventeen locations in their head, and several overlap. "
     "Nothing is removed — the same features are reached in fewer places.",
     [
         ["ID", "Work", "Effort", "Depends on", "What it solves"],
         ["F1", "<b>Seventeen views to eight.</b> Entities &amp; Graph + Network Intelligence → Network. Corroboration + "
                "Contradictions + Review Queue → Review. Integrity + Custody/Audit + Processing → Integrity. "
                "Reports + Report Versions → Reports.", "2 days", "—",
          "A navigable product, and a demo that can show every surface inside the time allowed."],
     ]),
    ("Phase G — Finishing the workflow",
     "The product analyses a case well and does not yet help an officer work one.",
     [
         ["ID", "Work", "Effort", "Depends on", "What it solves"],
         ["G1", "<b>Notes on entities and relations.</b>", "1 day", "B1",
          "An investigator cannot currently write anything down inside the system."],
         ["G2", "<b>Export.</b> CSV and JSON for entities, relations and findings.", "1 day", "—",
          "Nothing exports today; the next system has to be typed into by hand."],
         ["G3", "<b>Requisition draft.</b> Which numbers, which date ranges, drafted from the network.", "1 day", "C2",
          "The bridge from analysis to the next investigative action."],
         ["G4", "<b>What changed since you were last here.</b>", "1 day", "—",
          "An investigator opening a case should not have to work out what is new."],
     ]),
]

for title, intro, rows in PHASES:
    story.append(Paragraph(title, H1))
    story.append(Paragraph(intro, body))
    story.append(Spacer(1, 2 * mm))
    story.append(table(rows, [11 * mm, 60 * mm, 15 * mm, 18 * mm, 74 * mm]))
    story.append(Spacer(1, 5 * mm))

story.append(PageBreak())

# --------------------------------------------------------------------------- order
story.append(Paragraph("Order of work", H1))
story.append(Paragraph(
    "Ordered by what unlocks the most and what an evaluator sees first, not by phase letter. A1 is first because four "
    "other items are blocked behind it and it takes half a day.", body))
story.append(Spacer(1, 2 * mm))
story.append(table([
    ["Step", "Items", "Effort", "Why here"],
    ["1", "A1 + A2 — role capture and the summary card", "1.5 days",
     "The investigator's first question, and the cheapest large win. Everything in Phase B reads better afterwards."],
    ["2", "B1 — entity profile page", "2 days", "The largest missing surface in the product."],
    ["3", "E1 — chain verification", "1 day",
     "The theme is Blockchain &amp; Cybersecurity and the chain is currently unproven. One day closes that."],
    ["4", "B2 — incident date", "2 hours", "One field wakes an entire dormant feature."],
    ["5", "C1 + C2 — narrative alerts and the new rules", "4 days", "The largest readability gain after A2."],
    ["6", "D1 + D2 — report viewer and F-xx links", "2.5 days", "Closes the loop from report back to evidence."],
    ["7", "F1 — seventeen views to eight", "2 days", "Worth as much to the demo as any new feature."],
    ["8", "E3 — shared hash ledger", "3 days", "The blockchain story, told where it is true."],
    ["9", "A3, A4, C3, D3, E2, G1–G4", "7 days", "Polish, in whatever order time allows."],
], [12 * mm, 62 * mm, 18 * mm, 86 * mm]))

story.append(Spacer(1, 3 * mm))
story.append(Paragraph(
    "<b>Roughly 25 working days for one person.</b> Phases C, D and F are independent of each other and of Phase B, so "
    "three people can run them in parallel after step 2.", body))

# --------------------------------------------------------------------------- not building
story.append(Spacer(1, 6 * mm))
story.append(Paragraph("What is deliberately not being built", H1))
story.append(Paragraph(
    "Each of these was considered and rejected. Recording the reasons matters as much as recording the work, because "
    "every one of them will be suggested again.", body))
story.append(Spacer(1, 2 * mm))
story.append(table([
    ["Not building", "Reason"],
    ["A language model summarising case data",
     "It would send names, numbers and case context to a hosted provider and destroy the strongest claim this product "
     "has. The summary does not need one: the facts are structured, and a template-built summary is citable line by "
     "line where a generated one is not."],
    ["“Why did this person go there”",
     "That is intent. The system states what a source states and refuses to infer meaning. A confident wrong lead costs "
     "an investigation more than a missing one, and this restraint is what makes the output defensible."],
    ["A distributed ledger with consensus for the case record",
     "Consensus solves disagreement between parties who do not trust each other. A police evidence system has one "
     "responsible custodian. A chain written and read by one machine is a database table called a blockchain, and "
     "evaluators recognise it. The hash chain is the part that is genuinely needed, and it already exists."],
    ["Neo4j, PaddleOCR, or new infrastructure",
     "Binding non-goals from the original roadmap. NetworkX and the current stack carry the analytics; new "
     "infrastructure costs schedule and buys nothing before the demo."],
    ["Face recognition or biometric matching",
     "Not asked for by the problem statement, and an ethical surface this project should not open."],
], [52 * mm, 122 * mm], header_colour=colors.HexColor("#3d4952")))

# --------------------------------------------------------------------------- standing
story.append(Spacer(1, 6 * mm))
story.append(Paragraph("Standing items", H1))
story.append(table([
    ["Item", "Status"],
    ["<b>Fifty-plus commits exist only on one laptop.</b> The whole of phases 0–9 and everything since is unpushed. "
     "This is the largest single risk to the submission and takes one command to remove.",
     "Open — needs a decision to push"],
    ["<b>Demo rehearsal.</b> The benchmark case, uploaded to a clean clone, walked end to end three times: network → "
     "node → source panel → assistant → four reports.",
     "Open"],
    ["<b>Case type on the demo case</b> still reads “Digital Payment Fraud”. Create the demo case with the correct "
     "type and the correct source categories per file.",
     "Open — five minutes"],
], [122 * mm, 52 * mm], header_colour=colors.HexColor("#3d4952")))

story.append(Spacer(1, 8 * mm))
story.append(Paragraph(
    "Nothing in this document claims a capability is implemented unless it was verified in the running system during "
    "the walkthrough it came from.", SMALL))

SimpleDocTemplate(OUT, pagesize=A4, leftMargin=16 * mm, rightMargin=16 * mm, topMargin=17 * mm,
                  bottomMargin=15 * mm, title="DRISHYAM SIH26189 Build Roadmap").build(
    story, onFirstPage=frame, onLaterPages=frame)
print("written:", OUT)
