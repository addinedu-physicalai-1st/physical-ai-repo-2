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
import { watch, type Ref } from 'vue';
import { type RobotConfig, type EmotionId } from '@/config/robots';
import { isEmotionId } from '@/config/emotions';
import { useTTS } from './useTTS';
import { useWakeWord } from './useWakeWord';
import { useWebRTCVoice } from './useWebRTCVoice';
import { useVoiceStore, type ConfirmRequest } from '@/stores/voice';
import { useModeStore } from '@/stores/mode';
import type { IntentResponse } from './useIntentDispatch';
import { getActiveModeHandlers } from './useModeIntents';

// wake 분류기 default threshold. `?th=0.85` 로 override.
const WAKE_DEFAULT_THRESHOLD = 0.9;

function readWakeThreshold(): number {
  if (typeof window === 'undefined') return WAKE_DEFAULT_THRESHOLD;
  const thStr = new URLSearchParams(window.location.search).get('th');
  const parsed = thStr ? Number(thStr) : Number.NaN;
  return Number.isFinite(parsed) && parsed > 0 && parsed < 1 ? parsed : WAKE_DEFAULT_THRESHOLD;
}

function readDebug(): boolean {
  if (typeof window === 'undefined') return false;
  return new URLSearchParams(window.location.search).get('debug') === '1';
}

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
  /** 호출어 없이 wake gate 강제 open — TTS 로 사용자에게 질문한 직후
   *  답 받기 위해 사용. server 가 GATE_OPEN_TIMEOUT_S 후 자동 close. */
  forceWake: () => void;
  /** SiriBlob 시각화용 mic level. */
  micLevel: Ref<number>;
  /** `?debug=1` 일 때 wake score overlay 용. robot id → 직전 inference score. */
  wakeScores: Ref<Record<string, number>>;
  /** wake threshold (정상 fire 기준). overlay 색칠용. */
  wakeThreshold: number;
  /** 확인 사이클 시작 — TTS prompt 발화 + wake gate 자동 open + server
   *  awaiting_confirm sync. server 가 confirm_yes/no intent 로 답변 분류해
   *  돌려보내면 저장된 callback 실행. */
  startConfirm: (opts: ConfirmRequest) => void;
  /** `?debug=1` 활성 여부. */
  debug: boolean;
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

  // 현재 모드 → 서버 동기화. ai-service /voice/intent 의 컨텍스트 인지 핸들러
  // (예: 율동 안 '노래 그만' → rhythm_stop) 가 mode hint 를 받음.
  watch(
    () => mode.currentMode,
    (current, prev) => {
      console.log(`[voice][mode] ${prev} → ${current} (connected=${webrtcVoice.isConnected.value})`);
      if (!webrtcVoice.isConnected.value) return;
      webrtcVoice.send({ type: 'mode_set', mode: current });
    },
    { immediate: true },
  );
  // DC open 직후에도 한번 — webrtc start 가 mount 후 비동기라 위 watch 가 fire
  // 시점에 dc.readyState 가 connecting 일 수 있음.
  watch(webrtcVoice.isConnected, (connected) => {
    if (connected) {
      webrtcVoice.send({ type: 'mode_set', mode: mode.currentMode });
      webrtcVoice.send({ type: 'awaiting_confirm_set', awaiting: voice.confirm !== null });
      webrtcVoice.send({ type: 'stt_hints_set', keywords: voice.sttHints });
    }
  });

  // confirm 사이클 ↔ 서버 동기화. ConfirmHandler 가 이 hint 일 때만 활성.
  watch(
    () => voice.confirm,
    (c) => {
      if (!webrtcVoice.isConnected.value) return;
      webrtcVoice.send({ type: 'awaiting_confirm_set', awaiting: c !== null });
    },
  );

  // STT initial_prompt 에 mode/stage/library 의 expected 단어 동적 주입 —
  // Whisper 가 짧은 한국어 발화의 후보를 좁힘.
  watch(
    () => voice.sttHints,
    (kws) => {
      if (!webrtcVoice.isConnected.value) return;
      webrtcVoice.send({ type: 'stt_hints_set', keywords: kws });
    },
    { deep: true },
  );

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
      playChime(wakeOffSound);
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
    // wake_off 효과음은 호출자 (armListeningTimer 타임아웃 / onSttFinal) 가 직접
    // 재생 — listening → cooldown 전이일 때만 울리고, TTS 종료나 intent 처리 후
    // 진입은 사람 발화 감지와 무관하므로 무음.
    voice.setState('cooldown');
    clearCooldownTimer();
    cooldownTimer = window.setTimeout(() => {
      cooldownTimer = null;
      // cooldown 중 onTtsStart 가 state 를 'speaking' 으로 옮겼을 수 있다.
      // 그 경우 idle 로 덮어쓰면 진행 중 TTS 가 잘리고 외부 watch (예:
      // DancePlayPopup) 가 speaking→idle 전이로 오인해 wake gate 를 강제로 열어
      // server outbound TTS 가 비워진다. cooldown 상태일 때만 idle 로 전이.
      if (voice.state === 'cooldown') voice.setState('idle');
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

  const wakeThreshold = readWakeThreshold();
  const debug = readDebug();
  const wakeWord = useWakeWord({
    robotIds: [robot.id],
    thresholds: { [robot.id]: wakeThreshold },
    cooldownMs: 2500,
    // PC connected + (idle OR speaking) 일 때 추론. speaking 도중 허용해서 mid-TTS
    // barge-in 가능. listening/dispatching/wake_detected/cooldown 동안은 skip.
    isEnabled: () =>
      webrtcVoice.isConnected.value &&
      (voice.state === 'idle' || voice.state === 'speaking'),
    onWake: () => {
      try { onWakeDetected(); } catch (e) { voice.setError((e as Error).message); }
    },
    onError: (m) => voice.setError(`wake: ${m}`),
  });

  function handleDcMessage(msg: DcMsg): void {
    if (msg.type === 'stt_final' || msg.type === 'intent' || msg.type === 'tts_start' || msg.type === 'tts_end') {
      console.log(`[voice][${msg.type}] state=${voice.state} mode=${mode.currentMode} awaiting=${voice.confirm !== null}`, msg);
    }
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
    // STT 결과 도착 = 사람 발화 감지 종료. text 유무와 무관하게 wake_off 효과음.
    if (voice.state === 'listening') playChime(wakeOffSound);
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
    const handlers = getActiveModeHandlers(mode.currentMode);

    if (intent.kind === 'chat') {
      pendingEmotion = isEmotionId(intent.emotion) ? intent.emotion : 'basic';
      voice.setRobotReply(intent.reply);
      return;  // tts_start 도착 시 onTtsStart 가 speaking 으로 전이
    }
    if (intent.kind === 'goto_vertex') {
      void handleGotoVertex(intent.name);
      return;
    }
    if (intent.kind === 'sub_command') {
      if (intent.action === 'return') { void handleReturn(); enterCooldown(); return; }
      if (intent.action === 'start') {
        // 현재 mode 컴포넌트의 onStart handler 호출. 없으면 ignored.
        handlers?.onStart?.();
        enterCooldown();
        return;
      }
      if (intent.action === 'stop') {
        // 현재 mode 의 onModeExit handler 가 있으면 그것 우선. 없으면 framework
        // default (handleStop 으로 mode='대기' 전환 + 안내 TTS).
        if (handlers?.onModeExit) {
          handlers.onModeExit();
        } else {
          void handleStop();
        }
      }
      enterCooldown();
      return;
    }
    if (intent.kind === 'mode_change') {
      // sub_command(stop) 과 의미 같은 mode_change('대기') 는 onModeExit 로 위임.
      if (intent.mode === '대기' && handlers?.onModeExit) {
        handlers.onModeExit();
        enterCooldown();
        return;
      }
      // 일반 mode_change — useModeAnnouncer 가 setMode 후 자동 안내.
      enterCooldown();
      return;
    }
    if (intent.kind === 'rhythm_play') {
      handlers?.onRhythmPlay?.({ displayName: intent.display_name });
      enterCooldown();
      return;
    }
    if (intent.kind === 'rhythm_stop') {
      handlers?.onRhythmStop?.();
      enterCooldown();
      return;
    }
    if (intent.kind === 'confirm_yes') {
      const c = voice.confirm;
      voice.clearConfirm();
      if (c) void c.onConfirm();
      enterCooldown();
      return;
    }
    if (intent.kind === 'confirm_no') {
      const c = voice.confirm;
      voice.clearConfirm();
      if (c) void c.onCancel();
      enterCooldown();
      return;
    }
    enterCooldown();
  }

  async function handleGotoVertex(name: string): Promise<void> {
    if (!name) {
      enterCooldown();
      return;
    }
    let confirmation = '';
    try {
      // GOTO 진입 — Control 의 /api/gogoping/goto_vertex 호출.
      // SetGoal.srv → FSM trigger 경로라 robot 이동 + state GOTO 전이 둘 다 발생.
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
    // "그만"/"멈춰"/"정지"/"스톱" → 현재 mode 중단 + 대기 복귀. 각 로봇 별 처리:
    //   - gogoping: FSM cancel trigger (active task / MANUAL / RETURNING → IDLE). fetch
    //     로 mode_to_goal("대기") 보내서 ROS command_listener 가 cancel 발사.
    //   - eduping (및 그 외): mode store 만 '대기' 로 — 각 모드 컴포넌트
    //     (DancePlayPopup 등) 가 onUnmounted 에서 stream.close() / camera teardown.
    if (mode.currentMode === '대기') {
      speak('이미 쉬고 있어요');
      return;
    }
    if (robot.id === 'gogoping') {
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
      return;
    }
    // eduping / noriarm — 단순 mode 전환만. useModeAnnouncer 가 대기 진입 시
    // 자체 안내 TTS 처리하므로 별도 confirmation speak 불필요.
    mode.setMode('대기');
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
    console.log(`[voice][speak] state=${voice.state} text=`, trimmed);
    webrtcVoice.send({ type: 'speak', text: trimmed });
  }

  /** 진행 중인 server TTS 의 outbound buffer 비움 + 클라 lip-sync detach. */
  function cancelSpeak(): void {
    webrtcVoice.send({ type: 'tts_cancel' });
    lipsyncDetach?.();
    lipsyncDetach = null;
  }

  /** 확인 사이클 시작 — voice.confirm 저장 + 서버 awaiting_confirm sync +
   *  TTS prompt + TTS 끝나면 wake gate 자동 open. 사용자 답이 server 의
   *  ConfirmHandler 를 거쳐 confirm_yes/no intent 로 돌아오면 stored
   *  callback 실행. */
  let confirmAwaitingTtsEnd = false;
  function startConfirm(opts: ConfirmRequest): void {
    voice.setConfirm(opts);
    confirmAwaitingTtsEnd = true;
    speak(opts.prompt);
  }
  watch(
    () => voice.state,
    (next, prev) => {
      if (prev === 'speaking' && next === 'cooldown' && confirmAwaitingTtsEnd) {
        confirmAwaitingTtsEnd = false;
        forceWake();
      }
    },
  );

  /** 호출어 없이 wake gate 강제 open — TTS prompt 직후 사용자 답 받을 때.
   *  server 의 `wake` DC msg 와 동일 처리 (open_gate + outbound clear). 이미
   *  TTS 가 끝난 시점에 호출하면 clear 가 noop. */
  function forceWake(): void {
    console.log(`[voice][forceWake] state=${voice.state}`);
    webrtcVoice.send({ type: 'wake', robot: robot.id });
    voice.setState('listening');
    armListeningTimer();
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
    forceWake,
    startConfirm,
    micLevel: webrtcVoice.micLevel,
    wakeScores: wakeWord.lastScores,
    wakeThreshold,
    debug,
  };
}

export type VoiceController = ReturnType<typeof useVoiceController>;
