"""Industry packs: seed data (labels now; stages, sources, fields later). Never code branches."""

import json
import re
from pathlib import Path

from pydantic import BaseModel

PACKS_DIR = Path(__file__).parent
LABEL_KEYS = ("lead", "contact", "deal", "customer", "pipeline")
_KEY = re.compile(r"^[a-z][a-z0-9_-]{1,39}$")


class UnknownPackError(ValueError):
    pass


class Label(BaseModel):
    singular: str
    plural: str


class PackStage(BaseModel):
    name: str
    is_open: bool
    is_unqualified: bool = False
    is_converted: bool = False
    colour: str | None = None
    required_fields: list[str] = []


class PackField(BaseModel):
    key: str
    label: str
    type: str
    options: list[dict] = []
    required: bool = False
    is_unique: bool = False
    depends_on: str | None = None
    group_name: str | None = None


class PackActivityType(BaseModel):
    key: str
    label: str
    fields: list[dict] = []
    icon: str | None = None


class PackRecordStage(BaseModel):
    name: str
    is_open: bool = True
    colour: str | None = None


class PackRecordType(BaseModel):
    """A starting record type (e.g. Batch for EdTech). Companies edit or remove it."""

    key: str
    singular: str
    plural: str
    icon: str | None = None
    has_owner: bool = True
    stages: list[PackRecordStage] = []
    fields: list[PackField] = []


class PackLinkType(BaseModel):
    from_type: str | None = None  # a record type key; None = leads
    to_type: str | None = None
    label: str
    inverse_label: str
    many_to: bool = True
    many_from: bool = True


class PackPipelineStage(BaseModel):
    name: str
    kind: str = "open"  # open / won / lost
    probability: int = 0
    colour: str | None = None


class PackPipeline(BaseModel):
    name: str  # currency: the company's default currency
    stages: list[PackPipelineStage]


class PackProduct(BaseModel):
    name: str
    code: str | None = None
    description: str | None = None
    prices: dict[str, int] = {}  # currency -> minor units; seeded only in the company's currency


class CrmPack(BaseModel):
    """Starting CRM setup for a new company. Configuration only; every company can edit it."""

    stages: list[PackStage]
    sources: list[str]
    dispositions: list[str]
    custom_fields: list[PackField] = []
    activity_types: list[PackActivityType] = []
    record_types: list[PackRecordType] = []
    link_types: list[PackLinkType] = []
    pipelines: list[PackPipeline] = []
    lost_reasons: list[str] = []
    products: list[PackProduct] = []


class IndustryPack(BaseModel):
    key: str
    name: str
    labels: dict[str, Label]
    crm: CrmPack


def available_packs() -> list[str]:
    return sorted(p.stem for p in PACKS_DIR.glob("*.json"))


def load_pack(key: str) -> IndustryPack:
    if not _KEY.match(key) or key not in available_packs():
        raise UnknownPackError(f"Unknown industry pack: {key!r}")
    pack = IndustryPack.model_validate(json.loads((PACKS_DIR / f"{key}.json").read_text()))
    missing = set(LABEL_KEYS) - set(pack.labels)
    if missing:
        raise UnknownPackError(f"Pack {key!r} is missing labels: {sorted(missing)}")
    return pack
