from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import ai.class_notes as class_notes
import pdf_export
import server


EXPORT_TEXT = """Frame number: 2
Captured at: 2026-11-15T12:00:00+00:00
OCR status: ok
OCR confidence: 90.0%

Extracted Notes:
• First topic

OCR Text:
First topic

------------------------------------------------------------------------

Frame number: 10
Captured at: 2026-11-15T12:01:00+00:00
OCR status: ok
OCR confidence: 92.0%

Extracted Notes:
• Second topic

OCR Text:
Second topic
"""


class ClassNotesTests(unittest.TestCase):
    def test_dashboard_exposes_class_over_button(self):
        response = server.app.test_client().get("/")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Class Over", response.data)
        self.assertIn(b"generateClassNotes()", response.data)

    def test_parses_frame_notes_in_frame_number_order(self):
        frames = class_notes.parse_frame_notes(EXPORT_TEXT)

        self.assertEqual([frame.frame_number for frame in frames], [2, 10])
        self.assertEqual(frames[0].notes, "• First topic")
        self.assertEqual(frames[1].captured_at, "2026-11-15T12:01:00+00:00")

    def test_generation_uses_configured_model_and_augmented_prompt(self):
        response = Mock()
        response.json.return_value = {"response": "# Class Notes\n\n## Summary"}

        with patch.object(class_notes.requests, "post", return_value=response) as post:
            result = class_notes.generate_class_notes(
                class_notes.parse_frame_notes(EXPORT_TEXT),
                "http://localhost:11434",
                "llama3.2:3b",
            )

        self.assertIn("# Class Notes", result)
        request = post.call_args.kwargs
        self.assertEqual(request["json"]["model"], "llama3.2:3b")
        prompt = request["json"]["prompt"]
        self.assertIn("Do not invent facts", prompt)
        self.assertLess(prompt.index("[Frame 2"), prompt.index("[Frame 10"))

    def test_pdf_writer_creates_downloadable_pdf(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.object(pdf_export, "CLASS_NOTES_DIR", Path(temp_dir)):
                output_path = pdf_export.save_class_notes_pdf(
                    "# Class Notes\n\n## Summary\n\n- First point\n- Second point"
                )

            self.assertTrue(output_path.is_file())
            self.assertTrue(output_path.name.endswith(".pdf"))
            self.assertTrue(output_path.read_bytes().startswith(b"%PDF-"))

    def test_class_notes_endpoint_returns_a_downloadable_pdf(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            export_path = temp_path / "all_frames.txt"
            export_path.write_text(EXPORT_TEXT, encoding="utf-8")
            pdf_dir = temp_path / "pdfs"
            client = server.app.test_client()

            with (
                patch.object(server, "refresh_text_export", return_value=export_path),
                patch.object(server, "generate_class_notes", return_value="# Class Notes\n\n## Summary"),
                patch.object(pdf_export, "CLASS_NOTES_DIR", pdf_dir),
                patch.object(server, "CLASS_NOTES_DIR", pdf_dir),
            ):
                response = client.post("/api/class-notes")
                result = response.get_json()
                download = client.get(result["pdf_url"])

            self.assertEqual(response.status_code, 200)
            self.assertEqual(result["frame_count"], 2)
            self.assertEqual(download.status_code, 200)
            self.assertTrue(download.data.startswith(b"%PDF-"))
            download.close()


if __name__ == "__main__":
    unittest.main()
