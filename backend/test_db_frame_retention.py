from __future__ import annotations

import gc
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import db


class FrameRetentionTests(unittest.TestCase):
    def test_clear_frames_removes_all_database_records(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            db_path = root / "frames.db"

            with patch.object(db, "DB_PATH", db_path):
                db.init_db()
                db.insert_frame("first.jpg", 1, {})
                db.insert_frame("second.jpg", 2, {})

                db.clear_frames()

                frames = db.list_frames()

            gc.collect()
            self.assertEqual(frames, [])

    def test_startup_preserves_ocr_data_when_capture_image_is_missing(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            received_dir = root / "received_frames"
            received_dir.mkdir()
            db_path = root / "frames.db"

            with (
                patch.object(db, "DB_PATH", db_path),
                patch.object(db, "RECEIVED_DIR", received_dir),
            ):
                db.init_db()
                frame_id = db.insert_frame("missing.jpg", 0, {})
                db.update_processing(
                    frame_id,
                    result={
                        "ocr_status": "ok",
                        "ocr_text": "Retained note",
                        "ocr_confidence": 88.0,
                    },
                )

                db.init_db()
                frame = db.get_frame(frame_id)
                frame_texts = db.list_frame_texts()

            gc.collect()
            self.assertIsNotNone(frame)
            self.assertFalse(frame["image_available"])
            self.assertEqual(len(frame_texts), 1)
            self.assertEqual(frame_texts[0]["ocr_text"], "Retained note")


if __name__ == "__main__":
    unittest.main()
