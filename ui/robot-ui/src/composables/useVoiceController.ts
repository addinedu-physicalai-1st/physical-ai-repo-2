import { WAKE_WORD_VARIANT_MAP, type RobotConfig, type EmotionId } from '@/config/robots';
import { isEmotionId } from '@/config/emotions';
import { dispatchIntent } from './useIntentDispatch';
import { useSTT, type STTResult } from './useSTT';
import { useTTS } from './useTTS';
import { useVoiceStore } from '@/stores/voice';
import { useModeStore } from '@/stores/mode';
import {
  buildWakeRegex,
  isLikelyEchoOfRobotReply,
  isStopIntent,
  isWakeOnlyUtterance as isWakeOnlyUtterancePure,
  normalizeWakeText as normalizeSpeechText,
  tryWakeFromText as tryWakeFromTextPure,
} from './wakeMatcher';

const LISTENING_WINDOW_MS = 8000;
// 명령 처리 후 UI 가 잠시 쉬는 상태 cooldown.
const COOLDOWN_MS = 1500;
// TTS 가 끝난 뒤 echo (스피커 → 마이크) 가 STT 결과로 새는 걸 막기 위한 짧은 그레이스.
// COOLDOWN_MS 와 분리 — 너무 길면 사용자가 응답 직후 호출어 다시 부를 때 인식이 버려진다.
// TTS 끝과 동시에 stt.refresh() 로 인식 버퍼도 비우므로 이 그레이스는 짧아도 충분.
const ECHO_SUPPRESS_MS = 350;
// wake ack("네") 직후 아주 짧은 interim 잡음으로 즉시 끊기는 것을 방지.
const WAKE_ACK_BARGE_IN_GRACE_MS = 220;
// 호출어가 들어왔을 때 추가 발화를 기다리는 settle 시간.
// 이 시간 내에 새 interim 이 안 오면 그 시점 텍스트로 처리한다.
const WAKE_SETTLE_MS = 650;

// STT 가 띄어쓰며 인식하는 케이스도 잡기 위해 wake word 음절 사이 \s* 허용
//   ex) "고고 핑", "에듀 핑", "노리 암"
// alias (예: '에듀핀') 도 같은 패턴으로 등록 — 매칭 후 canonical wakeWord 로 정규화한다.
const WAKE_WORD_REGEX = buildWakeRegex(WAKE_WORD_VARIANT_MAP);

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
  let settleTimer: number | null = null;
  let pendingSettleText = '';
  // listening 상태에서 마지막으로 본 interim 텍스트. 갱신되면 사용자가 말하는 중으로 보고
  // listeningTimer 를 리셋한다.
  let lastListeningInterim = '';
  // 브라우저 STT final 이 짧게 잘리는 경우 보정용 (최근/가장 긴 interim).
  let bestListeningText = '';
  let suppressUntil = 0;
  // dispatching 중 호출어로 가로채기 위한 abort controller
  let dispatchAbort: AbortController | null = null;

  let pendingEmotion: EmotionId | null = null;
  let skipTtsEndCleanupOnce = false;
  let wakeAckInProgress = false;
  let wakeAckStartedAt = 0;
  // wake 직후 첫 발화는 restricted mode 제한을 1회 우회 (사용자는 호출 후 즉시 명령한다고 기대)
  let allowRestrictedBypassOnce = false;

  function baseEmotionForCurrentMode(): EmotionId {
    return mode.robot.defaultEmotionByMode[mode.currentMode] ?? 'basic';
  }

  const tts = useTTS({
    onStart: (text) => {
      voice.setSpeaking(true);
      voice.setRobotReply(text);
      if (text === '네!') wakeAckStartedAt = Date.now();
      // 웨이크 응답("네") 재생 중엔 listening barge-in 을 위해 wake_detected 유지
      if (!wakeAckInProgress) {
        voice.setState('speaking'); // Maintain thinking until audio starts
      }
      if (pendingEmotion) {
        mode.currentEmotion = pendingEmotion;
      }
    },
    onEnd: () => {
      voice.setSpeaking(false);
      if (skipTtsEndCleanupOnce) {
        // barge-in 으로 의도적으로 끊은 경우: echo suppress/refresh 를 걸면
        // 사용자가 이어서 말한 명령까지 버퍼에서 날아간다.
        skipTtsEndCleanupOnce = false;
        voice.setRobotReply('');
        return;
      }
      // 짧은 echo 그레이스 + STT 세션 refresh 로 누적 버퍼 비우기.
      // 이전엔 1500ms 동안 모든 STT 결과를 버려, 응답 직후 사용자가 호출어를 다시
      // 불러도 인식이 누락되는 문제가 있었음.
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

  function clearSettleTimer(): void {
    if (settleTimer !== null) {
      window.clearTimeout(settleTimer);
      settleTimer = null;
    }
    pendingSettleText = '';
  }

  function tryWakeFromText(text: string): { wakeWord: string; remainder: string } | null {
    return tryWakeFromTextPure(text, robot.wakeWord, WAKE_WORD_VARIANT_MAP, WAKE_WORD_REGEX);
  }

  function isWakeOnlyUtterance(text: string): boolean {
    return isWakeOnlyUtterancePure(text, robot.wakeWord, WAKE_WORD_VARIANT_MAP, WAKE_WORD_REGEX);
  }

  async function fireSettle(): Promise<void> {
    settleTimer = null;
    const text = pendingSettleText;
    pendingSettleText = '';
    if (voice.state !== 'idle') return;
    const settled = tryWakeFromText(text);
    if (settled) await enterWakeDetected(settled.remainder);
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
    // wake ack("네") 중에는 suppressUntil/echo 게이트를 우회해서 즉시 barge-in 허용
    if (wakeAckInProgress) return false;
    // 일반 발화(TTS) 중엔 STT 결과를 버리되, wake ack("네") 중엔 barge-in 허용.
    if (voice.isSpeaking && !wakeAckInProgress && voice.state !== 'speaking') return true;
    if (Date.now() < suppressUntil) return true;
    return false;
  }

  /**
   * dispatching / wake_detected / listening / cooldown 중 호출어가 다시 들리면
   * 진행 중 작업 (fetch / TTS / 타이머) 을 모두 취소하고 새 흐름 시작.
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
    clearSettleTimer();
    lastListeningInterim = '';
    bestListeningText = '';
    voice.setSpeaking(false);
    suppressUntil = 0;
    // 어떤 모드에서든 로봇이 말하는 중 호출되면 즉시 listening 으로 전이해
    // 사용자의 후속 명령을 놓치지 않도록 한다 (자장가 포함).
    if (duringRobotSpeech) {
      voice.setRobotReply('');
      // 호출어 인식 시에는 항상 "네" 응답 (중단 상황 포함)
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

    // 사용자 발화만 입력창에 표시. wake_detected/dispatching/cooldown 동안엔 echo 가 새는 걸
    // 막기 위해 sttText 자체를 갱신 안 함. 사용자가 입력창에 직접 타이핑 중일 때도 덮어쓰지 않음.
    const canUpdate =
      !voice.inputLocked && (voice.state === 'idle' || voice.state === 'listening');
    if (canUpdate) {
      voice.setSttText(result.text);
    }

    const trimmed = result.text.trim();

    // wake ack("네!") 도중 사용자가 이어서 말하면 즉시 TTS 중단 후 listening 으로 전이.
    if (wakeAckInProgress && voice.isSpeaking && trimmed) {
      const elapsed = Date.now() - wakeAckStartedAt;
      const significantSpeech =
        result.isFinal || (elapsed >= WAKE_ACK_BARGE_IN_GRACE_MS && trimmed.length >= 2);
      // "네"/호출어 재인식 같은 잔향은 wake ack barge-in 조건에서 제외
      const likelyWakeEcho = isWakeOnlyUtterance(trimmed) || trimmed === '네' || trimmed === '네요';
      if (!significantSpeech || likelyWakeEcho) {
        return;
      }
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
      // final 이 이미 온 경우 바로 dispatch.
      if (result.isFinal) {
        // "고고핑" 만 다시 final 로 떨어진 경우는 명령이 아님 — 계속 listening 유지
        if (isWakeOnlyUtterance(trimmed)) {
          return;
        }
        clearListeningTimer();
        await enterDispatching(trimmed);
      }
      return;
    }

    // speaking 중 wake barge-in은 final 만 — interim 은 스피커→마이크 echo 가
    // 호출어로 자주 뜨며 재생이 끊기고 "네!" 가 다시 나가는 현상을 만든다.
    if (voice.state === 'speaking' && trimmed && result.isFinal) {
      const wake = tryWakeFromText(trimmed);
      if (wake) {
        await bargeIn(wake.remainder);
        return;
      }
    }

    // 일반 speaking 중에도 사용자가 최종 발화를 하면 즉시 끊고 명령 처리.
    // 단, 로봇이 방금 말한 문장 echo 인식은 제외.
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

    // barge-in — idle / listening 외 상태에서도 호출어 들어오면 가로챈다.
    // (idle 은 아래 settle 로직, listening 은 일반 후속 발화 처리)
    if (
      result.isFinal &&
      (voice.state === 'wake_detected' ||
        voice.state === 'dispatching' ||
        voice.state === 'cooldown')
    ) {
      const wake = tryWakeFromText(trimmed);
      if (wake) {
        await bargeIn(wake.remainder);
        return;
      }
    }

    if (voice.state === 'idle') {
      // final 이면 즉시 처리 + settle 타이머 무력화
      if (result.isFinal) {
        clearSettleTimer();
        const wake = tryWakeFromText(trimmed);
        if (wake) await enterWakeDetected(wake.remainder);
        return;
      }

      // interim — 호출어 매칭되면 settle 타이머로 추가 발화 기다림
      const wake = tryWakeFromText(trimmed);
      if (!wake) return;

      // 텍스트가 실제로 자랐을 때만 reset, 같은 텍스트 반복 (STT chatter) 은 무시
      const grew = trimmed.length > pendingSettleText.length;
      pendingSettleText = trimmed;

      if (settleTimer === null) {
        // 첫 매칭 — 타이머 시작
        settleTimer = window.setTimeout(fireSettle, WAKE_SETTLE_MS);
      } else if (grew) {
        // 사용자가 계속 말하는 중 — 타이머 reset
        window.clearTimeout(settleTimer);
        settleTimer = window.setTimeout(fireSettle, WAKE_SETTLE_MS);
      }
      return;
    }

    if (voice.state === 'listening') {
      if (result.isFinal) {
        // wake-word만 final 로 떨어진 경우는 명령이 아님 — 계속 listening 유지
        if (isWakeOnlyUtterance(trimmed)) {
          bestListeningText = '';
          lastListeningInterim = '';
          armListeningTimer();
          return;
        }

        clearListeningTimer();
        lastListeningInterim = '';
        // final 이 짧게 끊긴 경우(예: "틀어") 최근 interim(예: "자장가 틀어줘")로 보정
        const candidate = bestListeningText.trim();
        const finalText = trimmed;
        const useCandidate =
          candidate.length > finalText.length &&
          (candidate.includes(finalText) || finalText.length <= 2);
        // candidate/final 이 서로 부분문자열이 아니면 접합해 의미 손실을 줄임
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
      // 사용자가 실제로 말을 시작/계속하는 중이면 listening 윈도우를 갱신.
      // 같은 interim 이 반복 (STT chatter) 되는 경우는 무시 — 무한 갱신 방지.
      if (trimmed && trimmed !== lastListeningInterim) {
        lastListeningInterim = trimmed;
        if (trimmed.length >= bestListeningText.length) {
          bestListeningText = trimmed;
        }
        armListeningTimer();
      }
    }
  }

  async function enterWakeDetected(remainder: string): Promise<void> {
    voice.setRobotReply('');
    voice.setState('wake_detected');
    // 직전 TTS suppress window 때문에 wake 직후 첫 음절이 버려지는 현상 방지
    suppressUntil = 0;

    mode.setEmotionTransient('hello', 1500);
    
    // 호출어 인식 시에는 항상 "네" 응답 후 listening/dispatch
    wakeAckInProgress = true;
    try {
      await tts.playWakeAck();
    } finally {
      wakeAckInProgress = false;
    }

    // wake ack 재생 중 사용자 발화가 이미 listening/dispatching 으로 전이시켰다면 덮어쓰지 않음
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
    // 모바일 STT 가 가끔 빈/공백 final 을 흘리는데, 서버 schema `text: min_length=1` 위반으로 422.
    // 잡음일 가능성이 높으므로 cooldown 으로 빠져 다음 발화 대기.
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
    if (restricted && !bypassRestricted && !isStopIntent(text) && !hasModeKeyword) {
      // 보조 모드: 정지 의도 외 발화는 의도 분류 건너뛰고 직전 동작 재개 신호
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
        // voice.setState('speaking') moved to onStart of TTS to maintain thinking status
        const idleEmotion = baseEmotionForCurrentMode();
        pendingEmotion = isEmotionId(response.emotion) ? response.emotion : 'basic';

        await tts.speak(response.reply);

        pendingEmotion = null;
        mode.currentEmotion = idleEmotion;

        enterCooldown();
      } else {
        voice.setRobotReply('');
      }
    } catch (err) {
      voice.setRobotReply('');
      // barge-in 으로 abort 된 경우는 정상 — error 로 표시 안 함
      if ((err as Error).name === 'AbortError') return;
      voice.setError((err as Error).message);
    } finally {
      if (dispatchAbort === controller) dispatchAbort = null;
      // barge-in 으로 이미 다른 상태 (wake_detected 등) 로 전이됐다면 cooldown 으로 덮지 않음
      if (!controller.signal.aborted && voice.state === 'dispatching') enterCooldown();
    }
  }

  function start(): void {
    stt.start();
  }

  function stop(): void {
    stt.stop();
    tts.cancel();
    if (dispatchAbort) {
      dispatchAbort.abort();
      dispatchAbort = null;
    }
    clearListeningTimer();
    clearCooldownTimer();
    clearSettleTimer();
    lastListeningInterim = '';
    bestListeningText = '';
    wakeAckInProgress = false;
    skipTtsEndCleanupOnce = false;
    suppressUntil = 0;
    pendingEmotion = null;
    allowRestrictedBypassOnce = false;
    // 타이핑 모드로 전환 시: 마이크에 잡힌 주변 발화·누적 STT 가 입력창에 남지 않도록 비움 (모든 로봇/모드 공통).
    voice.setSttText('');
    voice.setRobotReply('');
    voice.setInputLocked(false);
    voice.setSpeaking(false);
    voice.setState('idle');
  }

  /**
   * 텍스트 명령을 음성과 동일한 흐름으로 처리.
   * - wake word 단독이면 wake_detected (TTS 응답)
   * - "wake word + 명령" 이면 잔여 텍스트로 dispatch
   * - wake word 없으면 그대로 dispatch
   * 타이핑 입력에서 호출.
   */
  async function processCommand(text: string): Promise<void> {
    const trimmed = text.trim();
    if (!trimmed) return;

    const wake = tryWakeFromText(trimmed);

    if (wake) {
      if (wake.remainder) {
        // 호출어 + 명령 — TTS 응답 생략, 바로 dispatch
        await enterDispatching(wake.remainder);
      } else {
        // 호출어 단독 — 응답만 (타이핑은 follow-up 의미 없으므로 listening 안 함)
        voice.setState('wake_detected');
        mode.setEmotionTransient('hello', 1500);
        wakeAckInProgress = true;
        try {
          await tts.playWakeAck();
        } finally {
          wakeAckInProgress = false;
        }
        enterCooldown();
      }
      return;
    }
    // 호출어 없는 직접 명령 (타이핑 전용)
    await enterDispatching(trimmed);
  }

  return { start, stop, processCommand, micLevel: stt.level };
}

export type VoiceController = ReturnType<typeof useVoiceController>;
