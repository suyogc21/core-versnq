"""Grouping people under their organisation (Decision log #14, DM1).

Signals: the email/website domain (strong) and the company name (weaker). Free email
providers never match. Company-name matches are only ever suggestions; a company may let
domain matches link automatically. Off by default. Never crosses companies (RLS).
"""

import re
import uuid
from dataclasses import dataclass
from urllib.parse import urlparse

from sqlalchemy import func, or_, select, true
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Invalid
from app.modules.auth.deps import CurrentUser
from app.modules.crm import leads as L
from app.modules.crm.models import Lead, LeadIdentity
from app.modules.settings.models import TenantSettings

FREE_EMAIL = {
    "gmail.com", "googlemail.com", "yahoo.com", "yahoo.co.in", "yahoo.in", "ymail.com",
    "outlook.com", "hotmail.com", "live.com", "msn.com", "icloud.com", "me.com", "mac.com",
    "rediffmail.com", "aol.com", "proton.me", "protonmail.com", "zoho.com", "zohomail.in",
    "gmx.com", "mail.com", "yandex.com",
}  # fmt: skip
SUFFIXES = re.compile(
    r"\b(pvt|private|ltd|limited|llp|llc|inc|incorporated|corp|corporation|co|company|gmbh|"
    r"plc|fze|fzco|fz-llc)\b\.?",
    re.I,
)


def domain_of(value: str | None) -> str | None:
    """'rahul@Acme.com' → 'acme.com'; 'https://www.acme.com/x' → 'acme.com'. None for free mail."""
    if not value:
        return None
    value = value.strip().lower()
    if "@" in value:
        host = value.rsplit("@", 1)[1]
    else:
        host = urlparse(value if "://" in value else f"https://{value}").hostname or ""
    host = host.removeprefix("www.")
    if "." not in host or host in FREE_EMAIL:
        return None
    return host


def company_key(name: str | None) -> str | None:
    if not name:
        return None
    key = re.sub(r"[^a-z0-9 ]", " ", SUFFIXES.sub(" ", name.lower()))
    key = " ".join(key.split())
    return key or None


@dataclass
class Suggestion:
    organisation: Lead
    reason: str  # domain / name


async def suggestions(db: AsyncSession, lead: Lead, visible) -> list[Suggestion]:
    """Organisations this person may belong to (only ones the viewer can see)."""
    if lead.kind != "person" or lead.organisation_id:
        return []
    mode = await db.scalar(
        select(TenantSettings.org_grouping).where(TenantSettings.tenant_id == lead.tenant_id)
    )
    if mode == "off":
        return []
    dismissed = {uuid.UUID(i) for i in lead.org_suggestions_dismissed or []}
    found: dict[uuid.UUID, Suggestion] = {}
    emails = (
        await db.scalars(
            select(LeadIdentity.value_normalized).where(
                LeadIdentity.lead_id == lead.id, LeadIdentity.type == "email"
            )
        )
    ).all()
    domains = {d for d in (domain_of(e) for e in emails) if d}
    if domains:
        for org in await _orgs_with_domains(db, domains, visible):
            found.setdefault(org.id, Suggestion(org, "domain"))
    key = company_key(lead.org_name)
    if key:
        orgs = (
            await db.scalars(
                select(Lead)
                .where(Lead.kind == "organisation", visible)
                .where(func.lower(Lead.org_name).contains(key.split()[0]))
                .limit(50)
            )
        ).all()
        for org in orgs:
            if company_key(org.org_name) == key:
                found.setdefault(org.id, Suggestion(org, "name"))
    return [s for s in found.values() if s.organisation.id not in dismissed][:5]


async def _orgs_with_domains(db: AsyncSession, domains: set[str], visible) -> list[Lead]:
    patterns = [Lead.website.ilike(f"%{d}%") for d in domains]
    email_ids = select(LeadIdentity.lead_id).where(
        LeadIdentity.type == "email",
        or_(*[LeadIdentity.value_normalized.like(f"%@{d}") for d in domains]),
    )
    rows = (
        await db.scalars(
            select(Lead)
            .where(Lead.kind == "organisation", visible)
            .where(or_(*patterns, Lead.id.in_(email_ids)))
            .limit(50)
        )
    ).all()
    out = []
    for org in rows:  # the LIKE is a pre-filter; confirm the exact domain
        org_domains = {domain_of(org.website)}
        org_domains |= {
            domain_of(e)
            for e in (
                await db.scalars(
                    select(LeadIdentity.value_normalized).where(
                        LeadIdentity.lead_id == org.id, LeadIdentity.type == "email"
                    )
                )
            ).all()
        }
        if org_domains & domains:
            out.append(org)
    return out


async def link(
    db: AsyncSession, person: Lead, org: Lead | None, actor: CurrentUser | None, *, auto=False
) -> None:
    if person.kind != "person":
        raise Invalid("Only a person can be linked to an organisation")
    if org is not None and org.kind != "organisation":
        raise Invalid("Choose an organisation")
    new_id = org.id if org else None
    if new_id == person.organisation_id:
        return
    person.organisation_id = new_id
    summary = (
        f"{'Automatically linked' if auto else 'Linked'} to {org.display_name}"
        if org
        else "Unlinked from organisation"
    )
    await L.log(
        db,
        person,
        "organisation_linked",
        summary,
        actor,
        {"organisation_id": str(new_id) if new_id else None},
    )
    await L.event(db, person, "lead.updated", {"fields": ["organisation"]})


async def on_new_person(db: AsyncSession, lead: Lead) -> None:
    """At capture: link automatically when the company allows it and exactly one organisation
    shares the person's email domain."""
    mode = await db.scalar(
        select(TenantSettings.org_grouping).where(TenantSettings.tenant_id == lead.tenant_id)
    )
    if mode != "auto" or lead.kind != "person" or lead.organisation_id:
        return
    domains = {d for d in [domain_of(lead.primary_email)] if d}
    if not domains:
        return
    orgs = await _orgs_with_domains(db, domains, true())
    if len(orgs) == 1:
        await link(db, lead, orgs[0], None, auto=True)
