"""Read the connection QR codes TAK servers hand out to ATAK and iTAK.

Two formats are in use:

* The enrollment deep link ATAK (and newer iTAK) scans, e.g. from OpenTAKServer::

      tak://com.atakmap.app/enroll?host=tak.example.org&username=anna&token=eyJ...

  ``token`` is the enrollment password: it is sent as the Basic-auth password to
  ``/Marti/api/tls/signClient`` on port 8446, exactly like a typed password.
  ``host`` may carry a port; only the streaming port (8089) is taken from it,
  anything else (8443, 8446) is an API port and the CoT connection stays on 8089.

* iTAK's server QR, a plain comma-separated line::

      Beskrivning,tak.example.org,8089,SSL

  It names the server only — username and password still have to be entered.

The result maps straight onto Oden's TAK settings (``cot_url``,
``enroll_username``, ``enroll_password``); nothing is stored here.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import parse_qs, unquote, urlparse

STREAMING_PORT = 8089

# iTAK protocol field → pytak scheme. "quic" has no pytak transport; TAK
# servers that offer it also listen on SSL 8089, so fall back to that.
_ITAK_SCHEMES = {"ssl": "tls", "tls": "tls", "tcp": "tcp", "quic": "tls"}


@dataclass(frozen=True)
class TakQr:
    kind: str  # "enroll" (ATAK/iTAK deep link) or "itak" (iTAK server line)
    host: str
    port: int
    scheme: str  # "tls" or "tcp"
    username: str = ""
    token: str = ""
    description: str = ""

    @property
    def cot_url(self) -> str:
        return f"{self.scheme}://{self.host}:{self.port}"

    def summary(self) -> str:
        if self.kind == "enroll":
            return (
                f"Enrollment-QR för {self.host} som {self.username}: Oden hämtar ett klientcert "
                f"från {self.host}:8446 och ansluter till {self.cot_url}."
            )
        name = f"”{self.description}” " if self.description else ""
        return (
            f"iTAK-QR för servern {name}({self.cot_url}). Koden innehåller inga inloggningsuppgifter — "
            "fyll i enrollment-användarnamn och lösenord, eller ladda upp ett data-paket."
        )


def _split_host(host_param: str) -> tuple[str, int]:
    host_param = host_param.strip()
    if host_param.startswith("["):  # [ipv6]:port
        host, _, rest = host_param[1:].partition("]")
        port_str = rest.removeprefix(":")
    elif host_param.count(":") == 1:
        host, port_str = host_param.split(":")
    else:
        host, port_str = host_param, ""
    port = int(port_str) if port_str.isdigit() else STREAMING_PORT
    return host, port


def _parse_enroll(text: str) -> TakQr:
    parsed = urlparse(text)
    if parsed.netloc.lower() != "com.atakmap.app" or parsed.path.rstrip("/").lower() != "/enroll":
        raise ValueError(
            "QR-koden är en tak://-länk men inte en enrollment-länk "
            f"(”{parsed.netloc}{parsed.path}”). Bara tak://com.atakmap.app/enroll stöds."
        )
    qs = parse_qs(parsed.query, keep_blank_values=False)

    def one(name: str) -> str:
        values = qs.get(name) or [""]
        return unquote(values[0]).strip()

    missing = [name for name in ("host", "username", "token") if not one(name)]
    if missing:
        raise ValueError(f"Enrollment-länken saknar {', '.join(missing)}.")

    host, port = _split_host(one("host"))
    if not host:
        raise ValueError("Enrollment-länken saknar värdnamn.")
    # 8443/8446 in the link name the web/enrollment API, not the CoT stream.
    if port != STREAMING_PORT:
        port = STREAMING_PORT
    return TakQr(kind="enroll", host=host, port=port, scheme="tls", username=one("username"), token=one("token"))


def _parse_itak(text: str) -> TakQr:
    parts = [part.strip() for part in text.split(",")]
    if len(parts) != 4:
        raise ValueError(
            "Känner inte igen QR-koden. Stödda format: tak://com.atakmap.app/enroll?host=…&username=…&token=… "
            "(ATAK/iTAK) och ”namn,server,port,protokoll” (iTAK)."
        )
    description, host, port_str, protocol = parts
    if not host or not port_str.isdigit():
        raise ValueError("iTAK-QR:n saknar server eller port.")
    scheme = _ITAK_SCHEMES.get(protocol.lower())
    if scheme is None:
        raise ValueError(f"Okänt protokoll i iTAK-QR:n: ”{protocol}” (förväntade SSL eller TCP).")
    port = int(port_str)
    if protocol.lower() == "quic":
        port = STREAMING_PORT
    return TakQr(kind="itak", host=host, port=port, scheme=scheme, description=description)


def parse_tak_qr(text: str) -> TakQr:
    """Parse the text of a TAK connection QR code. Raises ValueError with a Swedish message."""
    text = (text or "").strip()
    if not text:
        raise ValueError("Ingen QR-text angiven.")
    if text.lower().startswith("tak://"):
        return _parse_enroll(text)
    return _parse_itak(text)
