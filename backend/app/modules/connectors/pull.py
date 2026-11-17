"""Leads come in from the connected LeadSquared by themselves (Suyog, Nov 17: no export and
upload, the dialer works on each rep's own LeadSquared leads).

Every 5 minutes, for a company that turned "Bring my reps' leads from LeadSquared" on:
1. LeadSquared's users are matched to Core's active users by the same email (case ignored).
2. Leads changed since the last pull (Leads.RecentlyModified; the first pull reads them all) are
   read a page at a time. A lead owned by a matched rep is created in Core for that rep, or, if
   Core already has it (linked, or the same phone or email), linked and given to that rep.
   LeadSquared stays the source of truth for the owner: a reassigned lead moves to the other rep,
   and a lead given to someone without a Core account leaves the rep (unassigned in Core).
3. Leads of people not in Core are left in LeadSquared. Names and numbers already in Core are
   not overwritten. Pulled leads come in quietly: LeadSquared already told the rep and runs its
   own response timers.
A run reads at most MAX_PAGES pages (LeadSquared allows about 25 requests per 5 seconds) and
carries on from that page the next time. A failure keeps the place and shows in Settings.
"""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from app.core.errors import Invalid
from app.core.tenancy import tenant_session
from app.modules.connectors import base as B
from app.modules.connectors.models import CrmConnection
from app.modules.connectors.service import connector_for, now
from app.modules.crm import intake as I
from app.modules.crm import leads as L
from app.modules.crm.identities import normalize
from app.modules.crm.models import ExternalRef, Lead, LeadSource
from app.modules.users.models import User

SYSTEM = "leadsquared"  # the same key the sync uses: a pulled lead's calls go to its own lead
EVERY = timedelta(minutes=5)
OVERLAP = timedelta(minutes=10)  # a lead changed while the last pull ran is read again
FIRST = datetime(2000, 1, 1, tzinfo=UTC)
PAGE = 1000
MAX_PAGES = 10
WHEN = "%Y-%m-%dT%H:%M:%S%z"


def _at(text: str | None) -> datetime | None:
    return datetime.strptime(text, WHEN) if text else None


async def _source(db) -> uuid.UUID | None:
    sources = (
        await db.scalars(
            select(LeadSource).where(LeadSource.is_active.is_(True)).order_by(LeadSource.position)
        )
    ).all()
    pick = next((s for s in sources if s.name.strip().lower() == "leadsquared"), None)
    pick = pick or (sources[0] if sources else None)
    return pick.id if pick else None


async def owners(db, crm) -> dict[str, uuid.UUID]:
    """LeadSquared user id → the Core user with the same email (active on both sides)."""
    core = {
        u.email.lower(): u.id
        for u in (await db.scalars(select(User).where(User.status == "active"))).all()
    }
    return {
        u["id"]: core[u["email"]] for u in await crm.users() if u["active"] and u["email"] in core
    }


async def _one(db, row: dict, mine: dict[str, uuid.UUID], source_id, country: str) -> str:
    """'created', 'moved', 'linked' or 'skipped'."""
    pid = (row.get("ProspectID") or "").strip()
    if not pid:
        return "skipped"
    owner_id = mine.get(row.get("OwnerId") or "")
    ref = await db.scalar(
        select(ExternalRef).where(ExternalRef.system == SYSTEM, ExternalRef.external_id == pid)
    )
    lead = await db.get(Lead, ref.lead_id) if ref else None
    if lead is None:
        if owner_id is None:
            return "skipped"  # not one of the company's reps in Core
        ids = []
        for kind, value in (
            ("phone", row.get("Mobile")),
            ("phone", row.get("Phone")),
            ("email", row.get("EmailAddress")),
        ):
            try:  # a number or email Core can't read is left out, not the whole lead
                if value and value.strip() and normalize(kind, value, country):
                    ids.append(L.IdentityInput(type=kind, value=value.strip()))
            except Invalid:
                pass
        if not ids or source_id is None:
            return "skipped"
        fields = {
            "first_name": (row.get("FirstName") or "").strip()[:120] or None,
            "last_name": (row.get("LastName") or "").strip()[:120] or None,
        }
        out = await I.intake(
            db,
            db.info["tenant_id"],
            I.Incoming(
                identities=ids,
                source_id=source_id,
                created_via="api",
                origin="outside",
                fields={k: v for k, v in fields.items() if v},
                owner=owner_id,
                enforce_required=False,
                external=(SYSTEM, pid),
                via_label="LeadSquared",
                quiet=True,
            ),
            policy="skip",
        )
        if out.result == "created":
            return "created"
        lead = out.match  # Core already had this person: link it
        await db.execute(
            insert(ExternalRef)
            .values(
                id=uuid.uuid4(),
                tenant_id=lead.tenant_id,
                system=SYSTEM,
                external_id=pid,
                lead_id=lead.id,
            )
            .on_conflict_do_nothing(constraint="uq_external_ref")
        )
    if lead.owner_user_id == owner_id:
        return "linked" if ref is None else "skipped"
    await L.change_owner(db, lead, await db.get(User, owner_id) if owner_id else None, None)
    return "moved"


async def pull_tenant(tenant_id: uuid.UUID, *, force: bool = False) -> dict:
    done = {"created": 0, "moved": 0, "linked": 0}
    async with tenant_session(tenant_id) as db:
        db.info["tenant_id"] = tenant_id
        conn = await db.scalar(
            select(CrmConnection).where(
                CrmConnection.is_active.is_(True), CrmConnection.provider == "leadsquared"
            )
        )
        cfg = dict(conn.config or {}) if conn else {}
        if conn is None or not cfg.get("pull_leads"):
            return done
        st = dict(cfg.get("pull") or {})
        if not st.get("until"):  # a new window, every EVERY
            last = _at(st.get("done_until"))
            if last and not force and now() - last < EVERY:
                return done
            st = {
                "since": ((last - OVERLAP) if last else FIRST).strftime(WHEN),
                "until": now().strftime(WHEN),
                "page": 1,
                "done_until": st.get("done_until"),
            }
        mine: dict[str, uuid.UUID] | None = None
        try:
            crm = connector_for(conn)
            mine = await owners(db, crm)
            source_id, country = await _source(db), await L.tenant_country(db, tenant_id)
            for _ in range(MAX_PAGES):
                rows = await crm.changed_leads(_at(st["since"]), _at(st["until"]), st["page"], PAGE)
                for row in rows:
                    r = await _one(db, row, mine, source_id, country)
                    if r in done:
                        done[r] += 1
                if len(rows) < PAGE:
                    st = {"done_until": st["until"]}
                    break
                st["page"] += 1
            conn.last_error = None
        except (B.CrmError, ValueError) as e:  # ValueError: keys that can't be read any more
            conn.last_error = f"Lead pull: {e}"[:300]
        if mine is not None:
            st["owners"] = len(mine)
        st["last"] = {**done, "at": now().strftime(WHEN)}
        conn.config = {**cfg, "pull": st}
    return done


async def pull_all(tenant_ids: list[uuid.UUID]) -> dict:
    total = {"created": 0, "moved": 0, "linked": 0}
    for t in tenant_ids:
        r = await pull_tenant(t)
        total = {k: total[k] + r[k] for k in total}
    return total
