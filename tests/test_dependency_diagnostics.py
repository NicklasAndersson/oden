import unittest
from unittest.mock import MagicMock, patch

from oden.dependency_diagnostics import (
    _classify_native_load_error,
    run_startup_dependency_diagnostics,
)


class TestDependencyDiagnostics(unittest.TestCase):
    def setUp(self):
        run_startup_dependency_diagnostics.cache_clear()

    def tearDown(self):
        run_startup_dependency_diagnostics.cache_clear()

    def test_classify_native_load_error_missing_vc_runtime(self):
        reason, hint = _classify_native_load_error(Exception("DLL load failed: VCRUNTIME140.dll"))

        self.assertEqual(reason, "missing_vc_runtime")
        self.assertIn("visual", hint)

    @patch("oden.dependency_diagnostics.platform.machine", return_value="x86_64")
    @patch("oden.dependency_diagnostics.platform.system", return_value="Windows")
    @patch("oden.dependency_diagnostics.is_bundled", return_value=True)
    @patch("oden.dependency_diagnostics._diagnose_optional_ui_deps")
    @patch("oden.dependency_diagnostics._diagnose_mgrs")
    @patch("oden.dependency_diagnostics._diagnose_signal_cli")
    @patch("oden.dependency_diagnostics._diagnose_java")
    @patch("oden.dependency_diagnostics.logger")
    def test_run_startup_dependency_diagnostics_invokes_all_checks_once(
        self,
        mock_logger,
        mock_java,
        mock_signal_cli,
        mock_mgrs,
        mock_ui,
        _mock_is_bundled,
        _mock_system,
        _mock_machine,
    ):
        run_startup_dependency_diagnostics()

        mock_logger.info.assert_called_once()
        mock_java.assert_called_once_with()
        mock_signal_cli.assert_called_once_with()
        mock_mgrs.assert_called_once_with()
        mock_ui.assert_called_once_with()

    @patch("oden.dependency_diagnostics._diagnose_optional_ui_deps")
    @patch("oden.dependency_diagnostics._diagnose_mgrs")
    @patch("oden.dependency_diagnostics._diagnose_signal_cli")
    @patch("oden.dependency_diagnostics._diagnose_java")
    @patch("oden.dependency_diagnostics.logger")
    def test_run_startup_dependency_diagnostics_is_cached(
        self,
        _mock_logger,
        mock_java,
        mock_signal_cli,
        mock_mgrs,
        mock_ui,
    ):
        run_startup_dependency_diagnostics()
        run_startup_dependency_diagnostics()

        self.assertEqual(mock_java.call_count, 1)
        self.assertEqual(mock_signal_cli.call_count, 1)
        self.assertEqual(mock_mgrs.call_count, 1)
        self.assertEqual(mock_ui.call_count, 1)

    @patch("oden.dependency_diagnostics.os.access", return_value=False)
    @patch("oden.dependency_diagnostics.find_signal_cli_executable", return_value="/tmp/signal-cli")
    @patch("oden.dependency_diagnostics.Path.exists", return_value=True)
    @patch("oden.dependency_diagnostics.logger")
    def test_diagnose_signal_cli_warns_when_not_executable(
        self,
        mock_logger,
        _mock_exists,
        _mock_find,
        _mock_access,
    ):
        from oden.dependency_diagnostics import _diagnose_signal_cli

        with patch("oden.dependency_diagnostics.sys.platform", "linux"):
            _diagnose_signal_cli()

        warning_calls = [args[0] for args, _ in mock_logger.warning.call_args_list]
        self.assertTrue(any("not executable" in call for call in warning_calls))

    @patch("oden.dependency_diagnostics.importlib.import_module", side_effect=Exception("Unable to load libmgrs"))
    @patch("oden.dependency_diagnostics.logger")
    def test_diagnose_mgrs_logs_classified_warning(self, mock_logger, _mock_import):
        from oden.dependency_diagnostics import _diagnose_mgrs

        _diagnose_mgrs()

        warning_calls = [args[0] for args, _ in mock_logger.warning.call_args_list]
        self.assertTrue(any("mgrs unavailable" in call for call in warning_calls))
