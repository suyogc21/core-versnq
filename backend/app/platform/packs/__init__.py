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


class IndustryPack(BaseModel):
    key: str
    name: str
    labels: dict[str, Label]


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
