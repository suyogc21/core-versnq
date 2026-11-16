"""Files on our own server's disk (Decision log #29).

Every file is saved under `FILES_DIR/<company-id>/<year>/<month>/<random-name>` and its record
(name, size, type, checksum, owner) lives in Postgres. Nothing else in the app touches the disk:
replacing this module is all it takes to move to outside storage later.

- The real type is read from the file's first bytes, never trusted from its name.
- A file is written to a temporary name and then renamed, so a failed upload leaves nothing.
- Paths are always ours (random names); reading checks the path stays inside the files folder.
"""

import hashlib
import os
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from fastapi import Request

from app.core.config import get_settings
from app.core.errors import Invalid

MAX_FILE_BYTES = 10 * 1024 * 1024

# content type, extension, needs "office files allowed"
_PDF = ("application/pdf", "pdf", False)
_JPG = ("image/jpeg", "jpg", False)
_PNG = ("image/png", "png", False)
_WEBP = ("image/webp", "webp", False)
_HEIC = ("image/heic", "heic", False)
_DOCX = ("application/vnd.openxmlformats-officedocument.wordprocessingml.document", "docx", True)
_XLSX = ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "xlsx", True)
_DOC = ("application/msword", "doc", True)
_XLS = ("application/vnd.ms-excel", "xls", True)
PREVIEWABLE = {"application/pdf", "image/jpeg", "image/png", "image/webp"}
MAX_AUDIO_BYTES = 50 * 1024 * 1024  # call recordings (step C1)


@dataclass(frozen=True)
class Saved:
    path: str  # relative to the files folder
    content_type: str
    size_bytes: int
    sha256: str


class TooLarge(Invalid):
    pass


def root() -> Path:
    return Path(get_settings().files_dir).resolve()


def sniff(head: bytes, name: str) -> tuple[str, str, bool] | None:
    """What the file really is, from its first bytes. None = a type we do not accept."""
    lower = name.lower()
    if head.startswith(b"%PDF-"):
        return _PDF
    if head.startswith(b"\xff\xd8\xff"):
        return _JPG
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return _PNG
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return _WEBP
    if head[4:8] == b"ftyp" and head[8:12] in (b"heic", b"heix", b"mif1", b"msf1", b"hevc"):
        return _HEIC
    if head.startswith(b"PK\x03\x04"):  # a zip: only Word / Excel by their extension
        if lower.endswith(".docx"):
            return _DOCX
        if lower.endswith(".xlsx"):
            return _XLSX
        return None
    if head.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"):  # old Office
        if lower.endswith(".doc"):
            return _DOC
        if lower.endswith(".xls"):
            return _XLS
    return None


def sniff_audio(head: bytes, name: str) -> tuple[str, str] | None:
    """Call recordings (step C1): what phone recorders and Twilio save. None = not audio."""
    lower = name.lower()
    if head.startswith(b"ID3") or head[:2] in (b"\xff\xfb", b"\xff\xf3", b"\xff\xf2"):
        return ("audio/mpeg", "mp3")
    if head[:2] in (b"\xff\xf1", b"\xff\xf9"):
        return ("audio/aac", "aac")
    if head[4:8] == b"ftyp" and head[8:12] in (b"M4A ", b"mp42", b"isom", b"3gp4", b"3gp5",
                                                b"3gp6", b"mp41", b"M4B "):  # fmt: skip
        return ("audio/mp4", "m4a")
    if head.startswith(b"#!AMR"):
        return ("audio/amr", "amr")
    if head[:4] == b"RIFF" and head[8:12] == b"WAVE":
        return ("audio/wav", "wav")
    if head.startswith(b"OggS"):
        return ("audio/ogg", "ogg")
    if head[:4] == b"\x1aE\xdf\xa3" and lower.endswith((".webm", ".mka")):
        return ("audio/webm", "webm")
    return None


_VIDEO_BRANDS = (b"isom", b"mp42", b"mp41", b"avc1", b"iso2", b"iso4", b"iso5", b"iso6", b"M4V ")
_3GP_BRANDS = (b"3gp4", b"3gp5", b"3gp6", b"3gp7", b"3gp8", b"3gp9")


def check_media(data: bytes, name: str, kind: str | None = None) -> tuple[str, str]:
    """WhatsApp media (finish plan, batch 3): documents and photos as for any upload, plus voice
    notes and audio (as call recordings) and MP4 / 3GP video. `kind` is WhatsApp's own word for
    the message ("video", "audio"…), used only where the bytes alone are ambiguous (an MP4 can
    hold sound or a film)."""
    head = data[:16]
    if kind == "video" and head[4:8] == b"ftyp":
        if head[8:12] in _3GP_BRANDS:
            return "video/3gpp", "3gp"
        if head[8:12] in _VIDEO_BRANDS:
            return "video/mp4", "mp4"
    kind_found = sniff(head, name)
    if kind_found is not None:
        return kind_found[0], kind_found[1]
    audio = sniff_audio(head, name)
    if audio is not None:
        return audio
    if head[4:8] == b"ftyp" and head[8:12] in _VIDEO_BRANDS:
        return "video/mp4", "mp4"
    raise Invalid(
        "This kind of file is not accepted here. Use a photo (JPG, PNG, WEBP), PDF, Word or "
        "Excel file, a voice note or an MP4 video."
    )


def clean_name(name: str) -> str:
    """The original file name, kept for display only (never used on disk)."""
    name = os.path.basename(name.replace("\\", "/")).strip()
    name = "".join(c for c in name if c.isprintable() and c not in '<>:"|?*')
    return (name or "file")[:200]


async def read_upload(request: Request, limit: int = MAX_FILE_BYTES) -> bytes:
    """The request body (the file's bytes), refusing anything over the limit as it arrives."""
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > limit:
        raise TooLarge(f"The file is larger than {limit // (1024 * 1024)} MB")
    chunks, size = [], 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > limit:
            raise TooLarge(f"The file is larger than {limit // (1024 * 1024)} MB")
        chunks.append(chunk)
    data = b"".join(chunks)
    if not data:
        raise Invalid("The file is empty")
    if declared and declared.isdigit() and int(declared) != len(data):
        raise Invalid("The upload did not arrive complete. Please try again.")
    return data


def check_type(data: bytes, name: str, allow_office: bool) -> tuple[str, str]:
    kind = sniff(data[:16], name)
    if kind is None or (kind[2] and not allow_office):
        allowed = "PDF, JPG, PNG, WEBP or HEIC" + (", Word or Excel" if allow_office else "")
        raise Invalid(f"This kind of file is not accepted here. Use {allowed}.")
    return kind[0], kind[1]


def save(tenant_id: uuid.UUID, data: bytes, ext: str, content_type: str) -> Saved:
    now = datetime.now(UTC)
    rel = Path(str(tenant_id), f"{now:%Y}", f"{now:%m}", f"{secrets.token_hex(16)}.{ext}")
    final = root() / rel
    final.parent.mkdir(parents=True, exist_ok=True)
    tmp = final.with_name(f".{final.name}.part")
    with open(tmp, "wb") as fh:
        fh.write(data)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, final)
    return Saved(rel.as_posix(), content_type, len(data), hashlib.sha256(data).hexdigest())


def full_path(rel: str) -> Path:
    base = root()
    p = (base / rel).resolve()
    if base not in p.parents:
        raise Invalid("Bad file path")
    return p


def remove(rel: str) -> None:
    try:
        full_path(rel).unlink()
    except FileNotFoundError:
        pass


def stored_paths(tenant_id: uuid.UUID) -> list[str]:
    """Every file on disk for one company (for the nightly clean-up)."""
    base = root() / str(tenant_id)
    if not base.exists():
        return []
    return [
        p.relative_to(root()).as_posix()
        for p in base.rglob("*")
        if p.is_file() and not p.name.startswith(".")
    ]


def leftover_parts(tenant_id: uuid.UUID, older_than_s: int = 3600) -> list[Path]:
    """Temporary files from uploads that died half-way."""
    base = root() / str(tenant_id)
    if not base.exists():
        return []
    cutoff = datetime.now(UTC).timestamp() - older_than_s
    return [p for p in base.rglob(".*.part") if p.stat().st_mtime < cutoff]
