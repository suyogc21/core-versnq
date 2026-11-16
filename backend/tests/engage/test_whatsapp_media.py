"""Finish plan, batch 3: WhatsApp extras on the company number. Voice notes and videos sent to
the company are kept on the lead; reps send photos and documents inside the 24-hour window only;
templates carry a photo / video / document or text header and buttons, in Meta's shapes; files
stay inside the company and with people who can see the lead. Meta is never called."""

from datetime import UTC, datetime

from sqlalchemy import select

from app.core.tenancy import tenant_session
from app.modules.crm.models import StoredFile
from app.modules.engage.models import Message, MessageAttachment
from tests.engage.test_whatsapp import (  # noqa: F401  (fake_meta and ws are fixtures)
    Recorder,
    _deliver,
    _lead,
    _payload,
    _text,
    fake_meta,
    ws,
)
from tests.factories import login_as, make_workspace, switch_on

JPG = b"\xff\xd8\xff\xe0" + b"\x00" * 600
PDF = b"%PDF-1.4\n" + b"x" * 600
OGG = b"OggS" + b"\x00" * 600
MP4 = b"\x00\x00\x00\x18ftypisom" + b"\x00" * 600
WEBP = b"RIFF\x00\x00\x00\x00WEBPVP8 " + b"\x00" * 600
WA_ID = "919876543210"


def _media_msg(kind, media_id, **extra):
    return {
        "from": WA_ID,
        "id": f"wamid.{kind}{media_id}",
        "timestamp": str(int(datetime.now(UTC).timestamp())),
        "type": kind,
        kind: {"id": media_id, **extra},
    }


def _upload(c, path, data, headers, name, **params):
    return c.post(path, content=data, params=params,
                  headers={**headers, "X-File-Name": name,
                           "Content-Type": "application/octet-stream"})  # fmt: skip


async def test_voice_notes_videos_and_photos_from_the_lead_are_kept(ws, monkeypatch):  # noqa: F811
    files = {"V1": (OGG, "audio/ogg"), "V2": (MP4, "video/mp4"), "P1": (JPG, "image/jpeg")}

    async def media(self, media_id):
        return files[media_id]

    monkeypatch.setattr(Recorder, "media", media)
    tenant_id, c, admin = ws
    await _lead(c, admin)
    kept = await _deliver(c, _payload(
        _media_msg("audio", "V1", voice=True), _media_msg("video", "V2", caption="our site"),
        _media_msg("image", "P1", caption="cheque"),
    ))  # fmt: skip
    assert kept == 3
    async with tenant_session(tenant_id) as db:
        rows = (await db.execute(
            select(Message.body, StoredFile.content_type)
            .join(MessageAttachment, MessageAttachment.message_id == Message.id)
            .join(StoredFile, StoredFile.id == MessageAttachment.file_id)
        )).all()  # fmt: skip
    assert sorted(rows) == [
        ("[photo] cheque", "image/jpeg"),
        ("[video] our site", "video/mp4"),
        ("[voice note]", "audio/ogg"),
    ]


async def test_photos_and_documents_go_out_only_inside_the_window(ws):  # noqa: F811
    tenant_id, c, admin = ws
    lead = await _lead(c, admin)
    url = f"/api/v1/leads/{lead['id']}/whatsapp/media"

    closed = await _upload(c, url, JPG, admin, "site.jpg", caption="Our campus")
    await _deliver(c, _payload(_text(WA_ID, "Please send the brochure")))  # opens the window
    photo = await _upload(c, url, JPG, admin, "site.jpg", caption="Our campus")
    webp = await _upload(c, url, WEBP, admin, "sticker.webp")
    conv_id = photo.json()["conversation_id"]
    doc = await _upload(c, f"/api/v1/conversations/{conv_id}/whatsapp-media", PDF, admin,
                        "brochure.pdf", caption="Fees")  # fmt: skip
    _, rep = await login_as(tenant_id, "sales_user")  # not the owner: can't see this lead
    hidden = await _upload(c, url, JPG, rep, "x.jpg")

    assert closed.status_code == 422 and closed.json()["code"] == "whatsapp_window_closed"
    assert photo.status_code == 201, photo.text
    assert webp.status_code == 422 and webp.json()["code"] == "whatsapp_media_type"
    assert doc.status_code == 200, doc.text
    assert hidden.status_code == 404
    sent = [p for p in Recorder.sent if p["type"] in ("image", "document")]
    assert sent[0]["image"]["caption"] == "Our campus" and sent[0]["image"]["id"]
    assert sent[1]["document"] == {"id": sent[1]["document"]["id"], "caption": "Fees",
                                   "filename": "brochure.pdf"}  # fmt: skip
    out = [m for m in doc.json()["messages"] if m["direction"] == "out"]
    assert [m["attachments"][0]["name"] for m in out] == ["site.jpg", "brochure.pdf"]


async def test_template_with_a_photo_header_and_buttons_in_metas_shapes(ws):  # noqa: F811
    tenant_id, c, admin = ws
    lead = await _lead(c, admin)
    up = await _upload(c, "/api/v1/whatsapp/templates/header-file", JPG, admin, "offer.jpg")
    assert up.status_code == 201 and up.json()["format"] == "image", up.text
    body = {
        "name": "offer", "category": "utility",
        "body": "Hi {{lead.first_name|there}}, your seat is held.",
        "header": {"format": "image", "file_key": up.json()["key"]},
        "buttons": [
            {"type": "quick_reply", "text": "Yes, book it"},
            {"type": "url", "text": "Pay now", "url": "https://pay.example.com/{{lead.first_name}}"},
            {"type": "phone", "text": "Call us", "phone": "+91 98200 11122"},
        ],
    }  # fmt: skip
    r = await c.post("/api/v1/whatsapp/templates", json=body, headers=admin)
    assert r.status_code == 201, r.text
    submitted = Recorder.submitted[-1]["components"]
    sent = await c.post(f"/api/v1/leads/{lead['id']}/whatsapp",
                        json={"template_id": r.json()["id"]}, headers=admin)  # fmt: skip

    assert submitted[0]["type"] == "HEADER" and submitted[0]["format"] == "IMAGE"
    assert submitted[0]["example"]["header_handle"][0].startswith("4::")
    assert submitted[-1] == {"type": "BUTTONS", "buttons": [
        {"type": "QUICK_REPLY", "text": "Yes, book it"},
        {"type": "URL", "text": "Pay now", "url": "https://pay.example.com/{{1}}",
         "example": ["https://pay.example.com/Asha"]},
        {"type": "PHONE_NUMBER", "text": "Call us", "phone_number": "+919820011122"},
    ]}  # fmt: skip
    assert r.json()["buttons"][1]["url"] == "https://pay.example.com/{{lead.first_name}}"
    assert sent.status_code == 201, sent.text
    parts = Recorder.sent[-1]["template"]["components"]
    assert parts[0]["type"] == "header" and parts[0]["parameters"][0]["image"]["id"]
    assert parts[1] == {"type": "body", "parameters": [{"type": "text", "text": "Asha"}]}
    assert parts[2] == {"type": "button", "sub_type": "url", "index": "1",
                        "parameters": [{"type": "text", "text": "Asha"}]}  # fmt: skip
    async with tenant_session(tenant_id) as db:
        msg = await db.get(Message, sent.json()["message_id"])
    assert msg.body.startswith("[photo] Hi Asha")
    assert msg.body.endswith("[Buttons: Yes, book it · Pay now · Call us]")


TEMPLATES = "/api/v1/whatsapp/templates"
BODY = "Your demo is confirmed, see you soon."


async def test_header_and_button_rules(ws):  # noqa: F811
    tenant_id, c, admin = ws

    async def make(name, **extra):
        body = {"category": "utility", "body": BODY, "name": name, **extra}
        return await c.post(TEMPLATES, json=body, headers=admin)

    urls = [{"type": "url", "text": f"Site {i}", "url": "https://example.com"} for i in range(3)]
    too_many = await make("a", buttons=urls)
    bad_phone = await make("b", buttons=[{"type": "phone", "text": "Call", "phone": "12345"}])
    plain_http = await make("c", buttons=[{"type": "url", "text": "Go", "url": "http://x.com"}])
    no_file = await make("d", header={"format": "image"})
    pdf = await _upload(c, f"{TEMPLATES}/header-file", PDF, admin, "terms.pdf")
    wrong = await make("e", header={"format": "image", "file_key": pdf.json()["key"]})
    text = await make("f", header={"format": "text", "text": "Demo booked"})
    _, rep = await login_as(tenant_id, "sales_user")
    by_rep = await _upload(c, "/api/v1/whatsapp/templates/header-file", JPG, rep, "x.jpg")

    assert [r.status_code for r in (too_many, bad_phone, plain_http, no_file, wrong)] == [422] * 5
    assert pdf.json()["format"] == "document"
    assert text.status_code == 201 and Recorder.submitted[-1]["components"][0] == {
        "type": "HEADER", "format": "TEXT", "text": "Demo booked"}  # fmt: skip
    assert by_rep.status_code == 403


async def test_a_header_file_and_conversations_stay_inside_their_company(ws, client_for):  # noqa: F811
    tenant_id, c, admin = ws
    up = await _upload(c, "/api/v1/whatsapp/templates/header-file", JPG, admin, "offer.jpg")
    lead = await _lead(c, admin)
    await _deliver(c, _payload(_text(WA_ID, "hi")))
    conv_id = (await _upload(c, f"/api/v1/leads/{lead['id']}/whatsapp/media", JPG, admin,
                             "a.jpg")).json()["conversation_id"]  # fmt: skip

    other_id, other_slug = await make_workspace()
    await switch_on(other_id, "whatsapp_number")
    o = client_for(other_slug)
    _, other_admin = await login_as(other_id, "admin")
    await o.put("/api/v1/whatsapp/account", json={"phone_number_id": "3333333",
                "waba_id": "4444444", "access_token": "t", "app_secret": "s"},
                headers=other_admin)  # fmt: skip
    header = {"format": "image", "file_key": up.json()["key"]}
    body = {"name": "x", "category": "utility", "body": BODY, "header": header}
    stolen = await o.post(TEMPLATES, json=body, headers=other_admin)
    theirs = await _upload(o, f"/api/v1/conversations/{conv_id}/whatsapp-media", JPG,
                           other_admin, "a.jpg")  # fmt: skip

    assert stolen.status_code == 422 and stolen.json()["code"] == "whatsapp_header_file"
    assert theirs.status_code == 404
