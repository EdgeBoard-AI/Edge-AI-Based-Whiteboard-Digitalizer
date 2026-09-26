# System Architecture

EdgeBoard AI is a local-first, privacy-respecting smart capture and OCR system designed to digitize whiteboards and presentation surfaces in real time.

---

## High-Level Architecture

```text
+-------------------------------------------------------------------------+
|                               EDGE TIER                                 |
|                                                                         |
|  [ Whiteboard ]                                                         |
|         │                                                               |
|         ▼                                                               |
|  [ OV3660 Camera ]                                                      |
|         │ (RGB565 / Grayscale Downsample)                               |
|         ▼                                                               |
|  [ ESP32-S3 Microcontroller ]                                           |
|    ├─ Frame Quality Filter (Brightness, Sharpness)                      |
|    ├─ Board Visibility Heuristic (Obstruction Detection)                |
|    ├─ Consecutive-Frame Stability Score (Noise Rejection)               |
|    └─ Meaningful-Change Score (Delta vs Last Accepted Frame)            |
|         │                                                               |
|         │ (HTTP POST with Metadata Headers)                             |
+─────────┼───────────────────────────────────────────────────────────────+
          │ (Wi-Fi Local Network)
          ▼
+─────────────────────────────────────────────────────────────────────────+
|                              BACKEND TIER                               |
|                                                                         |
|  [ Flask REST API Server ]                                              |
|    ├─ Ingestion & Verification (/upload)                                |
|    ├─ Metadata Storage (SQLite: frames)                                 |
|    └─ Background Worker Pool (ThreadPoolExecutor)                      |
|            │                                                            |
|            ▼                                                            |
|  [ AI & OCR Processing Pipeline ]                                       |
|    ├─ Region of Interest (ROI) Crop                                     |
|    ├─ Quad Detection & Perspective Rectification (OpenCV)               |
|    ├─ Enhancement (CLAHE, Denoising, Multi-Thresholding)                |
|    ├─ OCR Extraction (Tesseract OCR Engine)                             |
|    ├─ Structured Information Parsing (Formulas, Items, Key-Value)       |
|    └─ Optional Local LLM Summarization (Ollama llama3.2)                |
|            │                                                            |
|            ▼                                                            |
|  [ Web Management Dashboard ] (HTML5 / CSS / Vanilla JS)                |
+-------------------------------------------------------------------------+
```

---

## 1. Edge Layer (ESP32-S3 + OV3660)

The edge device performs localized frame quality assessment to prevent transmitting repetitive, noisy, or occluded frames over the network.

### Decision Pipeline

1. **Frame Capture**: Captures low-resolution analysis frames (80x60) periodically (`CHECK_INTERVAL = 1000ms`).
2. **Quality Verification**:
   - **Brightness**: Validated against `MIN_BRIGHTNESS` (35) and `MAX_BRIGHTNESS` (245).
   - **Sharpness**: Laplacian-based edge gradient check to ensure image is in focus (`MIN_SHARPNESS >= 1.5`).
   - **Board Visibility**: Heuristic check verifying the board surface is not obstructed by a speaker or hand (`MIN_BOARD_VISIBILITY >= 0.50`).
3. **Temporal Stability**:
   - Compares the current frame against the immediately preceding frame.
   - Requires stability for at least `REQUIRED_STABLE_TIME = 1500ms` (`STABILITY_THRESHOLD <= 0.045`).
4. **Change Detection**:
   - Compares the stable frame against the **last successfully captured reference frame**.
   - Requires meaningful difference (`CHANGE_THRESHOLD >= 0.020`, `MIN_CHANGED_PIXEL_RATIO >= 1.2%`).
5. **Conditional Transmission**:
   - When all conditions pass, captures a high-resolution JPEG and transmits it via HTTP `POST /upload` with custom telemetry headers.

---

## 2. Backend Layer (Flask & SQLite)

The backend runs locally on a computer on the same local network as the edge device.

- **Storage Engine**: SQLite database (`edgeboard.db`) storing frame metadata, edge metrics, OCR text, confidence scores, and structured data.
- **Asynchronous Execution**: Decoupled ingestion (`/upload` responds immediately with `202 Accepted`) using Python `ThreadPoolExecutor` for background image processing.
- **REST Endpoints**: Real-time APIs for querying status, frame history, re-running OCR, and previewing raw captures.

---

## 3. AI & OCR Pipeline

The image processing pipeline (`ai/pipeline.py`) transforms raw camera captures into readable text:

1. **ROI Extraction**: Configurable bounding box crop eliminating surrounding room background.
2. **Perspective Correction**: Automatic contour analysis identifying the 4 board corners and applying a 4-point perspective warp.
3. **Multi-Variant Enhancement**:
   - Fast Non-Local Means Denoising.
   - Contrast Limited Adaptive Histogram Equalization (CLAHE).
   - Kernel-based high-pass sharpening.
   - Multi-threshold generation (Otsu, Adaptive Gaussian, Fixed Binary).
4. **Tesseract OCR Execution**: Runs OCR across enhanced image variants to achieve the highest word confidence score.
5. **Local LLM Integration (Optional)**: If enabled via Ollama (`ENABLE_OLLAMA=1`), passes extracted text to a local model (e.g. `llama3.2:3b`) for automated summary and study note generation without cloud dependency.
