/**
 * 모드별 intent handler 등록 — Vue 컴포넌트가 mount 시 호출해 자기 mode 의
 * 도메인 동작 (곡 재생, 게임 종료 등) 을 useVoiceController 에 위임한다.
 *
 * 사용 예 (DancePlayPopup):
 *   useModeIntents('율동', {
 *     onRhythmPlay: ({ displayName }) => ...,
 *     onRhythmStop: () => ...,
 *     onModeExit: () => mode.setMode('대기'),
 *   });
 *
 * onMounted 시 registry 에 등록, onUnmounted 시 자동 제거. 같은 modeId 로 두
 * 컴포넌트가 등록되면 마지막 mount 가 우선 (LIFO). useVoiceController 가 intent
 * 받으면 currently active mode entry 의 handler 호출.
 */
import { onBeforeUnmount, onMounted } from 'vue';

export interface ModeIntentHandlers {
  /** mode 안 자유발화로 인식된 곡 선택 — rhythm_play intent. */
  onRhythmPlay?: (data: { displayName: string }) => void;
  /** mode 안 음악 정지 — rhythm_stop intent ('노래 그만' 같은 한정어 stop). */
  onRhythmStop?: () => void;
  /** mode 종료 요청 — sub_command(stop) 또는 mode_change('대기') 통합.
   *  미정의 시 framework default = mode.setMode('대기'). 컴포넌트가
   *  override 하면 default 가 일어나지 않음 (예: confirm popup 후 처리). */
  onModeExit?: () => void;
}

interface ModeEntry {
  modeId: string;
  handlers: ModeIntentHandlers;
}

const _registry: ModeEntry[] = [];

export function useModeIntents(modeId: string, handlers: ModeIntentHandlers): void {
  const entry: ModeEntry = { modeId, handlers };
  onMounted(() => {
    _registry.push(entry);
  });
  onBeforeUnmount(() => {
    const idx = _registry.lastIndexOf(entry);
    if (idx >= 0) _registry.splice(idx, 1);
  });
}

/** useVoiceController 가 호출 — 현재 mode 와 일치하는 가장 최근 등록 entry 의
 *  handlers 반환. 없으면 null. */
export function getActiveModeHandlers(modeId: string): ModeIntentHandlers | null {
  for (let i = _registry.length - 1; i >= 0; i--) {
    if (_registry[i].modeId === modeId) return _registry[i].handlers;
  }
  return null;
}
