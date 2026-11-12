"""B2B demo (Decision log #36): the invented client companies Brightlane Software sells to,
each with a few contacts. Every name is invented; none is a real company or brand."""

import random
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.crm.models import Lead, LeadSource, LeadStage

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
