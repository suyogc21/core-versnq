"""B2B demo (Decision log #36): the invented client companies Brightlane Software sells to,
each with a few contacts. Every name is invented; none is a real company or brand."""

import random
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.crm.models import Lead, LeadSource, LeadStage

ROLES = ["decision_maker", "influencer", "user", "gatekeeper", "influencer"]

# (name, industry, size, website) — invented
COMPANIES = [
    ("Varanta Group", "Manufacturing", "1000+"),
    ("Varanta Motors", "Manufacturing", "1000+"),
    ("Varanta Retail", "Retail", "1000+"),
    ("Varanta Finserv", "Financial services", "201–1000"),
    ("Kesarwal Logistics", "Other", "201–1000"),
    ("Ombrel Pharma", "Healthcare", "1000+"),
    ("Tarkesh Foods", "Manufacturing", "201–1000"),
    ("Pinewyn Hospitals", "Healthcare", "1000+"),
    ("Aranyak Textiles", "Manufacturing", "201–1000"),
    ("Bluvanta Infra", "Other", "1000+"),
    ("Corvela Systems", "IT services", "51–200"),
    ("Dhanvik Agro", "Other", "51–200"),
    ("Elmora Schools", "Other", "201–1000"),
    ("Feroza Securities", "Financial services", "51–200"),
    ("Granvik Cement", "Manufacturing", "1000+"),
    ("Harlune Shipping", "Other", "201–1000"),
    ("Indravo Polymers", "Manufacturing", "201–1000"),
    ("Jasvira Hotels", "Other", "1000+"),
    ("Kavelon Electronics", "Manufacturing", "201–1000"),
    ("Lumoria Labs", "IT services", "51–200"),
    ("Meruva Insurance", "Financial services", "1000+"),
    ("Navaro Retail", "Retail", "201–1000"),
    ("Opalyne Jewels", "Retail", "51–200"),
    ("Prisvo Media", "Other", "51–200"),
    ("Quorra Auto Parts", "Manufacturing", "201–1000"),
    ("Redanta Builders", "Other", "201–1000"),
    ("Sapvira Clinics", "Healthcare", "51–200"),
    ("Tidara Energy", "Other", "1000+"),
]


def _slug(name: str) -> str:
    return "".join(ch for ch in name.lower() if ch.isalnum())


async def seed_companies(
    db: AsyncSession, tenant_id: uuid.UUID, *, reps: list[uuid.UUID], seed: int
) -> int:
    """Organisations for the invented client companies, owned by the reps, with 3–6 of the
    seeded people attached to each as contacts. Returns how many organisations."""
    rng = random.Random(seed)
    stages = {s.name: s for s in (await db.scalars(select(LeadStage))).all()}
    sources = list((await db.scalars(select(LeadSource).where(LeadSource.is_active))).all())
    people = list(
        (
            await db.scalars(select(Lead).where(Lead.kind == "person").order_by(Lead.created_at))
        ).all()
    )
    rng.shuffle(people)
    now = datetime.now(UTC)
    made = 0
    for name, industry, size in COMPANIES:
        owner = rng.choice(reps)
        stage = stages.get(rng.choice(["Contacted", "Discovery call", "Qualified", "Qualified"]))
        created = now - timedelta(days=rng.uniform(20, 120))
        org = Lead(
            tenant_id=tenant_id,
            kind="organisation",
            org_name=name,
            display_name=name,
            website=f"https://{_slug(name)}.example",
            industry=industry,
            employee_range=size,
            owner_user_id=owner,
            assigned_at=created,
            stage_id=stage.id,
            stage_changed_at=created,
            is_open=True,
            origin="outside",
            source_id=rng.choice(sources).id,
            created_via="manual",
            custom_fields={"company_size": _value(size), "industry_segment": _value(industry)},
            city=rng.choice(["Mumbai", "Pune", "Bengaluru", "Delhi", "Hyderabad", "Chennai"]),
            created_at=created,
            attribution={},
        )
        db.add(org)
        await db.flush()
        for person in [people.pop() for _ in range(min(len(people), rng.randint(3, 6)))]:
            person.organisation_id, person.org_name = org.id, name
        made += 1
    await db.flush()
    return made


def _value(label: str) -> str:
    return label.lower().replace(" ", "_").replace("+", "plus").replace("–", "_").replace("-", "_")


async def seed_key_accounts(tenant_id: uuid.UUID, *, seed: int) -> int:
    """Key accounts demo (step 7b): the Varanta group tree and three more accounts, with
    departments, competitors, deals on the grid, a people map and an account plan."""
    from app.core.modules import set_module
    from app.core.tenancy import tenant_session
    from app.modules.accounts.models import (
        AccountCell,
        AccountContact,
        AccountGoal,
        AccountUnit,
        Competitor,
        KeyAccount,
    )
    from app.modules.crm.models import (
        Deal,
        DealProduct,
        LostReason,
        Pipeline,
        PipelineStage,
        Product,
    )

    rng = random.Random(seed)
    now = datetime.now(UTC)
    async with tenant_session(tenant_id) as db:
        await set_module(db, tenant_id, "key_accounts", True)
        orgs = {
            o.display_name: o
            for o in (await db.scalars(select(Lead).where(Lead.kind == "organisation"))).all()
        }
        products = {p.code: p for p in (await db.scalars(select(Product))).all()}
        pipeline = await db.scalar(select(Pipeline).order_by(Pipeline.position).limit(1))
        stages = {
            s.kind if s.kind != "open" else s.name: s
            for s in (
                await db.scalars(
                    select(PipelineStage).where(PipelineStage.pipeline_id == pipeline.id)
                )
            ).all()
        }
        chose_other = await db.scalar(
            select(LostReason).where(LostReason.name == "Chose a competitor")
        ) or await db.scalar(select(LostReason).limit(1))
        competitors = []
        for name in ("Talentra HR", "PayNest", "Workvana"):  # invented
            c = Competitor(tenant_id=tenant_id, name=name)
            db.add(c)
            competitors.append(c)
        await db.flush()

        plan = [  # (company, tier, parent, health, target in rupees)
            ("Varanta Group", "strategic", None, "on_track", 9_000_000),
            ("Varanta Motors", "strategic", "Varanta Group", "on_track", 4_000_000),
            ("Varanta Retail", "growth", "Varanta Group", "at_risk", 2_500_000),
            ("Varanta Finserv", "growth", "Varanta Group", "on_track", 1_500_000),
            ("Ombrel Pharma", "growth", None, "on_track", 3_000_000),
            ("Pinewyn Hospitals", "strategic", None, "off_track", 5_000_000),
            ("Granvik Cement", "maintain", None, "on_track", 1_000_000),
        ]
        accounts: dict[str, KeyAccount] = {}
        for name, tier, parent, health, target in plan:
            org = orgs[name]
            acc = KeyAccount(
                tenant_id=tenant_id,
                org_lead_id=org.id,
                tier=tier,
                owner_user_id=org.owner_user_id,
                parent_id=accounts[parent].id if parent else None,
                target_minor=target * 100,
                target_currency="INR",
                health=health,
                health_note={
                    "at_risk": "Their HR head is evaluating Talentra; renewal in 2 months",
                    "off_track": "Pilot stalled after the budget freeze",
                }.get(health),
            )
            db.add(acc)
            await db.flush()
            accounts[name] = acc
            people = list(
                (await db.scalars(select(Lead).where(Lead.organisation_id == org.id))).all()
            )
            units = []
            for i, unit_name in enumerate(("HR", "Finance", "IT")):
                holder = people[i] if i < len(people) else None
                u = AccountUnit(
                    tenant_id=tenant_id,
                    account_id=acc.id,
                    name=unit_name,
                    budget_holder_lead_id=holder.id if holder else None,
                    budget_minor=rng.choice([2_000_000, 3_500_000, 6_000_000]) * 100,
                    budget_currency="INR",
                    position=i,
                )
                db.add(u)
                units.append(u)
            await db.flush()
            for i, person in enumerate(people[:5]):
                db.add(
                    AccountContact(
                        tenant_id=tenant_id,
                        account_id=acc.id,
                        lead_id=person.id,
                        unit_id=units[i % 3].id,
                        role=["decision_maker", "influencer", "user", "gatekeeper", "influencer"][
                            i
                        ],
                        stance=["champion", "supporter", "neutral", "blocker", "neutral"][
                            (i + len(name)) % 5 if health != "on_track" else i % 3
                        ],
                        strength=[5, 4, 3, 2, 3][i],
                    )
                )
            # Deals on the grid: HR × Core HR won for most, Finance × Payroll in progress.
            grid = [
                ("HR", "HR-CORE", "won" if health != "off_track" else "open"),
                ("Finance", "PAYROLL", "Proposal" if tier != "maintain" else "lost"),
                ("IT", "RECRUIT", "Demo"),
            ]
            for unit_name, code, state in grid[: 3 if tier == "strategic" else 2]:
                product = products.get(code)
                if product is None:
                    continue
                stage = stages.get(state) or stages["won"]
                seats = rng.randint(80, 900)
                total = seats * product.price_minor
                when = now - timedelta(days=rng.uniform(5, 90))
                deal = Deal(
                    tenant_id=tenant_id,
                    name=f"{name} — {unit_name} — {product.name.split(' (')[0]}",
                    lead_id=org.id,
                    pipeline_id=pipeline.id,
                    stage_id=stage.id,
                    stage_changed_at=when,
                    status=stage.kind,
                    owner_user_id=org.owner_user_id,
                    team_id=org.team_id,
                    amount_minor=total,
                    currency=pipeline.currency,
                    closed_at=when if stage.kind != "open" else None,
                    lost_reason_id=chose_other.id if stage.kind == "lost" else None,
                    custom_fields={},
                    account_unit_id=next(u.id for u in units if u.name == unit_name),
                    created_at=when - timedelta(days=20),
                )
                db.add(deal)
                await db.flush()
                db.add(
                    DealProduct(
                        tenant_id=tenant_id, deal_id=deal.id, product_id=product.id,
                        name=product.name, quantity=seats, unit_price_minor=product.price_minor,
                        discount_minor=0, total_minor=total, position=0,
                    )
                )  # fmt: skip
            if "PAYROLL" in products and "RECRUIT" in products and tier != "strategic":
                db.add(
                    AccountCell(
                        tenant_id=tenant_id,
                        account_id=acc.id,
                        unit_id=units[2].id,
                        product_id=products["RECRUIT"].id,
                        status="competitor",
                        competitor_id=rng.choice(competitors).id,
                        note="Contract with them ends next year",
                    )
                )
            db.add(
                AccountGoal(
                    tenant_id=tenant_id,
                    account_id=acc.id,
                    title=f"Roll out payroll across {name}",
                    target_minor=target * 40,
                    currency="INR",
                    due_on=(now + timedelta(days=120)).date(),
                    status="open",
                    position=0,
                )
            )
        await db.flush()
    return len(accounts)
