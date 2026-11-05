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
