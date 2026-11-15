"""Demo data for local development and sales demos. Refuses to run in production.

  make demo-seed    add the demo companies (skipped if they already exist)
  make demo-reset   wipe the dev database, rebuild it from migrations, then seed

Everything here is invented: companies, people and history. The data goes in through the
same models and audit log the app uses, so every screen shows realistic content.
"""

import argparse
import asyncio
import secrets
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import select

from app.core.config import get_settings
from app.core.security import hash_password
from app.core.tenancy import platform_session
from app.modules.audit.models import AuditLog
from app.modules.crm.models import ActivityType, CustomFieldDefinition, LeadStage
from app.modules.roles.models import Role
from app.modules.roles.service import _set_permissions
from app.modules.settings.models import TenantSettings
from app.modules.teams.models import Team, TeamMember
from app.modules.users.models import User
from app.platform.demo_b2b import seed_companies, seed_key_accounts
from app.platform.demo_crm import (
    seed_batches,
    seed_customers,
    seed_deals,
    seed_leads,
    seed_money,
    seed_organise,
    seed_properties,
    seed_routing,
)
from app.platform.models import Tenant
from app.platform.staff.models import PlatformStaff
from app.platform.tenants.schemas import TenantCreate
from app.platform.tenants.service import provision_tenant, set_status


class DemoRefused(RuntimeError):
    pass


@dataclass
class Account:
    company: str
    role: str
    name: str
    email: str


@dataclass
class DemoResult:
    created: bool
    password: str = ""  # one shared password for every demo sign-in, shown once
    slugs: list[str] = field(default_factory=list)
    accounts: list[Account] = field(default_factory=list)
    form_key: str = ""  # Acme's demo web form (secret; local credentials file only)


# People at Acme Academy: (name, email local part, role key, team, is_manager, status)
ACME_PEOPLE = [
    ("Kabir Mehta", "kabir", "admin", None, False, "active"),
    ("Neha Joshi", "neha", "finance", None, False, "active"),
    ("Rohan Kapoor", "rohan", "sales_manager", "Pune Counsellors", True, "active"),
    ("Priya Shah", "priya", "sales_user", "Pune Counsellors", False, "active"),
    ("Anita Menon", "anita", "sales_user", "Pune Counsellors", False, "active"),
    ("Vikram Rao", "vikram", "sales_user", "Pune Counsellors", False, "active"),
    ("Meera Iyer", "meera", "sales_manager", "Mumbai Counsellors", True, "active"),
    ("Arjun Nair", "arjun", "sales_user", "Mumbai Counsellors", False, "active"),
    ("Sana Khan", "sana", "sales_user", "Mumbai Counsellors", False, "active"),
    ("Dev Malhotra", "dev", "sales_user", "Mumbai Counsellors", False, "invited"),
    ("Ishaan Gupta", "ishaan", "team_lead", "Online Admissions", True, "active"),
    ("Tara Pillai", "tara", "sales_user", "Online Admissions", False, "active"),
    ("Karan Bedi", "karan", "sales_user", None, False, "disabled"),
]
# Team tree: (name, parent)
ACME_TEAMS = [
    ("Admissions", None),
    ("Pune Counsellors", "Admissions"),
    ("Mumbai Counsellors", "Admissions"),
    ("Online Admissions", "Admissions"),
]
BLUEWAVE_PEOPLE = [
    ("Farah Siddiqui", "farah", "sales_manager", "Dubai Marina", True, "active"),
    ("Omar Haddad", "omar", "sales_user", "Dubai Marina", False, "active"),
    ("Lina George", "lina", "sales_user", "Dubai Marina", False, "active"),
]
# Brightlane Software: a B2B SaaS seller (b2b_saas pack, Decision log #36). All invented.
BRIGHTLANE_PEOPLE = [
    ("Nikhil Verma", "nikhil", "sales_manager", "Enterprise Sales", True, "active"),
    ("Ishita Kapoor", "ishita", "sales_user", "Enterprise Sales", False, "active"),
    ("Rahul Menon", "rahul", "sales_user", "Enterprise Sales", False, "active"),
    ("Sneha Iyer", "sneha", "sales_user", "Mid-market Sales", False, "active"),
    ("Aditya Bose", "aditya", "sales_user", "Mid-market Sales", False, "active"),
    ("Kavita Desai", "kavita", "finance", None, False, "active"),
]
BRIGHTLANE_TEAMS = [("Sales", None), ("Enterprise Sales", "Sales"), ("Mid-market Sales", "Sales")]
BRIGHTLANE_FIELDS = {
    "company_size": "pick",
    "industry_segment": "pick",
    "decision_timeline": "pick",
}
BRIGHTLANE_SEATS = {"HR-CORE": (50, 900), "PAYROLL": (50, 900), "RECRUIT": (10, 120)}

# A generic workspace renamed to real-estate words: industry is configuration, not code.
BLUEWAVE_LABELS = {
    "lead": {"singular": "Buyer enquiry", "plural": "Buyer enquiries"},
    "deal": {"singular": "Property deal", "plural": "Property deals"},
    "customer": {"singular": "Buyer", "plural": "Buyers"},
    "pipeline": {"singular": "Sales pipeline", "plural": "Sales pipelines"},
}


# Demo leads go to people who sell; custom values are picked from each field's options.
SELLING_ROLES = {"sales_user", "sales_manager", "team_lead"}
ACME_FIELDS = {
    "program_interest": "pick",
    "qualification": "pick",
    "application_number": "unique",
}
BLUEWAVE_FIELDS = {"project": "pick", "unit_type": "pick", "booking_ref": "unique"}


def _opts(*labels: str, parent: str | None = None) -> list[dict]:
    out = []
    for label in labels:
        value = label.lower().replace(" ", "_").replace("-", "_")
        out.append({"value": value, "label": label} | ({"parent": parent} if parent else {}))
    return out


async def _real_estate_setup(db, tenant_id: uuid.UUID) -> None:
    """Bluewave runs on the generic pack; real-estate words and fields are just settings."""
    fields = [
        dict(
            key="project",
            label="Project",
            type="select",
            group_name="Property",
            options=_opts("Marina Heights", "Palm Residences", "Creek View"),
        ),
        dict(
            key="unit_type",
            label="Unit type",
            type="select",
            group_name="Property",
            depends_on="project",
            options=_opts("1 BR", "2 BR", parent="marina_heights")
            + [
                o | {"value": "palm_" + o["value"]}
                for o in _opts("Villa", "Townhouse", parent="palm_residences")
            ]
            + [
                o | {"value": "creek_" + o["value"]}
                for o in _opts("Studio", "1 BR", parent="creek_view")
            ],
        ),
        dict(
            key="booking_ref",
            label="Booking reference",
            type="text",
            is_unique=True,
            group_name="Booking",
        ),
        dict(key="budget_aed", label="Budget (AED)", type="number", group_name="Property"),
    ]
    for i, f in enumerate(fields):
        db.add(CustomFieldDefinition(tenant_id=tenant_id, entity="lead", position=i, **f))
    won = await db.scalar(select(LeadStage).where(LeadStage.name == "Won"))
    won.required_fields = ["booking_ref"]
    db.add(
        ActivityType(
            tenant_id=tenant_id,
            key="site_visit",
            label="Site visit done",
            icon="map-pin",
            fields=[],
            position=50,
        )
    )
    await db.flush()


FIELD_STAFF = 236  # so the Users list can be seen at the size of a real company (250 people)
FIELD_TEAMS = [
    "Field Pune",
    "Field Mumbai",
    "Field Delhi",
    "Field Bengaluru",
    "Field Hyderabad",
    "Field Chennai",
]


async def _field_staff(db, tenant_id, roles, parent_team_id, pw_hash, count: int) -> None:
    """Invented field counsellors in six teams under Admissions. They own no leads; they are
    here so lists of people can be judged at real size. Not listed in the credentials file."""
    import random

    from app.platform.demo_crm import FIRST, LAST

    rng = random.Random(23)
    team_ids = []
    for name in FIELD_TEAMS:
        team = Team(tenant_id=tenant_id, name=name, parent_team_id=parent_team_id)
        db.add(team)
        await db.flush()
        team_ids.append(team.id)
    used: set[str] = set()
    for i in range(count):
        first, last = rng.choice(FIRST), rng.choice(LAST)
        local = f"{first}.{last}".lower()
        while local in used:
            local = f"{first}.{last}{rng.randint(2, 99)}".lower()
        used.add(local)
        r = rng.random()
        status = "active" if r < 0.9 else "invited" if r < 0.96 else "disabled"
        user = User(
            tenant_id=tenant_id,
            email=f"{local}@field.acme.demo",
            name=f"{first} {last}",
            status=status,
            role_id=roles["team_lead"] if i % 25 == 0 else roles["sales_user"],
            password_hash=pw_hash if status != "invited" else None,
            last_login_at=_ago(rng.uniform(0.05, 14))
            if status == "active" and rng.random() < 0.85
            else None,
        )
        db.add(user)
        await db.flush()
        db.add(
            TeamMember(
                tenant_id=tenant_id,
                team_id=team_ids[i % len(team_ids)],
                user_id=user.id,
                is_manager=i < len(team_ids),
            )
        )
    await db.flush()


def _ago(days: float) -> datetime:
    return datetime.now(UTC) - timedelta(days=days)


async def _company(
    db,
    staff_id: uuid.UUID,
    *,
    name: str,
    slug: str,
    pack: str,
    timezone: str,
    country: str,
    owner: tuple[str, str],
    password_hash: str | None,
) -> tuple[Tenant, User, dict[str, uuid.UUID]]:
    """Provision a company the way staff do; the Owner is active when a password is given."""
    owner_name, owner_email = owner
    tenant, _ = await provision_tenant(
        db,
        TenantCreate(
            name=name,
            slug=slug,
            industry_pack=pack,
            timezone=timezone,
            default_country=country,
            owner_name=owner_name,
            owner_email=owner_email,
        ),
        staff_id,
        ip=None,
    )  # leaves this transaction scoped to the new tenant
    owner_user = await db.scalar(select(User).where(User.email == owner_email))
    if password_hash:
        owner_user.password_hash, owner_user.status = password_hash, "active"
    from app.core.modules import set_module

    for key in ("whatsapp_number", "copy_in", "outreach"):  # demos show every feature
        await set_module(db, tenant.id, key, True)
    roles = {r.key: r.id for r in (await db.scalars(select(Role))).all()}
    return tenant, owner_user, roles


def _audit(
    db, tenant_id, actor_id, action, entity_type, entity_id, days_ago, before=None, after=None
):
    db.add(
        AuditLog(
            tenant_id=tenant_id,
            actor_type="user",
            actor_id=actor_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            before=before,
            after=after,
            created_at=_ago(days_ago),
        )
    )


async def _people(db, tenant, owner, roles, teams, people, domain, password_hash, start_days):
    """Add users and team memberships, with an audit trail spread over the past weeks."""
    added = []
    for i, (name, local, role_key, team, is_manager, status) in enumerate(people):
        days = start_days - i * (start_days / max(len(people), 1))
        user = User(
            tenant_id=tenant.id,
            email=f"{local}@{domain}",
            name=name,
            status=status,
            role_id=roles[role_key],
            password_hash=password_hash if status != "invited" else None,
        )
        db.add(user)
        await db.flush()
        after = {"email": user.email, "name": name, "role_id": str(roles[role_key])}
        _audit(db, tenant.id, owner.id, "user.invited", "user", user.id, days, after=after)
        if status == "disabled":
            _audit(
                db,
                tenant.id,
                owner.id,
                "user.disabled",
                "user",
                user.id,
                2,
                before={"status": "active"},
                after={"status": "disabled"},
            )
        if team:
            db.add(
                TeamMember(
                    tenant_id=tenant.id, team_id=teams[team], user_id=user.id, is_manager=is_manager
                )
            )
        added.append((user, role_key))
    return added


async def _teams(db, tenant, owner, tree, days_ago) -> dict[str, uuid.UUID]:
    ids: dict[str, uuid.UUID] = {}
    for name, parent in tree:
        team = Team(
            tenant_id=tenant.id, name=name, parent_team_id=ids.get(parent) if parent else None
        )
        db.add(team)
        await db.flush()
        ids[name] = team.id
        _audit(
            db,
            tenant.id,
            owner.id,
            "team.created",
            "team",
            team.id,
            days_ago,
            after={
                "name": name,
                "parent_id": str(team.parent_team_id) if team.parent_team_id else None,
            },
        )
    return ids


def _title(role_key: str) -> str:
    return role_key.replace("_", " ").title()


async def seed_demo(prefix: str = "", *, server: bool = False) -> DemoResult:
    """Create the demo companies. `prefix` keeps test runs apart (e.g. "t1-" -> t1-acme).
    `server`: the shared server (production mode, ALLOW_DEMO_DATA=true). Only Acme, Bluewave and
    Brightlane; no demo staff account (the companies are recorded as created by the first real
    staff member) and no suspended Sunrise. Demo people sign in with 2FA like everyone else."""
    settings = get_settings()
    if settings.environment == "prod" and not (server and settings.allow_demo_data):
        raise DemoRefused("demo data never goes into production")
    acme_slug, blue_slug, sun_slug = f"{prefix}acme", f"{prefix}bluewave", f"{prefix}sunrise"
    bright_slug = f"{prefix}brightlane"
    async with platform_session() as db:
        if await db.scalar(select(Tenant.id).where(Tenant.slug == acme_slug)):
            return DemoResult(created=False)

    password = secrets.token_urlsafe(9)  # 12 characters, shared by every demo account
    pw_hash = hash_password(password)
    result = DemoResult(
        created=True, password=password, slugs=[acme_slug, blue_slug, bright_slug, sun_slug]
    )
    scored: list[uuid.UUID] = []  # companies whose lead scores are filled in at the end

    if server:  # never a shared-password staff account on a real staff console
        result.slugs.remove(sun_slug)
        async with platform_session() as db:
            staff_id = await db.scalar(select(PlatformStaff.id).order_by(PlatformStaff.created_at))
        if staff_id is None:
            raise DemoRefused("Create your own staff account first (create-staff)")
    else:
        async with platform_session() as db:
            staff = PlatformStaff(
                email=f"staff@{prefix}demo.versnq.in", name="Demo Staff", password_hash=pw_hash
            )
            db.add(staff)
            await db.flush()
            staff_id = staff.id
        result.accounts.append(
            Account(
                "Versnq (staff console)",
                "Versnq staff",
                "Demo Staff",
                f"staff@{prefix}demo.versnq.in",
            )
        )

    # Acme Academy: an EdTech business with a full admissions team.
    async with platform_session() as db:
        domain = f"{acme_slug}.demo"
        tenant, owner, roles = await _company(
            db,
            staff_id,
            name="Acme Academy",
            slug=acme_slug,
            pack="edtech",
            timezone="Asia/Kolkata",
            country="IN",
            owner=("Riya Sharma", f"owner@{domain}"),
            password_hash=pw_hash,
        )
        lead_role = Role(
            tenant_id=tenant.id, name="Team Lead", key=None, scope="team", is_system=False
        )
        db.add(lead_role)
        await db.flush()
        await _set_permissions(db, lead_role, {"users.read"})
        roles["team_lead"] = lead_role.id
        _audit(
            db,
            tenant.id,
            owner.id,
            "role.created",
            "role",
            lead_role.id,
            40,
            after={"name": "Team Lead", "scope": "team", "permissions": ["users.read"]},
        )
        teams = await _teams(db, tenant, owner, ACME_TEAMS, 38)
        added = await _people(db, tenant, owner, roles, teams, ACME_PEOPLE, domain, pw_hash, 36)
        reps = [u.id for u, k in added if u.status == "active" and k in SELLING_ROLES]
        await _field_staff(db, tenant.id, roles, teams["Admissions"], pw_hash, count=FIELD_STAFF)
        await seed_leads(
            db, tenant.id, count=300, country="IN", reps=reps, unassigned=8, custom=ACME_FIELDS
        )
        result.form_key = await seed_routing(
            db, tenant.id, team_id=teams["Pune Counsellors"], reps=reps
        )
        await seed_batches(db, tenant.id)
        await seed_deals(db, tenant.id, count=60, seed=21)
        await seed_organise(
            db,
            tenant.id,
            owner_id=owner.id,
            seed=31,
            tags=["Scholarship", "Weekend batch", "Parent involved", "EMI"],
        )
        scored.append(tenant.id)
        result.accounts.append(Account("Acme Academy", "Owner", owner.name, owner.email))
        for user, role_key in added:
            if user.status == "active":
                label = "Team Lead" if role_key == "team_lead" else _title(role_key)
                result.accounts.append(Account("Acme Academy", label, user.name, user.email))

    # Bluewave Realty: a generic workspace whose labels say "Buyer enquiry", not "Lead".
    async with platform_session() as db:
        domain = f"{blue_slug}.demo"
        tenant, owner, roles = await _company(
            db,
            staff_id,
            name="Bluewave Realty",
            slug=blue_slug,
            pack="generic",
            timezone="Asia/Dubai",
            country="AE",
            owner=("Yusuf Rahman", f"owner@{domain}"),
            password_hash=pw_hash,
        )
        settings = await db.get(TenantSettings, tenant.id)
        before = {"labels": dict(settings.labels)}
        settings.labels = settings.labels | BLUEWAVE_LABELS
        settings.branding = {"primary_color": "#0e7490"}
        _audit(
            db,
            tenant.id,
            owner.id,
            "settings.updated",
            "settings",
            tenant.id,
            20,
            before=before,
            after={"labels": settings.labels},
        )
        await _real_estate_setup(db, tenant.id)
        teams = await _teams(db, tenant, owner, [("Dubai Marina", None)], 19)
        added = await _people(db, tenant, owner, roles, teams, BLUEWAVE_PEOPLE, domain, pw_hash, 18)
        reps = [u.id for u, k in added if u.status == "active" and k in SELLING_ROLES]
        await seed_leads(
            db,
            tenant.id,
            count=60,
            country="AE",
            reps=reps,
            unassigned=3,
            custom=BLUEWAVE_FIELDS,
            seed=11,
        )
        await seed_properties(db, tenant.id)
        await seed_deals(db, tenant.id, count=22, seed=23, link_property=True)
        await seed_organise(
            db,
            tenant.id,
            owner_id=owner.id,
            seed=37,
            tags=["Cash buyer", "Investor", "Golden visa"],
        )
        scored.append(tenant.id)
        result.accounts.append(Account("Bluewave Realty", "Owner", owner.name, owner.email))
        result.accounts.append(
            Account("Bluewave Realty", "Sales Manager", "Farah Siddiqui", f"farah@{domain}")
        )

    # Brightlane Software: B2B SaaS selling an HR and payroll suite to companies.
    async with platform_session() as db:
        domain = f"{bright_slug}.demo"
        tenant, owner, roles = await _company(
            db,
            staff_id,
            name="Brightlane Software",
            slug=bright_slug,
            pack="b2b_saas",
            timezone="Asia/Kolkata",
            country="IN",
            owner=("Ananya Rao", f"owner@{domain}"),
            password_hash=pw_hash,
        )
        settings = await db.get(TenantSettings, tenant.id)
        settings.branding = {"primary_color": "#c2410c"}
        teams = await _teams(db, tenant, owner, BRIGHTLANE_TEAMS, 30)
        added = await _people(
            db, tenant, owner, roles, teams, BRIGHTLANE_PEOPLE, domain, pw_hash, 28
        )
        reps = [u.id for u, k in added if u.status == "active" and k in SELLING_ROLES]
        await seed_leads(
            db,
            tenant.id,
            count=140,
            country="IN",
            reps=reps,
            unassigned=5,
            custom=BRIGHTLANE_FIELDS,
            seed=13,
        )
        await seed_companies(db, tenant.id, reps=reps, seed=15)
        await seed_deals(
            db,
            tenant.id,
            count=26,
            seed=27,
            lead_kind="organisation",
            quantities=BRIGHTLANE_SEATS,
        )
        await seed_organise(
            db,
            tenant.id,
            owner_id=owner.id,
            seed=39,
            tags=["Enterprise", "Renewal due", "Champion found", "Security review"],
        )
        bright_id = tenant.id
        result.accounts.append(Account("Brightlane Software", "Owner", owner.name, owner.email))
        for user, role_key in added:
            result.accounts.append(
                Account("Brightlane Software", _title(role_key), user.name, user.email)
            )

    from app.modules.crm.scoring import rescore_tenant  # scores need the saved activities

    for tenant_id in [*scored, bright_id]:
        await rescore_tenant(tenant_id)
    # Step 5: customers from won deals, with documents at every stage (as the company).
    acme_id, blue_id = scored
    await seed_customers(
        acme_id,
        count=14,
        seed=41,
        fields=[("admission_no", "Admission number"), ("guardian_phone", "Guardian's phone")],
    )
    await seed_customers(
        blue_id,
        count=8,
        seed=43,
        fields=[("passport_no", "Passport number"), ("emirates_id", "Emirates ID number")],
        rename={
            "ID proof": "Passport copy",
            "Proof of address": "Emirates ID",
            "Signed agreement": "Signed MoU (Form F)",
        },
    )
    # Step 6: invoices at every state (Decision log #34).
    await seed_money(
        acme_id,
        seed=51,
        item="Course fee",
        entity={
            "legal_name": "Acme Academy Pvt Ltd",
            "tax_id": "27AABCA1234F1Z5",
            "address": "4th floor, Lotus Park\nAndheri East, Mumbai 400069",
            "email": "accounts@acme.demo",
            "phone": "+91 22 4000 1234",
            "bank_details": "HDFC Bank · A/c 50200012345678 · IFSC HDFC0000123",
            "upi_id": "acmeacademy@hdfcbank",
            "terms": "Fees once paid are refundable only as per the admission policy.",
        },
    )
    await seed_money(
        blue_id,
        seed=53,
        item="Booking amount",
        entity={
            "legal_name": "Bluewave Realty LLC",
            "tax_id": "100123456700003",
            "address": "Office 1204, Bay Square\nBusiness Bay, Dubai",
            "email": "accounts@bluewave.demo",
            "bank_details": "Emirates NBD · IBAN AE07 0260 0010 1234 5678 901",
            "terms": "Booking amounts are adjusted against the final sale price.",
        },
    )
    # Brightlane: won opportunities became clients, billed yearly or quarterly.
    await seed_customers(
        bright_id,
        count=9,
        seed=45,
        fields=[("contract_id", "Contract ID"), ("renewal_date", "Renewal date")],
    )
    await seed_money(
        bright_id,
        seed=55,
        item="Annual subscription",
        entity={
            "legal_name": "Brightlane Software Pvt Ltd",
            "tax_id": "29AAKCB7731L1Z2",
            "address": "12th floor, Orion Tech Park\nOuter Ring Road, Bengaluru 560103",
            "email": "billing@brightlane.demo",
            "phone": "+91 80 4100 2200",
            "bank_details": "ICICI Bank · A/c 000405123456 · IFSC ICIC0000004",
            "upi_id": "brightlane@icici",
            "terms": "Subscriptions renew yearly. Payment due within 15 days of the invoice.",
            "due_days": 15,
        },
    )
    # Step 7b: key accounts for Brightlane (Decision log #36).
    await seed_key_accounts(bright_id, seed=57)

    if server:
        return result
    # Sunrise Coaching: the Owner never accepted the invite, and the company is suspended.
    async with platform_session() as db:
        tenant, _, _ = await _company(
            db,
            staff_id,
            name="Sunrise Coaching",
            slug=sun_slug,
            pack="edtech",
            timezone="Asia/Kolkata",
            country="IN",
            owner=("Aman Verma", f"owner@{sun_slug}.demo"),
            password_hash=None,
        )
        await set_status(db, tenant, "suspended", staff_id, ip=None)

    return result


def _reset_dev_database() -> None:
    """Rebuild the dev database from migrations. Dev only, never the test or e2e databases."""
    from alembic import command
    from alembic.config import Config
    from sqlalchemy.engine import make_url

    settings = get_settings()
    name = make_url(settings.migration_database_url).database
    if settings.environment != "dev" or name != "versnq":
        raise DemoRefused(f"demo-reset only rebuilds the dev database 'versnq' (got {name!r})")
    backend = Path(__file__).resolve().parents[2]
    cfg = Config(str(backend / "alembic.ini"))
    cfg.set_main_option("script_location", str(backend / "migrations"))
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
    import shutil

    from app.core import storage

    shutil.rmtree(storage.root(), ignore_errors=True)  # uploaded files of the old companies


def main() -> None:
    parser = argparse.ArgumentParser(prog="demo")
    parser.add_argument(
        "--reset", action="store_true", help="wipe and rebuild the dev database first"
    )
    parser.add_argument(
        "--server", action="store_true", help="the shared server (needs ALLOW_DEMO_DATA=true)"
    )
    args = parser.parse_args()
    if args.reset:
        _reset_dev_database()
    if args.server:
        _server_demo()
        return
    result = asyncio.run(seed_demo())
    if not result.created:
        print(
            "Demo companies already exist; nothing changed. "
            "Use 'make demo-reset' for a clean slate."
        )
        return
    base = get_settings().base_domain
    print("\nDemo companies (all invented):")
    print(f"  Acme Academy     http://acme.{base}:3000      EdTech, 250 people, 300 students")
    print(
        f"  Bluewave Realty  http://bluewave.{base}:3000  generic pack relabelled for real estate"
    )
    print(
        f"  Brightlane       http://brightlane.{base}:3000  B2B SaaS (HR software), b2b_saas pack"
    )
    print("  Sunrise Coaching (suspended; shows in the staff console only)")
    print(f"\nStaff console:     http://admincore.{base}:3001\n")
    for a in result.accounts:
        print(f"  {a.company:<24} {a.role:<14} {a.email}")
    print(f"\nEvery account above uses this password: {result.password}")
    print(
        "It is shown once. Owner, Admin and staff set up 2FA on first sign-in\n"
        "(skipped for these demo accounts while DEMO_SKIP_2FA=true).\n"
    )
    path = write_credentials_file(result, base)
    print(f"Saved to {path} (local only, never committed).\n")


def _server_demo() -> None:
    result = asyncio.run(seed_demo(server=True))
    if not result.created:
        print("Demo companies already exist; nothing changed.")
        return
    base = get_settings().base_domain
    print("\nDemo companies (all invented) — run add-company.sh for each slug for HTTPS:")
    for slug in result.slugs:
        print(f"  https://{slug}.{base}")
    for a in result.accounts:
        print(f"  {a.company:<24} {a.role:<14} {a.email}")
    print(f"\nEvery account above uses this password: {result.password}")
    print("Shown once; keep it in your password manager. Owner and Admin set up 2FA.\n")


CREDENTIALS_FILE = Path(__file__).resolve().parents[3] / "DEMO_CREDENTIALS.md"


def write_credentials_file(result: DemoResult, base: str, path: Path = CREDENTIALS_FILE) -> Path:
    """Local reference for demos: invented accounts only, rewritten on every demo-reset.
    The file is git-ignored; it never holds real people's passwords."""
    lines = [
        "# Demo credentials (local only, invented accounts)",
        "",
        "Rewritten by `make demo-reset`. Never commit this file. Dev machines only.",
        "",
        f"**Password for every account:** `{result.password}`",
        "",
        "2FA: skipped for these demo accounts while `DEMO_SKIP_2FA=true` is in `.env`.",
        "",
        "## Where to sign in",
        "",
        f"- Acme Academy (EdTech, 300 students): http://acme.{base}:3000/login",
        f"- Bluewave Realty (real estate setup, 60 enquiries): http://bluewave.{base}:3000/login",
        f"- Brightlane Software (B2B SaaS, client companies): http://brightlane.{base}:3000/login",
        f"- Versnq staff console: http://admincore.{base}:3001/login",
        "- Sunrise Coaching is suspended (shows in the staff console only)",
        "",
        "## Try lead capture",
        "",
        "- Import: Acme → Students → Import → choose `docs/demo/sample-import.csv`",
        "- Web form (Acme). Send a test enquiry from a terminal:",
        "",
        "```",
        f"curl -X POST http://acme.{base}:8000/api/v1/capture/{result.form_key} \\",
        "  -H 'Content-Type: application/json' \\",
        """  -d '{"name": "Test Enquiry", "phone": "98111 22233", "email": "test@example.org", """
        """"Which course?": "Data Science", "consent_email": "yes", "utm_source": "google"}'""",
        "```",
        "",
        "## Accounts",
        "",
        "| Company | Role | Name | Email |",
        "| --- | --- | --- | --- |",
        *[f"| {a.company} | {a.role} | {a.name} | {a.email} |" for a in result.accounts],
        "",
    ]
    path.write_text("\n".join(lines))
    return path


if __name__ == "__main__":
    main()
