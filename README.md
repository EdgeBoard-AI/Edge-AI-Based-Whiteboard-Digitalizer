# EdgeBoard AI

**ESP32-S3 + OV3660 Edge Capture + Local OCR + Optional Local LLM**

EdgeBoard AI is an end-to-end smart whiteboard and presentation capture system. The ESP32-S3 edge device performs real-time quality, stability, and change assessment to avoid transmitting redundant frames. A local Python backend receives valid JPEG frames, performs perspective rectification and enhancement, extracts text via Tesseract OCR, parses structured elements, and optionally formats study notes with a local Ollama model.

---

## Features

- **Smart Edge Filtering**: Frame stability analysis, quality checks (brightness, sharpness), and meaningful-change detection directly on the ESP32-S3 microcontroller.
- **Efficient Network Usage**: Transmits only stable, high-quality, changed frames over local Wi-Fi.
- **Automated Image Rectification**: 4-point perspective warp and OpenCV image enhancements (CLAHE, denoising, adaptive thresholding).
- **Local-First OCR**: Offline text extraction using Tesseract OCR with multi-variant confidence scoring.
- **Optional Local LLM Summarization**: Automated study note generation and concept extraction via Ollama (e.g. `llama3.2:3b`) with zero cloud dependencies.
- **Interactive Web Dashboard**: Real-time monitoring, live snapshots, capture history, and manual reprocessing controls.
- **RESTful Ingestion API**: Lightweight HTTP endpoints for device telemetry and image retrieval.

---

## Architecture

```text
Whiteboard / Presentation Surface
       │
       ▼
OV3660 Camera Sensor
       │
       ▼
ESP32-S3 Microcontroller
  ├─ Brightness & Sharpness Validation
  ├─ Board Visibility Heuristic
  ├─ Consecutive-Frame Stability Score
  └─ Change Detection vs Last Accepted Frame
       │ (HTTP POST with Telemetry Headers)
       ▼
Flask Backend Server (Local PC)
  ├─ SQLite Metadata Storage (`edgeboard.db`)
  ├─ Perspective Quad Warp & Crop
  ├─ CLAHE & Multi-Threshold Enhancement
  ├─ Tesseract OCR Pipeline
  └─ Optional Ollama Note Summarization
       │
       ▼
Web Dashboard (Browser Interface)
```

---

## Repository Structure

```text
EdgeAI/
├── backend/
│   ├── server.py             # Flask application & REST endpoints
│   ├── db.py                 # SQLite database layer
│   ├── config.py             # Application configuration & paths
│   ├── requirements.txt      # Python dependencies
│   ├── test_pipeline.py      # Local verification suite
│   ├── ai/
│   │   ├── __init__.py
│   │   └── pipeline.py       # Preprocessing, OCR & LLM pipeline
│   ├── templates/
│   │   └── index.html        # Web dashboard template
│   └── static/
│       └── style.css         # Dashboard styling
│
├── firmware/
│   └── esp32_camera/
│       └── esp32_camera.ino  # ESP32-S3 Arduino firmware
│
├── docs/
│   ├── architecture.md       # Comprehensive system architecture
│   ├── api.md                # REST API documentation
│   ├── setup.md              # Installation & setup guide
│   └── images/               # Documentation assets
│
├── scripts/
│   └── run_server.bat        # Server launcher script (Windows)
│
├── .gitignore                # Production gitignore
├── README.md                 # Project documentation
├── LICENSE                   # Project license
└── .env.example              # Environment variables template
```

---

## Installation & Setup

### 1. Backend Server Setup

Ensure Python 3.10+ and [Tesseract OCR](https://github.com/UB-Mannheim/tesseract/wiki) are installed.

```powershell
# Navigate to backend directory
cd backend

# Create and activate virtual environment
py -m venv .venv
.\.venv\Scripts\Activate.ps1

# Install required dependencies
pip install -r requirements.txt
```

### 2. Configure Environment

Copy `.env.example` to `.env` in the root or `backend` folder and adjust configurations as needed:

```ini
EDGEBOARD_HOST=0.0.0.0
EDGEBOARD_PORT=5000
TESSERACT_CMD=C:\Program Files\Tesseract-OCR\tesseract.exe
ENABLE_OLLAMA=0
```

### 3. Firmware Configuration

1. Open `firmware/esp32_camera/esp32_camera.ino` in Arduino IDE.
2. Select board **ESP32S3 Dev Module** with **OPI PSRAM** enabled.
3. Update your Wi-Fi SSID, password, and the backend server IP address:
   ```cpp
   const char* WIFI_SSID = "YOUR_WIFI_SSID";
   const char* WIFI_PASSWORD = "YOUR_WIFI_PASSWORD";
   const char* LAPTOP_SERVER = "http://YOUR_SERVER_IP:5000/upload";
   ```
4. Flash the sketch to your ESP32-S3 module.

---

## Running the Backend

Start the server using Python:

```powershell
cd backend
python server.py
```

Or launch using the script:

```powershell
.\scripts\run_server.bat
```

Open the dashboard in your web browser:
```text
http://127.0.0.1:5000
```

---

## ESP32 Upload Flow

1. The ESP32 camera samples the whiteboard periodically (default every 1.0s).
2. It evaluates frame quality (brightness and sharpness) and checks for physical obstructions.
3. Once the board remains stable for the required duration (`1500ms`), it computes the change score against the last accepted state.
4. If a meaningful delta is detected, a full-resolution JPEG is uploaded to `POST /upload` with telemetry metadata headers (`X-Change-Score`, `X-Board-Visibility`, `X-Sharpness`, `X-Stability-Score`).
5. The backend accepts the payload, records metadata in SQLite, and invokes the OCR processing worker.

---

## OCR Pipeline Overview

1. **ROI Cropping**: Extracts the whiteboard area based on configured bounding coordinates.
2. **Perspective Transform**: Automatically locates board corners and performs a 4-point perspective warp.
3. **Enhancement**: Applies noise reduction, CLAHE contrast equalization, sharpening, and multiple binarization variants (Otsu, Adaptive Gaussian).
4. **Tesseract OCR**: Extracts text from each variant and selects the result with the highest confidence.
5. **Structuring**: Identifies formulas, equations, list items, and key headings.
6. **LLM Synthesis (Optional)**: If Ollama is active, prompts a local model to structure clean lecture/study notes.

---

## Documentation

- [System Architecture](docs/architecture.md)
- [REST API Reference](docs/api.md)
- [Step-by-Step Setup Guide](docs/setup.md)

---

## Contributors

<!-- Organization contributors section -->
Contributions are welcome! Please feel free to submit issues and pull requests.

---

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
