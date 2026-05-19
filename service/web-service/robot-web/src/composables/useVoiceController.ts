import { type RobotConfig, type EmotionId } from '@/config/robots';
import { isEmotionId } from '@/config/emotions';
import { dispatchIntent } from './useIntentDispatch';
import { useSTT, type STTResult } from './useSTT';
import { useTTS } from './useTTS';
import { useWakeWord } from './useWakeWord';
import { useVoiceStore } from '@/stores/voice';
import { useModeStore } from '@/stores/mode';
import {
  isLikelyEchoOfRobotReply,
  isStopIntent,
  normalizeWakeText as normalizeSpeechText,
} from './wakeMatcher';

const LISTENING_WINDOW_MS = 8000;
// 명령 처리 후 UI 가 잠시 쉬는 상태 cooldown.
const COOLDOWN_MS = 1500;
// TTS 가 끝난 뒤 echo (스피커 → 마이크) 가 STT 결과로 새는 걸 막기 위한 짧은 그레이스.
const ECHO_SUPPRESS_MS = 350;
// wake ack("네") 직후 아주 짧은 interim 잡음으로 즉시 끊기는 것을 방지.
const WAKE_ACK_BARGE_IN_GRACE_MS = 220;

// ONNX wake 분류기 점수 임계값 — cycle 6 evaluate.py 측정값.
// hold-out FRR @ τ=0.99: eduping 1.2% / gogoping 1.2% / noriarm 1.8%.
// hard_3syl trigger @ τ=0.99: eduping 0.6% / gogoping 0.0% / noriarm 5.0%.
const WAKE_THRESHOLDS: Record<string, number> = {
  eduping: 0.99,
  gogoping: 0.99,
  noriarm: 0.99,
};

/** 쉼표 구분 — LLM 에 원아 명단으로 전달 (이름 질문 환각 완화). 비우면 전송 안 함. */
function classRosterFromEnv(): string[] | undefined {
  const raw = (import.meta.env.VITE_CLASS_ROSTER as string | undefined)?.trim();
  if (!raw) return undefined;
  const names = raw
    .split(/[,，]/)
    .map((s) => s.trim())
    .filter(Boolean)
    .slice(0, 40);
  return names.length ? names : undefined;
}

export function useVoiceController(robot: RobotConfig): {
  start: () => void;
  stop: () => void;
  processCommand: (text: string) => Promise<void>;
  /** STT 백엔드 (phone = 서버 STT 의 RMS) 가 노출하는 0~1 audio level. SiriBlob 시각화용. */
  micLevel: import('vue').Ref<number>;
} {
  const voice = useVoiceStore();
  const mode = useModeStore();

  let listeningTimer: number | null = null;
  let cooldownTimer: number | null = null;
  let lastListeningInterim = '';
  let bestListeningText = '';
  let suppressUntil = 0;
  // dispatching 중 호출어로 가로채기 위한 abort controller
  let dispatchAbort: AbortController | null = null;

  let pendingEmotion: EmotionId | null = null;
  let skipTtsEndCleanupOnce = false;
  let wakeAckInProgress = false;
  let wakeAckStartedAt = 0;
  // wake 직후 첫 발화는 restricted mode 제한을 1회 우회
  let allowRestrictedBypassOnce = false;

  function baseEmotionForCurrentMode(): EmotionId {
    return mode.robot.defaultEmotionByMode[mode.currentMode] ?? 'basic';
  }

  const tts = useTTS({
    onStart: (text) => {
      voice.setSpeaking(true);
      voice.setRobotReply(text);
      if (text === '네!') wakeAckStartedAt = Date.now();
      if (!wakeAckInProgress) {
        voice.setState('speaking');
      }
      if (pendingEmotion) {
        mode.currentEmotion = pendingEmotion;
      }
    },
    onEnd: () => {
      voice.setSpeaking(false);
      // TTS 끝난 직후 mic 가 잔향을 들을 수 있어 ONNX wake 그레이스 발동.
      speakerEchoGuardUntil = Date.now() + SPEAKER_ECHO_GUARD_MS;
      if (skipTtsEndCleanupOnce) {
        skipTtsEndCleanupOnce = false;
        voice.setRobotReply('');
        return;
      }
      suppressUntil = Date.now() + ECHO_SUPPRESS_MS;
      stt.refresh();
      voice.setRobotReply('');
    },
  });

  const stt = useSTT({
    lang: 'ko-KR',
    onResult: (result) => handleSttResult(result),
    onError: (message) => voice.setError(message),
  });

  // TTS 종료 직후 mic 가 마지막 출력 잔향을 듣는 짧은 그레이스. ONNX 에 한정.
  let speakerEchoGuardUntil = 0;
  const SPEAKER_ECHO_GUARD_MS = 800;

  const wakeWord = useWakeWord({
    robotIds: [robot.id],
    thresholds: { [robot.id]: WAKE_THRESHOLDS[robot.id] ?? 0.99 },
    cooldownMs: 2500,
    // idle 일 때만 inference. listening (STT 명령 캡쳐) / wake_detected /
    // speaking / dispatching / cooldown 동안은 wake 가 무시되는 시점이라
    // 메인 thread 를 비워 motion / TTS 가 안 끊기게 한다.
    isEnabled: () => voice.state === 'idle' && !wakeAckInProgress,
    onWake: () => {
      // wake ack 재생 도중 ONNX 가 자기 자신 또는 user 의 추가 발화로 트리거되는
      // 경우 무시 — 같은 호출이 여러 번 잡혀 무한 루프 되는 것 방지.
      if (wakeAckInProgress) return;
      // 일반 TTS (응답) 재생 중 wake 무시. AEC 가 완벽하지 않을 때 로봇 자기 발화가
      // mic 로 돌아와 false trigger 되는 것 방어.
      if (voice.isSpeaking) return;
      // TTS 끝난 직후 잔향 그레이스
      if (Date.now() < speakerEchoGuardUntil) return;
      void bargeIn('').catch((e) => voice.setError((e as Error).message));
    },
    onError: (msg) => voice.setError(`wake: ${msg}`),
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
    voice.setState('cooldown');
    clearCooldownTimer();
    cooldownTimer = window.setTimeout(() => {
      voice.setState('idle');
      cooldownTimer = null;
    }, COOLDOWN_MS);
  }

  function shouldDropResult(): boolean {
    if (wakeAckInProgress) return false;
    if (voice.isSpeaking && !wakeAckInProgress && voice.state !== 'speaking') return true;
    if (Date.now() < suppressUntil) return true;
    return false;
  }

  /**
   * ONNX 가 wake 감지 시 호출. 진행 중 작업 (fetch / TTS / 타이머) 모두 취소하고 새 흐름 시작.
   * remainder 는 텍스트 매칭 시절의 잔여 발화 — ONNX 경로에서는 항상 빈 문자열.
   */
  async function bargeIn(remainder: string): Promise<void> {
    const duringRobotSpeech =
      voice.state === 'speaking' || wakeAckInProgress || voice.isSpeaking;

    if (dispatchAbort) {
      dispatchAbort.abort();
      dispatchAbort = null;
    }
    tts.cancel();
    clearListeningTimer();
    clearCooldownTimer();
    lastListeningInterim = '';
    bestListeningText = '';
    voice.setSpeaking(false);
    suppressUntil = 0;
    if (duringRobotSpeech) {
      voice.setRobotReply('');
      voice.setState('wake_detected');
      mode.setEmotionTransient('hello', 800);
      wakeAckInProgress = true;
      try {
        await tts.playWakeAck();
      } finally {
        wakeAckInProgress = false;
      }
      if (voice.state !== 'wake_detected') return;
      voice.setState('listening');
      allowRestrictedBypassOnce = true;
      bestListeningText = '';
      lastListeningInterim = '';
      armListeningTimer();
      if (remainder.trim().length > 0) {
        clearListeningTimer();
        await enterDispatching(remainder);
      }
      return;
    }
    await enterWakeDetected(remainder);
  }

  async function handleSttResult(result: STTResult): Promise<void> {
    if (shouldDropResult()) return;

    const canUpdate =
      !voice.inputLocked && (voice.state === 'idle' || voice.state === 'listening');
    if (canUpdate) {
      voice.setSttText(result.text);
    }

    const trimmed = result.text.trim();

    // wake ack ("네!") 도중 user 가 이어서 명령을 시작하면 즉시 TTS 끊고 listening 전이.
    if (wakeAckInProgress && voice.isSpeaking && trimmed) {
      const elapsed = Date.now() - wakeAckStartedAt;
      const significantSpeech =
        result.isFinal || (elapsed >= WAKE_ACK_BARGE_IN_GRACE_MS && trimmed.length >= 2);
      if (!significantSpeech) return;
      skipTtsEndCleanupOnce = true;
      tts.cancel();
      wakeAckInProgress = false;
      voice.setSpeaking(false);
      voice.setRobotReply('');
      voice.setState('listening');
      allowRestrictedBypassOnce = true;
      lastListeningInterim = '';
      bestListeningText = trimmed;
      armListeningTimer();
      if (result.isFinal) {
        clearListeningTimer();
        await enterDispatching(trimmed);
      }
      return;
    }

    // 로봇이 일반 발화 (speaking) 중 user 가 final 발화 = wake 없는 직접 명령.
    // echo (자기 발화 잔향) 가 아니면 가로채서 dispatch.
    if (voice.state === 'speaking' && result.isFinal) {
      const heard = normalizeSpeechText(trimmed);
      const spoken = normalizeSpeechText(voice.robotReply ?? '');
      if (!isLikelyEchoOfRobotReply(heard, spoken)) {
        skipTtsEndCleanupOnce = true;
        tts.cancel();
        voice.setSpeaking(false);
        voice.setRobotReply('');
        await enterDispatching(trimmed);
      }
      return;
    }

    // idle / wake_detected / dispatching / cooldown — wake 감지는 ONNX 가 담당.
    // STT 결과는 listening 상태에서 command 로만 처리.
    if (voice.state !== 'listening') return;

    if (result.isFinal) {
      clearListeningTimer();
      lastListeningInterim = '';
      const candidate = bestListeningText.trim();
      const finalText = trimmed;
      const useCandidate =
        candidate.length > finalText.length &&
        (candidate.includes(finalText) || finalText.length <= 2);
      const mergedText =
        candidate &&
        finalText &&
        !candidate.includes(finalText) &&
        !finalText.includes(candidate)
          ? `${candidate} ${finalText}`.trim()
          : '';
      const dispatchText = useCandidate
        ? candidate
        : mergedText.length > finalText.length
          ? mergedText
          : finalText;
      bestListeningText = '';
      await enterDispatching(dispatchText);
      return;
    }
    // listening interim — 발화 갱신될 때마다 listening window reset.
    if (trimmed && trimmed !== lastListeningInterim) {
      lastListeningInterim = trimmed;
      if (trimmed.length >= bestListeningText.length) {
        bestListeningText = trimmed;
      }
      armListeningTimer();
    }
  }

  async function enterWakeDetected(remainder: string): Promise<void> {
    voice.setRobotReply('');
    voice.setState('wake_detected');
    suppressUntil = 0;

    mode.setEmotionTransient('hello', 1500);

    wakeAckInProgress = true;
    try {
      await tts.playWakeAck();
    } finally {
      wakeAckInProgress = false;
    }

    if (voice.state !== 'wake_detected') {
      return;
    }

    voice.setState('listening');
    allowRestrictedBypassOnce = true;
    lastListeningInterim = '';
    bestListeningText = '';
    armListeningTimer();
    if (remainder.trim().length > 0) {
      clearListeningTimer();
      await enterDispatching(remainder);
    }
  }

  async function enterDispatching(text: string): Promise<void> {
    if (!text.trim()) {
      enterCooldown();
      return;
    }
    voice.setState('dispatching');
    voice.setLastSpokenText(text);
    voice.setRobotReply('');

    const bypassRestricted = allowRestrictedBypassOnce;
    allowRestrictedBypassOnce = false;
    const restricted = robot.restrictedVoiceMode === mode.currentMode;
    const hasModeKeyword = robot.modes.some((m) => m && text.includes(m));
    const hasGotoPattern =
      /(로 가|로 이동|에 가|로 갑|에 갑|로 갈|에 갈| 가자| 가줘)/.test(text);
    const isReturnIntent = /복귀|돌아가|돌아와|충전소|충전 ?하러/.test(text);
    if (
      restricted && !bypassRestricted && !isStopIntent(text) && !hasModeKeyword
      && !hasGotoPattern && !isReturnIntent
    ) {
      mode.setProximityHalt(false);
      enterCooldown();
      return;
    }

    const controller = new AbortController();
    dispatchAbort = controller;
    try {
      const response = await dispatchIntent(
        text,
        robot.id,
        controller.signal,
        classRosterFromEnv(),
      );
      if (controller.signal.aborted) return;

      mode.applyIntent(response);
      if (response.kind === 'chat') {
        const idleEmotion = baseEmotionForCurrentMode();
        pendingEmotion = isEmotionId(response.emotion) ? response.emotion : 'basic';

        await tts.speak(response.reply);

        pendingEmotion = null;
        mode.currentEmotion = idleEmotion;

        enterCooldown();
      } else if (response.kind === 'goto_vertex') {
        try {
          const r = await fetch('/waypoints/navigate', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name: response.name }),
          });
          if (r.ok) {
            await tts.speak(`${response.name}으로 갈게요`);
          } else {
            await tts.speak(`${response.name}을(를) 찾지 못했어요`);
          }
        } catch {
          await tts.speak('지금은 이동할 수 없어요');
        }
        enterCooldown();
      } else if (response.kind === 'sub_command' && response.action === 'return') {
        try {
          const r = await fetch('/waypoints/navigate', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name: '충전소' }),
          });
          if (r.ok) {
            await tts.speak('충전소로 갈게요');
          } else {
            await tts.speak('충전소를 찾지 못했어요');
          }
        } catch {
          await tts.speak('지금은 복귀할 수 없어요');
        }
        enterCooldown();
      } else {
        voice.setRobotReply('');
      }
    } catch (err) {
      voice.setRobotReply('');
      if ((err as Error).name === 'AbortError') return;
      voice.setError((err as Error).message);
    } finally {
      if (dispatchAbort === controller) dispatchAbort = null;
      if (!controller.signal.aborted && voice.state === 'dispatching') enterCooldown();
    }
  }

  function start(): void {
    stt.start();
    void wakeWord.start().catch((e) => {
      voice.setError(`wake start failed: ${(e as Error).message}`);
    });
  }

  function stop(): void {
    stt.stop();
    void wakeWord.stop();
    tts.cancel();
    if (dispatchAbort) {
      dispatchAbort.abort();
      dispatchAbort = null;
    }
    clearListeningTimer();
    clearCooldownTimer();
    lastListeningInterim = '';
    bestListeningText = '';
    wakeAckInProgress = false;
    skipTtsEndCleanupOnce = false;
    suppressUntil = 0;
    pendingEmotion = null;
    allowRestrictedBypassOnce = false;
    voice.setSttText('');
    voice.setRobotReply('');
    voice.setInputLocked(false);
    voice.setSpeaking(false);
    voice.setState('idle');
  }

  /**
   * 텍스트 명령 처리 (타이핑 입력). ONNX wake 는 audio-only 라 타이핑 경로엔
   * wake-word 검사 없이 그대로 dispatch — 사용자가 입력란에 명령을 칠 때는
   * 호출 의도가 명시적이라고 본다.
   */
  async function processCommand(text: string): Promise<void> {
    const trimmed = text.trim();
    if (!trimmed) return;
    await enterDispatching(trimmed);
  }

  return { start, stop, processCommand, micLevel: stt.level };
}

export type VoiceController = ReturnType<typeof useVoiceController>;
