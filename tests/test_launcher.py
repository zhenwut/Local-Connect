"""Regression checks for the one-click dependency bootstrap."""

import unittest
from unittest.mock import Mock, patch

import run_local_connect


class LauncherTests(unittest.TestCase):
    def test_ready_dependencies_do_not_run_pip(self):
        with patch.object(run_local_connect, 'dependencies_ready', return_value=True), \
             patch.object(run_local_connect.subprocess, 'run') as command:
            run_local_connect.ensure_dependencies()
        command.assert_not_called()

    def test_missing_dependencies_install_into_project_directory(self):
        with patch.object(run_local_connect, 'dependencies_ready', side_effect=[False, True]), \
             patch.object(run_local_connect.subprocess, 'run', return_value=Mock(returncode=0)) as command:
            run_local_connect.ensure_dependencies()
        args = command.call_args.args[0]
        self.assertEqual(args[:4], [run_local_connect.sys.executable, '-m', 'pip', 'install'])
        self.assertEqual(args[args.index('--target') + 1], str(run_local_connect.DEPENDENCIES))
        self.assertEqual(args[args.index('-r') + 1], str(run_local_connect.REQUIREMENTS))

    def test_failed_install_stops_before_starting_server(self):
        with patch.object(run_local_connect, 'dependencies_ready', return_value=False), \
             patch.object(run_local_connect.subprocess, 'run', return_value=Mock(returncode=1)):
            with self.assertRaises(SystemExit):
                run_local_connect.ensure_dependencies()


if __name__ == '__main__':
    unittest.main()
