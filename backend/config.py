import os
import re
import shutil
import subprocess
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
RECEIVED_DIR = BASE_DIR / "received_frames"
PROCESSED_DIR = BASE_DIR / "processed"
CAPTURES_DIR = BASE_DIR / "captures"
DB_PATH = BASE_DIR / "edgeboard.db"

for directory in (RECEIVED_DIR, PROCESSED_DIR, CAPTURES_DIR):
    directory.mkdir(parents=True, exist_ok=True)

HOST = os.getenv("EDGEBOARD_HOST", "0.0.0.0")
PORT = int(os.getenv("EDGEBOARD_PORT", "5000"))
MAX_UPLOAD_MB = int(os.getenv("EDGEBOARD_MAX_UPLOAD_MB", "8"))


def _resolve_tesseract_cmd() -> str:
    """Resolve the Tesseract executable in a Windows-friendly, configurable way."""
    env_value = os.getenv("TESSERACT_CMD")
    if env_value:
        env_value = env_value.strip().strip('"')
        if os.path.exists(env_value):
            return env_value

    candidates = []
    if os.name == "nt":
        program_files = [
            os.getenv("ProgramFiles"),
            os.getenv("ProgramFiles(x86)"),
            os.getenv("PROGRAMFILES"),
            os.getenv("PROGRAMFILES(X86)"),
        ]
        for root in program_files:
            if root:
                candidates.extend([
                    str(Path(root) / "Tesseract-OCR" / "tesseract.exe"),
                    str(Path(root) / "Tesseract-OCR" / "tesseract"),
                ])
    candidates.extend([
        shutil.which("tesseract") or "",
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    ])
    for candidate in candidates:
        if candidate and os.path.exists(candidate):
            return candidate
    return env_value or ""


def _probe_tesseract_version(executable: str) -> str:
    if not executable or not os.path.exists(executable):
        return ""
    try:
        result = subprocess.run(
            [executable, "--version"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        if result.returncode != 0:
            return ""
        output = (result.stdout or "") + (result.stderr or "")
        match = re.search(r"tesseract\s+v?([0-9]+(?:\.[0-9]+){2,3})", output, re.IGNORECASE)
        return match.group(1) if match else "unknown"
    except Exception:
        return ""


# OCR / AI are deliberately local-first. No cloud key is required.
OCR_LANG = os.getenv("EDGEBOARD_OCR_LANG", "eng")
TESSERACT_CMD = _resolve_tesseract_cmd()
TESSERACT_VERSION = _probe_tesseract_version(TESSERACT_CMD)
TESSERACT_AVAILABLE = bool(TESSERACT_CMD and os.path.exists(TESSERACT_CMD) and TESSERACT_VERSION)
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2:3b")
ENABLE_OLLAMA = os.getenv("ENABLE_OLLAMA", "0") == "1"

# The camera can be mounted differently; set these to crop the actual board.
# Values are fractions of width/height. Full frame is the safe default.
ROI_X = float(os.getenv("EDGEBOARD_ROI_X", "0.02"))
ROI_Y = float(os.getenv("EDGEBOARD_ROI_Y", "0.02"))
ROI_W = float(os.getenv("EDGEBOARD_ROI_W", "0.96"))
ROI_H = float(os.getenv("EDGEBOARD_ROI_H", "0.96"))
