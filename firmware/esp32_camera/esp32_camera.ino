#include "esp_camera.h"
#include "img_converters.h"
#include <WiFi.h>
#include <WebServer.h>
#include <HTTPClient.h>

// =============================================================
// EDGEBOARD AI — ESP32-S3 N16R8 + OV3660
//
// Smart capture:
//   camera
//      ↓
//   quality check
//      ↓
//   stability check
//      ↓
//   meaningful-change detection
//      ↓
//   upload to laptop
//
// OCR / AI are performed on the laptop.
// =============================================================

// =============================================================
// Wi-Fi / Server
// =============================================================

const char* WIFI_SSID = "Brahmastra";
const char* WIFI_PASSWORD = "brahmastra";

const char* LAPTOP_SERVER =
    "http://192.168.137.218:5000/upload";

WebServer server(80);

#define STATUS_LED 48

// =============================================================
// OV3660 / ESP32-S3 N16R8 CAMERA PIN MAP
// =============================================================

#define PWDN_GPIO_NUM    -1
#define RESET_GPIO_NUM   -1

#define XCLK_GPIO_NUM    15
#define SIOD_GPIO_NUM     4
#define SIOC_GPIO_NUM     5

#define Y9_GPIO_NUM      16
#define Y8_GPIO_NUM      17
#define Y7_GPIO_NUM      18
#define Y6_GPIO_NUM      12
#define Y5_GPIO_NUM      10
#define Y4_GPIO_NUM       8
#define Y3_GPIO_NUM       9
#define Y2_GPIO_NUM      11

#define VSYNC_GPIO_NUM    6
#define HREF_GPIO_NUM     7
#define PCLK_GPIO_NUM    13

// =============================================================
// TIMING
// =============================================================

// How frequently a frame is analyzed
const unsigned long CHECK_INTERVAL = 1000;

// Condition 1: How long the board must remain stable (teacher not writing) before capture
const unsigned long REQUIRED_STABLE_TIME = 3500;

// Minimum time between successful captures (cooldown to avoid duplicates)
const unsigned long CAPTURE_COOLDOWN = 8000;

// Wi-Fi reconnect interval
const unsigned long WIFI_RETRY_INTERVAL = 10000;

// =============================================================
// ANALYSIS IMAGE
// =============================================================

#define ANALYSIS_WIDTH  80
#define ANALYSIS_HEIGHT 60
#define ANALYSIS_PIXELS (ANALYSIS_WIDTH * ANALYSIS_HEIGHT)

// =============================================================
// SMART CAPTURE THRESHOLDS (3 CORE CONDITIONS)
// =============================================================

// Condition 1: Consecutive-frame stability (detects teacher writing/hand movement)
// Lower score = still board; higher score = active motion/writing
const float STABILITY_THRESHOLD = 0.035f;

// Condition 2: Board visibility (detects hand, arm, or object in front of whiteboard)
// Clear whiteboard is ~0.78-0.85; an obstructing body/hand drops it below 0.73
const float MIN_BOARD_VISIBILITY = 0.73f;

// Condition 3: Significant change thresholds (prevents sending on few or small changes)
// Major overall difference (e.g. board wipe or major redraw)
const float CHANGE_THRESHOLD = 0.055f;

// Minimum percentage of board pixels that must have changed significantly (4.0%)
const float MIN_CHANGED_PIXEL_RATIO = 0.040f;

// Difference threshold for a single pixel to be considered changed
const int PIXEL_CHANGE_THRESHOLD = 20;

// Significant change in dark marker writing (2.5% of board area)
const float DARK_CHANGE_RATIO = 0.025f;

// Brightness limits
const float MIN_BRIGHTNESS = 35.0f;
const float MAX_BRIGHTNESS = 245.0f;

// Sharpness threshold
const float MIN_SHARPNESS = 1.5f;

// =============================================================
// STATE
// =============================================================

unsigned long lastCheck = 0;
unsigned long stableStart = 0;
unsigned long lastCapture = 0;
unsigned long lastWiFiRetry = 0;

unsigned long capturedFrames = 0;
unsigned long rejectedFrames = 0;
unsigned long processedFrames = 0;

bool previousValid = false;
bool referenceValid = false;
bool boardStable = false;

float currentStabilityScore = 1.0f;
float currentChangeScore = 0.0f;

float currentChangedPixelRatio = 0.0f;
float currentDarkChangeRatio = 0.0f;

float currentBoardVisibility = 0.0f;
float currentBrightness = 0.0f;
float currentSharpness = 0.0f;

String lastDecision = "STARTING";

// =============================================================
// PSRAM BUFFERS
// =============================================================

uint8_t* previousImage = nullptr;
uint8_t* referenceImage = nullptr;
uint8_t* currentImage = nullptr;

uint8_t* rgbBuffer = nullptr;

// =============================================================
// LED
// =============================================================

void ledOn() {
  digitalWrite(STATUS_LED, HIGH);
}

void ledOff() {
  digitalWrite(STATUS_LED, LOW);
}

void blinkLED(int times, int delayMs) {

  for (int i = 0; i < times; i++) {

    ledOn();
    delay(delayMs);

    ledOff();
    delay(delayMs);
  }
}

// =============================================================
// BUFFER ALLOCATION
// =============================================================

bool allocateAnalysisBuffers() {

  const size_t analysisBytes =
      ANALYSIS_PIXELS * sizeof(uint8_t);

  // VGA RGB buffer
  const size_t rgbBytes =
      640UL * 480UL * 3UL;

  previousImage =
      (uint8_t*)ps_malloc(analysisBytes);

  referenceImage =
      (uint8_t*)ps_malloc(analysisBytes);

  currentImage =
      (uint8_t*)ps_malloc(analysisBytes);

  rgbBuffer =
      (uint8_t*)ps_malloc(rgbBytes);

  if (!previousImage ||
      !referenceImage ||
      !currentImage ||
      !rgbBuffer) {

    Serial.println(
        "ERROR: PSRAM allocation failed.");

    return false;
  }

  memset(previousImage, 0, analysisBytes);
  memset(referenceImage, 0, analysisBytes);
  memset(currentImage, 0, analysisBytes);

  Serial.println(
      "Analysis buffers allocated successfully.");

  return true;
}

// =============================================================
// CAMERA
// =============================================================

bool initCamera() {

  camera_config_t config;

  config.ledc_channel = LEDC_CHANNEL_0;
  config.ledc_timer = LEDC_TIMER_0;

  config.pin_d0 = Y2_GPIO_NUM;
  config.pin_d1 = Y3_GPIO_NUM;
  config.pin_d2 = Y4_GPIO_NUM;
  config.pin_d3 = Y5_GPIO_NUM;
  config.pin_d4 = Y6_GPIO_NUM;
  config.pin_d5 = Y7_GPIO_NUM;
  config.pin_d6 = Y8_GPIO_NUM;
  config.pin_d7 = Y9_GPIO_NUM;

  config.pin_xclk = XCLK_GPIO_NUM;
  config.pin_pclk = PCLK_GPIO_NUM;

  config.pin_vsync = VSYNC_GPIO_NUM;
  config.pin_href = HREF_GPIO_NUM;

  config.pin_sccb_sda = SIOD_GPIO_NUM;
  config.pin_sccb_scl = SIOC_GPIO_NUM;

  config.pin_pwdn = PWDN_GPIO_NUM;
  config.pin_reset = RESET_GPIO_NUM;

  config.xclk_freq_hz = 20000000;

  config.pixel_format = PIXFORMAT_JPEG;

  if (psramFound()) {

    Serial.printf(
        "PSRAM: YES (%u MB)\n",
        ESP.getPsramSize() /
        (1024 * 1024));

    config.frame_size = FRAMESIZE_VGA;

    config.jpeg_quality = 12;

    config.fb_count = 2;

    config.fb_location =
        CAMERA_FB_IN_PSRAM;

    config.grab_mode =
        CAMERA_GRAB_LATEST;

  } else {

    Serial.println("PSRAM: NO");

    config.frame_size = FRAMESIZE_QVGA;

    config.jpeg_quality = 15;

    config.fb_count = 1;

    config.fb_location =
        CAMERA_FB_IN_DRAM;

    config.grab_mode =
        CAMERA_GRAB_WHEN_EMPTY;
  }

  esp_err_t err =
      esp_camera_init(&config);

  if (err != ESP_OK) {

    Serial.printf(
        "Camera initialization FAILED: 0x%X\n",
        err);

    return false;
  }

  sensor_t* sensor =
      esp_camera_sensor_get();

  if (sensor) {

    sensor->set_vflip(sensor, 1);

    sensor->set_hmirror(sensor, 0);

    sensor->set_whitebal(sensor, 1);

    sensor->set_exposure_ctrl(sensor, 1);

    sensor->set_gain_ctrl(sensor, 1);
  }

  Serial.println(
      "Camera initialized successfully.");

  return true;
}

// =============================================================
// CREATE LOW-RES ANALYSIS IMAGE
// =============================================================

bool createAnalysisImage(
    camera_fb_t* fb,
    uint8_t* output) {

  if (!fb ||
      !output ||
      !rgbBuffer) {

    return false;
  }

  if (!fmt2rgb888(
          fb->buf,
          fb->len,
          PIXFORMAT_JPEG,
          rgbBuffer)) {

    Serial.println(
        "JPEG -> RGB conversion failed.");

    return false;
  }

  // -----------------------------------------------------------
  // Central ROI
  // -----------------------------------------------------------

  const float ROI_X = 0.05f;
  const float ROI_Y = 0.05f;
  const float ROI_W = 0.90f;
  const float ROI_H = 0.90f;

  int startX =
      (int)(fb->width * ROI_X);

  int startY =
      (int)(fb->height * ROI_Y);

  int roiWidth =
      (int)(fb->width * ROI_W);

  int roiHeight =
      (int)(fb->height * ROI_H);

  // -----------------------------------------------------------
  // Downsample to 80x60 grayscale
  // -----------------------------------------------------------

  for (int y = 0;
       y < ANALYSIS_HEIGHT;
       y++) {

    for (int x = 0;
         x < ANALYSIS_WIDTH;
         x++) {

      int sourceX =
          startX +
          (x * roiWidth /
           ANALYSIS_WIDTH);

      int sourceY =
          startY +
          (y * roiHeight /
           ANALYSIS_HEIGHT);

      sourceX =
          constrain(
              sourceX,
              0,
              (int)fb->width - 1);

      sourceY =
          constrain(
              sourceY,
              0,
              (int)fb->height - 1);

      int index =
          (sourceY * fb->width +
           sourceX) * 3;

      uint8_t r =
          rgbBuffer[index];

      uint8_t g =
          rgbBuffer[index + 1];

      uint8_t b =
          rgbBuffer[index + 2];

      output[
          y * ANALYSIS_WIDTH + x
      ] =
          (uint8_t)(
              (299 * r +
               587 * g +
               114 * b) /
              1000
          );
    }
  }

  return true;
}

// =============================================================
// AVERAGE DIFFERENCE
// =============================================================

float calculateDifference(
    const uint8_t* a,
    const uint8_t* b) {

  if (!a || !b)
    return 1.0f;

  uint32_t total = 0;

  int samples = 0;

  for (int i = 0;
       i < ANALYSIS_PIXELS;
       i += 2) {

    total +=
        abs(
            (int)a[i] -
            (int)b[i]);

    samples++;
  }

  if (!samples)
    return 1.0f;

  return
      ((float)total / samples)
      / 255.0f;
}

// =============================================================
// CHANGED PIXEL RATIO
//
// This is the important new detection mechanism.
//
// A small amount of handwriting can produce a low average
// difference, but many pixels can still change noticeably.
// =============================================================

float calculateChangedPixelRatio(
    const uint8_t* current,
    const uint8_t* reference) {

  if (!current || !reference)
    return 1.0f;

  int changed = 0;
  int total = 0;

  for (int i = 0;
       i < ANALYSIS_PIXELS;
       i++) {

    int diff =
        abs(
            (int)current[i] -
            (int)reference[i]);

    if (diff >= PIXEL_CHANGE_THRESHOLD) {
      changed++;
    }

    total++;
  }

  if (total == 0)
    return 0.0f;

  return
      (float)changed /
      (float)total;
}

// =============================================================
// DARK PIXEL CHANGE
//
// Useful for detecting black marker writing on a bright board.
// =============================================================

float calculateDarkChangeRatio(
    const uint8_t* current,
    const uint8_t* reference) {

  if (!current || !reference)
    return 1.0f;

  int darkChanged = 0;
  int total = 0;

  for (int i = 0;
       i < ANALYSIS_PIXELS;
       i++) {

    bool currentDark =
        current[i] < 100;

    bool referenceDark =
        reference[i] < 100;

    if (currentDark != referenceDark) {
      darkChanged++;
    }

    total++;
  }

  if (total == 0)
    return 0.0f;

  return
      (float)darkChanged /
      (float)total;
}

// =============================================================
// BRIGHTNESS
// =============================================================

float calculateBrightness(
    const uint8_t* image) {

  if (!image)
    return 0;

  uint32_t total = 0;

  int samples = 0;

  for (int i = 0;
       i < ANALYSIS_PIXELS;
       i += 2) {

    total += image[i];

    samples++;
  }

  if (!samples)
    return 0;

  return
      (float)total /
      samples;
}

// =============================================================
// SHARPNESS
// =============================================================

float calculateSharpness(
    const uint8_t* image) {

  if (!image)
    return 0;

  uint32_t total = 0;

  int samples = 0;

  for (int y = 0;
       y < ANALYSIS_HEIGHT - 1;
       y += 2) {

    for (int x = 0;
         x < ANALYSIS_WIDTH - 1;
         x += 2) {

      int i =
          y * ANALYSIS_WIDTH + x;

      total +=
          abs(
              (int)image[i] -
              (int)image[i + 1]);

      total +=
          abs(
              (int)image[i] -
              (int)image[
                  i + ANALYSIS_WIDTH]);

      samples++;
    }
  }

  if (!samples)
    return 0;

  return
      (float)total /
      samples;
}

// =============================================================
// BOARD VISIBILITY
// =============================================================

float calculateBoardVisibility(
    const uint8_t* image) {

  if (!image)
    return 0;

  int bright = 0;
  int dark = 0;

  int samples = 0;

  for (int i = 0;
       i < ANALYSIS_PIXELS;
       i += 2) {

    uint8_t p = image[i];

    if (p >= 115)
      bright++;

    if (p < 65)
      dark++;

    samples++;
  }

  if (!samples)
    return 0;

  float brightFraction =
      (float)bright /
      samples;

  float darkFraction =
      (float)dark /
      samples;

  float visibility =
      0.82f * brightFraction +
      0.18f * (1.0f - darkFraction);

  return constrain(
      visibility,
      0.0f,
      1.0f);
}

// =============================================================
// QUALITY CHECK
// =============================================================

bool qualityGood() {

  if (currentBrightness <
      MIN_BRIGHTNESS) {

    lastDecision = "TOO_DARK";

    return false;
  }

  if (currentBrightness >
      MAX_BRIGHTNESS) {

    lastDecision = "TOO_BRIGHT";

    return false;
  }

  if (currentSharpness <
      MIN_SHARPNESS) {

    lastDecision = "LOW_SHARPNESS";

    return false;
  }

  return true;
}

// =============================================================
// BOARD CLEAR
// =============================================================

bool boardClear() {

  currentBoardVisibility =
      calculateBoardVisibility(
          currentImage);

  if (currentBoardVisibility <
      MIN_BOARD_VISIBILITY) {

    lastDecision =
        "OBSTRUCTION_DETECTED";

    return false;
  }

  return true;
}

// =============================================================
// WIFI
// =============================================================

void connectWiFi(bool blocking) {

  if (WiFi.status() ==
      WL_CONNECTED) {

    return;
  }

  WiFi.mode(WIFI_STA);

  WiFi.begin(
      WIFI_SSID,
      WIFI_PASSWORD);

  if (!blocking)
    return;

  Serial.printf(
      "Connecting to WiFi: %s\n",
      WIFI_SSID);

  for (int i = 0;
       i < 30 &&
       WiFi.status() != WL_CONNECTED;
       i++) {

    delay(500);

    Serial.print(".");
  }

  Serial.println();

  if (WiFi.status() ==
      WL_CONNECTED) {

    Serial.print(
        "ESP32 IP: ");

    Serial.println(
        WiFi.localIP());

    Serial.print(
        "RSSI: ");

    Serial.print(
        WiFi.RSSI());

    Serial.println(
        " dBm");

  } else {

    Serial.println(
        "WiFi connection failed.");
  }
}

// =============================================================
// UPLOAD TO LAPTOP
// =============================================================

bool uploadToLaptop(
    camera_fb_t* fb) {

  if (!fb ||
      WiFi.status() !=
          WL_CONNECTED) {

    Serial.println(
        "Upload skipped: WiFi unavailable.");

    return false;
  }

  HTTPClient http;

  WiFiClient client;

  http.setConnectTimeout(5000);

  http.setTimeout(15000);

  if (!http.begin(
          client,
          LAPTOP_SERVER)) {

    Serial.println(
        "HTTP begin failed.");

    return false;
  }

  http.addHeader(
      "Content-Type",
      "image/jpeg");

  http.addHeader(
      "X-Device",
      "ESP32-S3-EdgeBoard");

  http.addHeader(
      "X-Change-Score",
      String(
          currentChangeScore,
          4));

  http.addHeader(
      "X-Changed-Pixel-Ratio",
      String(
          currentChangedPixelRatio,
          4));

  http.addHeader(
      "X-Dark-Change-Ratio",
      String(
          currentDarkChangeRatio,
          4));

  http.addHeader(
      "X-Board-Visibility",
      String(
          currentBoardVisibility,
          4));

  http.addHeader(
      "X-Brightness",
      String(
          currentBrightness,
          2));

  http.addHeader(
      "X-Sharpness",
      String(
          currentSharpness,
          2));

  http.addHeader(
      "X-Stability-Score",
      String(
          currentStabilityScore,
          4));

  http.addHeader(
      "X-Timestamp",
      String(
          millis()));

  Serial.println(
      "Uploading image...");

  int code =
      http.POST(
          fb->buf,
          fb->len);

  Serial.printf(
      "Laptop response: %d (%s)\n",
      code,
      http.errorToString(code).c_str());

  http.end();

  return
      code >= 200 &&
      code < 300;
}

// =============================================================
// =============================================================
// MEANINGFUL CHANGE DETECTION (Condition 3)
// =============================================================

bool meaningfulChange() {

  // Hard minimum gate: If overall change is less than 4%, it is just camera noise / minor lighting shift.
  // NEVER send an image if change is tiny.
  if (currentChangeScore < 0.040f) {
    return false;
  }

  // Method 1: Substantial new/erased marker writing.
  // Both substantial pixel difference AND dark marker change must occur together.
  // This rejects tiny smudges, 1-character marks, and minor lighting noise.
  bool significantWriting =
      (currentChangedPixelRatio >= MIN_CHANGED_PIXEL_RATIO) &&
      (currentDarkChangeRatio >= DARK_CHANGE_RATIO);

  // Method 2: Major board wipe or complete redraw
  bool majorChange =
      (currentChangeScore >= CHANGE_THRESHOLD);

  return (significantWriting || majorChange);
}

// =============================================================
// PRINT DEBUG INFORMATION
// =============================================================

void printAnalysis() {

  Serial.print(
      "Change=");

  Serial.print(
      currentChangeScore,
      4);

  Serial.print(
      " | ChangedPixels=");

  Serial.print(
      currentChangedPixelRatio,
      4);

  Serial.print(
      " | DarkChange=");

  Serial.print(
      currentDarkChangeRatio,
      4);

  Serial.print(
      " | Stability=");

  Serial.print(
      currentStabilityScore,
      4);

  Serial.print(
      " | Visibility=");

  Serial.print(
      currentBoardVisibility,
      3);

  Serial.print(
      " | Brightness=");

  Serial.print(
      currentBrightness,
      1);

  Serial.print(
      " | Sharpness=");

  Serial.print(
      currentSharpness,
      1);

  Serial.print(
      " | Decision=");

  Serial.println(
      lastDecision);
}

// =============================================================
// SMART CAPTURE ENGINE
// =============================================================

void processFrame() {

  camera_fb_t* fb =
      esp_camera_fb_get();

  if (!fb) {

    rejectedFrames++;

    lastDecision =
        "CAMERA_ERROR";

    Serial.println(
        "Camera capture failed.");

    return;
  }

  processedFrames++;

  // -----------------------------------------------------------
  // Convert camera frame to analysis image
  // -----------------------------------------------------------

  if (!createAnalysisImage(
          fb,
          currentImage)) {

    rejectedFrames++;

    lastDecision =
        "ANALYSIS_ERROR";

    esp_camera_fb_return(fb);

    return;
  }

  // -----------------------------------------------------------
  // Calculate current quality
  // -----------------------------------------------------------

  currentBrightness =
      calculateBrightness(
          currentImage);

  currentSharpness =
      calculateSharpness(
          currentImage);

  currentBoardVisibility =
      calculateBoardVisibility(
          currentImage);

  // -----------------------------------------------------------
  // Basic quality
  // -----------------------------------------------------------

  if (!qualityGood()) {

    rejectedFrames++;

    memcpy(
        previousImage,
        currentImage,
        ANALYSIS_PIXELS);

    previousValid = true;

    boardStable = false;

    stableStart = 0;

    printAnalysis();

    esp_camera_fb_return(fb);

    return;
  }

  // -----------------------------------------------------------
  // First valid frame becomes reference
  // -----------------------------------------------------------

  if (!referenceValid) {

    memcpy(
        referenceImage,
        currentImage,
        ANALYSIS_PIXELS);

    memcpy(
        previousImage,
        currentImage,
        ANALYSIS_PIXELS);

    referenceValid = true;

    previousValid = true;

    currentChangeScore = 0.0f;

    currentChangedPixelRatio = 0.0f;

    currentDarkChangeRatio = 0.0f;

    currentStabilityScore = 0.0f;

    stableStart = millis();

    boardStable = false;

    lastDecision =
        "REFERENCE_CREATED";

    printAnalysis();

    esp_camera_fb_return(fb);

    return;
  }

  // -----------------------------------------------------------
  // Compare current frame with previous frame
  // -----------------------------------------------------------

  currentStabilityScore =
      previousValid
          ? calculateDifference(
                currentImage,
                previousImage)
          : 1.0f;

  // -----------------------------------------------------------
  // Compare current frame with LAST ACCEPTED frame
  // -----------------------------------------------------------

  currentChangeScore =
      calculateDifference(
          currentImage,
          referenceImage);

  currentChangedPixelRatio =
      calculateChangedPixelRatio(
          currentImage,
          referenceImage);

  currentDarkChangeRatio =
      calculateDarkChangeRatio(
          currentImage,
          referenceImage);

  // -----------------------------------------------------------
  // Stability
  // -----------------------------------------------------------

  if (currentStabilityScore <=
      STABILITY_THRESHOLD) {

    if (stableStart == 0) {

      stableStart =
          millis();
    }

    boardStable =
        (millis() -
         stableStart >=
         REQUIRED_STABLE_TIME);

  } else {

    stableStart = 0;

    boardStable = false;
  }

  // -----------------------------------------------------------
  // Update previous frame
  // -----------------------------------------------------------

  memcpy(
      previousImage,
      currentImage,
      ANALYSIS_PIXELS);

  previousValid = true;

  // -----------------------------------------------------------
  // Condition 1: Check stability (Teacher not writing)
  // -----------------------------------------------------------

  if (!boardStable) {

    lastDecision =
        "WAITING_STABLE (Teacher writing)";

    printAnalysis();

    esp_camera_fb_return(fb);

    return;
  }

  // -----------------------------------------------------------
  // Condition 2: Check board clear (No hand or object in front)
  // -----------------------------------------------------------

  if (!boardClear()) {

    rejectedFrames++;

    lastDecision =
        "OBSTRUCTION_DETECTED";

    printAnalysis();

    esp_camera_fb_return(fb);

    return;
  }

  // -----------------------------------------------------------
  // Condition 3: Check significant change (Ignore tiny changes)
  // -----------------------------------------------------------

  if (!meaningfulChange()) {

    lastDecision =
        "INSIGNIFICANT_CHANGE";

    printAnalysis();

    esp_camera_fb_return(fb);

    return;
  }

  // -----------------------------------------------------------
  // Cooldown
  // -----------------------------------------------------------

  if (millis() -
      lastCapture <
      CAPTURE_COOLDOWN) {

    lastDecision =
        "CAPTURE_COOLDOWN";

    printAnalysis();

    esp_camera_fb_return(fb);

    return;
  }

  // -----------------------------------------------------------
  // CAPTURE
  // -----------------------------------------------------------

  lastDecision =
      "UPLOADING";

  printAnalysis();

  ledOn();

  bool uploaded =
      uploadToLaptop(fb);

  ledOff();

  // -----------------------------------------------------------
  // SUCCESS
  // -----------------------------------------------------------

  if (uploaded) {

    capturedFrames++;

    lastCapture =
        millis();

    // VERY IMPORTANT:
    // Only update the reference after successful upload.

    memcpy(
        referenceImage,
        currentImage,
        ANALYSIS_PIXELS);

    // Reset stability timer so the same change
    // is not repeatedly uploaded.

    stableStart = 0;

    boardStable = false;

    lastDecision =
        "CAPTURED";

    Serial.println(
        ">>> IMAGE CAPTURED SUCCESSFULLY <<<");

  }

  // -----------------------------------------------------------
  // FAILURE
  // -----------------------------------------------------------

  else {

    rejectedFrames++;

    // Backoff cooldown to prevent rapid retry loops
    lastCapture = millis();

    // DO NOT update referenceImage.
    // This means the same change will be retried
    // on the next stable frame.

    lastDecision =
        "UPLOAD_FAILED";

    Serial.println(
        ">>> UPLOAD FAILED - WILL RETRY <<<");
  }

  printAnalysis();

  esp_camera_fb_return(fb);
}

// =============================================================
// JSON STATUS
// =============================================================

String jsonStatus() {

  String json = "{";

  json +=
      "\"decision\":\"" +
      lastDecision +
      "\",";

  json +=
      "\"change_score\":" +
      String(
          currentChangeScore,
          4) +
      ",";

  json +=
      "\"changed_pixel_ratio\":" +
      String(
          currentChangedPixelRatio,
          4) +
      ",";

  json +=
      "\"dark_change_ratio\":" +
      String(
          currentDarkChangeRatio,
          4) +
      ",";

  json +=
      "\"stability_score\":" +
      String(
          currentStabilityScore,
          4) +
      ",";

  json +=
      "\"board_visibility\":" +
      String(
          currentBoardVisibility,
          3) +
      ",";

  json +=
      "\"brightness\":" +
      String(
          currentBrightness,
          2) +
      ",";

  json +=
      "\"sharpness\":" +
      String(
          currentSharpness,
          2) +
      ",";

  json +=
      "\"stable\":" +
      String(
          boardStable
              ? "true"
              : "false") +
      ",";

  json +=
      "\"captured\":" +
      String(
          capturedFrames) +
      ",";

  json +=
      "\"rejected\":" +
      String(
          rejectedFrames) +
      ",";

  json +=
      "\"processed\":" +
      String(
          processedFrames) +
      ",";

  json +=
      "\"wifi_rssi\":" +
      String(
          WiFi.status() ==
                  WL_CONNECTED
              ? WiFi.RSSI()
              : 0);

  json += "}";

  return json;
}

// =============================================================
// ESP32 DASHBOARD
// =============================================================

void handleRoot() {

  String html = R"rawliteral(
<!doctype html>

<html>

<head>

<meta name="viewport"
content="width=device-width,initial-scale=1">

<title>EdgeBoard AI</title>

<style>

body{
font-family:Arial;
background:#10131a;
color:#eee;
margin:0;
padding:18px;
text-align:center
}

.card{
max-width:800px;
margin:12px auto;
background:#1b2130;
padding:18px;
border-radius:14px
}

.grid{
display:grid;
grid-template-columns:repeat(2,1fr);
gap:10px
}

.v{
font-size:20px;
font-weight:bold;
margin:6px
}

button{
padding:12px 20px;
border:0;
border-radius:8px;
margin:6px;
cursor:pointer
}

pre{
text-align:left;
white-space:pre-wrap
}

</style>

</head>

<body>

<h1>EdgeBoard AI</h1>

<p>ESP32-S3 Local Smart Capture</p>

<div class="card">

<h2 id="decision">
Loading...
</h2>

<div class="grid">

<div>
Change
<div class="v" id="change">-</div>
</div>

<div>
Changed Pixels
<div class="v" id="changedPixels">-</div>
</div>

<div>
Dark Change
<div class="v" id="darkChange">-</div>
</div>

<div>
Stability
<div class="v" id="stability">-</div>
</div>

<div>
Board Visibility
<div class="v" id="visibility">-</div>
</div>

<div>
Brightness
<div class="v" id="brightness">-</div>
</div>

<div>
Sharpness
<div class="v" id="sharpness">-</div>
</div>

<div>
Wi-Fi RSSI
<div class="v" id="rssi">-</div>
</div>

<div>
Accepted
<div class="v" id="captured">-</div>
</div>

<div>
Rejected
<div class="v" id="rejected">-</div>
</div>

</div>

</div>

<div class="card">

<p>Live Snapshot</p>

<img
id="snapshot"
style="max-width:100%;border-radius:10px"
src="/snapshot">

</div>

<div class="card">

<button onclick="manualCapture()">
Manual Capture
</button>

<button onclick="refresh()">
Refresh
</button>

</div>

<script>

async function refresh(){

try{

let r =
await fetch(
'/status?t=' +
Date.now()
);

let d =
await r.json();

document.getElementById(
'decision'
).textContent =
d.decision;

document.getElementById(
'change'
).textContent =
d.change_score;

document.getElementById(
'changedPixels'
).textContent =
(d.changed_pixel_ratio * 100)
.toFixed(2) + '%';

document.getElementById(
'darkChange'
).textContent =
(d.dark_change_ratio * 100)
.toFixed(2) + '%';

document.getElementById(
'stability'
).textContent =
d.stability_score;

document.getElementById(
'visibility'
).textContent =
d.board_visibility;

document.getElementById(
'brightness'
).textContent =
d.brightness;

document.getElementById(
'sharpness'
).textContent =
d.sharpness;

document.getElementById(
'rssi'
).textContent =
d.wifi_rssi + ' dBm';

document.getElementById(
'captured'
).textContent =
d.captured;

document.getElementById(
'rejected'
).textContent =
d.rejected;

document.getElementById(
'snapshot'
).src =
'/snapshot?t=' +
Date.now();

}

catch(e){

document.getElementById(
'decision'
).textContent =
'OFFLINE';

}

}

async function manualCapture(){

try{

let r =
await fetch(
'/capture',
{
method:'POST'
}
);

let d =
await r.json();

alert(
d.success
? 'Image uploaded successfully'
: 'Upload failed'
);

}

catch(e){

alert(
'Capture request failed'
);

}

}

setInterval(
refresh,
1200
);

refresh();

</script>

</body>

</html>
)rawliteral";

  server.send(
      200,
      "text/html",
      html);
}

// =============================================================
// STATUS
// =============================================================

void handleStatus() {

  server.send(
      200,
      "application/json",
      jsonStatus());
}

// =============================================================
// SNAPSHOT
// =============================================================

void handleSnapshot() {

  camera_fb_t* fb =
      esp_camera_fb_get();

  if (!fb) {

    server.send(
        500,
        "text/plain",
        "Camera capture failed");

    return;
  }

  WiFiClient client =
      server.client();

  client.print(
      "HTTP/1.1 200 OK\r\n"
      "Content-Type: image/jpeg\r\n"
      "Cache-Control: no-cache\r\n"
      "Content-Length: ");

  client.print(
      fb->len);

  client.print(
      "\r\n\r\n");

  client.write(
      fb->buf,
      fb->len);

  esp_camera_fb_return(fb);
}

// =============================================================
// MANUAL CAPTURE
// =============================================================

void handleManualCapture() {

  camera_fb_t* fb =
      esp_camera_fb_get();

  if (!fb) {

    server.send(
        500,
        "application/json",
        "{\"success\":false}");

    return;
  }

  bool ok =
      uploadToLaptop(fb);

  esp_camera_fb_return(fb);

  server.send(
      ok ? 200 : 502,
      "application/json",
      ok
          ? "{\"success\":true}"
          : "{\"success\":false}");
}

// =============================================================
// SETUP
// =============================================================

void setup() {

  Serial.begin(115200);

  delay(1500);

  pinMode(
      STATUS_LED,
      OUTPUT);

  ledOff();

  Serial.println(
      "\n========================================");

  Serial.println(
      "EDGEBOARD AI — ESP32-S3 + OV3660");

  Serial.println(
      "========================================");

  // -----------------------------------------------------------
  // PSRAM
  // -----------------------------------------------------------

  if (!psramFound()) {

    Serial.println(
        "WARNING: PSRAM not found.");

    Serial.println(
        "QVGA fallback will be used.");
  }

  // -----------------------------------------------------------
  // Buffers
  // -----------------------------------------------------------

  if (!allocateAnalysisBuffers()) {

    while (true) {

      blinkLED(
          3,
          150);

      delay(1000);
    }
  }

  // -----------------------------------------------------------
  // Camera
  // -----------------------------------------------------------

  if (!initCamera()) {

    while (true) {

      blinkLED(
          5,
          100);

      delay(1000);
    }
  }

  // -----------------------------------------------------------
  // Wi-Fi
  // -----------------------------------------------------------

  connectWiFi(true);

  // -----------------------------------------------------------
  // Web server
  // -----------------------------------------------------------

  server.on(
      "/",
      handleRoot);

  server.on(
      "/status",
      handleStatus);

  server.on(
      "/snapshot",
      handleSnapshot);

  server.on(
      "/capture",
      HTTP_POST,
      handleManualCapture);

  server.begin();

  Serial.println(
      "Web server started.");

  if (WiFi.status() ==
      WL_CONNECTED) {

    Serial.print(
        "Dashboard: http://");

    Serial.println(
        WiFi.localIP());

    Serial.print(
        "Snapshot : http://");

    Serial.print(
        WiFi.localIP());

    Serial.println(
        "/snapshot");

    Serial.print(
        "Capture  : http://");

    Serial.print(
        WiFi.localIP());

    Serial.println(
        "/capture");
  }

  Serial.println(
      "========================================");

  Serial.println(
      "EDGEBOARD READY");

  Serial.println(
      "========================================");
}

// =============================================================
// LOOP
// =============================================================

void loop() {

  // Web server
  server.handleClient();

  // Wi-Fi reconnect
  if (
      WiFi.status() !=
          WL_CONNECTED &&
      millis() -
          lastWiFiRetry >=
          WIFI_RETRY_INTERVAL) {

    lastWiFiRetry =
        millis();

    connectWiFi(false);
  }

  // Smart capture
  if (
      millis() -
          lastCheck >=
      CHECK_INTERVAL) {

    lastCheck =
        millis();

    processFrame();
  }

  delay(5);
}