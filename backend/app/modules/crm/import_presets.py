"""Ready-made column matches for CRM exports (finishing plan, batch 2): a HubSpot or
LeadSquared export imports without matching columns by hand.

The header names below are the common ones in those products' contact / lead exports. Exact
headers vary by account, language and the properties a company chose to export, so they are
matched ignoring case, spaces and punctuation, and the person can still change every match.
They must be checked against one real export file before this is called done.

A detected preset also turns on "keep unknown values in a note": a stage, owner or source
that isn't in Core doesn't fail the row; the row gets the default instead and the original
value is kept in the lead's first note (see imports._row).
"""

import re

from app.modules.crm import mapping as MP


def key(header: str) -> str:
    """Headers compared without case, spaces or punctuation: "State/Region" == "state region"."""
    return re.sub(r"[^a-z0-9]", "", header.lower())


# preset -> header key -> target. Several headers may share a target (e.g. two phones, notes).
PRESETS: dict[str, dict[str, str]] = {
    "hubspot": {
        "recordid": "external_id",
        "contactid": "external_id",
        "firstname": "first_name",
        "lastname": "last_name",
        "email": "email",
        "emailaddress": "email",
        "phonenumber": "phone",
        "mobilephonenumber": "phone",
        "companyname": "org_name",
        "company": "org_name",
        "website": "website",
        "websiteurl": "website",
        "industry": "industry",
        "city": "city",
        "stateregion": "region",
        "state": "region",
        "lifecyclestage": "stage",
        "leadstatus": "message",
        "contactowner": "owner_email",
        "hubspotowner": "owner_email",
        "hubspotowneremail": "owner_email",
        "originalsource": "source",
        "countryregion": "message",
        "country": "message",
        "createdate": "message",
        "jobtitle": "message",
    },
    "leadsquared": {
        "prospectid": "external_id",
        "leadnumber": "external_id",
        "firstname": "first_name",
        "lastname": "last_name",
        "emailaddress": "email",
        "email": "email",
        "phonenumber": "phone",
        "phone": "phone",
        "mobilenumber": "phone",
        "mobile": "phone",
        "company": "org_name",
        "companyname": "org_name",
        "website": "website",
        "city": "city",
        "state": "region",
        "leadstage": "stage",
        "prospectstage": "stage",
        "leadsource": "source",
        "source": "source",
        "owner": "owner_email",
        "leadowner": "owner_email",
        "owneremail": "owner_email",
        "country": "message",
        "createdon": "message",
        "jobtitle": "message",
        "notes": "message",
    },
}

# Headers only these products use: what tells their exports apart from any other CSV.
MARKERS: dict[str, set[str]] = {
    "hubspot": {
        "recordid", "lifecyclestage", "contactowner", "hubspotowner", "originalsource",
        "createdate", "stateregion", "countryregion", "leadstatus",
    },
    "leadsquared": {
        "prospectid", "leadnumber", "leadstage", "prospectstage", "leadowner", "createdon",
        "leadsource", "mobilenumber",
    },
}  # fmt: skip
NAMES = {"hubspot": "HubSpot", "leadsquared": "LeadSquared"}
REPEATABLE = {"phone", "email", "message"}  # targets several columns may feed


def detect(headers: list[str]) -> str | None:
    """The product that made this file: at least two of its own headers, more than the other."""
    keys = {key(h) for h in headers}
    scores = {name: len(keys & marks) for name, marks in MARKERS.items()}
    best = max(scores, key=lambda n: scores[n])
    others = [s for n, s in scores.items() if n != best]
    if scores[best] >= 2 and all(scores[best] > s for s in others):
        return best
    return None


def suggest(preset: str, headers: list[str], generic: dict[str, str]) -> dict[str, str]:
    """The preset's matches first; columns it doesn't know keep the usual by-name guess."""
    table = PRESETS[preset]
    allowed = set(MP.BUILTIN_TARGETS) | set(MP.IMPORT_ONLY_TARGETS)
    out: dict[str, str] = {}
    used: set[str] = set()
    for h in headers:
        target = table.get(key(h))
        if target and target in allowed and (target not in used or target in REPEATABLE):
            out[h] = target
            used.add(target)
    for h, target in generic.items():
        if h not in out and (target not in used or target in REPEATABLE):
            out[h] = target
            used.add(target)
    return out
