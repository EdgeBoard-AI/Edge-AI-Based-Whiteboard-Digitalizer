from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import server


class ServerShutdownTests(unittest.TestCase):
    def test_cleanup_removes_files_and_clears_database_records(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            directories = [root / name for name in ("received", "processed", "captures", "text")]
            for directory in directories:
                directory.mkdir()
                (directory / "saved.txt").write_text("data", encoding="utf-8")
                nested = directory / "nested"
                nested.mkdir()
                (nested / "saved.txt").write_text("data", encoding="utf-8")

            with (
                patch.object(server, "RECEIVED_DIR", directories[0]),
                patch.object(server, "PROCESSED_DIR", directories[1]),
                patch.object(server, "CAPTURES_DIR", directories[2]),
                patch.object(server, "EXTRACTED_TEXT_DIR", directories[3]),
                patch.object(server.db, "clear_frames") as clear_frames,
            ):
                server.clear_persisted_data()

            self.assertTrue(all(not list(directory.iterdir()) for directory in directories))
            clear_frames.assert_called_once_with()

    def test_server_exit_waits_for_workers_then_cleans_data(self):
        with (
            patch.object(server.app, "run") as app_run,
            patch.object(server.executor, "shutdown") as shutdown,
            patch.object(server, "clear_persisted_data") as clear_persisted_data,
        ):
            server.run_server()

        app_run.assert_called_once_with(
            host=server.HOST,
            port=server.PORT,
            debug=False,
            threaded=True,
        )
        shutdown.assert_called_once_with(wait=True)
        clear_persisted_data.assert_called_once_with()

    def test_keyboard_interrupt_cleans_data_after_workers_finish(self):
        with (
            patch.object(server.app, "run", side_effect=KeyboardInterrupt),
            patch.object(server.executor, "shutdown") as shutdown,
            patch.object(server, "clear_persisted_data") as clear_persisted_data,
        ):
            server.run_server()

        shutdown.assert_called_once_with(wait=True)
        clear_persisted_data.assert_called_once_with()

    def test_server_startup_failure_does_not_clear_saved_data(self):
        with (
            patch.object(server.app, "run", side_effect=OSError("port unavailable")),
            patch.object(server.executor, "shutdown") as shutdown,
            patch.object(server, "clear_persisted_data") as clear_persisted_data,
        ):
            with self.assertRaisesRegex(OSError, "port unavailable"):
                server.run_server()

        shutdown.assert_called_once_with(wait=True)
        clear_persisted_data.assert_not_called()


if __name__ == "__main__":
    unittest.main()
