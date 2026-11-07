import pytest

from app.core.errors import Invalid
from app.modules.crm.identities import normalize


@pytest.mark.parametrize(
    ("value", "country", "expected"),
    [
        ("98765 43210", "IN", "+919876543210"),
        ("+91 98765-43210", "AE", "+919876543210"),
        ("050 123 4567", "AE", "+971501234567"),
        ("(415) 555-2671", "US", "+14155552671"),
        ("+44 20 7946 0958", "IN", "+442079460958"),
    ],
)
def test_phones_become_international_format(value, country, expected):
    assert normalize("phone", value, country) == expected


def test_email_and_linkedin_are_tidied():
    assert normalize("email", "  Rahul.K@Gmail.com ", "IN") == "rahul.k@gmail.com"  # dots kept
    assert (
        normalize("linkedin", "linkedin.com/in/Rahul-K/", "IN")
        == "https://www.linkedin.com/in/rahul-k"
    )


@pytest.mark.parametrize(
    ("kind", "value"), [("phone", "12345"), ("email", "not-an-email"), ("linkedin", "x.com/rahul")]
)
def test_bad_identifiers_are_refused(kind, value):
    with pytest.raises(Invalid):
        normalize(kind, value, "IN")
