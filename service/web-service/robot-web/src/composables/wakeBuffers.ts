/**
 * 호출어 인식 파이프라인의 ring buffer + 임계값 결정 — DOM·ONNX 의존 없는 순수 모듈.
 *
 * 별도 모듈로 추출해 vitest 로 단위 테스트 가능하게 한다 ([tests/wakeBuffers.test.ts]).
 */

export class AudioRing {
  private buf: Float32Array;
  private filled = 0;
  private newSinceFlush = 0;

  constructor(public readonly capacity: number) {
    this.buf = new Float32Array(capacity);
  }

  push(chunk: Float32Array): void {
    if (chunk.length >= this.capacity) {
      // 들어온 청크가 ring 보다 크면 최신 capacity 개만 보관
      this.buf.set(chunk.subarray(chunk.length - this.capacity));
      this.filled = this.capacity;
      this.newSinceFlush += chunk.length;
      return;
    }
    if (this.filled + chunk.length <= this.capacity) {
      this.buf.set(chunk, this.filled);
      this.filled += chunk.length;
    } else {
      const slide = this.filled + chunk.length - this.capacity;
      this.buf.copyWithin(0, slide, this.filled);
      this.buf.set(chunk, this.filled - slide);
      this.filled = this.capacity;
    }
    this.newSinceFlush += chunk.length;
  }

  isReady(): boolean {
    return this.filled >= this.capacity;
  }

  snapshot(): Float32Array {
    // 가장 오래된 → 가장 최근 순서로 capacity 길이 반환
    return this.buf.subarray(0, this.filled);
  }

  newSamplesSinceFlush(): number {
    return this.newSinceFlush;
  }

  flushNew(): void {
    this.newSinceFlush = 0;
  }
}

export class EmbedRing {
  private buf: Float32Array;
  private framesFilled = 0;

  constructor(public readonly windowFrames: number, public readonly dim: number) {
    this.buf = new Float32Array(windowFrames * dim);
  }

  push(frame: Float32Array): void {
    if (frame.length !== this.dim) {
      throw new Error(
        `EmbedRing.push(): frame length ${frame.length} != dim ${this.dim}`,
      );
    }
    if (this.framesFilled < this.windowFrames) {
      this.buf.set(frame, this.framesFilled * this.dim);
      this.framesFilled += 1;
    } else {
      // slide left by 1 frame, append new at the end
      this.buf.copyWithin(0, this.dim, this.windowFrames * this.dim);
      this.buf.set(frame, (this.windowFrames - 1) * this.dim);
    }
  }

  isReady(): boolean {
    return this.framesFilled >= this.windowFrames;
  }

  snapshot(): Float32Array {
    return this.buf.subarray(0, this.framesFilled * this.dim);
  }
}

export interface WakeHit {
  robotId: string;
  score: number;
}

export function decideWakeHits(
  scoresByRobot: Record<string, number>,
  thresholdsByRobot: Record<string, number>,
): WakeHit[] {
  const hits: WakeHit[] = [];
  for (const [robotId, score] of Object.entries(scoresByRobot)) {
    const th = thresholdsByRobot[robotId];
    if (th === undefined) continue;
    if (score > th) hits.push({ robotId, score });
  }
  hits.sort((a, b) => b.score - a.score);
  return hits;
}
