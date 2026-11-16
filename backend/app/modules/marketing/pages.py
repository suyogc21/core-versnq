"""Landing pages (finishing plan, batch 5a).

A company builds simple pages out of blocks and publishes them at /p/<slug> on its own
address. Blocks: heading, text (plain text, line breaks kept, never HTML), image (an https
address), video (YouTube or Vimeo, shown with their privacy-friendly players), one of the
company's hosted forms, and a button (an https link). Everything is checked here and shown as
text by the page, so nothing a page holds can run as code.

Visits are counted without cookies: once per visitor address per page every 30 minutes. A lead
sent through a page's form carries attribution landing_page = /p/<slug>; each page's lead count
is counted from the leads themselves.
"""

import re
import uuid
from datetime import UTC, datetime
from typing import Annotated
from urllib.parse import urlparse

from fastapi import APIRouter, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select, update

from app.core.client_ip import client_ip
from app.core.errors import Conflict, Invalid, NotFound
from app.core.ratelimit import get_redis, hit
from app.modules.auth.deps import CurrentUser, WorkspaceDep, require
from app.modules.crm.deps import CRM, SCREENS, CrmDb, audit
from app.modules.crm.models import CaptureSource, Lead
from app.modules.marketing.models import LandingPage
from app.modules.settings.models import TenantSettings

router = APIRouter(prefix="/api/v1", tags=["landing-pages"], dependencies=[*CRM, *SCREENS])
public = APIRouter(prefix="/api/v1/pages", tags=["landing-pages"], dependencies=CRM)
Builder = Annotated[CurrentUser, require("pages.manage")]

MAX_BLOCKS = 40
SLUG = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,78}[a-z0-9])?$")
VISIT_SECONDS = 30 * 60
YOUTUBE_ID = re.compile(r"^[A-Za-z0-9_-]{6,20}$")


def now() -> datetime:
    return datetime.now(UTC)


def page_path(slug: str) -> str:
    return f"/p/{slug}"


# ---------- blocks ----------
def _https(url: str, what: str) -> str:
    url = (url or "").strip()
    u = urlparse(url)
    if u.scheme != "https" or not u.netloc or len(url) > 1000 or any(c in url for c in "\"'<> "):
        raise Invalid(f"{what}: use a full https:// address")
    return url


def video_embed(url: str) -> str:
    """A YouTube or Vimeo address as the provider's embeddable player; anything else refused."""
    u = urlparse(_https(url, "Video"))
    host = (u.hostname or "").lower().removeprefix("www.").removeprefix("m.")
    vid = None
    if host in ("youtube.com", "youtube-nocookie.com"):
        if u.path == "/watch":
            q = dict(p.split("=", 1) for p in u.query.split("&") if "=" in p)
            vid = q.get("v")
        elif u.path.startswith(("/embed/", "/shorts/")):
            vid = u.path.split("/")[2]
    elif host == "youtu.be":
        vid = u.path.lstrip("/").split("/")[0]
    elif host in ("vimeo.com", "player.vimeo.com"):
        num = u.path.rstrip("/").split("/")[-1]
        if num.isdigit():
            return f"https://player.vimeo.com/video/{num}"
        raise Invalid("Video: use a Vimeo video address like https://vimeo.com/123456")
    if vid and YOUTUBE_ID.match(vid):
        return f"https://www.youtube-nocookie.com/embed/{vid}"
    raise Invalid("Video: use a YouTube or Vimeo address")


async def clean_blocks(db, blocks: list[dict]) -> list[dict]:
    """Every block checked and reduced to the fields its kind has."""
    if len(blocks) > MAX_BLOCKS:
        raise Invalid(f"A page can have up to {MAX_BLOCKS} blocks")
    out: list[dict] = []
    for i, b in enumerate(blocks, start=1):
        if not isinstance(b, dict):
            raise Invalid(f"Block {i}: unknown kind of block")
        kind = b.get("type")

        def text(key: str, limit: int, b: dict = b) -> str:
            return str(b.get(key) or "").strip()[:limit]

        if kind == "heading":
            if not text("text", 200):
                raise Invalid(f"Block {i}: write the heading")
            out.append({"type": "heading", "text": text("text", 200),
                        "level": 2 if b.get("level") == 2 else 1})  # fmt: skip
        elif kind == "text":
            if not text("text", 5000):
                raise Invalid(f"Block {i}: write the text")
            out.append({"type": "text", "text": text("text", 5000)})
        elif kind == "image":
            out.append({"type": "image", "url": _https(str(b.get("url") or ""), f"Block {i}"),
                        "alt": text("alt", 200)})  # fmt: skip
        elif kind == "video":
            url = str(b.get("url") or "")
            out.append({"type": "video", "url": url.strip(), "embed_url": video_embed(url)})
        elif kind == "form":
            form_id = str(b.get("form_id") or "")
            src = await db.scalar(select(CaptureSource).where(CaptureSource.public_id == form_id))
            if src is None or not src.hosted or not src.form:
                raise Invalid(f"Block {i}: choose one of your forms")
            out.append({"type": "form", "form_id": form_id})
        elif kind == "button":
            if not text("label", 60):
                raise Invalid(f"Block {i}: write the button's label")
            out.append({"type": "button", "label": text("label", 60),
                        "url": _https(str(b.get("url") or ""), f"Block {i}")})  # fmt: skip
        else:
            raise Invalid(f"Block {i}: unknown kind of block")
    return out


# ---------- shapes ----------
class PageIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    slug: str = Field(min_length=1, max_length=80)
    blocks: list[dict] = Field(default=[], max_length=MAX_BLOCKS)
    published: bool = False
    brand_id: uuid.UUID | None = None
    seo_title: str | None = Field(default=None, max_length=200)
    seo_description: str | None = Field(default=None, max_length=300)


class PageOut(BaseModel):
    model_config = {"from_attributes": True}
    id: uuid.UUID
    title: str
    slug: str
    path: str = ""
    blocks: list[dict]
    published: bool
    published_at: datetime | None
    brand_id: uuid.UUID | None
    seo_title: str | None
    seo_description: str | None
    visits: int
    leads: int = 0
    created_at: datetime
    updated_at: datetime


class PublicCompany(BaseModel):
    name: str
    logo_url: str | None = None
    primary_color: str | None = None


class PublicPageOut(BaseModel):
    slug: str
    title: str
    seo_title: str | None
    seo_description: str | None
    company: PublicCompany
    blocks: list[dict]


# ---------- the builder ----------
async def _out(db, pages: list[LandingPage]) -> list[PageOut]:
    paths = [page_path(p.slug) for p in pages]
    key = Lead.attribution["landing_page"].astext
    counts = dict(
        (await db.execute(select(key, func.count()).where(key.in_(paths)).group_by(key))).all()
    ) if paths else {}  # fmt: skip
    out = []
    for p in pages:
        item = PageOut.model_validate(p)
        item.path, item.leads = page_path(p.slug), counts.get(page_path(p.slug), 0)
        out.append(item)
    return out


async def _check(db, body: PageIn, page_id: uuid.UUID | None) -> dict:
    slug = body.slug.strip().lower()
    if not SLUG.match(slug):
        raise Invalid("The address may use small letters, numbers and dashes, like summer-batch")
    taken = await db.scalar(select(LandingPage.id).where(LandingPage.slug == slug))
    if taken and taken != page_id:
        raise Conflict("Another page already uses this address", code="slug_taken")
    if body.brand_id:
        from app.modules.brands.models import Brand

        if await db.get(Brand, body.brand_id) is None:
            raise Invalid("Choose one of your brands")
    return {
        "title": body.title.strip(), "slug": slug, "blocks": await clean_blocks(db, body.blocks),
        "published": body.published, "brand_id": body.brand_id,
        "seo_title": (body.seo_title or "").strip() or None,
        "seo_description": (body.seo_description or "").strip() or None,
    }  # fmt: skip


@router.get("/landing-pages", response_model=list[PageOut])
async def list_pages(db: CrmDb, actor: Builder) -> list[PageOut]:
    rows = (await db.scalars(select(LandingPage).order_by(LandingPage.created_at.desc()))).all()
    return await _out(db, list(rows))


@router.post("/landing-pages", response_model=PageOut, status_code=status.HTTP_201_CREATED)
async def create_page(body: PageIn, db: CrmDb, actor: Builder) -> PageOut:
    values = await _check(db, body, None)
    page = LandingPage(id=uuid.uuid4(), tenant_id=actor.user.tenant_id,
                       created_by_user_id=actor.user.id, **values)  # fmt: skip
    if page.published:
        page.published_at = now()
    db.add(page)
    await db.flush()
    await audit(db, actor, "landing_page.created", "landing_page", page.id, None,
                {"slug": page.slug, "published": page.published})  # fmt: skip
    await db.refresh(page)
    return (await _out(db, [page]))[0]


async def _get(db, page_id: uuid.UUID) -> LandingPage:
    page = await db.get(LandingPage, page_id)
    if page is None:
        raise NotFound("Page not found")
    return page


@router.get("/landing-pages/{page_id}", response_model=PageOut)
async def get_page(page_id: uuid.UUID, db: CrmDb, actor: Builder) -> PageOut:
    return (await _out(db, [await _get(db, page_id)]))[0]


@router.put("/landing-pages/{page_id}", response_model=PageOut)
async def update_page(page_id: uuid.UUID, body: PageIn, db: CrmDb, actor: Builder) -> PageOut:
    page = await _get(db, page_id)
    values = await _check(db, body, page.id)
    was = page.published
    for k, v in values.items():
        setattr(page, k, v)
    if page.published and not was:
        page.published_at = now()
    await db.flush()
    await audit(db, actor, "landing_page.updated", "landing_page", page.id, None,
                {"slug": page.slug, "published": page.published})  # fmt: skip
    await db.refresh(page)
    return (await _out(db, [page]))[0]


@router.delete("/landing-pages/{page_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_page(page_id: uuid.UUID, db: CrmDb, actor: Builder) -> None:
    page = await _get(db, page_id)
    await db.delete(page)
    await audit(db, actor, "landing_page.deleted", "landing_page", page_id, {"slug": page.slug})


# ---------- the public page ----------
async def _published(db, slug: str) -> LandingPage:
    page = await db.scalar(select(LandingPage).where(LandingPage.slug == slug.lower()[:80]))
    if page is None or not page.published:
        raise NotFound("Page not found")
    return page


@public.get("/{slug}", response_model=PublicPageOut)
async def public_page(slug: str, ws: WorkspaceDep, db: CrmDb) -> PublicPageOut:
    """Public: a published page, for /p/<slug>."""
    page = await _published(db, slug)
    settings = await db.get(TenantSettings, ws.id)
    brand = (settings.branding if settings else None) or {}
    company = PublicCompany(name=ws.name, logo_url=brand.get("logo_url"),
                            primary_color=brand.get("primary_color"))  # fmt: skip
    if page.brand_id:
        from app.modules.brands.models import Brand

        own = await db.get(Brand, page.brand_id)
        if own is not None and own.is_active:
            company = PublicCompany(name=own.name, logo_url=own.logo_url or company.logo_url,
                                    primary_color=own.colour or company.primary_color)  # fmt: skip
    blocks = [
        {k: v for k, v in b.items() if k != "url"} if b["type"] == "video" else b
        for b in page.blocks
    ]
    return PublicPageOut(
        slug=page.slug, title=page.title, seo_title=page.seo_title,
        seo_description=page.seo_description, company=company, blocks=blocks,
    )  # fmt: skip


@public.post("/{slug}/visit", status_code=status.HTTP_204_NO_CONTENT)
async def count_visit(slug: str, request: Request, ws: WorkspaceDep, db: CrmDb) -> None:
    """Public: the page was opened. Counted once per visitor address per page every 30 minutes,
    with no cookies; unknown or unpublished pages answer 404."""
    if not await hit(f"rl:pagevisit:{ws.id}:{client_ip(request)}", 60, 60):
        return
    page = await _published(db, slug)
    first = await get_redis().set(
        f"pagevisit:{page.id}:{client_ip(request)}", "1", ex=VISIT_SECONDS, nx=True
    )
    if first:
        more = update(LandingPage).where(LandingPage.id == page.id)
        await db.execute(more.values(visits=LandingPage.visits + 1))
