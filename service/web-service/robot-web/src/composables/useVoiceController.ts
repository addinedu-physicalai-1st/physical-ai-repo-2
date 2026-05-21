/**
 * 음성 컨트롤러 — WebRTC 단일화 후.
 *
 * 책임:
 *  - 호출어 ONNX (`useWakeWord`) 콜백 처리: 서버 gate 열기 + outbound buffer 비움 (barge-in).
 *  - WebRTC DataChannel 메시지 수신 (`stt_final` / `intent` / `tts_start` / `tts_end`)
 *    으로 voice state machine 구동.
 *  - 의도 응답 (goto_vertex / sub_command return) 의 navigate API 호출 + 결과 멘트
 *    를 서버에 `speak` DC msg 로 요청.
 *  - 외부에서 `speak(text)` / `processCommand(text)` API 제공.
 *
 * State machine:
 *   idle → wake_detected → listening → dispatching → speaking → cooldown → idle
 *
 * 제거된 구조 (WebRTC 가 대체):
 *   - useServerSTT (MediaRecorder + multipart upload).
 *   - useTTS 의 speak/streaming MP3 (server outbound track 이 대체).
 *   - useIntentDispatch.dispatchIntent 클라 HTTP 호출 (서버가 stt_final 후 직접 처리).
 *   - echo guard / refresh / wakeAckInProgress 등 가드 flag 다수 (단일 PC + 서버 gate
 *     로 흐름이 깨끗해 불필요).
 */
import { type Ref } from 'vue';
import { type RobotConfig, type EmotionId } from '@/config/robots';
import { isEmotionId } from '@/config/emotions';
import { useTTS } from './useTTS';
import { useWakeWord } from './useWakeWord';
import { useWebRTCVoice, LOG_VOICE_DEBUG } from './useWebRTCVoice';
import { useVoiceStore } from '@/stores/voice';
import { useModeStore } from '@/stores/mode';
import type { IntentResponse } from './useIntentDispatch';

// ONNX wake 분류기 점수 임계값 — cycle 6 evaluate.py 측정값.
const WAKE_THRESHOLDS: Record<string, number> = {
  eduping: 0.99,
  gogoping: 0.99,
  noriarm: 0.99,
};

// 호출어 사이클 효과음 — listening 시작/종료 신호. Ubuntu Yaru sound theme
// (bell.oga / complete.oga, CC-BY-SA-4.0) 를 mp3 로 변환해 번들.
// 로컬 재생이라 AEC 미적용이지만 비음성·1초 미만이라 VAD 가 발화로 분류할 가능성 낮고,
// OFF 는 gate 가 이미 닫힌 cooldown 진입 시 울려 오탐 dispatch 위험 없음.
const wakeOnSound = new Audio('/sounds/wake_on.mp3');
const wakeOffSound = new Audio('/sounds/wake_off.mp3');
wakeOnSound.preload = 'auto';
wakeOffSound.preload = 'auto';

function playChime(el: HTMLAudioElement): void {
  try {
    el.currentTime = 0;
    void el.play().catch(() => { /* autoplay/cleanup race — 무시 */ });
  } catch { /* noop */ }
}

// 명령 처리 후 잠시 쉬는 cooldown — UI / wake guard 둘 다 쉬는 시간.
const COOLDOWN_MS = 1500;
// listening window — wake 직후 사용자가 명령을 시작하지 않으면 cooldown 으로 복귀.
// 서버측 gate timeout (6s) 와 정렬.
const LISTENING_WINDOW_MS = 6000;

interface DcMsg {
  type: string;
  [k: string]: unknown;
}

export function useVoiceController(robot: RobotConfig): {
  start: () => void;
  stop: () => void;
  /** voiceMode 토글용 — PC/DC 살려둔 채 mic + wake 만 on/off. */
  setMicActive: (active: boolean) => void;
  /** 텍스트 명령 (CommandBar 타이핑) — wake gate 우회, 서버에 dispatch_text 송신. */
  processCommand: (text: string) => void;
  /** 외부에서 임의 발화 요청 — 서버에 speak DC msg 송신 (TTS outbound 로 재생). */
  speak: (text: string) => void;
  /** 진행 중 server TTS outbound buffer 비움 + 클라 lip-sync detach. */
  cancelSpeak: () => void;
  /** SiriBlob 시각화용 mic level. */
  micLevel: Ref<number>;
} {
  const voice = useVoiceStore();
  const mode = useModeStore();

  let listeningTimer: number | null = null;
  let cooldownTimer: number | null = null;
  let lipsyncDetach: (() => void) | null = null;
  let pendingEmotion: EmotionId | null = null;

  const tts = useTTS();

  const webrtcVoice = useWebRTCVoice({
    robot: robot.id,
    onMessage: (msg) => handleDcMessage(msg as DcMsg),
    onError: (m) => voice.setError(m),
  });

  function clearListeningTimer(): void {
    if (listeningTimer !== null) {
      window.clearTimeout(listeningTimer);
      listeningTimer = null;
    }
  }

  function armListeningTimer(): void {
    clearListeningTimer();
    listeningTimer = window.setTimeout(() => {
      listeningTimer = null;
      enterCooldown();
    }, LISTENING_WINDOW_MS);
  }

  function clearCooldownTimer(): void {
    if (cooldownTimer !== null) {
      window.clearTimeout(cooldownTimer);
      cooldownTimer = null;
    }
  }

  function enterCooldown(): void {
    playChime(wakeOffSound);
    voice.setState('cooldown');
    clearCooldownTimer();
    cooldownTimer = window.setTimeout(() => {
      voice.setState('idle');
      cooldownTimer = null;
    }, COOLDOWN_MS);
  }

  function baseEmotionForCurrentMode(): EmotionId {
    return mode.robot.defaultEmotionByMode[mode.currentMode] ?? 'basic';
  }

  /** 호출어 ONNX 감지 → 서버 gate 즉시 열기. 호출어 단독 발화는 서버 STT 후
   *  WakeNameHandler 가 "네" chat reply 로 처리 → 서버 outbound TTS 로 응답.
   *  - 연속 발화 ("에듀핑인사해") 시 사용자 명령 캡처 가능.
   *  - speaking 상태 (로봇이 응답 TTS 중) 에서 wake 발화 시 진행 중 TTS 끊고 새 사이클.
   *    (서버 wake handler 가 outbound buffer clear)
   */
  function onWakeDetected(): void {
    if (voice.state !== 'idle' && voice.state !== 'speaking') return;
    clearListeningTimer();
    clearCooldownTimer();
    // 진행 중 lipsync 있으면 detach (speaking 도중 wake 시 입 모양 잔재 제거).
    lipsyncDetach?.();
    lipsyncDetach = null;
    pendingEmotion = null;
    voice.setRobotReply('');
    voice.setSttText('');
    voice.setSpeaking(false);
    voice.setState('wake_detected');
    voice.bumpWake();
    mode.setEmotionTransient('hello', 1000);
    // 서버에 wake msg → 서버가 (a) gate 열고 (b) outbound 버퍼 비움 (barge-in).
    webrtcVoice.send({ type: 'wake', robot: robot.id });
    playChime(wakeOnSound);
    voice.setState('listening');
    armListeningTimer();
  }

  const wakeWord = useWakeWord({
    robotIds: [robot.id],
    thresholds: { [robot.id]: WAKE_THRESHOLDS[robot.id] ?? 0.99 },
    cooldownMs: 2500,
    // PC connected + (idle OR speaking) 일 때 추론. speaking 도중 허용해서 mid-TTS
    // barge-in 가능. listening/dispatching/wake_detected/cooldown 동안은 skip.
    isEnabled: () =>
      webrtcVoice.isConnected.value &&
      (voice.state === 'idle' || voice.state === 'speaking'),
    onWake: () => {
      try { onWakeDetected(); } catch (e) { voice.setError((e as Error).message); }
    },
    onScore: LOG_VOICE_DEBUG ? (s) => { console.log('[wake]', s); } : undefined,
    onError: (m) => voice.setError(`wake: ${m}`),
  });

  function handleDcMessage(msg: DcMsg): void {
    switch (msg.type) {
      case 'stt_final':
        onSttFinal(String(msg.text ?? ''));
        break;
      case 'intent':
        onIntent(intentFromMsg(msg));
        break;
      case 'tts_start':
        onTtsStart(String(msg.text ?? ''), Number(msg.duration_ms ?? 0));
        break;
      case 'tts_end':
        onTtsEnd();
        break;
      default:
        break;
    }
  }

  function intentFromMsg(msg: DcMsg): IntentResponse {
    const copy = { ...msg } as Record<string, unknown>;
    delete copy.type;
    return copy as unknown as IntentResponse;
  }

  function onSttFinal(text: string): void {
    const trimmed = text.trim();
    if (!trimmed) {
      enterCooldown();
      return;
    }
    clearListeningTimer();
    voice.setSttText(trimmed);
    voice.setLastSpokenText(trimmed);
    voice.setState('dispatching');
  }

  function onIntent(intent: IntentResponse): void {
    mode.applyIntent(intent);
    if (intent.kind === 'chat') {
      pendingEmotion = isEmotionId(intent.emotion) ? intent.emotion : 'basic';
      voice.setRobotReply(intent.reply);
      // TTS audio + tts_start 가 곧 도착 → onTtsStart 가 speaking 전이.
    } else if (intent.kind === 'goto_vertex') {
      void handleGotoVertex(intent.name);
    } else if (intent.kind === 'sub_command') {
      if (intent.action === 'return') void handleReturn();
      else if (intent.action === 'stop') void handleStop();
      // mode.applyIntent 가 proximityHalt 도 함께 처리 (안전망).
      enterCooldown();
    } else if (intent.kind === 'mode_change') {
      // mode.applyIntent 가 setMode 처리. useModeAnnouncer 가 모드 안내 발화 트리거.
      enterCooldown();
    } else {
      enterCooldown();
    }
  }

  async function handleGotoVertex(name: string): Promise<void> {
    if (!name) {
      enterCooldown();
      return;
    }
    let confirmation = '';
    try {
      // ASSIST/goto 진입 — Control 의 /api/gogoping/goto_vertex 호출.
      // SetGoal.srv → FSM trigger 경로라 robot 이동 + state ASSIST 전이 둘 다 발생.
      // (직접 graph_router action 호출인 /waypoints/navigate 는 FSM 우회 — admin 디버그 전용.)
      const r = await fetch('/api/gogoping/goto_vertex', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name }),
      });
      confirmation = r.ok ? `${name}으로 갈게요` : `${name}을(를) 찾지 못했어요`;
    } catch {
      confirmation = '지금은 이동할 수 없어요';
    }
    speak(confirmation);
  }

  async function handleStop(): Promise<void> {
    // "그만"/"멈춰"/"정지"/"스톱" → 현재 mode 중단 + IDLE 전이. mode_to_goal("대기")
    // 가 Goal(mode="IDLE") 로 변환 → command_listener 가 FSM cancel trigger 발사 →
    // ASSIST/PLAY/MANUAL/RETURNING 어느 상태든 IDLE 복귀. 자장가/이동/추종/숨바꼭질
    // 모두 동일 경로. gogoping 외 robot 은 stop 의미가 다르므로 skip (proximityHalt 만).
    if (robot.id !== 'gogoping') return;
    // 이미 대기 중이면 fetch 자체 skip — FSM cancel trigger 가 IDLE 에선 미정의라
    // 항상 거부되는데, 그때마다 "멈출 수 없어요" 안내가 어색하므로 응답만 자연스럽게.
    if (mode.currentMode === '대기') {
      speak('이미 쉬고 있어요');
      return;
    }
    let confirmation = '';
    try {
      const r = await fetch('/api/gogoping/mode', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ robot: 'gogoping', mode: '대기' }),
      });
      confirmation = r.ok ? '네, 멈출게요' : '지금은 멈출 수 없어요';
    } catch {
      confirmation = '지금은 멈출 수 없어요';
    }
    speak(confirmation);
  }

  async function handleReturn(): Promise<void> {
    let confirmation = '';
    try {
      // 복귀 = FSM RETURNING 진입 (BT_return_sub 가 충전소까지 lane 따라 이동 + 도킹).
      // /api/gogoping/mode 로 한국어 라벨 "복귀" → mode_to_goal → Goal(mode="RETURNING")
      // → SetGoal.srv → command_listener → fsm.trigger("return_request").
      const r = await fetch('/api/gogoping/mode', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ robot: 'gogoping', mode: '복귀' }),
      });
      confirmation = r.ok ? '충전소로 갈게요' : '지금은 복귀할 수 없어요';
    } catch {
      confirmation = '지금은 복귀할 수 없어요';
    }
    speak(confirmation);
  }

  function onTtsStart(text: string, durationMs: number): void {
    voice.setState('speaking');
    if (pendingEmotion) {
      mode.currentEmotion = pendingEmotion;
    }
    const stream = webrtcVoice.remoteStream.value;
    if (stream && text) {
      lipsyncDetach?.();
      lipsyncDetach = tts.attachRemoteLipSync(stream, text, durationMs);
    }
  }

  function onTtsEnd(): void {
    lipsyncDetach?.();
    lipsyncDetach = null;
    pendingEmotion = null;
    mode.currentEmotion = baseEmotionForCurrentMode();
    voice.setRobotReply('');
    enterCooldown();
  }

  /** 외부에서 호출 — 서버에 speak DC msg. 즉시 반환, audio 는 tts_start 도착 시 재생 시작. */
  function speak(text: string): void {
    const trimmed = text.trim();
    if (!trimmed) return;
    webrtcVoice.send({ type: 'speak', text: trimmed });
  }

  /** 진행 중인 server TTS 의 outbound buffer 비움 + 클라 lip-sync detach. */
  function cancelSpeak(): void {
    webrtcVoice.send({ type: 'tts_cancel' });
    lipsyncDetach?.();
    lipsyncDetach = null;
  }

  /** CommandBar 타이핑 — wake 없이 서버 dispatch 사이클 시작. */
  function processCommand(text: string): void {
    const trimmed = text.trim();
    if (!trimmed) return;
    clearListeningTimer();
    clearCooldownTimer();
    voice.setSttText(trimmed);
    voice.setLastSpokenText(trimmed);
    voice.setState('dispatching');
    webrtcVoice.send({ type: 'dispatch_text', text: trimmed });
  }

  function start(): void {
    void webrtcVoice.start().catch((e) => {
      voice.setError(`webrtc start failed: ${(e as Error).message}`);
    });
    void wakeWord.start().catch((e) => {
      voice.setError(`wake start failed: ${(e as Error).message}`);
    });
  }

  function stop(): void {
    void wakeWord.stop();
    webrtcVoice.stop();
    tts.cancel();
    lipsyncDetach?.();
    lipsyncDetach = null;
    clearListeningTimer();
    clearCooldownTimer();
    pendingEmotion = null;
    voice.setSttText('');
    voice.setRobotReply('');
    voice.setInputLocked(false);
    voice.setSpeaking(false);
    voice.setState('idle');
  }

  /** 모드 전환용 — WebRTC PC/DC 는 살려두고 mic 캡처와 wake word 만 토글.
   * 텍스트 모드에서는 사용자 발화가 들어가면 안 되지만 dispatch DC 는 필요. */
  function setMicActive(active: boolean): void {
    webrtcVoice.setMicEnabled(active);
    if (active) {
      void wakeWord.start().catch((e) => {
        voice.setError(`wake start failed: ${(e as Error).message}`);
      });
    } else {
      void wakeWord.stop();
    }
  }

  return {
    start,
    stop,
    setMicActive,
    processCommand,
    speak,
    cancelSpeak,
    micLevel: webrtcVoice.micLevel,
  };
}

export type VoiceController = ReturnType<typeof useVoiceController>;
