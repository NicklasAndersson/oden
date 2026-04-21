"""Signal account registration with CAPTCHA support."""

import asyncio
import logging

from oden.signal_manager import (
    build_signal_cli_command,
    find_signal_cli_executable,
    get_process_creationflags,
    get_signal_cli_env,
)

logger = logging.getLogger(__name__)


class SignalRegistrar:
    """Handles Signal account registration with CAPTCHA support."""

    def __init__(self) -> None:
        self.executable = find_signal_cli_executable()
        self.env = get_signal_cli_env()
        self.phone_number: str | None = None
        self.use_voice: bool = False
        self.needs_captcha: bool = False
        self.captcha_url: str = "https://signalcaptchas.org/registration/generate.html"
        self.error: str | None = None
        self.status: str = "idle"  # idle, awaiting_captcha, awaiting_code, registered, error

    async def start_register(
        self, phone_number: str, use_voice: bool = False, captcha_token: str | None = None
    ) -> dict:
        """Start the registration process.

        Args:
            phone_number: Phone number in international format (e.g., +46701234567)
            use_voice: If True, request voice call instead of SMS
            captcha_token: Optional CAPTCHA token if required

        Returns:
            dict with keys: success, needs_captcha, error, status
        """
        self.phone_number = phone_number
        self.use_voice = use_voice
        self.error = None

        command_args = ["-u", phone_number, "register"]

        if use_voice:
            command_args.append("--voice")

        if captcha_token:
            command_args.extend(["--captcha", captcha_token])

        command = build_signal_cli_command(self.executable, command_args)

        logger.info("Starting registration (use_voice=%s, has_captcha=%s)", use_voice, bool(captcha_token))

        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=self.env,
                creationflags=get_process_creationflags(),
            )

            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=60.0)

            stdout_text = stdout.decode("utf-8") if stdout else ""
            stderr_text = stderr.decode("utf-8") if stderr else ""

            if process.returncode == 0:
                self.status = "awaiting_code"
                self.needs_captcha = False
                logger.info("Registration started, awaiting verification code")
                return {
                    "success": True,
                    "needs_captcha": False,
                    "status": "awaiting_code",
                    "message": f"Verifieringskod skickad till {phone_number} via {'samtal' if use_voice else 'SMS'}",
                }

            # Check if CAPTCHA is required
            combined_output = (stdout_text + stderr_text).lower()
            if "captcha" in combined_output:
                self.status = "awaiting_captcha"
                self.needs_captcha = True
                logger.info("CAPTCHA required for registration")
                return {
                    "success": False,
                    "needs_captcha": True,
                    "status": "awaiting_captcha",
                    "captcha_url": self.captcha_url,
                    "message": "CAPTCHA krävs. Lös CAPTCHA och klistra in länken.",
                }

            # Other error
            self.status = "error"
            self.error = stderr_text or stdout_text or "Registrering misslyckades"
            logger.error(f"Registration failed: {self.error}")
            return {
                "success": False,
                "needs_captcha": False,
                "status": "error",
                "error": self.error,
            }

        except asyncio.TimeoutError:
            self.status = "error"
            self.error = "Timeout vid registrering"
            logger.error("Registration timeout")
            return {"success": False, "status": "error", "error": self.error}
        except Exception as e:
            self.status = "error"
            self.error = str(e)
            logger.error(f"Registration error: {e}")
            return {"success": False, "status": "error", "error": self.error}

    async def verify(self, code: str) -> dict:
        """Verify the registration with the received code.

        Args:
            code: The verification code received via SMS or voice call

        Returns:
            dict with keys: success, error, phone_number
        """
        if not self.phone_number:
            return {"success": False, "error": "Inget telefonnummer registrerat"}

        # Remove any spaces or dashes from code
        code = code.replace(" ", "").replace("-", "")

        command = build_signal_cli_command(self.executable, ["-u", self.phone_number, "verify", code])

        logger.info("Verifying registration code")

        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=self.env,
                creationflags=get_process_creationflags(),
            )

            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=30.0)

            if process.returncode == 0:
                self.status = "registered"
                logger.info("Registration verified successfully")
                return {
                    "success": True,
                    "status": "registered",
                    "phone_number": self.phone_number,
                    "message": f"Nummer {self.phone_number} registrerat!",
                }

            stderr_text = stderr.decode("utf-8") if stderr else ""
            self.status = "error"
            self.error = stderr_text or "Verifiering misslyckades"
            logger.error(f"Verification failed: {self.error}")
            return {"success": False, "status": "error", "error": self.error}

        except asyncio.TimeoutError:
            self.status = "error"
            self.error = "Timeout vid verifiering"
            return {"success": False, "status": "error", "error": self.error}
        except Exception as e:
            self.status = "error"
            self.error = str(e)
            logger.error(f"Verification error: {e}")
            return {"success": False, "status": "error", "error": self.error}
