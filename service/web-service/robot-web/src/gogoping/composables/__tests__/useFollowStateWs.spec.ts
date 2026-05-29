import { describe, it, expect, vi, beforeEach } from 'vitest';
import { useFollowStateWs } from '../useFollowStateWs';

class MockWebSocket {
  static lastInstance: MockWebSocket | null = null;
  url: string;
  onmessage: ((ev: { data: string }) => void) | null = null;
  onclose: (() => void) | null = null;
  onopen: (() => void) | null = null;
  onerror: (() => void) | null = null;
  closeMock = vi.fn();
  readyState = 1;
  constructor(url: string) {
    this.url = url;
    MockWebSocket.lastInstance = this;
  }
  close() { this.closeMock(); }
}

describe('useFollowStateWs', () => {
  beforeEach(() => {
    global.WebSocket = MockWebSocket as unknown as typeof WebSocket;
    MockWebSocket.lastInstance = null;
  });

  it('/ws/follow-state 로 연결', () => {
    const { stop } = useFollowStateWs();
    expect(MockWebSocket.lastInstance?.url).toContain('/ws/follow-state');
    stop();
  });

  it('mode 메시지 수신 → state ref 갱신', () => {
    const { state, stop } = useFollowStateWs();
    const ws = MockWebSocket.lastInstance!;
    ws.onmessage?.({ data: JSON.stringify({ mode: 'voice_search' }) });
    expect(state.value.mode).toBe('voice_search');
    stop();
  });

  it('stop() → ws.close 호출', () => {
    const { stop } = useFollowStateWs();
    const ws = MockWebSocket.lastInstance!;
    stop();
    expect(ws.closeMock).toHaveBeenCalled();
  });
});
