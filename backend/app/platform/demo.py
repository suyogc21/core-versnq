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
from app.modules.roles.models import Role
from app.modules.roles.service import _set_permissions
from app.modules.settings.models import TenantSettings
from app.modules.teams.models import Team, TeamMember
from app.modules.users.models import User
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
# A generic workspace renamed to real-estate words: industry is configuration, not code.
BLUEWAVE_LABELS = {
    "lead": {"singular": "Buyer enquiry", "plural": "Buyer enquiries"},
    "deal": {"singular": "Property deal", "plural": "Property deals"},
    "customer": {"singular": "Buyer", "plural": "Buyers"},
    "pipeline": {"singular": "Sales pipeline", "plural": "Sales pipelines"},
}


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


async def seed_demo(prefix: str = "") -> DemoResult:
    """Create the demo companies. `prefix` keeps test runs apart (e.g. "t1-" -> t1-acme)."""
    if get_settings().environment == "prod":
        raise DemoRefused("demo data never goes into production")
    acme_slug, blue_slug, sun_slug = f"{prefix}acme", f"{prefix}bluewave", f"{prefix}sunrise"
    async with platform_session() as db:
        if await db.scalar(select(Tenant.id).where(Tenant.slug == acme_slug)):
            return DemoResult(created=False)

    password = secrets.token_urlsafe(9)  # 12 characters, shared by every demo account
    pw_hash = hash_password(password)
    result = DemoResult(created=True, password=password, slugs=[acme_slug, blue_slug, sun_slug])

    async with platform_session() as db:
        staff = PlatformStaff(
            email=f"staff@{prefix}demo.versnq.in", name="Demo Staff", password_hash=pw_hash
        )
        db.add(staff)
        await db.flush()
        staff_id = staff.id
    result.accounts.append(
        Account(
            "Versnq (staff console)", "Versnq staff", "Demo Staff", f"staff@{prefix}demo.versnq.in"
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
        teams = await _teams(db, tenant, owner, [("Dubai Marina", None)], 19)
        await _people(db, tenant, owner, roles, teams, BLUEWAVE_PEOPLE, domain, pw_hash, 18)
        result.accounts.append(Account("Bluewave Realty", "Owner", owner.name, owner.email))
        result.accounts.append(
            Account("Bluewave Realty", "Sales Manager", "Farah Siddiqui", f"farah@{domain}")
        )

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


def main() -> None:
    parser = argparse.ArgumentParser(prog="demo")
    parser.add_argument(
        "--reset", action="store_true", help="wipe and rebuild the dev database first"
    )
    args = parser.parse_args()
    if args.reset:
        _reset_dev_database()
    result = asyncio.run(seed_demo())
    if not result.created:
        print(
            "Demo companies already exist; nothing changed. "
            "Use 'make demo-reset' for a clean slate."
        )
        return
    base = get_settings().base_domain
    print("\nDemo companies (all invented):")
    print(f"  Acme Academy     http://acme.{base}:3000      EdTech, 14 people, 4 teams")
    print(
        f"  Bluewave Realty  http://bluewave.{base}:3000  generic pack relabelled for real estate"
    )
    print("  Sunrise Coaching (suspended; shows in the staff console only)")
    print(f"\nStaff console:     http://admincore.{base}:3001\n")
    for a in result.accounts:
        print(f"  {a.company:<24} {a.role:<14} {a.email}")
    print(f"\nEvery account above uses this password: {result.password}")
    print("It is shown once. Owner, Admin and staff set up 2FA on first sign-in.\n")


if __name__ == "__main__":
    main()
