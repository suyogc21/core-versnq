"""Exact money (rule 7): integer minor units plus an ISO 4217 currency code. No floats.

A currency's exponent is how many minor-unit digits it has: INR 2 (paise), JPY 0, KWD 3.
"""

from app.core.errors import Invalid

# ISO 4217 active codes with a non-default exponent. Every other listed code has 2.
_EXPONENT = {
    **dict.fromkeys(
        "BIF CLP DJF GNF ISK JPY KMF KRW PYG RWF UGX UYI VND VUV XAF XOF XPF".split(), 0
    ),
    **dict.fromkeys("BHD IQD JOD KWD LYD OMR TND".split(), 3),
    **dict.fromkeys("CLF UYW".split(), 4),
}
_TWO = (
    "AED AFN ALL AMD ANG AOA ARS AUD AWG AZN BAM BBD BDT BGN BMD BND BOB BRL BSD BTN BWP BYN "
    "BZD CAD CDF CHF CNY COP CRC CUP CVE CZK DKK DOP DZD EGP ERN ETB EUR FJD FKP GBP GEL GHS "
    "GIP GMD GTQ GYD HKD HNL HTG HUF IDR ILS INR IRR JMD KES KGS KHR KPW KYD KZT LAK LBP LKR "
    "LRD LSL MAD MDL MGA MKD MMK MNT MOP MRU MUR MVR MWK MXN MYR MZN NAD NGN NIO NOK NPR NZD "
    "PAB PEN PGK PHP PKR PLN QAR RON RSD RUB SAR SBD SCR SDG SEK SGD SHP SLE SOS SRD SSP STN "
    "SVC SYP SZL THB TJS TMT TOP TRY TTD TWD TZS UAH USD UYU UZS VES WST XCD YER ZAR ZMW ZWL"
).split()
EXPONENT: dict[str, int] = {**dict.fromkeys(_TWO, 2), **_EXPONENT}

# A company's starting currency from its country; anything else starts in USD (editable).
COUNTRY_CURRENCY = {"IN": "INR", "AE": "AED", "US": "USD", "GB": "GBP", "SG": "SGD", "AU": "AUD"}

# Ceiling for any one amount (a deal, a line, a price): far above any real sale, and keeps
# quantity × price well inside Postgres bigint.
MAX_MINOR = 10**15
MAX_QUANTITY = 100_000


def currency(code: str) -> str:
    code = (code or "").strip().upper()
    if code not in EXPONENT:
        raise Invalid(f"Unknown currency: {code or '—'}")
    return code


def for_country(country: str | None) -> str:
    return COUNTRY_CURRENCY.get((country or "").upper(), "USD")


def check_amount(minor: int, what: str = "Amount") -> int:
    if not isinstance(minor, int) or isinstance(minor, bool):
        raise Invalid(f"{what} must be a whole number of minor units")
    if minor < 0:
        raise Invalid(f"{what} cannot be negative")
    if minor > MAX_MINOR:
        raise Invalid(f"{what} is too large")
    return minor


def line_total(quantity: int, unit_price_minor: int, discount_minor: int) -> int:
    """quantity × unit price − discount, exactly. The discount cannot exceed the line."""
    if not 1 <= quantity <= MAX_QUANTITY:
        raise Invalid(f"Quantity must be between 1 and {MAX_QUANTITY}")
    check_amount(unit_price_minor, "Price")
    check_amount(discount_minor, "Discount")
    gross = quantity * unit_price_minor
    if discount_minor > gross:
        raise Invalid("The discount is more than the line")
    return check_amount(gross - discount_minor, "Line total")


def weighted(amount_minor: int, probability: int) -> int:
    """amount × probability %, rounded half up to a whole minor unit."""
    return (amount_minor * probability * 2 + 100) // 200
