// servo_bridge.ino — Arduino Uno firmware for camera pan/tilt servos.
//
// Hardware:
//   D6 — pan  servo (좌우)         · 활성, 명령으로 제어
//   D3 — tilt servo (상하)         · 고정 (TILT_FIXED_DEG 로 setup 시 set, 동작 중 변경 X)
//
// Setup 초기 위치:
//   pan  → PAN_CENTER_DEG  (90)
//   tilt → TILT_FIXED_DEG  (120)
//
// Protocol (115200 baud, line-delimited):
//   host -> uno : "A:<deg>\n"   set pan servo angle (integer degrees, 0~180)
//   uno  -> host: "OK:<deg>\n"  ack with applied pan angle
// Watchdog: pan 명령이 WATCHDOG_MS 동안 없으면 PAN_CENTER_DEG 로 복귀.
//           (tilt 는 영향 없음 — 고정 유지)

#include <Servo.h>

static const uint8_t  PAN_PIN          = 6;    // D6 = pan (좌우)
static const uint8_t  TILT_PIN         = 3;    // D3 = tilt (상하, 고정)
static const int      PAN_MIN_DEG      = 0;
static const int      PAN_MAX_DEG      = 180;
static const int      PAN_CENTER_DEG   = 90;
static const int      TILT_FIXED_DEG   = 120;
static const uint32_t WATCHDOG_MS      = 500;
static const uint32_t SERIAL_BAUD      = 115200;

Servo pan;
Servo tilt;
int panDeg = PAN_CENTER_DEG;
uint32_t lastCmdMs = 0;
String buf;

void applyPan(int deg) {
  if (deg < PAN_MIN_DEG) deg = PAN_MIN_DEG;
  if (deg > PAN_MAX_DEG) deg = PAN_MAX_DEG;
  pan.write(deg);
  panDeg = deg;
  Serial.print("OK:");
  Serial.println(deg);
}

void setup() {
  Serial.begin(SERIAL_BAUD);
  pan.attach(PAN_PIN);
  tilt.attach(TILT_PIN);
  pan.write(PAN_CENTER_DEG);
  tilt.write(TILT_FIXED_DEG);
  panDeg = PAN_CENTER_DEG;
  lastCmdMs = millis();
}

void loop() {
  while (Serial.available() > 0) {
    char c = (char)Serial.read();
    if (c == '\n') {
      if (buf.startsWith("A:")) {
        int deg = buf.substring(2).toInt();
        applyPan(deg);
        lastCmdMs = millis();
      }
      buf = "";
    } else if (c != '\r') {
      buf += c;
      if (buf.length() > 16) buf = "";
    }
  }

  if (millis() - lastCmdMs > WATCHDOG_MS && panDeg != PAN_CENTER_DEG) {
    applyPan(PAN_CENTER_DEG);
    lastCmdMs = millis();
  }
}
