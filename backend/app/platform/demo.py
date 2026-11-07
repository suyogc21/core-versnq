"""Demo data for local development: `make demo-seed`. Refuses to run in production."""

import asyncio
import secrets
from dataclasses import dataclass, field

from sqlalchemy import select

from app.core.config import get_settings
from app.core.security import hash_password
from app.core.tenancy import platform_session
from app.modules.roles.models import Role
from app.modules.teams.models import Team, TeamMember
from app.modules.users.models import User
from app.platform.models import Tenant
from app.platform.staff.models import PlatformStaff
from app.platform.tenants.schemas import TenantCreate
from app.platform.tenants.service import provision_tenant


class DemoRefused(RuntimeError):
    pass


@dataclass
class Account:
    role: str
    name: str
    email: str
    password: str


@dataclass
class DemoResult:
    created: bool
    slug: str
    accounts: list[Account] = field(default_factory=list)


def _password() -> str:
    return secrets.token_urlsafe(9)  # 12 characters


async def seed_demo(slug: str = "acme") -> DemoResult:
    if get_settings().environment == "prod":
        raise DemoRefused("demo-seed never runs in production")
    async with platform_session() as db:
        if await db.scalar(select(Tenant.id).where(Tenant.slug == slug)):
            return DemoResult(created=False, slug=slug)

        staff_pw = _password()
        staff = PlatformStaff(
            email=f"staff-{slug}@demo.versnq.in",
            name="Demo Staff",
            password_hash=hash_password(staff_pw),
        )
        db.add(staff)
        await db.flush()

        owner_email = f"owner@{slug}.demo"
        tenant, _ = await provision_tenant(
            db,
            TenantCreate(
                name="Acme Academy",
                slug=slug,
                industry_pack="edtech",
                timezone="Asia/Kolkata",
                default_country="IN",
                owner_name="Riya Owner",
                owner_email=owner_email,
            ),
            staff.id,
            ip=None,
        )  # leaves this transaction scoped to the new tenant
        roles = {r.key: r.id for r in (await db.scalars(select(Role))).all()}

        accounts = [Account("Owner", "Riya Owner", owner_email, _password())]
        owner = await db.scalar(select(User).where(User.email == owner_email))
        owner.password_hash, owner.status = hash_password(accounts[0].password), "active"

        people = [
            ("Sales Manager", "sales_manager", "Rohan Kapoor", f"rohan@{slug}.demo"),
            ("Sales User", "sales_user", "Priya Shah", f"priya@{slug}.demo"),
            ("Sales User", "sales_user", "Anita Menon", f"anita@{slug}.demo"),
        ]
        team = Team(tenant_id=tenant.id, name="Pune Counsellors")
        db.add(team)
        await db.flush()
        for role_name, key, name, email in people:
            account = Account(role_name, name, email, _password())
            user = User(
                tenant_id=tenant.id,
                email=email,
                name=name,
                status="active",
                role_id=roles[key],
                password_hash=hash_password(account.password),
            )
            db.add(user)
            await db.flush()
            db.add(
                TeamMember(
                    tenant_id=tenant.id,
                    team_id=team.id,
                    user_id=user.id,
                    is_manager=key == "sales_manager",
                )
            )
            accounts.append(account)
        accounts.append(Account("Versnq staff", "Demo Staff", staff.email, staff_pw))
        return DemoResult(created=True, slug=slug, accounts=accounts)


def main() -> None:
    result = asyncio.run(seed_demo())
    base = get_settings().base_domain
    if not result.created:
        print(f"Demo workspace '{result.slug}' already exists; nothing changed.")
        return
    print(f"\nClient app:    http://{result.slug}.{base}:3000/login")
    print(f"Staff console: http://admincore.{base}:3001/login  (screens not built yet)\n")
    for a in result.accounts:
        print(f"  {a.role:<14} {a.email:<32} {a.password}")
    print("\nPasswords are shown once. The Owner sets up 2FA on first login.\n")


if __name__ == "__main__":
    main()
