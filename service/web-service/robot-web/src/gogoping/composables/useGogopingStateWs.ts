/**
 * GogoPing BT snapshot WS 구독 — admin UI 또는 다른 client 가 BT mode 를 바꿨을 때
 * robot-web 의 mode store 가 자동으로 따라가게 한다.
 *
 * 흐름:
 *   admin UI / BT 외부 source → mode 변경 → BT FSM 변경 → 1Hz snapshot publish
 *   → control-service /ws/robot-state fan-out → 본 composable 수신
 *   → snapshotToModeLabel(snap) 매핑 → mode.setMode(label)
 *
 * 무한 루프 회피: mode.setMode 는 store 만 갱신, postModeClick 발동 안 함.
 * robot-web 자체 click / voice 경로만 postModeClick 호출. BT 진실 소스 패턴.
 *
 * 사용: App.vue 에서 `robot.value.id === 'gogoping'` 일 때만 호출.
 */
import { onBeforeUnmount } from 'vue';
import { useModeStore } from '@/stores/mode';

interface GogopingSnapshot {
  robot_id?: string;
  fsm_state?: string;
  // 평탄화 (2026-05-25): assist_task / play_task 필드 제거. fsm_state 자체가 task.
  // 그 외 필드는 본 composable 에서 사용 안 함 (main_tree / sub_tree / battery_level 등)
}

/**
 * snapshot 의 fsm_state → robot-web 의 한국어 mode 라벨 매핑.
 * 매핑 불가 (예: ERROR) 면 null.
 */
function snapshotToModeLabel(snap: GogopingSnapshot): string | null {
  const fsm = snap.fsm_state ?? '';
  switch (fsm) {
    case 'IDLE':
    case 'CHARGING':            return '대기';
    case 'MANUAL':              return '수동';
    case 'RETURNING':
    case 'LOW_BATTERY_RETURNING':  return '복귀';
    case 'GOTO':                return '이동';
    case 'FOLLOW':              return '추종';
    case 'LULLABY':             return '자장가';
    case 'HIDEANDSEEK':         return '숨바꼭질';
    default:                    return null;  // ERROR / 알 수 없는 state — mode 변경 안 함
  }
}

export function useGogopingStateWs(): { stop: () => void } {
  const mode = useModeStore();

  const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws';
  const url = `${protocol}://${window.location.host}/ws/robot-state`;

  let ws: WebSocket | null = null;
  let reconnectTimer: number | null = null;
  let stopped = false;

  function connect(): void {
    if (stopped) return;
    ws = new WebSocket(url);

    ws.onmessage = (ev) => {
      try {
        const snap = JSON.parse(ev.data) as GogopingSnapshot;
        if (snap.robot_id && snap.robot_id !== 'gogoping') return;
        const label = snapshotToModeLabel(snap);
        if (label && label !== mode.currentMode) {
          // 추종 모드 진행 중인데 BT 가 아직 IDLE snapshot (FOLLOW 진입 전) 이면
          // mode 를 '대기' 로 강제 전이하지 않음 — 인증 모달이 사라지는 race 차단.
          // 사용자 명시적 정지 / 다른 모드 선택은 별도 경로 (정지 버튼, 메뉴 click) 로 처리.
          if (mode.currentMode === '추종' && label === '대기') return;
          mode.setMode(label);  // postModeClick 발동 안 함 — 무한루프 회피
        }
      } catch {
        // JSON 파싱 실패는 무시 (서버 측 포맷 변경 등 — 다음 메시지에서 회복)
      }
    };

    ws.onclose = () => {
      ws = null;
      if (stopped) return;
      // 1초 후 재연결
      reconnectTimer = window.setTimeout(connect, 1000);
    };

    ws.onerror = () => {
      // close 가 이어서 호출됨 — 별도 처리 불필요
    };
  }

  connect();

  function stop(): void {
    stopped = true;
    if (reconnectTimer !== null) {
      window.clearTimeout(reconnectTimer);
      reconnectTimer = null;
    }
    if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) {
      ws.close();
    }
    ws = null;
  }

  onBeforeUnmount(stop);

  return { stop };
}
