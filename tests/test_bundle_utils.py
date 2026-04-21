"""Tests for bundle_utils module."""

import tempfile
from pathlib import Path
from unittest.mock import patch

from oden.bundle_utils import get_bundled_java_path


class TestGetBundledJavaPath:
    """Tests for get_bundled_java_path function."""

    def test_returns_none_when_not_bundled(self):
        """Returns None when not running as a PyInstaller bundle."""
        with patch("oden.bundle_utils.is_bundled", return_value=False):
            result = get_bundled_java_path()
        assert result is None

    def test_macos_uses_contents_home_structure(self):
        """On macOS, the JRE uses Contents/Home/bin/java (macOS app bundle convention)."""
        with tempfile.TemporaryDirectory() as tmp:
            bundle_path = Path(tmp)
            # Create the macOS JRE directory structure
            java_bin = bundle_path / "jre-x64" / "Contents" / "Home" / "bin" / "java"
            java_bin.parent.mkdir(parents=True)
            java_bin.touch()

            with (
                patch("oden.bundle_utils.is_bundled", return_value=True),
                patch("oden.bundle_utils.get_bundle_path", return_value=bundle_path),
                patch("oden.bundle_utils.platform.system", return_value="Darwin"),
                patch("oden.bundle_utils.platform.machine", return_value="x86_64"),
            ):
                result = get_bundled_java_path()

        assert result == str(java_bin)

    def test_macos_apple_silicon_uses_x64_jre(self):
        """On macOS Apple Silicon, x64 JRE is used (via Rosetta)."""
        with tempfile.TemporaryDirectory() as tmp:
            bundle_path = Path(tmp)
            java_bin = bundle_path / "jre-x64" / "Contents" / "Home" / "bin" / "java"
            java_bin.parent.mkdir(parents=True)
            java_bin.touch()

            with (
                patch("oden.bundle_utils.is_bundled", return_value=True),
                patch("oden.bundle_utils.get_bundle_path", return_value=bundle_path),
                patch("oden.bundle_utils.platform.system", return_value="Darwin"),
                patch("oden.bundle_utils.platform.machine", return_value="arm64"),
            ):
                result = get_bundled_java_path()

        assert result == str(java_bin)

    def test_linux_x64_uses_bin_java(self):
        """On Linux x86_64, the JRE uses bin/java directly."""
        with tempfile.TemporaryDirectory() as tmp:
            bundle_path = Path(tmp)
            java_bin = bundle_path / "jre-x64" / "bin" / "java"
            java_bin.parent.mkdir(parents=True)
            java_bin.touch()

            with (
                patch("oden.bundle_utils.is_bundled", return_value=True),
                patch("oden.bundle_utils.get_bundle_path", return_value=bundle_path),
                patch("oden.bundle_utils.platform.system", return_value="Linux"),
                patch("oden.bundle_utils.platform.machine", return_value="x86_64"),
            ):
                result = get_bundled_java_path()

        assert result == str(java_bin)

    def test_linux_arm64_uses_jre_arm64(self):
        """On Linux arm64, the arm64 JRE is used."""
        with tempfile.TemporaryDirectory() as tmp:
            bundle_path = Path(tmp)
            java_bin = bundle_path / "jre-arm64" / "bin" / "java"
            java_bin.parent.mkdir(parents=True)
            java_bin.touch()

            with (
                patch("oden.bundle_utils.is_bundled", return_value=True),
                patch("oden.bundle_utils.get_bundle_path", return_value=bundle_path),
                patch("oden.bundle_utils.platform.system", return_value="Linux"),
                patch("oden.bundle_utils.platform.machine", return_value="arm64"),
            ):
                result = get_bundled_java_path()

        assert result == str(java_bin)

    def test_windows_uses_java_exe(self):
        """On Windows, the bundled JRE uses bin/java.exe."""
        with tempfile.TemporaryDirectory() as tmp:
            bundle_path = Path(tmp)
            java_bin = bundle_path / "jre-x64" / "bin" / "java.exe"
            java_bin.parent.mkdir(parents=True)
            java_bin.touch()

            with (
                patch("oden.bundle_utils.is_bundled", return_value=True),
                patch("oden.bundle_utils.get_bundle_path", return_value=bundle_path),
                patch("oden.bundle_utils.platform.system", return_value="Windows"),
                patch("oden.bundle_utils.platform.machine", return_value="AMD64"),
            ):
                result = get_bundled_java_path()

        assert result == str(java_bin)

    def test_returns_none_when_java_missing_on_macos(self):
        """Returns None and logs warning when macOS JRE is not present in bundle."""
        with tempfile.TemporaryDirectory() as tmp:
            bundle_path = Path(tmp)
            # Do NOT create any java binary

            with (
                patch("oden.bundle_utils.is_bundled", return_value=True),
                patch("oden.bundle_utils.get_bundle_path", return_value=bundle_path),
                patch("oden.bundle_utils.platform.system", return_value="Darwin"),
                patch("oden.bundle_utils.platform.machine", return_value="x86_64"),
            ):
                result = get_bundled_java_path()

        assert result is None

    def test_returns_none_for_unknown_architecture(self):
        """Returns None for unsupported architectures on non-Darwin systems."""
        with tempfile.TemporaryDirectory() as tmp:
            bundle_path = Path(tmp)

            with (
                patch("oden.bundle_utils.is_bundled", return_value=True),
                patch("oden.bundle_utils.get_bundle_path", return_value=bundle_path),
                patch("oden.bundle_utils.platform.system", return_value="Linux"),
                patch("oden.bundle_utils.platform.machine", return_value="riscv64"),
            ):
                result = get_bundled_java_path()

        assert result is None

    def test_macos_does_not_use_flat_bin_java(self):
        """On macOS, the flat bin/java layout (Linux style) is NOT used."""
        with tempfile.TemporaryDirectory() as tmp:
            bundle_path = Path(tmp)
            # Only create the Linux-style flat path (should NOT match on macOS)
            flat_java = bundle_path / "jre-x64" / "bin" / "java"
            flat_java.parent.mkdir(parents=True)
            flat_java.touch()

            with (
                patch("oden.bundle_utils.is_bundled", return_value=True),
                patch("oden.bundle_utils.get_bundle_path", return_value=bundle_path),
                patch("oden.bundle_utils.platform.system", return_value="Darwin"),
                patch("oden.bundle_utils.platform.machine", return_value="x86_64"),
            ):
                result = get_bundled_java_path()

        # Should return None because macOS expects Contents/Home/bin/java
        assert result is None
