from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from config import EXTRACTED_TEXT_DIR


def _read_existing_frames(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []

    content = path.read_text(encoding="utf-8")
    frames = []
    for block in re.split(r"\n-{72}\n", content):
        frame_match = re.search(r"^Frame number:\s*(\d+)\s*$", block, re.MULTILINE)
        if not frame_match:
            continue

        notes_marker = re.search(
            r"^(?:Extracted Notes|Extracted text):\s*$",
            block,
            re.MULTILINE,
        )
        if not notes_marker:
            continue

        remaining = block[notes_marker.end():]
        ocr_marker = re.search(r"^OCR Text:\s*$", remaining, re.MULTILINE)
        notes = (remaining[:ocr_marker.start()] if ocr_marker else remaining).strip()
        ocr_text = remaining[ocr_marker.end():].strip() if ocr_marker else notes
        captured_at = re.search(r"^Captured at:\s*(.*?)\s*$", block, re.MULTILINE)
        ocr_status = re.search(r"^OCR status:\s*(.*?)\s*$", block, re.MULTILINE)
        confidence = re.search(
            r"^OCR confidence:\s*([0-9]+(?:\.[0-9]+)?)%",
            block,
            re.MULTILINE,
        )
        frames.append({
            "id": int(frame_match.group(1)),
            "received_at": captured_at.group(1) if captured_at else "unknown",
            "ocr_status": ocr_status.group(1) if ocr_status else "unknown",
            "ocr_confidence": float(confidence.group(1)) if confidence else 0.0,
            "ocr_text": ocr_text,
            "notes": notes,
        })
    return frames


def write_all_frame_texts(frames: list[dict[str, Any]]) -> Path:
    output_path = EXTRACTED_TEXT_DIR / "all_frames.txt"
    merged_frames = {
        frame["id"]: frame
        for frame in _read_existing_frames(output_path)
    }
    merged_frames.update((frame["id"], frame) for frame in frames)
    entries = []
    for frame in sorted(merged_frames.values(), key=lambda item: item["id"]):
        ocr_text = (frame.get("ocr_text") or "").strip()
        notes = (frame.get("notes") or "").strip()
        displayed_notes = notes or ocr_text or "(No OCR text detected)"
        entries.append(
            f"Frame number: {frame['id']}\n"
            f"Captured at: {frame.get('received_at', 'unknown')}\n"
            f"OCR status: {frame.get('ocr_status', 'unknown')}\n"
            f"OCR confidence: {float(frame.get('ocr_confidence', 0.0) or 0.0):.1f}%\n\n"
            "Extracted Notes:\n"
            f"{displayed_notes}\n\n"
            "OCR Text:\n"
            f"{ocr_text or '(No OCR text detected)'}"
        )

    separator = "\n\n" + ("-" * 72) + "\n\n"
    content = separator.join(entries)
    output_path.write_text(
        content + ("\n" if content else ""),
        encoding="utf-8",
    )
    return output_path
