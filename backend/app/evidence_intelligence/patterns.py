"""Deterministic identifier patterns shared by every extractor.

Kept separate from `app/extraction/normalizer.py` so the legacy `mvp-v1` pipeline keeps its exact
current behaviour while the grounded pipeline can evolve its own rules.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from dateutil import parser as date_parser

PHONE_PATTERN = re.compile(r"(?<!\d)(?:\+?91[\s-]?)?[6-9]\d{9}(?!\d)")
EMAIL_PATTERN = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
UPI_PATTERN = re.compile(r"\b[a-zA-Z0-9._-]{2,120}@[a-zA-Z][a-zA-Z0-9.-]{1,80}\b")
IFSC_PATTERN = re.compile(r"\b[A-Z]{4}0[A-Z0-9]{6}\b")
ACCOUNT_PATTERN = re.compile(r"(?:A/C|ACCOUNT(?:\s+NO\.?)?)\s*[:#-]?\s*(\d{9,18})", re.IGNORECASE)
UTR_PATTERN = re.compile(r"(?:UTR|RRN|REFERENCE(?:\s+ID)?|TXN(?:\s+ID)?|TRANSACTION\s+ID)\s*[:#-]?\s*([A-Z0-9-]{8,32})", re.IGNORECASE)
URL_PATTERN = re.compile(r"https?://[^\s<>'\"]+", re.IGNORECASE)
DEVICE_PATTERN = re.compile(r"(?:IMEI|DEVICE(?:\s+ID)?)\s*[:#-]?\s*([A-Z0-9-]{8,32})", re.IGNORECASE)

CURRENCY_SYMBOLS = {"₹": "INR", "rs": "INR", "rs.": "INR", "inr": "INR", "$": "USD", "usd": "USD", "€": "EUR", "eur": "EUR"}
AMOUNT_PATTERN = re.compile(
    r"(?P<currency>₹|INR|RS\.?|\$|USD|€|EUR)?\s*(?P<value>\d[\d,]*(?:\.\d{1,2})?)\s*(?P<trailing>₹|INR|RS\.?|\$|USD|€|EUR|rupees|rupaye)?",
    re.IGNORECASE,
)

_MONTH_NAME = r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?"

# One calendar date, written any of the ways evidence actually writes them.
_DATE = "|".join(
    (
        r"\d{4}-\d{2}-\d{2}",
        rf"\d{{1,2}}\s+{_MONTH_NAME}\s+\d{{4}}",
        rf"{_MONTH_NAME}\s+\d{{1,2}},?\s+\d{{4}}",
        r"\d{1,2}[/-]\d{1,2}[/-]\d{2,4}",
    )
)
_CLOCK = r"\d{1,2}:\d{2}(?::\d{2})?"
_MERIDIEM = r"[AaPp]\.?[Mm]\.?"
_OFFSET = r"[+-]\d{4}"

# Ordered most-specific first. A rule only fires when the date and the time are written next to
# each other; a date at the top of a screen is never welded onto a clock time further down.
TIMESTAMP_RULES: list[tuple[re.Pattern[str], str]] = [
    # 2024-03-12T21:15 / 2024-03-12 21:15:00
    (re.compile(rf"(?P<date>\d{{4}}-\d{{2}}-\d{{2}})[ T](?P<time>{_CLOCK})(?P<tz>\s*{_OFFSET})?"), "exact"),
    # 12/03/2024, 21:16  ·  12 Mar 2024 21:15:00 +0530  ·  02 Sep 2026 at 11:42 am
    (
        re.compile(
            rf"(?P<date>{_DATE})(?:,)?\s*(?:at\s+)?(?P<time>{_CLOCK}\s*(?:{_MERIDIEM})?)(?P<tz>\s*{_OFFSET})?",
            re.IGNORECASE,
        ),
        "exact",
    ),
    # 11:42 am on 02 Sep 2026
    (
        re.compile(rf"(?P<time>{_CLOCK}\s*{_MERIDIEM})\s*(?:on\s+)?(?P<date>{_DATE})", re.IGNORECASE),
        "exact",
    ),
    # A bare calendar date.
    (re.compile(rf"(?P<date>{_DATE})", re.IGNORECASE), "date_only"),
    # A bare clock reading. It fixes a time of day but says nothing about which day.
    (re.compile(rf"(?P<time>{_CLOCK}\s*{_MERIDIEM})"), "time_only"),
]

# Kept for callers that only need "does this look like a date"; the rules above drive parsing.
DATE_PATTERNS = [pattern for pattern, _ in TIMESTAMP_RULES]

# A chat screen prints a calendar divider once and then switches to relative words. Everything
# after "Today" belongs to an unstated day, so the earlier divider must not be reused as its date.
RELATIVE_DAY_PATTERN = re.compile(r"\b(?:today|yesterday|aaj|kal)\b", re.IGNORECASE)

MIN_PLAUSIBLE_AMOUNT = 1
# A number with no currency marker beside it is only treated as an amount above this floor.
# Below it the digits are far more likely to be a count, an index or part of an identifier.
MIN_BARE_AMOUNT = 100
MAX_BARE_AMOUNT_DIGITS = 9

# OCR renders the rupee sign as whatever glyph is closest. These count as a currency marker only
# when they touch the digits, so "Total = 500" stays a bare number while "=12,000" is INR 12,000.
OCR_RUPEE_GLYPHS = "=%¥₩₹"

# Words that establish a number is money. Without a currency marker *and* without one of these on
# the same line, digits are just digits — "SYNTHETIC-ACCOUNT-8233 212,000" is an account row, not a
# payment, and reading it as one invents a transaction that the evidence never recorded.
MONEY_CONTEXT_PATTERN = re.compile(
    r"\b(?:paid|pay|pays|payment|sent|send|sending|bhej\w*|bheja|transferr?\w*|"
    r"debit\w*|credit\w*|amount|amt|balance|bal|fee|fees|charge[sd]?|refund\w*|"
    r"deposit\w*|withdraw\w*|receiv\w*|total|due|paise|rupay\w*|rupees?|remit\w*|"
    r"invoice|price|cost|cash|worth)\b",
    re.IGNORECASE,
)


# What a figure IS, not merely that it is money. "Your balance is now INR 29,500" and "Paid to
# Release Desk 12,000" are both amounts; only one of them is money that moved. Reading every figure
# as a transaction put a balance quoted in an email into the transaction trail as though someone had
# transferred it, which is precisely the kind of claim the evidence does not make.
AMOUNT_ROLE_PATTERNS = (
    ("balance", re.compile(r"\b(?:closing|available|avl|current|opening)?\s*(?:balance|bal|wallet|holdings?|corpus)\b", re.IGNORECASE)),
    ("payment", re.compile(r"\b(?:paid|sent|debited|credited|transferred|remitted|withdrawn|deposited|received)\b", re.IGNORECASE)),
    ("fee", re.compile(r"\b(?:fees?|charges?|commission|penalty|fine|tax|gst)\b", re.IGNORECASE)),
    ("request", re.compile(r"\b(?:pay|send|transfer|remit|deposit|requires?|required|needs?|due|payable)\b", re.IGNORECASE)),
)
AMOUNT_ROLE_UNKNOWN = "unknown"


def classify_amount_role(text: str, quote: str, *, index: int | None = None) -> str:
    """Say what the figure is, judged only by the words printed beside it.

    The line carrying the amount is the whole evidence. A word elsewhere on the page describes a
    different figure, and borrowing it would be the same guess this module exists to refuse.

    `index` is where the figure actually matched. Without it the first textual occurrence of the
    quote has to stand in, and a page that prints the same figure twice — an email subject and its
    body — would be classified from the wrong line.
    """
    if index is None:
        index = text.find(quote)
    line = _line_around(text, max(index, 0))
    for role, pattern in AMOUNT_ROLE_PATTERNS:
        if pattern.search(line):
            return role
    return AMOUNT_ROLE_UNKNOWN


def _line_around(text: str, index: int) -> str:
    """The single line a match sits on. Money context has to be adjacent to be evidence of money."""
    start = text.rfind("\n", 0, index) + 1
    end = text.find("\n", index)
    return text[start:] if end == -1 else text[start:end]


def normalize_phone(value: str) -> str:
    digits = re.sub(r"\D", "", value)
    return "+91" + digits[-10:] if len(digits) >= 10 else value.strip()


def normalize_identifier(entity_type: str, value: str) -> str:
    value = value.strip()
    if entity_type == "phone":
        return normalize_phone(value)
    if entity_type in {"email", "upi_id", "url", "ifsc", "utr", "transaction_reference"}:
        return value.lower().rstrip(".,;:)")
    if entity_type in {"account_number", "device_identifier"}:
        return re.sub(r"[\s-]", "", value)
    return value


def find_phone_numbers(text: str) -> list[str]:
    return sorted({normalize_phone(match.group(0)) for match in PHONE_PATTERN.finditer(text)})


def find_email_addresses(text: str) -> list[str]:
    return sorted({match.group(0).lower() for match in EMAIL_PATTERN.finditer(text)})


def find_account_identifiers(text: str) -> list[str]:
    found = {match.group(1) for match in ACCOUNT_PATTERN.finditer(text)}
    found |= {match.group(0).upper() for match in IFSC_PATTERN.finditer(text)}
    for match in UPI_PATTERN.finditer(text):
        candidate = match.group(0)
        if not EMAIL_PATTERN.fullmatch(candidate):
            found.add(candidate.lower())
    return sorted(found)


def find_transaction_reference(text: str) -> str | None:
    match = UTR_PATTERN.search(text)
    return match.group(1).strip() if match else None


def find_device_identifier(text: str) -> str | None:
    match = DEVICE_PATTERN.search(text)
    return match.group(1).strip() if match else None


# A phone number written in groups, including OCR misreads of the country code such as
# "+9] 87072 93840". The strict phone pattern cannot match those, and without this guard the middle
# group gets read as a rupee amount.
GROUPED_DIGITS_PATTERN = re.compile(r"(?<!\d)\d{4,6}[\s-]\d{4,6}(?!\d)")


def _protected_spans(text: str) -> list[tuple[int, int]]:
    """Character ranges that belong to an identifier or a date, not to a monetary amount.

    Without this, the digits inside `HDFC0012345678` or `12 Mar 2024` get read as rupee values.
    """
    spans: list[tuple[int, int]] = []
    for pattern in (PHONE_PATTERN, UTR_PATTERN, ACCOUNT_PATTERN, IFSC_PATTERN, EMAIL_PATTERN, UPI_PATTERN, URL_PATTERN, DEVICE_PATTERN, *DATE_PATTERNS):
        spans.extend((match.start(), match.end()) for match in pattern.finditer(text))
    for match in GROUPED_DIGITS_PATTERN.finditer(text):
        if sum(character.isdigit() for character in match.group(0)) >= 10:
            spans.append((match.start(), match.end()))
    return spans


def find_amount_detail(text: str, *, declared_monetary: bool = False) -> tuple[float, str | None, str, str] | None:
    """Return (value, currency, exact quote, role) for the first plausible amount.

    Currency stays `None` when the source shows only a bare number. Assuming INR because the case
    is Indian would be exactly the kind of common-sense filling the evidence rules forbid.

    `declared_monetary` is for callers reading a cell the source itself labelled as money — a bank
    statement column headed "Amount". There the header is the evidence that the digits are money,
    so the surrounding-words check would only reject a value the source has already declared.
    """
    protected = _protected_spans(text)
    for match in AMOUNT_PATTERN.finditer(text):
        raw_value = match.group("value")
        if not raw_value or not any(character.isdigit() for character in raw_value):
            continue
        start, end = match.span("value")
        if any(begin < end and start < finish for begin, finish in protected):
            continue
        if start > 0 and (text[start - 1].isalnum() or text[start - 1] in "_-/"):
            continue
        if end < len(text) and (text[end].isalnum() or text[end] in "_-/"):
            continue
        try:
            value = float(Decimal(raw_value.replace(",", "")))
        except InvalidOperation:
            continue
        if value < MIN_PLAUSIBLE_AMOUNT:
            continue

        marker = (match.group("currency") or match.group("trailing") or "").strip().lower().rstrip(".")
        currency = CURRENCY_SYMBOLS.get(marker) or ("INR" if marker in {"rupees", "rupaye"} else None)
        quote = match.group(0).strip()

        if currency is None and start > 0 and text[start - 1] in OCR_RUPEE_GLYPHS:
            # OCR reduces the rupee sign to whatever glyph is nearest in shape. Touching the digits
            # is what makes it a marker: "=12,000" is a price tag, "Total = 500" is not.
            currency = "INR"
            quote = text[start - 1 : end]

        if currency is None:
            digits = raw_value.replace(",", "").split(".")[0]
            if value < MIN_BARE_AMOUNT or len(digits) > MAX_BARE_AMOUNT_DIGITS:
                continue
            if not declared_monetary and not MONEY_CONTEXT_PATTERN.search(_line_around(text, start)):
                # No currency marker and no money word on the line. "SYNTHETIC-ACCOUNT-8233 212,000"
                # is an account row; calling it a payment invents a transaction the source never
                # recorded, which is the single worst thing this extractor can do.
                continue
        return value, currency, quote, classify_amount_role(text, quote, index=start)
    return None


def find_amount(text: str, *, declared_monetary: bool = False) -> tuple[float, str | None, str] | None:
    """The amount alone, for callers that do not care what kind of figure it is."""
    found = find_amount_detail(text, declared_monetary=declared_monetary)
    return (found[0], found[1], found[2]) if found else None


def _relative_day_supersedes(scope: str, raw: str) -> bool:
    """True when a "Today"/"Yesterday" divider appears after this calendar date in the source.

    A chat screen prints the date once and then switches to relative words, so the messages below
    such a divider belong to an unstated day. Reusing the earlier date for them is a fabrication.
    """
    position = scope.find(raw)
    if position == -1:
        return False
    return RELATIVE_DAY_PATTERN.search(scope, position + len(raw)) is not None


def _parse_moment(date_text: str, time_text: str | None, offset: str | None) -> datetime | None:
    candidate = " ".join(part.strip() for part in (date_text, time_text, offset) if part)
    try:
        parsed = date_parser.parse(candidate, dayfirst=True, fuzzy=False)
    except (ValueError, OverflowError):
        return None
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)


def find_timestamp(text: str, *, context: str | None = None) -> tuple[datetime | None, str | None, str]:
    """Return (parsed UTC datetime, exact quote, precision).

    Two readings are deliberately refused rather than guessed. A clock with no date beside it
    yields `None` — the time of day is observed, the day is not, and letting the parser default the
    date to today is how a 5:58 pm email ended up stamped with the day the report was generated.
    A calendar date that a later "Today" divider supersedes is skipped for the same reason.

    `context` is the wider source the text was cut from; the divider check reads it so a per-block
    scan still sees the divider that appears further down the same screenshot.
    """
    scope = text if context is None else context
    for pattern, precision in TIMESTAMP_RULES:
        for match in pattern.finditer(text):
            raw = match.group(0).strip()
            if precision == "time_only":
                return None, raw, "time_only"
            groups = match.groupdict()
            if precision == "date_only" and _relative_day_supersedes(scope, raw):
                continue
            parsed = _parse_moment(groups.get("date") or raw, groups.get("time"), groups.get("tz"))
            if parsed is None:
                continue
            return parsed, raw, precision
    return None, None, "unknown"
