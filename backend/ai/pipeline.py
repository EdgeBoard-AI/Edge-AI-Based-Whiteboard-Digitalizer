"""Local-first image processing and OCR pipeline for EdgeBoard AI."""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import pytesseract
import requests

from config import (
    ENABLE_OLLAMA,
    OLLAMA_MODEL,
    OLLAMA_URL,
    OCR_LANG,
    PROCESSED_DIR,
    ROI_H,
    ROI_W,
    ROI_X,
    ROI_Y,
    TESSERACT_AVAILABLE,
    TESSERACT_CMD,
)

if TESSERACT_AVAILABLE and TESSERACT_CMD:
    pytesseract.pytesseract.tesseract_cmd = TESSERACT_CMD


def _order_points(points: np.ndarray) -> np.ndarray:
    rect = np.zeros((4, 2), dtype="float32")
    s = points.sum(axis=1)
    d = np.diff(points, axis=1).reshape(-1)
    rect[0] = points[np.argmin(s)]
    rect[2] = points[np.argmax(s)]
    rect[1] = points[np.argmin(d)]
    rect[3] = points[np.argmax(d)]
    return rect


def _four_point_warp(image: np.ndarray, pts: np.ndarray) -> np.ndarray:
    rect = _order_points(pts.astype("float32"))
    tl, tr, br, bl = rect
    width_a = np.linalg.norm(br - bl)
    width_b = np.linalg.norm(tr - tl)
    height_a = np.linalg.norm(tr - br)
    height_b = np.linalg.norm(tl - bl)
    width = max(1, int(max(width_a, width_b)))
    height = max(1, int(max(height_a, height_b)))
    width = min(width, 1600)
    height = min(height, 1200)
    dst = np.array([[0, 0], [width - 1, 0], [width - 1, height - 1], [0, height - 1]], dtype="float32")
    matrix = cv2.getPerspectiveTransform(rect, dst)
    return cv2.warpPerspective(image, matrix, (width, height))


def crop_configured_roi(image: np.ndarray) -> np.ndarray:
    h, w = image.shape[:2]
    x1 = max(0, min(w - 1, int(w * ROI_X)))
    y1 = max(0, min(h - 1, int(h * ROI_Y)))
    x2 = max(x1 + 1, min(w, int(w * (ROI_X + ROI_W))))
    y2 = max(y1 + 1, min(h, int(h * (ROI_Y + ROI_H))))
    return image[y1:y2, x1:x2].copy()


def detect_board_quad(image: np.ndarray) -> np.ndarray | None:
    """Find a strong quadrilateral candidate; return None when uncertain."""
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    blur = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(blur, 40, 140)
    contours, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    image_area = gray.shape[0] * gray.shape[1]
    candidates = []
    for contour in contours:
        area = cv2.contourArea(contour)
        if area < image_area * 0.20 or area > image_area * 0.98:
            continue
        perimeter = cv2.arcLength(contour, True)
        approx = cv2.approxPolyDP(contour, 0.025 * perimeter, True)
        if len(approx) == 4 and cv2.isContourConvex(approx):
            candidates.append((area, approx.reshape(4, 2)))
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0], reverse=True)
    return candidates[0][1]


def enhance_for_ocr(image: np.ndarray) -> np.ndarray:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if len(image.shape) == 3 else image
    # Upscale 2x for sharp character recognition
    gray_2x = cv2.resize(gray, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC)

    # Mild Gaussian blur suppresses sensor noise and paper lines
    blurred = cv2.GaussianBlur(gray_2x, (3, 3), 0)

    # Otsu automatic optimal thresholding separates black ink from whiteboard
    _, binary = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return binary


def preprocess(image_path: str | Path, stem: str) -> dict[str, Any]:
    image_path = Path(image_path)
    image = cv2.imread(str(image_path))
    if image is None:
        raise ValueError(f"Could not decode image: {image_path}")

    roi = crop_configured_roi(image)
    quad = detect_board_quad(roi)
    if quad is not None:
        try:
            board = _four_point_warp(roi, quad)
            used_perspective = True
        except cv2.error:
            board = roi
            used_perspective = False
    else:
        board = roi
        used_perspective = False

    # Generate ONLY a single high-contrast binary image to save disk space and processing time
    binary = enhance_for_ocr(board)
    binary_path = PROCESSED_DIR / f"{stem}_binary.jpg"
    cv2.imwrite(str(binary_path), binary)

    return {
        "binary_path": binary_path,
        "enhanced_path": binary_path,
        "board_path": binary_path,
        "used_perspective": used_perspective,
        "original_width": int(image.shape[1]),
        "original_height": int(image.shape[0]),
    }


def _clean_text(text: str) -> str:
    lines = []
    for raw in text.splitlines():
        line = re.sub(r"\s+", " ", raw).strip()
        if not line:
            continue
        line = re.sub(r"([A-Za-z0-9])\1{4,}", r"\1\1", line)
        line = re.sub(r"[._-]{3,}", "", line)
        line = re.sub(r"\s{2,}", " ", line)
        line = line.strip(" ,;:.!?[]{}()\"'")
        if not line:
            continue
        if re.fullmatch(r"(?:[._-]\s*){2,}", line):
            continue
        if re.fullmatch(r"[A-Za-z0-9=<>/+-]+", line) or re.fullmatch(r"[A-Za-z0-9=<>/+-]+\s+[A-Za-z0-9=<>/+-]+", line):
            lines.append(line)
        elif len(line) > 1 and not re.fullmatch(r"[\W_]+", line):
            lines.append(line)
    return "\n".join(lines)


def _looks_like_noise(text: str) -> bool:
    cleaned = (text or "").strip()
    if not cleaned:
        return True
    if re.fullmatch(r"[\W_]+", cleaned):
        return True
    if re.fullmatch(r"(?:[._-]\s*){3,}", cleaned):
        return True
    if len(cleaned) >= 6 and cleaned == cleaned[0] * len(cleaned):
        return True
    if re.fullmatch(r"[A-Za-z0-9=<>/+-]+", cleaned) and len(cleaned) <= 3 and re.search(r"[A-Za-z]", cleaned):
        return False
    if re.fullmatch(r"[A-Za-z0-9=<>/+-]+", cleaned) and len(cleaned) <= 5:
        return False
    if len(cleaned) < 2 and re.search(r"[A-Za-z0-9]", cleaned):
        return False
    return False


def _ocr_variant(image: np.ndarray, label: str, psm: int) -> dict[str, Any]:
    config = f"--psm {psm} --oem 3"
    raw_text = pytesseract.image_to_string(image, lang=OCR_LANG, config=config)
    data = pytesseract.image_to_data(
        image, lang=OCR_LANG, config=config, output_type=pytesseract.Output.DICT
    )
    confidences = []
    for c in data.get("conf", []):
        try:
            val = float(c)
            if val >= 0:
                confidences.append(val)
        except (TypeError, ValueError):
            pass
    mean_conf = sum(confidences) / len(confidences) if confidences else 0.0
    cleaned = _clean_text(raw_text)
    meaningful_chars = len(re.sub(r"[^A-Za-z0-9]", "", cleaned))
    return {
        "variant": label,
        "text": cleaned,
        "confidence": round(mean_conf, 1),
        "word_count": len(cleaned.split()),
        "meaningful_char_count": meaningful_chars,
    }


def run_ocr(binary_path: Path, *args, **kwargs) -> dict[str, Any]:
    if not TESSERACT_AVAILABLE or not TESSERACT_CMD or not os.path.exists(TESSERACT_CMD):
        message = "Tesseract executable was not found."
        return {
            "text": "",
            "confidence": 0.0,
            "status": "missing_tesseract",
            "error": message,
            "variants": [],
            "errors": [message],
            "tesseract_version": "unavailable",
        }

    version = "unknown"
    try:
        version = str(pytesseract.get_tesseract_version())
    except Exception as exc:
        message = f"Tesseract executable was not found: {exc}"
        return {
            "text": "",
            "confidence": 0.0,
            "status": "missing_tesseract",
            "error": message,
            "variants": [],
            "errors": [str(exc)],
            "tesseract_version": "unavailable",
        }

    image = cv2.imread(str(binary_path))
    if image is None:
        return {
            "text": "",
            "confidence": 0.0,
            "status": "failed",
            "error": f"Could not decode binary image at {binary_path}",
            "variants": [],
            "errors": ["Image decode failed"],
            "tesseract_version": version,
        }

    variants = []
    errors = []
    # Test PSM 3 (auto page segmentation), PSM 6 (single block), and PSM 11 (sparse text)
    configs = [
        ("auto_psm3", 3),
        ("block_psm6", 6),
        ("sparse_psm11", 11),
    ]

    for label, psm in configs:
        try:
            variant = _ocr_variant(image, label, psm)
            if variant["text"] and not _looks_like_noise(variant["text"]):
                variants.append(variant)
        except Exception as exc:
            errors.append(f"{label}: {exc}")

    if not variants:
        return {
            "text": "",
            "confidence": 0.0,
            "status": "no_text",
            "error": "OCR completed but no readable text was detected.",
            "variants": variants,
            "errors": errors,
            "tesseract_version": version,
        }

    # Pick the variant with the most meaningful characters and best confidence
    variants.sort(
        key=lambda item: (
            item.get("meaningful_char_count", 0) >= 3,
            item.get("confidence", 0),
            item.get("meaningful_char_count", 0),
        ),
        reverse=True,
    )
    best = variants[0]
    best_text = best["text"]
    confidence = best["confidence"]

    # Threshold for handwriting / whiteboard notes: confidence >= 30 is accepted as ok
    if confidence < 30.0 or best.get("meaningful_char_count", 0) < 1:
        return {
            "text": best_text,
            "confidence": confidence,
            "status": "low_confidence",
            "error": "OCR completed with low confidence.",
            "variants": variants,
            "errors": errors,
            "tesseract_version": version,
        }

    return {
        "text": best_text,
        "confidence": confidence,
        "status": "ok",
        "error": "",
        "variants": variants,
        "errors": errors,
        "tesseract_version": version,
    }


def extract_structured_content(text: str) -> dict[str, list[str]]:
    lines = [x.strip() for x in text.splitlines() if x.strip()]
    equations = []
    bullets = []
    other = []
    for line in lines:
        if re.search(r"[=<>]|\b(sin|cos|tan|log|ln)\b|\^|[∫√π]", line, re.I):
            equations.append(line)
        elif re.match(r"^[•*-]", line):
            bullets.append(re.sub(r"^[•*-]\s*", "", line))
        else:
            other.append(line)
    return {"text": other, "equations": equations, "bullets": bullets}


def generate_notes(text: str, structured: dict[str, list[str]], ocr_status: str | None = None) -> tuple[str, str]:
    """Return summary and notes. Ollama is optional; deterministic fallback is always available."""
    status = (ocr_status or "").strip().lower()
    if not text.strip():
        fallback_summary = "No readable board text was detected."
    elif status in {"low_confidence", "no_text", "missing_tesseract", "failed", "error"}:
        fallback_summary = "Insufficient readable text for AI summarization."
    else:
        fallback_summary = " ".join(text.split()[:80])

    fallback_notes = "\n".join(f"• {line}" for line in structured.get("text", [])[:20])
    if structured.get("equations"):
        fallback_notes += ("\n" if fallback_notes else "") + "\n".join(
            f"• Equation: {line}" for line in structured["equations"][:10]
        )

    if not ENABLE_OLLAMA or not text.strip() or status in {"low_confidence", "no_text", "missing_tesseract", "failed", "error"}:
        return fallback_summary, fallback_notes

    prompt = (
        "You are an assistant for lecture whiteboards. Convert the extracted OCR into concise study notes. "
        "Do not invent information. Preserve equations exactly when possible. Return plain text with sections "
        "Summary and Key Points.\n\nOCR:\n" + text[:12000]
    )
    try:
        response = requests.post(
            f"{OLLAMA_URL.rstrip('/')}/api/generate",
            json={"model": OLLAMA_MODEL, "prompt": prompt, "stream": False},
            timeout=90,
        )
        response.raise_for_status()
        generated = response.json().get("response", "").strip()
        if generated:
            summary = generated.split("Key Points", 1)[0].replace("Summary", "").strip()
            return summary or fallback_summary, generated
    except Exception:
        pass
    return fallback_summary, fallback_notes


def process_image(image_path: str | Path) -> dict[str, Any]:
    image_path = Path(image_path)
    if not image_path.exists():
        raise FileNotFoundError(f"Missing image: {image_path}")
    try:
        stem = image_path.stem
        prep = preprocess(image_path, stem)
        ocr = run_ocr(prep["binary_path"])
        structured = extract_structured_content(ocr["text"])
        summary, notes = generate_notes(ocr["text"], structured, ocr.get("status"))
        return {
            "ocr_text": ocr["text"],
            "ocr_confidence": ocr.get("confidence", 0.0),
            "ocr_status": ocr.get("status", "unknown"),
            "ocr_error": ocr.get("error", ""),
            "ocr_variants": ocr["variants"],
            "ocr_errors": ocr["errors"],
            "structured": structured,
            "summary": summary,
            "notes": notes,
            "board_image": prep["board_path"].name,
            "enhanced_image": prep["enhanced_path"].name,
            "binary_image": prep["binary_path"].name,
            "used_perspective": prep["used_perspective"],
            "tesseract_version": ocr.get("tesseract_version", "unknown"),
        }
    except Exception as exc:
        message = f"Image processing failed: {exc}"
        return {
            "ocr_text": "",
            "ocr_confidence": 0.0,
            "ocr_status": "failed",
            "ocr_error": message,
            "ocr_variants": [],
            "ocr_errors": [message],
            "structured": {"text": [], "equations": [], "bullets": []},
            "summary": "",
            "notes": "",
            "board_image": "",
            "enhanced_image": "",
            "binary_image": "",
            "used_perspective": False,
            "tesseract_version": "unknown",
        }
