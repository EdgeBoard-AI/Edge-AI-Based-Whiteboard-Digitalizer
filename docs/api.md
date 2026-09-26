# API Reference

The EdgeBoard AI backend exposes a REST API for device telemetry ingestion, image retrieval, and dashboard integration.

Base URL: `http://<HOST>:<PORT>` (Default: `http://127.0.0.1:5000`)

---

## Endpoints

### 1. Ingestion Endpoint

#### `POST /upload`
Receives high-resolution JPEG frames uploaded by the ESP32 camera device. Ingestion responds immediately (`202 Accepted`) and schedules background OCR processing.

**Headers:**
| Header | Type | Description |
| :--- | :--- | :--- |
| `Content-Type` | `string` | Must be `image/jpeg` or raw binary stream |
| `X-Device` | `string` | Device identifier (e.g. `ESP32-S3-OV3660`) |
| `X-Change-Score` | `float` | Difference score vs last reference frame |
| `X-Board-Visibility` | `float` | Board visibility score (0.0 to 1.0) |
| `X-Brightness` | `float` | Average frame brightness |
| `X-Sharpness` | `float` | Laplacian focus measure score |
| `X-Stability-Score` | `float` | Frame stability score |
| `X-Timestamp` | `string` | Device timestamp (millis) |

**Response (`202 Accepted`):**
```json
{
  "success": true,
  "status": "accepted",
  "filename": "20260926_162011_686435.jpg",
  "frame_id": 42,
  "processing_error": ""
}
```

---

### 2. System Status & Health

#### `GET /health` | `GET /status`
Returns system operational state, Tesseract engine availability, Ollama integration status, and frame statistics.

**Response (`200 OK`):**
```json
{
  "ok": true,
  "service": "EdgeBoard AI",
  "port": 5000,
  "tesseract_available": true,
  "tesseract_version": "5.4.0",
  "ollama_enabled": false,
  "capture_count": 120,
  "accepted_count": 115,
  "rejected_count": 5
}
```

---

### 3. Frame Data & OCR Querying

#### `GET /api/latest`
Fetches the most recently recorded frame record.

**Response (`200 OK`):**
```json
{
  "id": 42,
  "filename": "20260926_162011_686435.jpg",
  "received_at": "2026-09-26T16:20:11.686435+00:00",
  "size_bytes": 48291,
  "device": "ESP32-S3",
  "change_score": 0.042,
  "board_visibility": 0.94,
  "brightness": 162.3,
  "sharpness": 4.12,
  "stability_score": 0.012,
  "processing_status": "complete",
  "ocr_text": "V = I * R\nP = V * I",
  "ocr_confidence": 92.4,
  "ocr_engine": "tesseract",
  "ocr_status": "ok",
  "summary": "Electrical Ohm's Law and Power equations.",
  "notes": "- V = I * R (Voltage)\n- P = V * I (Power)",
  "structured": {
    "equations": ["V = I * R", "P = V * I"],
    "bullets": [],
    "headings": []
  },
  "processed_image_path": "20260926_162011_686435_variant_2_adaptive.jpg",
  "image_available": true
}
```

#### `GET /api/frames`
Lists recent frames with optional pagination limit.

**Query Parameters:**
- `limit` (integer, optional, default: `50`, min: `1`, max: `100`)

**Response (`200 OK`):**
```json
[
  { "id": 42, "filename": "...", "ocr_text": "..." },
  { "id": 41, "filename": "...", "ocr_text": "..." }
]
```

#### `GET /api/frames/<int:frame_id>`
Fetches detailed metadata and OCR results for a specific frame ID.

---

### 4. Image Serving

#### `GET /snapshot`
Returns the raw JPEG image of the latest captured frame (`image/jpeg`).

#### `GET /captures/<filename>`
Serves raw incoming JPEG images stored in the capture directory.

#### `GET /processed/<filename>`
Serves warped and thresholded image artifacts produced by the OCR pipeline.

---

### 5. Reprocessing Endpoints

#### `POST /api/process/<int:frame_id>`
Re-runs perspective correction, image enhancement, and OCR on a specific frame.

**Response (`200 OK`):**
```json
{
  "success": true,
  "result": {
    "ocr_status": "ok",
    "ocr_text": "...",
    "ocr_confidence": 91.5,
    "binary_image": "20260926_162011_686435_variant_2_adaptive.jpg"
  }
}
```

#### `POST /api/reprocess-all`
Iterates through all stored frames in the database and re-executes the processing pipeline.

**Response (`200 OK`):**
```json
{
  "success": true,
  "completed": 42,
  "failed": 0
}
```
