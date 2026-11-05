import pytest

from app.platform.tenants.slugs import InvalidSlug, validate_slug


@pytest.mark.parametrize("slug", ["acme", "acme-edu", "a1b", "x" * 30])
def test_valid_slug_accepted(slug):
    assert validate_slug(slug) == slug


@pytest.mark.parametrize(
    "slug", ["Acme", "ac me", "ab", "x" * 31, "1acme", "-acme", "acme-", "admin", "www", "api"]
)
def test_invalid_slugs_rejected(slug):
    with pytest.raises(InvalidSlug):
        validate_slug(slug)
