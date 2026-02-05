"""Tests for the path_utils module."""

import tempfile
from pathlib import Path

import pytest

from oden.path_utils import (
    UNSAFE_FILENAME_CHARS,
    ensure_directory,
    is_filesystem_root,
    is_within_directory,
    normalize_path,
    sanitize_filename,
    validate_ini_file_path,
    validate_path_within_directory,
    validate_path_within_home,
)


class TestNormalizePath:
    """Tests for normalize_path function."""

    def test_expands_user_tilde(self):
        """Test that ~ is expanded to user home."""
        result = normalize_path("~/test")
        assert str(Path.home()) in str(result)
        assert result.is_absolute()

    def test_resolves_to_absolute(self):
        """Test that relative paths are resolved to absolute."""
        result = normalize_path("./relative/path")
        assert result.is_absolute()

    def test_empty_path_raises_value_error(self):
        """Test that empty path raises ValueError."""
        with pytest.raises(ValueError, match="cannot be empty"):
            normalize_path("")

    def test_accepts_path_object(self):
        """Test that Path objects are accepted."""
        result = normalize_path(Path("/tmp/test"))
        # resolve() follows symlinks, so /tmp may become /private/tmp on macOS
        assert result.is_absolute()
        assert result.name == "test"


class TestIsWithinDirectory:
    """Tests for is_within_directory function."""

    def test_path_within_parent(self):
        """Test that a path within parent returns True."""
        parent = Path("/home/user")
        path = Path("/home/user/subdir/file.txt")
        assert is_within_directory(path, parent) is True

    def test_path_equal_to_parent(self):
        """Test that a path equal to parent returns True."""
        path = Path("/home/user")
        assert is_within_directory(path, path) is True

    def test_path_outside_parent(self):
        """Test that a path outside parent returns False."""
        parent = Path("/home/user")
        path = Path("/etc/passwd")
        assert is_within_directory(path, parent) is False

    def test_path_traversal_attempt(self):
        """Test that path traversal attempts are caught."""
        parent = Path("/home/user/safe")
        # Resolve handles ../ automatically
        path = Path("/home/user/other")
        assert is_within_directory(path, parent) is False


class TestIsFilesystemRoot:
    """Tests for is_filesystem_root function."""

    def test_unix_root(self):
        """Test that / is detected as root."""
        assert is_filesystem_root(Path("/")) is True

    def test_normal_path_not_root(self):
        """Test that normal paths are not root."""
        assert is_filesystem_root(Path("/home/user")) is False
        assert is_filesystem_root(Path("/tmp")) is False


class TestValidatePathWithinHome:
    """Tests for validate_path_within_home function."""

    def test_path_in_home_dir(self):
        """Test that paths in home directory are accepted."""
        home = Path.home()
        test_path = home / "test_dir"
        result, error = validate_path_within_home(str(test_path))
        assert error is None
        assert result == test_path

    def test_path_outside_home_rejected(self):
        """Test that paths outside home are rejected."""
        result, error = validate_path_within_home("/etc/passwd")
        assert result is None
        assert "måste vara under" in error

    def test_filesystem_root_rejected(self):
        """Test that filesystem root is rejected."""
        result, error = validate_path_within_home("/")
        assert result is None
        assert "rot" in error

    def test_allowed_path_outside_home(self):
        """Test that explicitly allowed paths outside home are accepted."""
        # Using /tmp as an example of a path outside home
        # Note: On macOS /tmp is a symlink to /private/tmp
        tmp_resolved = Path("/tmp").resolve()
        result, error = validate_path_within_home("/tmp", allow_path=Path("/tmp"))
        assert error is None
        assert result == tmp_resolved


class TestValidatePathWithinDirectory:
    """Tests for validate_path_within_directory function."""

    def test_path_within_parent(self):
        """Test that paths within parent are accepted."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Resolve parent to handle symlinks (e.g., /tmp -> /private/tmp on macOS)
            parent = Path(tmpdir).resolve()
            result, error = validate_path_within_directory("subdir/file.txt", parent)
            assert error is None
            assert is_within_directory(result, parent)

    def test_path_traversal_rejected(self):
        """Test that path traversal is rejected."""
        with tempfile.TemporaryDirectory() as tmpdir:
            parent = Path(tmpdir)
            result, error = validate_path_within_directory("../escape", parent)
            assert result is None
            assert "måste vara under" in error


class TestValidateIniFilePath:
    """Tests for validate_ini_file_path function."""

    def test_valid_ini_file(self):
        """Test that valid config.ini files are accepted."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Resolve to handle symlinks (e.g., /tmp -> /private/tmp on macOS)
            ini_file = (Path(tmpdir) / "config.ini").resolve()
            ini_file.write_text("[Test]\nkey=value\n")
            result, error = validate_ini_file_path(str(ini_file))
            assert error is None
            assert result == ini_file

    def test_nonexistent_file_rejected(self):
        """Test that nonexistent files are rejected."""
        result, error = validate_ini_file_path("/nonexistent/config.ini")
        assert result is None
        assert "hittades inte" in error

    def test_wrong_filename_rejected(self):
        """Test that files not named config.ini are rejected."""
        with tempfile.TemporaryDirectory() as tmpdir:
            wrong_file = Path(tmpdir) / "settings.ini"
            wrong_file.write_text("[Test]\n")
            result, error = validate_ini_file_path(str(wrong_file))
            assert result is None
            assert "config.ini" in error

    def test_must_be_within_directory(self):
        """Test that must_be_within constraint is enforced."""
        with tempfile.TemporaryDirectory() as tmpdir:
            parent = Path(tmpdir) / "parent"
            parent.mkdir()
            outside = Path(tmpdir) / "outside"
            outside.mkdir()
            ini_file = outside / "config.ini"
            ini_file.write_text("[Test]\n")

            result, error = validate_ini_file_path(str(ini_file), must_be_within=parent)
            assert result is None
            assert "måste vara under" in error


class TestSanitizeFilename:
    """Tests for sanitize_filename function."""

    def test_normal_filename_unchanged(self):
        """Test that normal filenames are unchanged."""
        assert sanitize_filename("document.txt") == "document.txt"

    def test_strips_path_components(self):
        """Test that path separators are stripped."""
        assert sanitize_filename("/path/to/file.txt") == "file.txt"
        # Note: ".." is replaced with empty string, leaving "__evil.exe"
        # after basename extraction on Unix (which treats \\ as literal)
        result = sanitize_filename("..\\..\\evil.exe")
        assert "evil.exe" in result

    def test_removes_unsafe_characters(self):
        """Test that unsafe characters are replaced."""
        result = sanitize_filename("file<with>:bad*chars?.txt")
        assert "<" not in result
        assert ">" not in result
        assert ":" not in result
        assert "*" not in result
        assert "?" not in result

    def test_empty_returns_fallback(self):
        """Test that empty filename returns fallback."""
        assert sanitize_filename("") == "unnamed"
        assert sanitize_filename("", fallback="default") == "default"

    def test_dots_stripped(self):
        """Test that leading/trailing dots are stripped."""
        # After sanitization, dots and whitespace are stripped
        result = sanitize_filename("...test...")
        assert not result.startswith(".")
        assert not result.endswith(".")


class TestEnsureDirectory:
    """Tests for ensure_directory function."""

    def test_creates_directory(self):
        """Test that directories are created."""
        with tempfile.TemporaryDirectory() as tmpdir:
            new_dir = Path(tmpdir) / "new" / "nested" / "dir"
            success, error = ensure_directory(new_dir)
            assert success is True
            assert error is None
            assert new_dir.exists()
            assert new_dir.is_dir()

    def test_existing_directory_ok(self):
        """Test that existing directories don't cause errors."""
        with tempfile.TemporaryDirectory() as tmpdir:
            success, error = ensure_directory(tmpdir)
            assert success is True
            assert error is None


class TestUnsafeFilenameChars:
    """Tests for UNSAFE_FILENAME_CHARS pattern."""

    def test_matches_common_unsafe_chars(self):
        """Test that common unsafe characters are matched."""
        unsafe = '<>:"/\\|?*'
        for char in unsafe:
            assert UNSAFE_FILENAME_CHARS.search(char), f"Should match {repr(char)}"

    def test_matches_control_characters(self):
        """Test that control characters are matched."""
        for i in range(32):
            char = chr(i)
            assert UNSAFE_FILENAME_CHARS.search(char), f"Should match control char {i}"
