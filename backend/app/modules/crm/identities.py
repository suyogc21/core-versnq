"""Normalising the ways to reach a lead (rule R7): phones to E.164 with the company's default
country, emails trimmed and lowercased (Gmail dots kept), LinkedIn profile URLs tidied."""

import re

import phonenumbers

from app.core.errors import Invalid

EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
LINKEDIN = re.compile(
    r"^(?:https?://)?(?:[a-z]{2,3}\.)?linkedin\.com/(in|company)/([^/?#\s]+)/?", re.I
)
TYPES = ("email", "phone", "linkedin")


def normalize(kind: str, value: str, default_country: str) -> str:
    value = (value or "").strip()
    if not value:
        raise Invalid(f"Enter a {kind}")
    if kind == "email":
        if not EMAIL.match(value) or len(value) > 320:
            raise Invalid(f"'{value}' is not a valid email")
        return value.lower()
    if kind == "phone":
        try:
            number = phonenumbers.parse(value, default_country.upper())
        except phonenumbers.NumberParseException:
            raise Invalid(f"'{value}' is not a valid phone number") from None
        if not phonenumbers.is_valid_number(number):
            raise Invalid(f"'{value}' is not a valid phone number")
        return phonenumbers.format_number(number, phonenumbers.PhoneNumberFormat.E164)
    if kind == "linkedin":
        match = LINKEDIN.match(value)
        if not match:
            raise Invalid("Enter a LinkedIn profile link like linkedin.com/in/name")
        return f"https://www.linkedin.com/{match.group(1).lower()}/{match.group(2).lower()}"
    raise Invalid(f"Unknown identifier type: {kind}")
