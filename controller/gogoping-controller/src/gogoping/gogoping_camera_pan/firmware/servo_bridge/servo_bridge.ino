// servo_bridge.ino — Arduino Uno firmware for camera pan servo.
//
// Protocol (115200 baud, line-delimited):
//   host -> uno : "A:<deg>\n"   set servo angle (integer degrees)
//   uno  -> host: "OK:<deg>\n"  ack with applied angle
// Watchdog: if no command for WATCHDOG_MS, return to CENTER_DEG.

#include <Servo.h>

static const uint8_t  SERVO_PIN     = 9;
static const int      MIN_DEG       = 0;
static const int      MAX_DEG       = 180;
static const int      CENTER_DEG    = 90;
static const uint32_t WATCHDOG_MS   = 500;
static const uint32_t SERIAL_BAUD   = 115200;

Servo servo;
int currentDeg = CENTER_DEG;
uint32_t lastCmdMs = 0;
String buf;

void applyAngle(int deg) {
  if (deg < MIN_DEG) deg = MIN_DEG;
  if (deg > MAX_DEG) deg = MAX_DEG;
  servo.write(deg);
  currentDeg = deg;
  Serial.print("OK:");
  Serial.println(deg);
}

void setup() {
  Serial.begin(SERIAL_BAUD);
  servo.attach(SERVO_PIN);
  applyAngle(CENTER_DEG);
  lastCmdMs = millis();
}

void loop() {
  while (Serial.available() > 0) {
    char c = (char)Serial.read();
    if (c == '\n') {
      if (buf.startsWith("A:")) {
        int deg = buf.substring(2).toInt();
        applyAngle(deg);
        lastCmdMs = millis();
      }
      buf = "";
    } else if (c != '\r') {
      buf += c;
      if (buf.length() > 16) buf = "";
    }
  }

  if (millis() - lastCmdMs > WATCHDOG_MS && currentDeg != CENTER_DEG) {
    applyAngle(CENTER_DEG);
    lastCmdMs = millis();
  }
}
