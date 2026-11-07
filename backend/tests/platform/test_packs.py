import pytest

from app.platform.packs import LABEL_KEYS, UnknownPackError, available_packs, load_pack


def test_edtech_lead_label_is_student():
    lead = load_pack("edtech").labels["lead"]
    assert (lead.singular, lead.plural) == ("Student", "Students")


def test_edtech_deal_label_is_course_enrolment():
    assert load_pack("edtech").labels["deal"].singular == "Course enrolment"


def test_generic_lead_label_is_lead():
    assert load_pack("generic").labels["lead"].singular == "Lead"


def test_unknown_pack_raises():
    with pytest.raises(UnknownPackError):
        load_pack("does-not-exist")


@pytest.mark.parametrize("key", ["generic", "edtech"])
def test_every_pack_defines_every_label_key(key):
    assert set(load_pack(key).labels) == set(LABEL_KEYS)


def test_available_packs_lists_both():
    assert set(available_packs()) >= {"generic", "edtech"}


def test_pack_key_cannot_escape_the_packs_folder():
    with pytest.raises(UnknownPackError):
        load_pack("../../core/config")


async def test_staff_can_list_packs_for_the_create_company_form():
    from httpx import ASGITransport, AsyncClient

    from app.main import app
    from tests.factories import staff_headers

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        anonymous = await c.get("/platform/packs")
        listed = await c.get("/platform/packs", headers=await staff_headers())
    assert anonymous.status_code == 401
    assert listed.status_code == 200
    assert {"key": "edtech", "name": "EdTech"} in listed.json()
    assert [p["key"] for p in listed.json()] == available_packs()
