from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np

import ai.pipeline as pipeline


class ImagePreprocessingTests(unittest.TestCase):
    def test_enhance_for_ocr_returns_binary_and_grayscale_variants(self):
        image = np.full((120, 320), 235, dtype=np.uint8)
        cv2.putText(image, "BOARD", (10, 80), cv2.FONT_HERSHEY_SIMPLEX, 2, 20, 4)

        adaptive, grayscale = pipeline.enhance_for_ocr(image)

        self.assertEqual(adaptive.shape, grayscale.shape)
        self.assertTrue(set(np.unique(adaptive)).issubset({0, 255}))
        self.assertGreater(np.unique(grayscale).size, 2)

    def test_run_ocr_tries_adaptive_and_grayscale_images(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            adaptive_path = Path(temp_dir) / "adaptive.png"
            grayscale_path = Path(temp_dir) / "grayscale.png"
            image = np.full((120, 320), 255, dtype=np.uint8)
            self.assertTrue(cv2.imwrite(str(adaptive_path), image))
            self.assertTrue(cv2.imwrite(str(grayscale_path), image))

            tried_variants = []

            def fake_ocr_variant(image, label, psm):
                tried_variants.append(label)
                return {
                    "variant": label,
                    "text": "BOARD NOTE",
                    "confidence": 90.0,
                    "word_count": 2,
                    "meaningful_char_count": 9,
                }

            with (
                patch.object(pipeline, "TESSERACT_AVAILABLE", True),
                patch.object(pipeline, "TESSERACT_CMD", sys.executable),
                patch.object(pipeline.pytesseract, "get_tesseract_version", return_value="test"),
                patch.object(pipeline, "_ocr_variant", side_effect=fake_ocr_variant),
            ):
                result = pipeline.run_ocr(adaptive_path, grayscale_path)

        self.assertEqual(result["status"], "ok")
        self.assertTrue(any(label.startswith("adaptive_") for label in tried_variants))
        self.assertTrue(any(label.startswith("grayscale_") for label in tried_variants))


if __name__ == "__main__":
    unittest.main()
