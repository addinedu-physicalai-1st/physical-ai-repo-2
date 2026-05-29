/**
 * 근접 안전정지 모드별 우회 — 이 composable 을 쓰는 컴포넌트가 마운트되면 우회 ON,
 * 언마운트되면 OFF 를 control bridge 에 알린다.
 *
 * 우회 모드(원격진찰/건강검진/녹화 등)에서는 사람이 팔에 의도적으로 다가가므로 근접
 * 정지가 오히려 방해 → 해당 모드 진입 동안만 안전정지를 끈다. 무궁화도 우회 — 접근이
 * 게임 목표라 정지 대신 perception 노드의 reached 이벤트(게임 종료)로 처리한다. 나머지
 * (등원·하원·율동)는 안전 ON 유지.
 *
 * 엔드포인트: POST /api/eduping/arm/proximity-override {enabled}. control-service 가
 * bridge.set_proximity_override 호출. ROS 미가동 시 503/400 은 무시 (sim 머신 등).
 */
import { onBeforeUnmount, onMounted } from 'vue';

async function setOverride(enabled: boolean): Promise<void> {
  try {
    await fetch('/api/eduping/arm/proximity-override', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ enabled }),
    });
  } catch {
    /* 우회 설정 실패는 모드 진입을 막지 않음 */
  }
}

export function useProximityOverride(): void {
  onMounted(() => {
    void setOverride(true);
  });
  onBeforeUnmount(() => {
    void setOverride(false);
  });
}
