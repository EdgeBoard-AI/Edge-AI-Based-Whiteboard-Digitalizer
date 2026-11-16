from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import text_export


class FrameTextExportTests(unittest.TestCase):
    def test_writes_all_frames_in_order_to_one_utf8_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.object(text_export, "EXTRACTED_TEXT_DIR", Path(temp_dir)):
                output_path = text_export.write_all_frame_texts([
                    {
                        "id": 42,
                        "received_at": "2026-11-15T12:30:00+00:00",
                        "ocr_status": "ok",
                        "ocr_confidence": 87.5,
                        "ocr_text": "Café board notes",
                        "notes": "• Café board notes",
                    },
                    {
                        "id": 7,
                        "received_at": "2026-11-15T12:00:00+00:00",
                        "ocr_status": "ok",
                        "ocr_confidence": 91.0,
                        "ocr_text": "Earlier frame",
                    },
                ])

            self.assertEqual(output_path.name, "all_frames.txt")
            content = output_path.read_text(encoding="utf-8")
            self.assertLess(content.index("Frame number: 7"), content.index("Frame number: 42"))
            self.assertIn("Captured at: 2026-11-15T12:30:00+00:00", content)
            self.assertIn("OCR confidence: 87.5%", content)
            self.assertIn("Café board notes", content)
            self.assertIn("Extracted Notes:\n• Café board notes", content)

    def test_rebuilding_file_replaces_old_frame_text(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.object(text_export, "EXTRACTED_TEXT_DIR", Path(temp_dir)):
                output_path = text_export.write_all_frame_texts([
                    {"id": 7, "received_at": "time", "ocr_text": "First result"},
                ])
                text_export.write_all_frame_texts([
                    {"id": 7, "received_at": "time", "ocr_text": "Updated result"},
                ])

            self.assertEqual(len(list(Path(temp_dir).glob("*.txt"))), 1)
            content = output_path.read_text(encoding="utf-8")
            self.assertIn("Updated result", content)
            self.assertNotIn("First result", content)

    def test_empty_database_input_does_not_erase_existing_export(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.object(text_export, "EXTRACTED_TEXT_DIR", Path(temp_dir)):
                output_path = text_export.write_all_frame_texts([
                    {
                        "id": 18,
                        "received_at": "2026-11-15T12:00:00+00:00",
                        "ocr_status": "ok",
                        "ocr_text": "Keep this note",
                        "notes": "Keep this note",
                    },
                ])
                text_export.write_all_frame_texts([])

            content = output_path.read_text(encoding="utf-8")
            self.assertIn("Frame number: 18", content)
            self.assertIn("Keep this note", content)


if __name__ == "__main__":
    unittest.main()
