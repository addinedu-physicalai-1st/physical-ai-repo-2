# Wake-word 재설계 — Design Spec (cycle 6)

- **작성일**: 2026-05-19
- **브랜치**: `woo/feat-open-wake-word`
- **관련 SR**: SR-WAKE-RD-1 ~ SR-WAKE-RD-4 (본 문서에서 정의)
- **목적**: 학습/추론 audio 분포 불일치로 브라우저 인식 실패하는 문제를 학습 데이터 구조 변경으로 해결. 브라우저는 raw audio 만 흘려도 동작하도록.

## 배경

`wakeword-plan.md` cycle 1-5 의 학습은 positive WAV (0.6-0.9s 짧은 발화) 를 `np.pad(data, (0, clip_samples - data.size))` 로 끝부분에 **literal zero** 채워 2.7s 로 만들어 `openwakeword.utils.AudioFeatures` 에 통과시켰다. 모델은 결과적으로 "앞부분 wake word + 뒷부분 absolute silence" 분포만 학습.

브라우저 추론 시점에는:
- `AudioRing` 이 2.7s 연속 mic stream 을 들고 있음
- silence 구간에도 mic noise floor (RMS 0.003~0.004) 가 있어 **literal zero 가 아님**
- mel ONNX 의 frame-wise mean 이 학습 3.85 / 브라우저 7.01 로 거의 2배 → 학습 분포 밖
- 결과: real-voice positives 의 brower score 가 0.001 근처로 깔림 (offline 같은 WAV 는 0.99+)

이번 세션에서 inference-side 에 VAD-compact (voiced chunk 만 ring 시작 위치로 압축 + zero pad) hack 으로 임시 해결했으나, 후속 cascade (TTS hang, isSpeaking stuck, CPU stutter) 가 줄줄이 발생. 학습 데이터 분포를 **production 입력에 맞추는 것** 이 올바른 fix.

## 결정사항

| # | 결정 | 내용 |
|---|---|---|
| A | 파이프라인 유지 | openwakeword 의 mel + embedding + binary classifier 3-stage 그대로 |
| B | positive 구조 변경 | "wake word + literal zero" → "wake word at random offset within 2.7s + continuous ambient" |
| C | ambient 소스 | `data/wake_training/negative/realworld/*.wav` (직접 녹음 + 카페 ASMR) + `data/wake_training/noise/esc50/*.wav` 풀에서 매번 랜덤 샘플 + mix |
| D | hard negatives 추가 | 한국어 3음절 단어 MMS-TTS 합성 (~1500) + 실음성 30 개. 기존 cycle 의 "큰 소리 3음절 단어가 wake 로 fire" FA 문제 대응 |
| E | 브라우저 preprocessing 0 | useWakeWord.ts 의 VAD-compact / stride / threshold 0.5 등 임시 fix 제거. raw audio 만 mel ONNX 에 흘림 |
| F | useTTS fix 유지 | cloneNode → currentTime=0 reuse 패턴, safety timeout, settled guard 는 학습과 무관한 진짜 버그 fix 라 그대로 둠 |

## 아키텍처 — 데이터 흐름

### 학습 시

```
positive source WAV (0.6~0.9s "에듀핑")
        │
        ▼
augmentation (audiomentations: pitch ±2 semitones, speed 0.85-1.15, gain ±6dB)
        │
        ▼
mix_into_ambient(wake, ambient_pool, rng, snr_db=uniform(5,20))
   ─ ambient pool 에서 클립 랜덤 선택 → 2.7s slice
   ─ random offset ∈ [0, 2.7 - wake_duration)
   ─ wake 를 ambient 위에 가산 → clip [-1, 1]
        │
        ▼
2.7s float32 → int16 cast → openwakeword AudioFeatures.embed_clips
        │
        ▼
(N_clip × T_emb × 96) .npy
        │
        ▼
classifier 학습 (기존 train.py 그대로)
```

### 추론 시 (브라우저)

```
mic → AudioWorklet → 1280-sample chunks → AudioRing(43200 samples = 2.7s)
        │
        ▼
ring.snapshot() — preprocessing 없음
        │
        ▼
audio × 32767 (int16 scale)
        │
        ▼
melspec ONNX → embedding ONNX → classifier ONNX
        │
        ▼
sliding max score (16-frame window stride 1) → decideWakeHits
```

학습 / 추론 모두 "2.7s continuous mix" 구조 → mel mean 동일 분포 → classifier 일관 동작.

## mix-into-ambient builder

### 모듈 위치
`service/ai-service/ai_service/wake_training/mix.py`

### 시그니처

```python
def mix_into_ambient(
    wake: np.ndarray,
    ambient_pool: list[np.ndarray],
    rng: np.random.Generator,
    target_sec: float = 2.7,
    snr_db_range: tuple[float, float] = (5.0, 20.0),
) -> tuple[np.ndarray, dict]:
    """
    Returns (clip, meta) — clip 은 (43200,) float32, meta 는 디버그용
    {'offset_sec': float, 'snr_db': float, 'ambient_idx': int}.
    """
```

### 알고리즘

1. `ambient = ambient_pool[rng.choice(len(pool))]`
2. ambient 길이 ≥ 2.7s 이면 random start 로 slice; 짧으면 cyclic concat
3. `snr_db = rng.uniform(*snr_db_range)`
4. `rms_wake = sqrt(mean(wake^2))`; `rms_amb = sqrt(mean(ambient^2))`
5. `target_rms_amb = rms_wake / 10**(snr_db/20)`
6. `ambient *= target_rms_amb / max(rms_amb, 1e-9)`
7. `offset = rng.uniform(0, target_sec - wake_duration_sec)`
8. `out = ambient.copy(); out[off:off+len(wake)] += wake`
9. `np.clip(out, -1.0, 1.0)`

### 단위 테스트 (pytest)

| 케이스 | 검증 |
|---|---|
| 출력 길이 | `len(out) == 43200` |
| offset 정확성 | meta['offset_sec'] 위치에서 RMS 가 다른 위치보다 큰지 |
| SNR 정확성 | 측정 SNR 이 meta['snr_db'] ± 1.5dB 이내 |
| edge: wake ≥ 2.7s | crop 동작 검증 |
| edge: ambient 짧음 | cyclic concat 검증 |
| determinism | 같은 seed 로 두 번 호출 시 byte-identical |

## hard negatives (3음절 한국어)

### 3.5.1 — MMS-TTS 합성

**모듈**: `scripts/wakeword/synth_hard_negatives.py` (새 스크립트)

- 입력: 한국어 3음절 단어 list (~500). 명사/동사/형용사 mix.
  - source: korean wordnet, NIKL 표준 사전, 또는 직접 큐레이션
  - 예시: 안녕해 어떻게 이상해 행복해 노력해 사진해 자장가 어디서 학교에 어머니 아버지 선생님 가까이 친구야 미안해 사랑해 일어나 들어가 도와줘 도와요 ...
  - phonetic risk 높은 단어 우선: "에/고/노" 로 시작, "핑/암" 으로 끝나는 등
- 합성: 기존 `service/ai-service/ai_service/wake_training/synthesizer.py` 의 MMS-TTS 코드 재활용
- 단어당 3 variants (pitch/speed 약간 다름) → 총 ~1500 hard negatives
- 출력: `data/wake_training/negative/hard_3syl/<word>_<idx>.wav`

### 3.5.2 — 실음성 hard negatives

- `scripts/wakeword/record_realworld.py` 에 `hard-negative` 서브커맨드 추가
- 사용자가 "에듀핑/고고핑/노리암 과 헷갈리기 쉬운 단어" 30 개 발화 (prompt loop UI)
- 출력: `data/wake_training/negative/hard_3syl_realworld/9999_<idx>_<word>.wav`

### 학습에서의 위치

- `extract_features.py` 가 두 directory 를 모두 negative 로 추가 추출
- `train.py` 에서 별도 negative source 로 합쳐짐 (기존 cross-robot oversample 와는 별개; 오버샘플 안 함, 자연 분량)
- evaluate 시 별도 metric 으로 보고 (FRR/FAR 외 "hard-neg trigger rate" 칸 추가)

## 브라우저 cleanup

### useWakeWord.ts — 제거

| 코드 | 비고 |
|---|---|
| VAD-compact 루프 (chunk RMS gating + writeOff 압축) | mix-into-ambient 학습 후 불필요 |
| `MIN_VOICED_CHUNKS` 6 미만 skip | 위와 묶음 |
| `INFERENCE_STRIDE = 2` | 매 hop (80ms) 1회 inference 로 복원 |
| `window.__dumpWakeAudio` helper | 유지 (dev tool — 인식 실패 시 audio 추출용) |
| `[wake-init]` 로그 | 유지 (sanity check) |

`runStep` 의 audio 처리 부분이 다음과 같이 단순화:

```ts
const audio = audioRing.snapshot();      // 43200 samples
const scaledAudio = new Float32Array(audio.length);
for (let i = 0; i < audio.length; i++) {
  const v = audio[i];
  const clipped = v < -1 ? -1 : v > 1 ? 1 : v;
  scaledAudio[i] = Math.round(clipped * 32767);
}
// → mel ONNX → embedding ONNX → classifier ONNX
```

### useVoiceController.ts — 조정

| 항목 | Before | After |
|---|---|---|
| `WAKE_THRESHOLDS` | 임시 eduping/gogoping=0.5, noriarm=0.95 | cycle-6 evaluate 결과로 robot별 재설정 (TBD, RD-3 단계) |
| `[wake] spike` 로그 | score ≥ 0.1 마다 표시 | score ≥ τ-0.2 (threshold 근접) 또는 0.5 이상만 표시. 도배 회피 |

### useTTS.ts — 유지

cloneNode 제거 + currentTime=0 reuse / lipsync graph 1 회 attach / safety timeout 1.5s / settled guard 는 학습과 무관한 진짜 버그 fix. 그대로 둠.

## Testing & Validation

### Unit
- `service/ai-service/ai_service/tests/test_wake_training_mix.py` (새) — mix builder 6 케이스
- `service/web-service/robot-web/tests/wakeBuffers.test.ts` — VAD-compact 분기 제거 후에도 통과
- `service/web-service/robot-web/tests/wakeMatcher.test.ts` — 변경 없음

### Offline (`scripts/wakeword/evaluate.py` 갱신)

eval positive 도 같은 mix builder 통과시켜 production 분포 일치. 3가지 metric 분리:

| metric set | 입력 | 목적 |
|---|---|---|
| `real_voice_mixed` | 9999_ WAV → mix builder → embed | 실환경에 가까운 FRR |
| `synth_mixed` | 0000_ MMS WAV → mix builder → embed | 학습 분포 sanity |
| `hard_neg_3syl` | hard negative WAV 의 hold-out 20% (학습 split 분리) | FA 측정 |

threshold sweep: τ ∈ {0.3, 0.5, 0.7, 0.85, 0.9, 0.95, 0.99}.

### Browser end-to-end

cycle-6 onnx deploy 후:
1. "에듀핑" 10회 발화 → 8+ /10 fire (cycle 1-3 의 75% 도 OK, 그 이상이면 개선)
2. 무작위 한국어 3음절 단어 10개 발화 → 0~1 /10 fire (cycle 1-5 의 "큰 소리 3음절 발화 → wake" 문제 회복)
3. 큰 소리 3음절 ("뭐라고!", "안녕해!") → fire 안 해야 함

실패 시 `__dumpWakeAudio()` → offline 동일 audio score 와 비교 → 학습 vs 브라우저 측 분기.

### Decision gate (RD-2 완료 시)

| 결과 | 다음 |
|---|---|
| FRR < 15% AND FA < 2/hr AND hard-neg FAR < 0.5/hr | RD-3 진행 |
| FRR 15-30% | Approach B (real-voice 추가 녹음) → RD-1.5 재실행 |
| FA > 3/hr 또는 hard-neg FAR > 1/hr | 3.5.3 phonetic 유사 단어 negative 추가 |

## SR 분해 / 실행 순서

| SR | 작업 | 산출물 | 의존 |
|---|---|---|---|
| **SR-WAKE-RD-1** | mix builder + hard negatives + feature/eval 갱신 | `service/ai-service/ai_service/wake_training/mix.py`, `scripts/wakeword/synth_hard_negatives.py`, `scripts/wakeword/record_realworld.py` 의 hard-negative 서브커맨드, `scripts/wakeword/extract_features.py` patch, `scripts/wakeword/evaluate.py` patch | — |
| **SR-WAKE-RD-2** | 재학습 + offline FRR/FAR/hard-neg 측정 | cycle-6 `<robot>.onnx` 3개, evaluate 결과 표 | RD-1 |
| **SR-WAKE-RD-3** | 브라우저 cleanup + threshold 설정 + 라이브 검증 | `useWakeWord.ts`/`useVoiceController.ts` 정리, 실 mic 테스트 로그 | RD-2 (threshold) |
| **SR-WAKE-RD-4** | 문서 갱신 | `wakeword-plan.md` cycle-6 섹션 추가, 결과 기록 | RD-3 |

실행 순서: RD-1 → RD-2 → RD-3 → RD-4. RD-3 의 코드 cleanup (VAD-compact 제거 등) 은 RD-2 학습 진행 중 일부 병렬 가능.

## Out of scope

- TTS streaming (HTTP chunked) 전환 — wakeword-plan.md 의 별도 항목
- WebRTC 도입 — 학습과 무관
- Picovoice/Snowboy 등 wake-word 프레임워크 교체 — openwakeword 유지 결정
- Model architecture 변경 (DNN depth, hidden dim 등) — cycle 6 결과 후 RD-2 미달 시 별도 SR
