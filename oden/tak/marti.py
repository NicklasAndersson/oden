"""Marti file store: mission packages -> inbound CoT.

An ATAK 8S sent *with* an attachment never appears on the CoT broadcast stream.
ATAK packs the event and the attachment into a *mission package* zip, uploads that
to the TAK Server's file store, and puts nothing on the channel. Listening to CoT
therefore loses the whole report, not only its image — verified against a live
server, where four attachment-free reports arrived and two with attachments left
no trace at all.

So this module is the second half of the inbound path: ask the file store what is
new, download it, and hand the embedded CoT back to the listener, which runs it
through the same filters, dedup and pipelines as a broadcast event.

Everything here is blocking (urllib, zipfile); the listener calls it through
``asyncio.to_thread`` so the rx queue keeps draining meanwhile.

Untrusted input all the way through: the zip comes off the network, so entry
count, entry size and total size are all capped, and a zipEntry may never escape
the directory it is unpacked into.
"""

from __future__ import annotations

import datetime as _dt
import json
import logging
import os
import ssl
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# A mission package is a report plus a photo or two. Anything far larger is a data
# package someone shared with the whole unit, not something Oden should ingest.
MAX_PACKAGE_BYTES = 32 * 1024 * 1024
# Guard against a zip bomb: a handful of entries is normal (manifest, CoT, media).
MAX_ENTRIES = 64
MAX_UNCOMPRESSED_BYTES = 64 * 1024 * 1024
MAX_ATTACHMENT_BYTES = 16 * 1024 * 1024
# The CoT inside the package is a single event; anything bigger is not one.
MAX_COT_BYTES = 512 * 1024

_MANIFEST_DIR = "manifest/"
_COT_SUFFIX = ".cot"


@dataclass(frozen=True)
class MartiFile:
    """One row from ``/Marti/sync/search``."""

    hash: str
    name: str
    submitted_at: str  # ISO 8601 as the server writes it; only ever compared as text
    creator_uid: str
    submitter: str
    size: int

    @property
    def looks_like_mission_package(self) -> bool:
        """Cheap pre-filter so we do not download every ``transfer.zip`` on the server."""
        return self.name.lower().endswith(".zip")


@dataclass
class MissionPackage:
    """What we pulled out of one package zip."""

    cot: bytes | None = None
    # (filename, bytes) — already size-checked and stripped of any directory part.
    attachments: list[tuple[str, bytes]] = field(default_factory=list)
    skipped_empty: int = 0  # entries declared by the manifest but zero bytes (an ATAK bug)


def _p12_to_pem(p12_path: Path, passphrase: str, dest_dir: Path) -> Path:
    """Our cached ``.p12`` as a PEM, because :mod:`ssl` cannot load PKCS#12 directly.

    Same conversion ``scripts/tak_channels.py`` does. It lives here rather than
    being imported from ``scripts/`` because a script is not a library.
    """
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.serialization import pkcs12

    key, cert, chain = pkcs12.load_key_and_certificates(p12_path.read_bytes(), passphrase.encode() or None)
    if key is None or cert is None:
        raise ValueError(f"{p12_path.name} innehåller inte både nyckel och certifikat")
    blob = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ) + cert.public_bytes(serialization.Encoding.PEM)
    for extra in chain or ():
        blob += extra.public_bytes(serialization.Encoding.PEM)
    pem = dest_dir / "marti-client.pem"
    pem.write_bytes(blob)
    pem.chmod(0o600)
    return pem


def ssl_context(config: object, workdir: Path) -> ssl.SSLContext:
    """A client-authenticated context from the bridge's pytak config.

    Reuses exactly what the CoT connection already established — same cert, same
    CA, same hostname policy — so the file store cannot end up on a different
    trust footing than the stream.
    """
    get = config.get  # type: ignore[attr-defined]
    ca_file = str(get("PYTAK_TLS_CLIENT_CAFILE") or "") or None
    context = ssl.create_default_context(cafile=ca_file)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    # Oden's documented default: a TAK cert rarely matches the address you dial.
    # CA verification stays on; only the name check is relaxed, and only when the
    # CoT connection is already running that way.
    context.check_hostname = not get("PYTAK_TLS_DONT_CHECK_HOSTNAME")
    if get("PYTAK_TLS_DONT_VERIFY"):
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE

    cert_path = str(get("PYTAK_TLS_CLIENT_CERT") or "")
    if not cert_path:
        raise ValueError("TAK: inget klientcert att fråga filarkivet med")
    password = str(get("PYTAK_TLS_CLIENT_PASSWORD") or "")
    path = Path(os.path.expanduser(cert_path))
    if path.suffix.lower() in (".p12", ".pfx"):
        context.load_cert_chain(_p12_to_pem(path, password, workdir))
    else:
        context.load_cert_chain(path, password=password or None)
    return context


def marti_base_url(cot_url: str, port: int) -> str:
    """``https://<host>:<port>`` — the Marti API never rides on the CoT port."""
    host = urlparse(cot_url).hostname
    if not host:
        raise ValueError(f"TAK: kunde inte läsa ut värdnamnet ur {cot_url!r}")
    return f"https://{host}:{int(port)}"


def _get(url: str, context: ssl.SSLContext, timeout: float, *, max_bytes: int) -> bytes:
    """Body of a GET, or raise. Reads at most ``max_bytes`` so a huge file cannot fill memory."""
    opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=context))
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    with opener.open(request, timeout=timeout) as response:
        body = response.read(max_bytes + 1)
    if len(body) > max_bytes:
        raise ValueError(f"svaret är större än {max_bytes} byte")
    return body


def _decode_listing(body: bytes) -> str:
    """Marti's JSON is not reliably UTF-8, so decode it defensively.

    A filename typed on a client with a Windows locale comes back as raw CP1252
    bytes inside an otherwise UTF-8 response — a live server returned
    ``test blågul`` with an ``0xd6`` in it, and strict decoding threw. Losing the
    *entire* listing over one accented character is a far worse trade than a
    mangled name: ``Name`` is only used for logging and the ``.zip`` test, while a
    failed decode means no package is ever ingested.

    Decoding as CP1252 wholesale would be worse still — it would turn every
    correctly-encoded character into mojibake — so only the offending bytes are
    replaced.
    """
    try:
        return body.decode("utf-8")
    except UnicodeDecodeError:
        logger.warning("TAK: filarkivet svarade med tecken som inte är UTF-8 — filnamn kan se konstiga ut")
        return body.decode("utf-8", "replace")


def supports_incremental(base_url: str, context: ssl.SSLContext, *, timeout: float = 15.0) -> bool:
    """True when the server honours ``?startTime=`` on ``/Marti/sync/search``.

    Asked with a timestamp an hour in the *future*, so the three outcomes are
    unambiguous and the probe costs almost nothing:

    * honoured  -> no rows, a few hundred bytes
    * ignored   -> the whole archive comes back, hundreds of kB
    * rejected  -> HTTP 400

    Only an empty 200 counts as support. Guessing wrong in the other direction
    just means full listings, which is the old behaviour.
    """
    ahead = _dt.datetime.now(_dt.timezone.utc) + _dt.timedelta(hours=1)
    try:
        body = _get(_search_url(base_url, _as_marti_time(ahead)), context, timeout, max_bytes=1024 * 1024)
        return not (json.loads(_decode_listing(body)).get("results") or [])
    except (urllib.error.URLError, OSError, ValueError, json.JSONDecodeError):
        return False


def _as_marti_time(when: _dt.datetime) -> str:
    """The ISO-8601 shape the server's own ``SubmissionDateTime`` uses."""
    return when.astimezone(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _search_url(base_url: str, since: str = "") -> str:
    url = f"{base_url}/Marti/sync/search"
    return f"{url}?{urllib.parse.urlencode({'startTime': since})}" if since else url


def shift_back(timestamp: str, seconds: int) -> str:
    """``timestamp`` moved back by ``seconds``, or unchanged if it will not parse."""
    try:
        when = _dt.datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError:
        return timestamp
    return _as_marti_time(when - _dt.timedelta(seconds=seconds))


def search(
    base_url: str,
    context: ssl.SSLContext,
    *,
    timeout: float = 30.0,
    since: str = "",
) -> list[MartiFile]:
    """Everything the file store will show this account. Never raises: a broken
    query means "nothing new this round", not a listener that stops.

    ``since`` narrows the query to packages submitted after that timestamp. The
    full listing is 400 kB of JSON for ~950 rows and grows with the exercise, so
    fetching all of it every minute is what otherwise stops the poll interval
    from being lowered.
    """
    try:
        body = _get(_search_url(base_url, since), context, timeout, max_bytes=16 * 1024 * 1024)
        rows = json.loads(_decode_listing(body)).get("results") or []
    except (urllib.error.URLError, OSError, ValueError, json.JSONDecodeError) as exc:
        logger.warning("TAK: kunde inte läsa filarkivet (%s)", exc)
        return []

    files: list[MartiFile] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        digest = str(row.get("Hash") or "").strip()
        if not digest:
            continue
        try:
            size = int(row.get("Size") or 0)
        except (TypeError, ValueError):
            size = 0
        files.append(
            MartiFile(
                hash=digest,
                name=str(row.get("Name") or ""),
                submitted_at=str(row.get("SubmissionDateTime") or ""),
                creator_uid=str(row.get("CreatorUid") or ""),
                submitter=str(row.get("SubmissionUser") or ""),
                size=size,
            )
        )
    return files


def fetch(base_url: str, digest: str, context: ssl.SSLContext, *, timeout: float = 60.0) -> bytes | None:
    """One file's bytes, or None. Never raises, for the same reason as :func:`search`."""
    url = f"{base_url}/Marti/sync/content?hash={urllib.parse.quote(digest)}"
    try:
        return _get(url, context, timeout, max_bytes=MAX_PACKAGE_BYTES)
    except (urllib.error.URLError, OSError, ValueError) as exc:
        logger.warning("TAK: kunde inte hämta %s ur filarkivet (%s)", digest[:16], exc)
        return None


def _safe_name(entry: str) -> str | None:
    """The bare filename of a zip entry, or None when the entry tries to escape.

    ``zipEntry`` is attacker-controlled text. ``basename`` alone already defeats
    ``../``, but an absolute path or a bare ``..`` deserves to be named and dropped
    rather than silently turned into something else.
    """
    if not entry or entry.endswith("/"):
        return None
    normalized = entry.replace("\\", "/")
    if normalized.startswith("/") or ".." in normalized.split("/"):
        logger.warning("TAK: hoppar över misstänkt sökväg i paketet: %r", entry)
        return None
    name = os.path.basename(normalized)
    return name or None


def unpack(blob: bytes) -> MissionPackage | None:
    """Pull the CoT event and any real attachments out of a mission package.

    Entries are classified by extension rather than by reading the manifest: the
    manifest is one more piece of untrusted text, and every package seen in the
    wild names its event ``<uid>.cot`` regardless. A package with no CoT is not
    one of ours and yields None.
    """
    package = MissionPackage()
    try:
        with zipfile.ZipFile(BytesIO(blob)) as archive:
            infos = archive.infolist()
            if len(infos) > MAX_ENTRIES:
                logger.warning("TAK: paketet har %d poster — hoppar över det", len(infos))
                return None
            if sum(i.file_size for i in infos) > MAX_UNCOMPRESSED_BYTES:
                logger.warning("TAK: paketet packar upp till mer än %d byte", MAX_UNCOMPRESSED_BYTES)
                return None

            for info in infos:
                if info.is_dir() or info.filename.lower().startswith(_MANIFEST_DIR):
                    continue
                name = _safe_name(info.filename)
                if name is None:
                    continue

                if name.lower().endswith(_COT_SUFFIX):
                    if info.file_size > MAX_COT_BYTES:
                        logger.warning("TAK: CoT-posten i paketet är orimligt stor (%d byte)", info.file_size)
                        continue
                    package.cot = archive.read(info)
                    continue

                if info.file_size == 0:
                    # ATAK can upload a manifest that declares a photo and then pack
                    # an empty file. An empty attachment in the vault is worse than none.
                    package.skipped_empty += 1
                    continue
                if info.file_size > MAX_ATTACHMENT_BYTES:
                    logger.warning("TAK: hoppar över bilagan %s (%d byte)", name, info.file_size)
                    continue
                package.attachments.append((name, archive.read(info)))
    except (zipfile.BadZipFile, OSError, RuntimeError) as exc:
        logger.warning("TAK: kunde inte packa upp paketet (%s)", exc)
        return None

    return package if package.cot else None
