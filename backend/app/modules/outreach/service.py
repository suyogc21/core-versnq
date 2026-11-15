"""Outreach (step O2, Decision log #44): cold contacts and campaigns, kept apart from leads.

The promise: "Already your lead? Never a cold email." A contact whose email is a lead (or a
customer, who is a lead too) is skipped at import and checked again before every send; anyone
who unsubscribes, bounces or complains is blocked for the whole company. A reply stops that
person in that campaign; "Convert to lead" moves them, and their whole thread, into the CRM.
"""

import re
import uuid
from dataclasses import dataclass, field

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Invalid, NotFound
from app.core.events import emit
from app.modules.auth.deps import CurrentUser, has_permission
from app.modules.crm import consent as C
from app.modules.crm import intake as I
from app.modules.crm import leads as L
from app.modules.crm.imports import read_csv
from app.modules.crm.models import Lead, LeadIdentity, LeadSource
from app.modules.engage import render as R
from app.modules.engage.models import Conversation, Mailbox, Message
from app.modules.outreach.models import Campaign, CampaignContact, CampaignStep, Contact

ADMINS = ("owner", "admin")
MAX_ROWS = 20_000
MAX_VARIANTS = 5
MAX_STEPS = 10
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
FIELDS = ("email", "first_name", "last_name", "company", "title", "phone", "website")
STANDARD_VARS = frozenset({*FIELDS, "name", "sender_name", "my_company"})
# CSV header words that map to a field without the person choosing
GUESS = {
    "email": "email", "e-mail": "email", "email address": "email", "work email": "email",
    "first name": "first_name", "firstname": "first_name", "first_name": "first_name",
    "last name": "last_name", "lastname": "last_name", "last_name": "last_name",
    "surname": "last_name", "company": "company", "company name": "company",
    "organisation": "company", "organization": "company", "title": "title",
    "job title": "title", "designation": "title", "phone": "phone", "mobile": "phone",
    "phone number": "phone", "website": "website", "url": "website", "domain": "website",
}  # fmt: skip
OPEN = ("pending", "active")  # a campaign contact still to be emailed
DEFAULT_SCHEDULE = {"days": [0, 1, 2, 3, 4], "from": "09:00", "to": "18:00"}


def var_key(name: str) -> str:
    """A CSV column name as a variable name: 'Pain point' -> pain_point."""
    key = re.sub(r"[^a-z0-9]+", "_", name.strip().lower()).strip("_")
    return key[:60] or "column"


def values_for(contact: Contact, sender_name: str, company: str) -> dict[str, str | None]:
    v: dict[str, str | None] = {f: getattr(contact, f) for f in FIELDS}
    v |= {"name": contact.name, "sender_name": sender_name, "my_company": company}
    for k, val in (contact.variables or {}).items():
        v.setdefault(k, None if val is None else str(val))
    return v


# ---------- who sees what ----------
def sees_all(actor: CurrentUser) -> bool:
    return actor.role.key in ADMINS or has_permission(actor.permissions, "campaigns.manage")


def campaign_filter(actor: CurrentUser):
    """SQL condition: campaigns this person may see (all with campaigns.manage, else own)."""
    if sees_all(actor):
        return Campaign.id.isnot(None)
    return Campaign.owner_user_id == actor.user.id


async def get_campaign(db: AsyncSession, actor: CurrentUser, campaign_id: uuid.UUID) -> Campaign:
    c = await db.scalar(select(Campaign).where(Campaign.id == campaign_id, campaign_filter(actor)))
    if c is None:
        raise NotFound("Campaign not found")
    return c


def conversation_filter(actor: CurrentUser):
    """SQL condition: campaign conversations (no lead yet) this person may see."""
    seen = select(Campaign.id).where(campaign_filter(actor))
    return (Conversation.lead_id.is_(None)) & (Conversation.campaign_id.in_(seen))


# ---------- the lead check ----------
async def lead_for_email(db: AsyncSession, address: str) -> Lead | None:
    return await db.scalar(
        select(Lead)
        .join(LeadIdentity, LeadIdentity.lead_id == Lead.id)
        .where(LeadIdentity.type == "email", LeadIdentity.value_normalized == address.lower())
        .order_by(Lead.created_at)
        .limit(1)
    )


async def _lead_emails(db: AsyncSession, addresses: set[str]) -> set[str]:
    if not addresses:
        return set()
    rows = await db.scalars(
        select(LeadIdentity.value_normalized).where(
            LeadIdentity.type == "email", LeadIdentity.value_normalized.in_(addresses)
        )
    )
    return set(rows.all())


async def _suppressed(db: AsyncSession, addresses: set[str]) -> set[str]:
    from app.modules.crm.models import Suppression

    if not addresses:
        return set()
    rows = await db.scalars(
        select(Suppression.value_normalized).where(
            Suppression.channel == "email", Suppression.value_normalized.in_(addresses)
        )
    )
    return set(rows.all())


# ---------- stopping ----------
async def stop(db: AsyncSession, contact_id: uuid.UUID, status: str, reason: str, *,
               campaign_id: uuid.UUID | None = None) -> None:  # fmt: skip
    """End the contact's open places in every campaign (or one campaign)."""
    q = (
        update(CampaignContact)
        .where(CampaignContact.contact_id == contact_id, CampaignContact.status.in_(OPEN))
        .values(status=status, ended_reason=reason, next_run_at=None)
    )
    if campaign_id is not None:
        q = q.where(CampaignContact.campaign_id == campaign_id)
    await db.execute(q)


async def contact_opted_out(db: AsyncSession, contact_id: uuid.UUID, reason: str) -> None:
    """Unsubscribe, hard bounce or spam complaint on a campaign email: the address is already
    suppressed for the company (engine._opt_out); the contact stops everywhere."""
    contact = await db.get(Contact, contact_id)
    if contact is None:
        return
    status = "bounced" if reason == "bounce" else "unsubscribed"
    if contact.status == "active":
        contact.status = status
    await stop(db, contact_id, status, {"bounce": "bounced", "complaint": "complaint"}.get(
        reason, "unsubscribed"))  # fmt: skip


async def became_lead(db: AsyncSession, contact: Contact, lead: Lead) -> None:
    """The person is already ours: never a cold email again."""
    contact.status, contact.lead_id = "converted", lead.id
    await stop(db, contact.id, "stopped", "already_lead")


# ---------- import ----------
@dataclass
class ImportReport:
    rows: int = 0
    added: int = 0
    duplicates_in_file: int = 0
    invalid_email: int = 0
    already_lead: int = 0
    suppressed: int = 0
    already_in_campaign: int = 0
    variables: list[str] = field(default_factory=list)
    problems: list[dict] = field(default_factory=list)  # first 50: {row, email, reason}


def guess_mapping(header: list[str]) -> dict[str, str]:
    return {h: GUESS.get(h.strip().lower(), "variable") for h in header}


async def import_contacts(
    db: AsyncSession,
    actor: CurrentUser,
    campaign: Campaign,
    text: str,
    mapping: dict[str, str] | None,
    *,
    dry_run: bool,
    source: str,
) -> ImportReport:
    header, rows = read_csv(text)
    if len(rows) > MAX_ROWS:
        raise Invalid(f"The file has more than {MAX_ROWS:,} rows. Split it into parts")
    mapping = {**guess_mapping(header), **(mapping or {})}
    allowed = {*FIELDS, "variable", "ignore"}
    for col, target in mapping.items():
        if col not in header:
            raise Invalid(f"The file has no column '{col}'")
        if target not in allowed:
            raise Invalid(f"'{target}' is not something a column can be mapped to")
    targets = [mapping[h] for h in header]
    if targets.count("email") != 1:
        raise Invalid("Choose exactly one column as the email address", code="email_column")
    for f in FIELDS:
        if targets.count(f) > 1:
            raise Invalid(f"Two columns are mapped to {f}")

    report = ImportReport(rows=len(rows))
    report.variables = sorted({var_key(h) for h, t in zip(header, targets, strict=True)
                               if t == "variable"})  # fmt: skip
    parsed: list[tuple[int, dict, dict]] = []
    seen: set[str] = set()

    def problem(i: int, email: str, reason: str) -> None:
        if len(report.problems) < 50:
            report.problems.append({"row": i + 2, "email": email, "reason": reason})

    for i, row in enumerate(rows):
        values = dict(zip(targets, row, strict=True))
        email = (values.get("email") or "").strip().lower()
        if not EMAIL.match(email) or len(email) > 320:
            report.invalid_email += 1
            problem(i, email, "not an email address")
            continue
        if email in seen:
            report.duplicates_in_file += 1
            continue
        seen.add(email)
        fields = {f: (values.get(f) or "").strip() or None for f in FIELDS if f != "email"}
        variables = {
            var_key(h): cell
            for h, t, cell in zip(header, targets, row, strict=True)
            if t == "variable" and cell
        }
        parsed.append((i, {"email": email, **fields}, variables))

    emails = {p[1]["email"] for p in parsed}
    leads = await _lead_emails(db, emails)
    blocked = await _suppressed(db, emails)
    existing = {
        c.email.lower(): c
        for c in (
            await db.scalars(select(Contact).where(func.lower(Contact.email).in_(emails)))
        ).all()
    }
    in_campaign = set(
        (
            await db.scalars(
                select(CampaignContact.contact_id).where(CampaignContact.campaign_id == campaign.id)
            )
        ).all()
    )
    running = campaign.status == "running"
    places: list[CampaignContact] = []
    for i, fields, variables in parsed:
        email = fields["email"]
        contact = existing.get(email)
        if email in leads or (contact is not None and contact.status == "converted"):
            report.already_lead += 1
            problem(i, email, "already a lead or customer")
            continue
        if email in blocked or (contact is not None and contact.status != "active"):
            report.suppressed += 1
            problem(i, email, "unsubscribed, bounced or on the do-not-contact list")
            continue
        if contact is not None and contact.id in in_campaign:
            report.already_in_campaign += 1
            continue
        report.added += 1
        if dry_run:
            continue
        if contact is None:
            contact = Contact(
                id=uuid.uuid4(),
                tenant_id=campaign.tenant_id,
                status="active",
                variables=variables,
                source=source[:200],
                created_by_user_id=actor.user.id,
                **fields,
            )
            db.add(contact)
            existing[email] = contact
        else:  # fill what was blank; new columns are added
            for f, v in fields.items():
                if v and not getattr(contact, f):
                    setattr(contact, f, v)
            contact.variables = {**variables, **(contact.variables or {})}
        places.append(
            CampaignContact(
                tenant_id=campaign.tenant_id,
                campaign_id=campaign.id,
                contact_id=contact.id,
                status="active" if running else "pending",
                next_run_at=L.now() if running else None,
                variant=report.added - 1,
            )
        )
    await db.flush()  # the contacts first: their places point at them
    db.add_all(places)
    await db.flush()
    return report


# ---------- steps ----------
def check_steps(steps: list[dict]) -> None:
    if not steps:
        raise Invalid("Add at least one step")
    if len(steps) > MAX_STEPS:
        raise Invalid(f"A campaign has at most {MAX_STEPS} steps")
    for n, step in enumerate(steps, 1):
        variants = step.get("variants") or []
        if not 1 <= len(variants) <= MAX_VARIANTS:
            raise Invalid(f"Step {n} needs 1 to {MAX_VARIANTS} versions")
        for v in variants:
            if not (v.get("body") or "").strip():
                raise Invalid(f"Step {n}: every version needs a body")
            if n == 1 and not (v.get("subject") or "").strip():
                raise Invalid("The first step needs a subject (later steps may reply in thread)")
            for text in (v.get("subject") or "", v["body"]):
                if "{{" in R.VAR.sub("", text):
                    raise Invalid(f"Step {n}: a {{{{ is not closed, or a variable is wrong")


def variables_used(steps: list[CampaignStep]) -> dict[str, bool]:
    """Variable name -> True when every use has a fallback."""
    used: dict[str, bool] = {}
    for s in steps:
        for v in s.variants:
            for text in (v.get("subject") or "", v.get("body") or ""):
                for name, fallback in R.VAR.findall(text):
                    used[name] = used.get(name, True) and bool(fallback.strip())
    return used


async def launch_problems(db: AsyncSession, campaign: Campaign) -> list[str]:
    """Everything that would stop a launch, in plain words (empty: ready)."""
    problems = []
    steps = (
        await db.scalars(select(CampaignStep).where(CampaignStep.campaign_id == campaign.id))
    ).all()
    if not steps:
        problems.append("Add at least one step")
    q = select(func.count()).select_from(Mailbox).where(Mailbox.in_pool, Mailbox.status == "active")
    if campaign.mailbox_ids:
        q = q.where(Mailbox.id.in_([uuid.UUID(i) for i in campaign.mailbox_ids]))
    if not await db.scalar(q):
        problems.append("Choose at least one working sending inbox (Settings → Inboxes)")
    contacts = (
        await db.scalars(
            select(Contact)
            .join(CampaignContact, CampaignContact.contact_id == Contact.id)
            .where(CampaignContact.campaign_id == campaign.id, CampaignContact.status.in_(OPEN))
        )
    ).all()
    if not contacts:
        problems.append("Add contacts")
    for name, has_fallback in sorted(variables_used(steps).items()):
        if has_fallback or name in ("sender_name", "my_company"):
            continue
        if name not in STANDARD_VARS and not any(name in (c.variables or {}) for c in contacts):
            problems.append(f"{{{{{name}}}}} is not a column of these contacts")
            continue
        missing = sum(1 for c in contacts if not values_for(c, "", "").get(name))
        if missing:
            problems.append(
                f"{missing} contact(s) have no {name}: add a fallback, e.g. {{{{{name}|there}}}}"
            )
    return problems


# ---------- convert to lead ----------
async def _outreach_source(db: AsyncSession, tenant_id: uuid.UUID) -> uuid.UUID:
    src = await db.scalar(select(LeadSource).where(func.lower(LeadSource.name) == "outreach"))
    if src is None:
        last = await db.scalar(select(func.max(LeadSource.position))) or 0
        src = LeadSource(tenant_id=tenant_id, name="Outreach", position=last + 1, is_active=True)
        db.add(src)
        await db.flush()
    return src.id


async def convert(db: AsyncSession, actor: CurrentUser, contact: Contact) -> Lead:
    if contact.status == "converted" and contact.lead_id:
        lead = await db.get(Lead, contact.lead_id)
        if lead is not None:
            return lead
    campaign = await db.scalar(
        select(Campaign)
        .join(CampaignContact, CampaignContact.campaign_id == Campaign.id)
        .where(CampaignContact.contact_id == contact.id)
        .order_by(CampaignContact.updated_at.desc())
        .limit(1)
    )
    identities = [L.IdentityInput("email", contact.email, is_primary=True)]
    if contact.phone:
        identities.append(L.IdentityInput("phone", contact.phone, is_primary=True))
    inc = I.Incoming(
        identities=identities,
        source_id=await _outreach_source(db, contact.tenant_id),
        created_via="outreach",
        fields={
            "first_name": contact.first_name,
            "last_name": contact.last_name,
            "org_name": contact.company,
            "website": contact.website,
            "campaign": campaign.name if campaign else None,
        },
        origin="outbound_ace",  # the spec's "Outbound" way in (campaigns are in Core since #44)
        enforce_required=False,
        via_label=f"Outreach ({campaign.name})" if campaign else "Outreach",
    )
    try:
        outcome = await I.intake(db, contact.tenant_id, inc, policy="skip", actor=actor)
    except I.DuplicateFound:  # pragma: no cover - "skip" never refuses
        outcome = None
    lead = (outcome.lead or outcome.match) if outcome else await lead_for_email(db, contact.email)
    if lead is None:  # pragma: no cover - intake always gives one
        raise Invalid("The lead could not be made")
    contact.status, contact.lead_id = "converted", lead.id
    await stop(db, contact.id, "stopped", "converted")
    await db.execute(
        update(Conversation)
        .where(Conversation.contact_id == contact.id)
        .values(lead_id=lead.id, assignee_user_id=None)  # it now follows the lead's owner
    )
    await db.execute(
        update(Message)
        .where(Message.contact_id == contact.id, Message.lead_id.is_(None))
        .values(lead_id=lead.id)
    )
    extra = [f"{k}: {v}" for k, v in (contact.variables or {}).items() if v]
    if contact.title:
        extra.insert(0, f"title: {contact.title}")
    await L.log(
        db,
        lead,
        "note",
        f"Converted from outreach{f' ({campaign.name})' if campaign else ''}",
        actor,
        {"contact_id": str(contact.id), "campaign_id": str(campaign.id) if campaign else None},
        body="\n".join(extra)[:2000] or None,
    )
    await emit(
        db,
        contact.tenant_id,
        "contact.converted",
        {"contact_id": str(contact.id), "lead_id": str(lead.id)},
    )
    return lead


async def unsubscribe(db: AsyncSession, contact: Contact) -> None:
    """By hand from the outreach inbox: never email this address again, anywhere."""
    await C.suppress(db, contact.tenant_id, "email", [contact.email.lower()], "opt_out")
    await contact_opted_out(db, contact.id, "opt_out")
