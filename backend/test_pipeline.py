"""Local validation suite for EdgeBoard AI reliability and OCR foundation checks."""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

import db
from ai.pipeline import process_image
from config import RECEIVED_DIR, TESSERACT_AVAILABLE, TESSERACT_CMD, TESSERACT_VERSION
from server import app


def write_valid_jpeg(path: Path, text: str = "CPU") -> None:
    image = Image.new("RGB", (800, 500), color="white")
    draw = ImageDraw.Draw(image)
    try:
        font = ImageFont.truetype("arial.ttf", 72)
    except OSError:
        font = ImageFont.load_default()
    draw.text((80, 180), text, fill="black", font=font)
    image.save(path, format="JPEG")


def write_blank_jpeg(path: Path) -> None:
    Image.new("RGB", (600, 400), color="white").save(path, format="JPEG")


print("=== PHASE 1 + 2 LOCAL VALIDATION ===")

# 1. valid JPEG
valid_path = RECEIVED_DIR / "validation_valid.jpg"
write_valid_jpeg(valid_path, "CPU")
valid_result = process_image(valid_path)
print("1. valid JPEG:", valid_result.get("ocr_status"), valid_result.get("ocr_text"))

# 2. invalid JPEG
invalid_path = RECEIVED_DIR / "validation_invalid.txt"
invalid_path.write_text("not an image", encoding="utf-8")
client = app.test_client()
invalid_response = client.post("/upload", data=invalid_path.read_bytes(), content_type="application/octet-stream")
print("2. invalid JPEG:", invalid_response.status_code, invalid_response.get_json())

# 3. missing image
missing_result = process_image(RECEIVED_DIR / "missing_test.jpg")
print("3. missing image:", missing_result.get("ocr_status"), missing_result.get("ocr_error"))

# 4. Tesseract available
print("4. Tesseract available:", TESSERACT_AVAILABLE, TESSERACT_CMD, TESSERACT_VERSION)

# 5. OCR no-text image
blank_path = RECEIVED_DIR / "validation_blank.jpg"
write_blank_jpeg(blank_path)
blank_result = process_image(blank_path)
print("5. OCR no-text image:", blank_result.get("ocr_status"), blank_result.get("ocr_error"))

# 6. OCR text image
text_path = RECEIVED_DIR / "validation_text.jpg"
write_valid_jpeg(text_path, "V=IR")
text_result = process_image(text_path)
print("6. OCR text image:", text_result.get("ocr_status"), text_result.get("ocr_confidence"), text_result.get("ocr_text"))

# 7. short text
short_path = RECEIVED_DIR / "validation_short.jpg"
write_valid_jpeg(short_path, "A")
short_result = process_image(short_path)
print("7. short text:", short_result.get("ocr_status"), short_result.get("ocr_confidence"), short_result.get("ocr_text"))

# 8. stale DB record and 9. valid DB record
with sqlite3.connect(db.DB_PATH) as conn:
    conn.execute("INSERT OR IGNORE INTO frames (filename, received_at, size_bytes, processing_status, ocr_status) VALUES (?, ?, ?, ?, ?)", ("missing_stale.jpg", "2020-01-01T00:00:00Z", 0, "received", "received"))
    conn.execute("INSERT OR IGNORE INTO frames (filename, received_at, size_bytes, processing_status, ocr_status) VALUES (?, ?, ?, ?, ?)", ("validation_valid.jpg", "2020-01-01T00:00:00Z", 0, "received", "received"))
    conn.commit()

db.purge_missing_frames()
valid_db_row = db.get_frame(next(row[0] for row in sqlite3.connect(db.DB_PATH).execute("SELECT id FROM frames WHERE filename = ?", ("validation_valid.jpg",))))
print("8. stale DB record:", not any(row[0] for row in sqlite3.connect(db.DB_PATH).execute("SELECT id FROM frames WHERE filename = ?", ("missing_stale.jpg",))))
print("9. valid DB record:", bool(valid_db_row), valid_db_row.get("filename") if valid_db_row else None)

# 10. /captures/<filename> and 11. nonexistent /captures/<filename>
valid_capture = client.get("/captures/validation_valid.jpg")
missing_capture = client.get("/captures/definitely_missing.jpg")
print("10. /captures/valid:", valid_capture.status_code)
print("11. /captures/missing:", missing_capture.status_code, missing_capture.get_json())

# cleanup
for path in [valid_path, invalid_path, blank_path, text_path, short_path]:
    if path.exists():
        path.unlink()

for name in ["validation_valid.jpg", "validation_blank.jpg", "validation_text.jpg", "validation_short.jpg"]:
    candidate = RECEIVED_DIR / name
    if candidate.exists():
        candidate.unlink()

with sqlite3.connect(db.DB_PATH) as conn:
    conn.execute("DELETE FROM frames WHERE filename IN (?, ?, ?, ?, 'missing_stale.jpg')", ("validation_valid.jpg", "validation_blank.jpg", "validation_text.jpg", "validation_short.jpg"))
    conn.commit()

print("=== COMPLETE ===")
