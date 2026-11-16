"""Batch 5a: landing pages. Only pages.manage builds them; blocks are checked (https only, no
javascript: links, YouTube/Vimeo players only, the company's own forms); an unpublished page
and another company's page are a 404; visits are counted once per address every 30 minutes;
a lead sent through the page's form carries the page and is counted for it."""

import pytest
from sqlalchemy import select

from app.core.tenancy import tenant_session
from app.modules.crm.models import Lead
from tests.factories import login_as, make_workspace

FORM = {
    "title": "Book a demo",
    "button": "Send",
    "fields": [
        {"target": "full_name", "label": "Name", "required": True},
        {"target": "phone", "label": "Mobile", "required": True},
    ],
    "thank_you": "Thanks!",
}


@pytest.fixture
async def ws(client_for):
    tenant_id, slug = await make_workspace()
    c = client_for(slug)
    _, admin = await login_as(tenant_id, "admin")
    return tenant_id, c, admin


async def _form(c, h) -> str:
    sources = {s["name"]: s["id"] for s in (await c.get("/api/v1/lead-sources", headers=h)).json()}
    r = await c.post("/api/v1/capture-sources", json={
        "name": "Demo", "source_id": sources["Website"], "form": FORM, "hosted": True,
    }, headers=h)  # fmt: skip
    assert r.status_code == 201, r.text
    return r.json()["public_id"]


def _page(form_id: str, **extra) -> dict:
    return {
        "title": "Summer batch", "slug": "Summer-Batch", "published": True,
        "seo_title": "Summer batch 2026",
        "blocks": [
            {"type": "heading", "text": "Learn data science", "level": 1},
            {"type": "text", "text": "Twelve weeks.\nWeekends only. <b>no html</b>"},
            {"type": "image", "url": "https://example.com/hero.jpg", "alt": "Class"},
            {"type": "video", "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"},
            {"type": "form", "form_id": form_id},
            {"type": "button", "label": "Brochure", "url": "https://example.com/brochure.pdf"},
        ],
        **extra,
    }  # fmt: skip


async def test_a_published_page_shows_its_blocks_and_counts_its_leads(ws):
    tenant_id, c, admin = ws
    form_id = await _form(c, admin)
    made = await c.post("/api/v1/landing-pages", json=_page(form_id), headers=admin)
    assert made.status_code == 201, made.text
    page = (await c.get("/api/v1/pages/summer-batch")).json()
    sent = await c.post(f"/api/v1/forms/{form_id}", json={
        "full_name": "Asha Rao", "phone": "98765 11122", "landing_page": "/p/summer-batch",
    })  # fmt: skip
    listed = (await c.get("/api/v1/landing-pages", headers=admin)).json()

    assert made.json()["slug"] == "summer-batch" and made.json()["path"] == "/p/summer-batch"
    assert [b["type"] for b in page["blocks"]] == [
        "heading", "text", "image", "video", "form", "button"]  # fmt: skip
    assert page["blocks"][1]["text"].endswith("<b>no html</b>")  # kept as text, shown as text
    video = page["blocks"][3]
    assert video == {
        "type": "video",
        "embed_url": "https://www.youtube-nocookie.com/embed/dQw4w9WgXcQ",
    }
    assert page["company"]["name"] and page["seo_title"] == "Summer batch 2026"
    assert sent.status_code == 201
    assert listed[0]["leads"] == 1
    async with tenant_session(tenant_id) as db:
        lead = await db.scalar(select(Lead))
    assert lead.attribution["landing_page"] == "/p/summer-batch"


async def test_blocks_are_checked(ws):
    tenant_id, c, admin = ws
    form_id = await _form(c, admin)
    bad = [
        {"type": "button", "label": "Go", "url": "javascript:alert(1)"},
        {"type": "button", "label": "Go", "url": "http://example.com"},
        {"type": "image", "url": 'https://example.com/a.jpg" onerror="x'},
        {"type": "video", "url": "https://evil.example.com/watch?v=dQw4w9WgXcQ"},
        {"type": "form", "form_id": "not-a-form"},
        {"type": "html", "text": "<script>"},
        {"type": "heading", "text": "   "},
    ]
    results = [
        await c.post(
            "/api/v1/landing-pages",
            json={"title": "x", "slug": f"x{i}", "blocks": [b]},
            headers=admin,
        )  # fmt: skip
        for i, b in enumerate(bad)
    ]
    bad_slug = await c.post("/api/v1/landing-pages",
                            json={"title": "x", "slug": "no spaces!"}, headers=admin)  # fmt: skip
    first = await c.post("/api/v1/landing-pages", json=_page(form_id), headers=admin)
    taken = await c.post("/api/v1/landing-pages", json=_page(form_id), headers=admin)
    vimeo = await c.post("/api/v1/landing-pages", headers=admin, json={
        "title": "v", "slug": "v", "blocks": [{"type": "video", "url": "https://vimeo.com/76979871"}],
    })  # fmt: skip

    assert [r.status_code for r in results] == [422] * len(bad)
    assert bad_slug.status_code == 422 and first.status_code == 201
    assert taken.status_code == 409 and taken.json()["code"] == "slug_taken"
    assert vimeo.json()["blocks"][0]["embed_url"] == "https://player.vimeo.com/video/76979871"


async def test_unpublished_and_other_companies_pages_are_a_404(ws, client_for):
    tenant_id, c, admin = ws
    form_id = await _form(c, admin)
    draft = await c.post("/api/v1/landing-pages",
                         json=_page(form_id, published=False), headers=admin)  # fmt: skip
    hidden = await c.get("/api/v1/pages/summer-batch")
    visit = await c.post("/api/v1/pages/summer-batch/visit")
    await c.put(f"/api/v1/landing-pages/{draft.json()['id']}", json=_page(form_id), headers=admin)
    shown = await c.get("/api/v1/pages/summer-batch")
    other_id, other_slug = await make_workspace()
    elsewhere = await client_for(other_slug).get("/api/v1/pages/summer-batch")

    assert hidden.status_code == 404 and visit.status_code == 404
    assert shown.status_code == 200 and elsewhere.status_code == 404


async def test_visits_are_counted_once_per_address_and_only_builders_manage_pages(ws):
    tenant_id, c, admin = ws
    form_id = await _form(c, admin)
    page = (await c.post("/api/v1/landing-pages", json=_page(form_id), headers=admin)).json()
    for _ in range(3):
        assert (await c.post("/api/v1/pages/summer-batch/visit")).status_code == 204
    _, rep = await login_as(tenant_id, "sales_user")
    by_rep = await c.get("/api/v1/landing-pages", headers=rep)
    edit_by_rep = await c.put(
        f"/api/v1/landing-pages/{page['id']}", json=_page(form_id), headers=rep
    )
    listed = (await c.get("/api/v1/landing-pages", headers=admin)).json()

    assert listed[0]["visits"] == 1
    assert by_rep.status_code == 403 and edit_by_rep.status_code == 403
    gone = await c.delete(f"/api/v1/landing-pages/{page['id']}", headers=admin)
    assert gone.status_code == 204
    assert (await c.get("/api/v1/pages/summer-batch")).status_code == 404
