"""Workspace slugs: the <slug> in <slug>.<BASE_DOMAIN>."""

import re

RESERVED = frozenset(
    {"www", "app", "api", "admin", "platform", "mail", "static", "assets", "auth", "docs", "status"}
)
_PATTERN = re.compile(r"^[a-z][a-z0-9-]{1,28}[a-z0-9]$")


class InvalidSlug(ValueError):
    pass


def validate_slug(slug: str) -> str:
    if not _PATTERN.match(slug):
        raise InvalidSlug(
            "Use 3-30 lowercase letters, digits or hyphens, starting with a letter "
            "and not ending with a hyphen"
        )
    if slug in RESERVED:
        raise InvalidSlug(f"'{slug}' is reserved")
    return slug
