"""Step C4.2 (docs/plans/android-app-plan.md): the Android app's phone key. A signed-in rep gets
one for their phone; it reports that rep's calls and uploads their recordings, and nothing else;
reconnecting the same install replaces the old key; the rep or an admin can remove a phone; a
key from another company doesn't work."""

import uuid

from tests.calls.test_calls import MP3, _call, _setup
from tests.crm.helpers import new_lead, setup_ids
from tests.factories import login_as, make_custom_role, make_workspace


def bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _connect(c, headers, install="install-abc-123"):
    body = {"install_id": install, "device": "samsung SM-A155F", "version": "0.2.0"}
    r = await c.post("/api/v1/phone/devices", json=body, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


async def test_the_phone_key_reports_calls_and_uploads_recordings_only(ws):
    tenant_id, c, admin, rep_id, rep, lead = await _setup(ws)
    key = bearer((await _connect(c, rep))["token"])

    me = await c.get("/api/v1/phone/me", headers=key)
    r = await c.post("/api/v1/calls", json=_call(), headers=key)
    call = r.json()["call"]
    up = await c.put(f"/api/v1/calls/{call['id']}/recording", content=MP3, headers=key)
    reads = [await c.get(p, headers=key) for p in (
        "/api/v1/leads", f"/api/v1/leads/{lead['id']}", "/api/v1/calls",
        f"/api/v1/calls/{call['id']}/recording", "/api/v1/auth/me")]  # fmt: skip
    another = await c.post("/api/v1/phone/devices", json={"install_id": "install-xyz-999"},
                           headers=key)  # fmt: skip
    listed = (await c.get("/api/v1/phone/devices", headers=rep)).json()

    assert me.json() == {"user_name": me.json()["user_name"], "company": me.json()["company"],
                         "record_calls": True}  # fmt: skip
    assert r.status_code == 200 and call["user_id"] == str(rep_id) and call["source"] == "app"
    assert up.status_code == 200 and up.json()["has_recording"]
    assert [x.status_code for x in reads] == [401] * 5
    assert another.status_code == 401  # a phone can't mint more keys
    assert len(listed) == 1 and listed[0]["last_call_at"] and listed[0]["device"]


async def test_reconnecting_replaces_and_removing_stops_the_key(ws):
    tenant_id, c, admin, rep_id, rep, lead = await _setup(ws)
    first = await _connect(c, rep)
    second = await _connect(c, rep)  # the same install signs in again
    old = await c.get("/api/v1/phone/me", headers=bearer(first["token"]))
    new = await c.get("/api/v1/phone/me", headers=bearer(second["token"]))
    _, other_rep = await login_as(tenant_id, "sales_user")
    by_other = await c.post(f"/api/v1/phone/devices/{second['device_id']}/remove",
                            headers=other_rep)  # fmt: skip
    everyone = (await c.get("/api/v1/phone/all-devices", headers=admin)).json()
    removed = await c.post(f"/api/v1/phone/devices/{second['device_id']}/remove", headers=admin)
    after = await c.get("/api/v1/phone/me", headers=bearer(second["token"]))

    assert old.status_code == 401 and new.status_code == 200
    assert by_other.status_code == 404
    assert [d["id"] for d in everyone] == [second["device_id"]]
    assert removed.status_code == 204 and after.status_code == 401


async def test_api_keys_cant_make_phone_keys_and_other_companies_cant_use_them(ws, client_for):
    tenant_id, c, admin, rep_id, rep, lead = await _setup(ws)
    key = bearer((await _connect(c, rep))["token"])
    other_id, other_slug = await make_workspace()
    other = client_for(other_slug)
    elsewhere = await other.get("/api/v1/phone/me", headers=key)
    missing = await c.get("/api/v1/phone/me", headers=bearer("vq_app_" + uuid.uuid4().hex))
    junk = await c.post("/api/v1/phone/devices", json={"install_id": "bad id!"}, headers=rep)
    role = await make_custom_role(tenant_id, "Tool", "all", ("leads.edit",))
    api = await c.post("/api/v1/integrations/keys", json={"name": "Tool", "role_id": str(role)},
                       headers=admin)  # fmt: skip
    by_api = await c.post("/api/v1/phone/devices", json={"install_id": "install-api-1"},
                          headers=bearer(api.json()["key"]))  # fmt: skip

    assert elsewhere.status_code == 401 and missing.status_code == 401
    assert junk.status_code == 422 and by_api.status_code == 403


async def test_the_caller_popup_names_only_leads_the_rep_can_see(ws):
    tenant_id, c, admin, rep_id, rep, lead = await _setup(ws)
    key = bearer((await _connect(c, rep))["token"])
    _, other_rep = await login_as(tenant_id, "sales_user")
    other_key = bearer((await _connect(c, other_rep, install="install-other-1"))["token"])

    mine = await c.get("/api/v1/phone/lookup", params={"number": "+91 98765 43210"}, headers=key)
    unknown = await c.get("/api/v1/phone/lookup", params={"number": "98111 22233"}, headers=key)
    hidden = await c.get("/api/v1/phone/lookup", params={"number": "9876543210"}, headers=other_key)
    junk = await c.get("/api/v1/phone/lookup", params={"number": "abc"}, headers=key)

    assert mine.status_code == 200 and mine.json()["lead_id"] == lead["id"]
    assert mine.json()["is_yours"] is True and mine.json()["stage"]
    assert unknown.json() is None and hidden.json() is None and junk.json() is None


async def test_another_number_is_added_to_the_lead_and_the_call_then_lands_there(ws):
    tenant_id, c, admin, rep_id, rep, lead = await _setup(ws)
    key = bearer((await _connect(c, rep))["token"])
    call = _call(number="98111 00011", direction="in")

    before = await c.post("/api/v1/calls", json=call, headers=key)  # unknown: not kept
    added = await c.post(f"/api/v1/leads/{lead['id']}/numbers", json={"number": "98111 00011"},
                         headers=rep)  # fmt: skip
    again = await c.post(f"/api/v1/leads/{lead['id']}/numbers", json={"number": "+919811100011"},
                         headers=rep)  # fmt: skip
    after = await c.post("/api/v1/calls", json=call, headers=key)  # the same call, sent again
    _, sources = await setup_ids(c, admin)
    other = (await new_lead(c, admin, sources["Website"], phone="98222 00022")).json()
    taken = await c.post(f"/api/v1/leads/{lead['id']}/numbers", json={"number": "98222 00022"},
                         headers=admin)  # fmt: skip

    assert before.json() == {"tracked": False, "call": None}
    assert added.status_code == 204 and again.status_code == 204
    assert after.json()["tracked"] and after.json()["call"]["lead_id"] == lead["id"]
    assert taken.status_code == 409 and taken.json()["code"] == "number_on_another_lead"
    assert other["id"] != lead["id"]
