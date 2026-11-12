"""Templates with variables (step 9a).

`{{lead.first_name}}` or with a fallback `{{lead.first_name|there}}`. Known names:
lead.first_name, lead.last_name, lead.name, lead.company, lead.city, lead.email, lead.phone,
owner.name, owner.email, owner.phone, company.name and lead.cf.<custom field key>. Unknown
names are refused when the template is saved, so a send never shows a raw `{{...}}`.

Email bodies are plain text: on sending they become simple HTML (paragraphs, links made
clickable and tracked, an open pixel) plus a plain-text part, and every email ends with a
one-click unsubscribe link (rule 8).
"""

import html
import re
from dataclasses import dataclass

from app.core.errors import Invalid

VAR = re.compile(r"\{\{\s*([a-z_.0-9]+)\s*(?:\|([^}]*))?\}\}")
URL = re.compile(r"https?://[^\s<>\"')\]]+", re.IGNORECASE)
SIMPLE = {
    "lead.first_name", "lead.last_name", "lead.name", "lead.company", "lead.city",
    "lead.email", "lead.phone", "owner.name", "owner.email", "owner.phone", "company.name",
}  # fmt: skip


def check(text: str, custom_keys: set[str]) -> None:
    for name, _ in VAR.findall(text or ""):
        if name in SIMPLE:
            continue
        if name.startswith("lead.cf.") and name[8:] in custom_keys:
            continue
        raise Invalid(f"Unknown variable {{{{{name}}}}}")
    if "{{" in VAR.sub("", text or ""):
        raise Invalid("A {{ is not closed, or a variable is written wrongly")


def fill(text: str, values: dict[str, str | None]) -> str:
    def one(m: re.Match) -> str:
        value = values.get(m.group(1))
        if value in (None, ""):
            return (m.group(2) or "").strip()
        return str(value)

    return VAR.sub(one, text or "")


@dataclass
class Built:
    text: str
    html: str
    links: list[str]


def build_email(
    body: str, *, track_base: str | None, token: str, unsubscribe_url: str | None
) -> Built:
    """Plain text → (text, html, tracked links). `track_base` None = no tracking (tests can
    still check the links list)."""
    links: list[str] = []

    def link(m: re.Match) -> str:
        url = m.group(0)
        links.append(url)
        target = f"{track_base}/c/{token}/{len(links) - 1}" if track_base else url
        return f'<a href="{html.escape(target, quote=True)}">{html.escape(url)}</a>'

    paragraphs = []
    for block in re.split(r"\n\s*\n", (body or "").strip()):
        parts, last = [], 0
        for m in URL.finditer(block):  # text is escaped, links become tracked anchors
            parts.append(html.escape(block[last : m.start()]))
            parts.append(link(m))
            last = m.end()
        parts.append(html.escape(block[last:]))
        paragraphs.append("<p>" + "".join(parts).replace("\n", "<br>") + "</p>")
    pixel = (
        f'<img src="{html.escape(track_base)}/o/{token}.gif" width="1" height="1" alt=""'
        ' style="display:none">'
        if track_base
        else ""
    )
    footer = (
        '<p style="color:#888;font-size:12px">Don\'t want these emails? '
        f'<a href="{html.escape(unsubscribe_url, quote=True)}">Unsubscribe</a></p>'
        if unsubscribe_url
        else ""
    )
    page = (
        '<div style="font-family:Arial,Helvetica,sans-serif;font-size:14px;line-height:1.5">'
        + "".join(paragraphs)
        + footer
        + pixel
        + "</div>"
    )
    text = (body or "").strip() + "\n"
    if unsubscribe_url:
        text += f"\n—\nUnsubscribe: {unsubscribe_url}\n"
    return Built(text=text, html=page, links=links)
