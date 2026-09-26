import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from config import DB_PATH, RECEIVED_DIR


def _ensure_columns():
    with sqlite3.connect(DB_PATH) as conn:
        columns = [row[1] for row in conn.execute("PRAGMA table_info(frames)").fetchall()]
        for column_name, column_sql in (
            ("ocr_confidence", "REAL DEFAULT 0"),
            ("ocr_engine", "TEXT DEFAULT 'tesseract'"),
            ("ocr_status", "TEXT DEFAULT 'pending'"),
            ("processed_image_path", "TEXT DEFAULT ''"),
            ("last_error", "TEXT DEFAULT ''"),
            ("sharpness", "REAL DEFAULT 0"),
            ("stability_score", "REAL DEFAULT 0"),
        ):
            if column_name not in columns:
                conn.execute(f"ALTER TABLE frames ADD COLUMN {column_name} {column_sql}")
        conn.commit()


def purge_missing_frames():
    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute("SELECT id, filename FROM frames").fetchall()
        for frame_id, filename in rows:
            path = (RECEIVED_DIR / Path(filename).name)
            if not path.exists():
                conn.execute("DELETE FROM frames WHERE id = ?", (frame_id,))
        conn.commit()


def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
        CREATE TABLE IF NOT EXISTS frames (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filename TEXT NOT NULL UNIQUE,
            received_at TEXT NOT NULL,
            size_bytes INTEGER NOT NULL,
            device TEXT,
            change_score REAL,
            board_visibility REAL,
            brightness REAL,
            sharpness REAL DEFAULT 0,
            stability_score REAL DEFAULT 0,
            timestamp_device TEXT,
            processing_status TEXT NOT NULL DEFAULT 'received',
            ocr_text TEXT DEFAULT '',
            summary TEXT DEFAULT '',
            notes TEXT DEFAULT '',
            structured_json TEXT DEFAULT '{}',
            processing_error TEXT DEFAULT '',
            ocr_confidence REAL DEFAULT 0,
            ocr_engine TEXT DEFAULT 'tesseract',
            ocr_status TEXT DEFAULT 'received',
            processed_image_path TEXT DEFAULT '',
            last_error TEXT DEFAULT ''
        )
        """)
        conn.commit()
    _ensure_columns()
    purge_missing_frames()


def _row(row):
    if row is None:
        return None
    keys = [
        "id", "filename", "received_at", "size_bytes", "device", "change_score",
        "board_visibility", "brightness", "sharpness", "stability_score", "timestamp_device",
        "processing_status", "ocr_text", "summary", "notes", "structured_json",
        "processing_error", "ocr_confidence", "ocr_engine", "ocr_status",
        "processed_image_path", "last_error"
    ]
    item = dict(zip(keys, row))
    item["image_available"] = bool(item.get("filename") and (RECEIVED_DIR / Path(item["filename"]).name).exists())
    try:
        item["structured"] = json.loads(item.pop("structured_json") or "{}")
    except json.JSONDecodeError:
        item["structured"] = {}
        item.pop("structured_json", None)
    return item


def insert_frame(filename, size_bytes, headers):
    clean_name = Path(filename or "").name.replace("..", "_")
    now = datetime.now(timezone.utc).isoformat()
    def number(name):
        try:
            return float(headers.get(name))
        except (TypeError, ValueError):
            return None
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.execute("""
            INSERT INTO frames
            (filename, received_at, size_bytes, device, change_score,
             board_visibility, brightness, sharpness, stability_score, timestamp_device)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            clean_name, now, size_bytes, headers.get("X-Device"),
            number("X-Change-Score"), number("X-Board-Visibility"),
            number("X-Brightness"), number("X-Sharpness"),
            number("X-Stability-Score"), headers.get("X-Timestamp")
        ))
        conn.commit()
        return cur.lastrowid


def list_frames(limit=50):
    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute("""
            SELECT id, filename, received_at, size_bytes, device, change_score,
                   board_visibility, brightness, sharpness, stability_score, timestamp_device,
                   processing_status, ocr_text, summary, notes, structured_json,
                   processing_error, ocr_confidence, ocr_engine, ocr_status,
                   processed_image_path, last_error
            FROM frames ORDER BY id DESC LIMIT ?
        """, (limit,)).fetchall()
    frames = [_row(row) for row in rows]
    return [frame for frame in frames if frame and (RECEIVED_DIR / Path(frame["filename"]).name).exists()]


def get_frame(frame_id):
    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute("""
            SELECT id, filename, received_at, size_bytes, device, change_score,
                   board_visibility, brightness, sharpness, stability_score, timestamp_device,
                   processing_status, ocr_text, summary, notes, structured_json,
                   processing_error, ocr_confidence, ocr_engine, ocr_status,
                   processed_image_path, last_error
            FROM frames WHERE id = ?
        """, (frame_id,)).fetchone()
    frame = _row(row)
    if frame and not (RECEIVED_DIR / Path(frame["filename"]).name).exists():
        return None
    return frame


def set_processing(frame_id, status="processing"):
    status = status or "processing"
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "UPDATE frames SET processing_status=?, ocr_status=?, processing_error='', last_error='' WHERE id=?",
            (status, status, frame_id),
        )
        conn.commit()


def update_processing(frame_id, result=None, error=""):
    if error:
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute(
                "UPDATE frames SET processing_status='failed', ocr_status='failed', processing_error=?, last_error=? WHERE id=?",
                (error, error, frame_id),
            )
            conn.commit()
        return

    if result is None:
        return

    status = result.get("ocr_status", "complete")
    if status == "ok":
        processing_status = "complete"
    elif status in {"low_confidence", "no_text", "missing_tesseract", "failed", "error"}:
        processing_status = status
    else:
        processing_status = "failed"
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            UPDATE frames SET processing_status=?, ocr_text=?, summary=?, notes=?, structured_json=?,
                              processing_error=?, ocr_confidence=?, ocr_engine='tesseract',
                              ocr_status=?, processed_image_path=?, last_error=?
            WHERE id=?
            """,
            (
                processing_status,
                result.get("ocr_text", ""),
                result.get("summary", ""),
                result.get("notes", ""),
                json.dumps(result.get("structured", {}), ensure_ascii=False),
                result.get("ocr_error", ""),
                float(result.get("ocr_confidence", 0.0) or 0.0),
                status,
                result.get("binary_image", ""),
                result.get("ocr_error", ""),
                frame_id,
            ),
        )
        conn.commit()
