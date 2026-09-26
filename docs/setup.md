# Setup Guide

This guide covers installing and deploying the EdgeBoard AI backend server, setting up Tesseract OCR, configuring optional Ollama LLM support, and flashing the ESP32-S3 firmware.

---

## 1. Backend Server Setup

### Requirements
- **Python**: 3.10, 3.11, 3.12, or 3.13
- **Tesseract OCR**: 5.x recommended

### Step 1: Create Virtual Environment

From the project root:

```powershell
cd backend
py -m venv .venv
.\.venv\Scripts\Activate.ps1
```

*(On Linux / macOS: `python3 -m venv .venv && source .venv/bin/activate`)*

### Step 2: Install Python Dependencies

```bash
pip install -r requirements.txt
```

### Step 3: Install Tesseract OCR

- **Windows**: Download and install from [UB-Mannheim Tesseract Releases](https://github.com/UB-Mannheim/tesseract/wiki). Default installation path is `C:\Program Files\Tesseract-OCR\tesseract.exe`.
- **Linux (Ubuntu/Debian)**: `sudo apt-get install tesseract-ocr`
- **macOS**: `brew install tesseract`

Ensure `tesseract` is added to system `PATH`, or specify its location via `TESSERACT_CMD` in `.env`.

### Step 4: Configure Environment Variables

Copy `.env.example` to `.env` or set environment variables:

```ini
# Server configuration
EDGEBOARD_HOST=0.0.0.0
EDGEBOARD_PORT=5000
EDGEBOARD_MAX_UPLOAD_MB=8

# Tesseract executable (if not in PATH)
TESSERACT_CMD=C:\Program Files\Tesseract-OCR\tesseract.exe
EDGEBOARD_OCR_LANG=eng

# Board Region of Interest (ROI) percentages (0.0 to 1.0)
EDGEBOARD_ROI_X=0.02
EDGEBOARD_ROI_Y=0.02
EDGEBOARD_ROI_W=0.96
EDGEBOARD_ROI_H=0.96

# Optional Ollama Local LLM
ENABLE_OLLAMA=0
OLLAMA_URL=http://127.0.0.1:11434
OLLAMA_MODEL=llama3.2:3b
```

### Step 5: Start the Backend Server

```powershell
python server.py
```

Or run the helper script:
```powershell
..\scripts\run_server.bat
```

Access the web dashboard in your browser:
```text
http://127.0.0.1:5000
```

---

## 2. Firmware Setup (Arduino IDE)

The firmware is located in `firmware/esp32_camera/esp32_camera.ino`.

### Hardware Requirements
- **Microcontroller**: ESP32-S3 (N16R8 module with 16MB Flash, 8MB PSRAM)
- **Camera Module**: OV3660 (or compatible pinout)

### Arduino IDE Configuration

1. Install **Arduino IDE** (v2.x recommended).
2. Install the **ESP32 by Espressif Systems** board package via Boards Manager.
3. Open `firmware/esp32_camera/esp32_camera.ino`.
4. Configure Board Settings under **Tools**:
   - **Board**: `ESP32S3 Dev Module`
   - **Flash Size**: `16MB (128Mb)`
   - **Flash Mode**: `QIO 80MHz`
   - **PSRAM**: `OPI PSRAM`
   - **Partition Scheme**: `16M Flash (3MB APP/9.9MB FAT)` or standard 16MB scheme
   - **USB CDC On Boot**: `Enabled` (or according to your dev board specification)

### Wi-Fi and Laptop IP Configuration

In `firmware/esp32_camera/esp32_camera.ino`, update your Wi-Fi credentials and the laptop's local IP address:

```cpp
const char* WIFI_SSID = "YOUR_WIFI_NETWORK";
const char* WIFI_PASSWORD = "YOUR_WIFI_PASSWORD";

// Replace with your laptop's IPv4 address on the shared network
const char* LAPTOP_SERVER = "http://192.168.1.100:5000/upload";
```

### Uploading & Monitoring

1. Connect the ESP32-S3 board to your computer via USB.
2. Select the corresponding COM port.
3. Click **Upload**.
4. Open the Serial Monitor at **115200 baud** to view real-time diagnostics and capture telemetry.

---

## 3. Optional Local LLM (Ollama)

To automatically summarize board captures and format study notes:

1. Install [Ollama](https://ollama.ai/).
2. Pull the default model:
   ```bash
   ollama pull llama3.2:3b
   ```
3. Set in your `.env`:
   ```ini
   ENABLE_OLLAMA=1
   OLLAMA_MODEL=llama3.2:3b
   ```
4. Restart the backend server.
