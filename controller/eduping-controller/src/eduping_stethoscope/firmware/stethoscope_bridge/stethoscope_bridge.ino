// EduPing 청진기 FSR402 raw 송출.
// FSR402 분압 출력 → A0. 고정 레이트로 "F<raw>\n" (raw = analogRead, 0..1023) 출력.
// host(ROS fsr_bridge_node) 는 읽기 전용 — host→uno 명령 없음.

const int FSR_PIN = A0;
const unsigned long PERIOD_MS = 33;  // ~30Hz

unsigned long lastMs = 0;

void setup() {
  Serial.begin(115200);
}

void loop() {
  unsigned long now = millis();
  if (now - lastMs >= PERIOD_MS) {
    lastMs = now;
    int raw = analogRead(FSR_PIN);  // 0..1023
    Serial.print('F');
    Serial.println(raw);
  }
}
