"""Signal account linking via QR code."""

import asyncio
import contextlib
import logging
import re

from oden.signal_manager import (
    build_signal_cli_command,
    find_signal_cli_executable,
    get_existing_accounts,
    get_process_creationflags,
    get_signal_cli_env,
)

logger = logging.getLogger(__name__)

_LINK_URI_TIMEOUT_MSG = "Tidsgränsen överskreds i väntan på länk-URI från signal-cli"


class SignalLinker:
    """Handles Signal account linking via QR code."""

    def __init__(self, device_name: str = "Oden"):
        self.device_name = device_name
        self.executable = find_signal_cli_executable()
        self.env = get_signal_cli_env()
        self.process: asyncio.subprocess.Process | None = None
        self.link_uri: str | None = None
        self.linked_number: str | None = None
        self.error: str | None = None
        self.status: str = "idle"  # idle, waiting, linked, error, timeout
        self._accounts_before: set[str] = set()

    @staticmethod
    def _extract_phone_number(*texts: str) -> str | None:
        """Extract the first international phone number found in command output."""
        for text in texts:
            match = re.search(r"\+\d{6,15}", text)
            if match:
                return match.group(0)
        return None

    def _load_existing_account_numbers(self) -> set[str]:
        """Return known Signal account numbers from signal-cli data."""
        try:
            return {account["number"] for account in get_existing_accounts() if account.get("number")}
        except Exception as exc:
            logger.warning("Could not load existing accounts while linking: %s", exc)
            return set()

    def _resolve_linked_number_from_accounts(self) -> str | None:
        """Infer the linked number from accounts.json when signal-cli omits it."""
        accounts_after = self._load_existing_account_numbers()
        new_accounts = accounts_after - self._accounts_before

        if len(new_accounts) == 1:
            number = next(iter(new_accounts))
            logger.info("Recovered linked number from new signal-cli account: %s", number)
            return number

        if len(accounts_after) == 1:
            number = next(iter(accounts_after))
            logger.info("Recovered linked number from sole signal-cli account: %s", number)
            return number

        if accounts_after:
            logger.warning(
                "Link completed but could not determine linked number from accounts: before=%s after=%s",
                sorted(self._accounts_before),
                sorted(accounts_after),
            )
        return None

    async def start_link(self) -> str | None:
        """Start the linking process and return the device link URI.

        Returns:
            The sgnl:// URI for QR code generation, or None if failed.
        """
        self.status = "waiting"
        self.link_uri = None
        self.linked_number = None
        self.error = None
        self._accounts_before = self._load_existing_account_numbers()

        command = build_signal_cli_command(
            self.executable,
            [
                "link",
                "-n",
                self.device_name,
            ],
        )

        logger.info(f"Starting signal-cli link: {' '.join(command)}")

        try:
            self.process = await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=self.env,
                creationflags=get_process_creationflags(),
            )

            # Read lines from stdout looking for the link URI.
            # signal-cli may output warnings or other text before the
            # actual sgnl:// URI, so we scan multiple lines.
            non_uri_lines: list[str] = []
            if self.process.stdout:
                try:
                    loop = asyncio.get_running_loop()
                    deadline = loop.time() + 30.0
                    while True:
                        remaining = deadline - loop.time()
                        if remaining <= 0:
                            raise asyncio.TimeoutError()
                        line = await asyncio.wait_for(
                            self.process.stdout.readline(),
                            timeout=remaining,
                        )
                        if not line:
                            # EOF – process closed stdout without
                            # producing a link URI
                            break
                        text = line.decode("utf-8").strip()
                        if "sgnl://" in text:
                            uri = text[text.index("sgnl://") :]
                            self.link_uri = uri
                            logger.info(f"Got link URI: {uri[:50]}...")
                            return uri
                        if text:
                            non_uri_lines.append(text)
                            logger.debug("signal-cli output (not URI): %s", text)
                except asyncio.TimeoutError:
                    self.status = "error"
                    self.error = _LINK_URI_TIMEOUT_MSG
                    if non_uri_lines:
                        logger.error(
                            "Timeout waiting for link URI. signal-cli output so far: %s",
                            "\n".join(non_uri_lines),
                        )
                    await self.cancel()
                    return None

            # Check stderr line-by-line — some signal-cli versions
            # write the URI there.  Use readline() so we can return as
            # soon as a matching line appears without waiting for EOF
            # (the process keeps running while the user scans the QR).
            stderr_lines: list[str] = []
            if self.process.stderr:
                try:
                    stderr_deadline = asyncio.get_running_loop().time() + 5.0
                    while True:
                        remaining = stderr_deadline - asyncio.get_running_loop().time()
                        if remaining <= 0:
                            break
                        raw = await asyncio.wait_for(
                            self.process.stderr.readline(),
                            timeout=remaining,
                        )
                        if not raw:
                            break
                        line = raw.decode("utf-8").strip()
                        if line:
                            stderr_lines.append(line)
                        if "sgnl://" in line:
                            uri = line[line.index("sgnl://") :]
                            self.link_uri = uri
                            logger.info(f"Got link URI from stderr: {uri[:50]}...")
                            return uri
                except asyncio.TimeoutError:
                    pass

            stderr_text = "\n".join(stderr_lines)

            self.status = "error"
            if non_uri_lines:
                logger.error(
                    "No link URI found in signal-cli output: %s",
                    "\n".join(non_uri_lines),
                )
            if stderr_text:
                logger.error("signal-cli stderr: %s", stderr_text)

            self.error = (
                f"Kunde inte hämta länk-URI från signal-cli: {stderr_text}"
                if stderr_text
                else "Kunde inte hämta länk-URI från signal-cli"
            )
            return None

        except asyncio.TimeoutError:
            self.status = "error"
            self.error = _LINK_URI_TIMEOUT_MSG
            await self.cancel()
            return None
        except Exception as e:
            self.status = "error"
            self.error = str(e)
            logger.error(f"Error starting link: {e}")
            return None

    async def wait_for_link(self, timeout: float = 60.0) -> bool:
        """Wait for the linking to complete.

        Args:
            timeout: Maximum seconds to wait for linking.

        Returns:
            True if successfully linked, False otherwise.
        """
        if not self.process:
            return False

        try:
            # Wait for process to complete (user scans QR code)
            stdout, stderr = await asyncio.wait_for(
                self.process.communicate(),
                timeout=timeout,
            )

            if self.process.returncode == 0:
                output = stdout.decode("utf-8") if stdout else ""
                error_output = stderr.decode("utf-8") if stderr else ""
                self.linked_number = self._extract_phone_number(output, error_output)
                if not self.linked_number:
                    self.linked_number = self._resolve_linked_number_from_accounts()

                self.status = "linked"
                logger.info(f"Successfully linked to number: {self.linked_number}")
                return True
            else:
                error_output = stderr.decode("utf-8") if stderr else "Unknown error"
                self.status = "error"
                if "Invalid ACI" in error_output:
                    self.error = (
                        "Länkning misslyckades: signal-cli-versionen är för gammal. "
                        "Uppdatera till signal-cli 0.14.0 eller nyare för att åtgärda detta."
                    )
                else:
                    self.error = error_output
                logger.error(f"Link failed: {error_output}")
                return False

        except asyncio.TimeoutError:
            self.status = "timeout"
            self.error = "Timeout waiting for QR code scan"
            logger.warning("Link timeout - user did not scan QR code in time")
            await self.cancel()
            return False
        except Exception as e:
            self.status = "error"
            self.error = str(e)
            logger.error(f"Error during linking: {e}")
            return False

    async def cancel(self) -> None:
        """Cancel the linking process."""
        if self.process:
            try:
                self.process.terminate()
                await asyncio.wait_for(self.process.wait(), timeout=5.0)
            except (asyncio.TimeoutError, ProcessLookupError):
                with contextlib.suppress(ProcessLookupError):
                    self.process.kill()
            self.process = None

    def get_manual_instructions(self) -> str:
        """Get manual linking instructions for terminal."""
        return f"""
## Manuell Signal-länkning

Länkningen tog för lång tid. Följ dessa steg i terminalen:

1. Öppna Terminal

2. Kör följande kommando:
   {self.executable} link -n "{self.device_name}"

3. En QR-kod visas. Scanna den med Signal-appen:
   - Öppna Signal på din telefon
   - Gå till Inställningar → Länkade enheter
   - Tryck på "+" eller "Länka ny enhet"
   - Scanna QR-koden

4. När länkningen är klar, skriv in ditt telefonnummer i fältet ovan
   och klicka "Spara konfiguration".
"""
