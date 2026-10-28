"""Input and output guardrails shared by every chat path.

* Input checks: size limits, control characters and obvious prompt-injection
  or destructive-intent phrases.
* Output checks: PII masking for database results before they reach an LLM
  or the browser.

These checks complement, not replace, the query validator in
``backend/validator.py``, which remains the authority on what may run
against VeloDB.
"""

import re

from backend.config import settings

INJECTION_PATTERNS = [
    r"ignore (all |any )?(the )?(previous|prior|above) (instructions|rules|prompts?)",
    r"disregard (all |any )?(the )?(previous|prior|above|system) (instructions|rules|prompts?)",
    r"(reveal|print|show|repeat) (me )?(your|the) (system|hidden) prompt",
    r"you are now (in )?(developer|dan|jailbreak) mode",
    r"\b(api[_ ]?key|secret[_ ]?key|password hash|connection string)\b",
]

DESTRUCTIVE_PATTERNS = [
    r"\b(drop|truncate)\s+(the\s+)?(database|table|schema|collection)s?\b",
    r"\b(delete|remove|wipe|erase)\s+(all\s+)?(the\s+)?(records|rows|documents|data|tables?|collections?)\b",
    r"\b(update|modify|insert|overwrite)\s+(the\s+)?(records|rows|documents|database|tables?|collections?)\b",
    # SQL DDL/DML and injection markers, for the VeloDB backend.
    r"\b(drop|truncate|alter|grant|revoke)\s+(table|database|schema|user)\b",
    r"\binto\s+outfile\b|\bload\s+data\b|\bunion\s+all\s+select\b|;\s*(drop|delete|update|insert)\b",
    # MongoDB phrasing is still blocked. The warehouse no longer speaks it,
    # but a user can still type it, and it is still destructive intent.
    r"\$where|\$function|\$out\b|\$merge\b|db\.\w+\.(drop|remove|delete|update|insert)",
]

_INJECTION_RE = [re.compile(p, re.IGNORECASE) for p in INJECTION_PATTERNS]
_DESTRUCTIVE_RE = [re.compile(p, re.IGNORECASE) for p in DESTRUCTIVE_PATTERNS]
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


class GuardrailViolation(ValueError):
    """Raised when a request must be refused before any model or tool runs."""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.message = message


def check_question(question):
    """Validate and normalise a user question.

    Returns the cleaned question or raises ``GuardrailViolation``.
    """

    text = _CONTROL_CHARS.sub("", str(question or "")).strip()

    if not text:
        raise GuardrailViolation("empty", "Please enter a question.")

    if len(text) > settings.max_question_chars:
        raise GuardrailViolation(
            "too_long",
            f"Questions are limited to {settings.max_question_chars} characters.",
        )

    if any(pattern.search(text) for pattern in _INJECTION_RE):
        raise GuardrailViolation(
            "prompt_injection",
            "This request tries to change the assistant's instructions or "
            "obtain secrets, so it was not processed.",
        )

    if any(pattern.search(text) for pattern in _DESTRUCTIVE_RE):
        raise GuardrailViolation(
            "write_operation",
            "The chatbot has read-only access to the data. It cannot delete, "
            "update, insert or drop records.",
        )

    return text


# --------------------------------------------------
# PII masking
# --------------------------------------------------

PII_FIELD_PATTERN = re.compile(
    r"(e[-_]?mail|phone|mobile|contact_number|address|street|zip|postal|"
    r"password|passwd|ssn|social_security|national_id|passport|"
    r"credit_card|card_number|iban|account_number|dob|date_of_birth|birth_date)",
    re.IGNORECASE,
)

EMAIL_VALUE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
PHONE_VALUE = re.compile(r"(?<!\d)(\+?\d[\d\s().-]{8,}\d)(?!\d)")


def _mask(value):
    text = str(value)
    if EMAIL_VALUE.fullmatch(text):
        name, _, domain = text.partition("@")
        return f"{name[:1]}***@{domain}"
    if len(text) <= 4:
        return "***"
    return f"{text[:2]}***{text[-2:]}"


def _redact_value(key, value):
    if isinstance(value, dict):
        return {k: _redact_value(k, v) for k, v in value.items()}

    if isinstance(value, list):
        return [_redact_value(key, item) for item in value]

    if key and PII_FIELD_PATTERN.search(str(key)) and value not in (None, ""):
        return _mask(value)

    if isinstance(value, str):
        value = EMAIL_VALUE.sub(lambda m: _mask(m.group(0)), value)

    return value


def redact_pii(records):
    """Mask personal data in query results (column names and e-mail values)."""

    if not settings.redact_pii:
        return records

    return _redact_value(None, records)
