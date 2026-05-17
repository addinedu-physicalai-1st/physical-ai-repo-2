// servo_bridge.ino — Arduino Uno firmware for 2-axis camera pan/tilt (MG995 x2).
//
// Protocol (115200 baud, line-delimited):
//   host -> uno : "PT:<pan_deg>,<tilt_deg>\n"   set both servo angles (integers)
//   uno  -> host: "OK:<pan>,<tilt>\n"           ack with applied angles
// Watchdog: if no command for WATCHDOG_MS, return to (CENTER_PAN, CENTER_TILT).
//
// MG995 power: must be powered from external 5–6V supply (≥1A). Arduino 5V
// pin cannot source MG995 stall current. Common GND with Arduino is required.

#include <Servo.h>

static const uint8_t  PAN_PIN       = 9;
static const uint8_t  TILT_PIN      = 10;
static const int      PAN_MIN       = 5;
static const int      PAN_MAX       = 175;
static const int      TILT_MIN      = 30;
static const int      TILT_MAX      = 150;
static const int      CENTER_PAN    = 90;
static const int      CENTER_TILT   = 90;
static const uint32_t WATCHDOG_MS   = 1000;
static const uint32_t SERIAL_BAUD   = 115200;

Servo panServo;
Servo tiltServo;
int currentPan  = CENTER_PAN;
int currentTilt = CENTER_TILT;
uint32_t lastCmdMs = 0;
String buf;

int clampInt(int v, int lo, int hi) {
  if (v < lo) return lo;
  if (v > hi) return hi;
  return v;
}

void applyAngles(int pan, int tilt) {
  pan  = clampInt(pan,  PAN_MIN,  PAN_MAX);
  tilt = clampInt(tilt, TILT_MIN, TILT_MAX);
  panServo.write(pan);
  tiltServo.write(tilt);
  currentPan  = pan;
  currentTilt = tilt;
  Serial.print("OK:");
  Serial.print(pan);
  Serial.print(',');
  Serial.println(tilt);
}

void setup() {
  Serial.begin(SERIAL_BAUD);
  panServo.attach(PAN_PIN);
  tiltServo.attach(TILT_PIN);
  applyAngles(CENTER_PAN, CENTER_TILT);
  lastCmdMs = millis();
}

void handleLine() {
  if (!buf.startsWith("PT:")) return;
  int comma = buf.indexOf(',', 3);
  if (comma < 0) return;
  int pan  = buf.substring(3, comma).toInt();
  int tilt = buf.substring(comma + 1).toInt();
  applyAngles(pan, tilt);
  lastCmdMs = millis();
}

void loop() {
  while (Serial.available() > 0) {
    char c = (char)Serial.read();
    if (c == '\n') {
      handleLine();
      buf = "";
    } else if (c != '\r') {
      buf += c;
      if (buf.length() > 24) buf = "";
    }
  }

  if (millis() - lastCmdMs > WATCHDOG_MS &&
      (currentPan != CENTER_PAN || currentTilt != CENTER_TILT)) {
    applyAngles(CENTER_PAN, CENTER_TILT);
    lastCmdMs = millis();
  }
}
