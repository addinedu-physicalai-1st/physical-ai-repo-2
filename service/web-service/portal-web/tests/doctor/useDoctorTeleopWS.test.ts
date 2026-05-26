import { describe, expect, it } from 'vitest';
import { encodeState } from '../../src/doctor/pose_codec';
import { handleIncomingMessage } from '../../src/doctor/useDoctorTeleopWS';

describe('useDoctorTeleopWS message handler', () => {
  it('parses state frame', () => {
    const buf = encodeState({
      tsMs: 7,
      left: { joints: [0.1, 0, 0, 0, 0, 0, 0], gripper: 0.5, servoStatus: 0 },
      right: { joints: [0, 0, 0, 0, 0, 0, 0], gripper: 0.5, servoStatus: 1 },
    });
    let captured: unknown = null;
    handleIncomingMessage(
      { data: buf } as MessageEvent,
      (state) => { captured = state; },
      () => { throw new Error('event handler should not fire on binary'); },
    );
    expect(captured).not.toBeNull();
    expect((captured as any).left.joints[0]).toBeCloseTo(0.1, 3);
  });

  it('parses event json', () => {
    let captured: unknown = null;
    handleIncomingMessage(
      { data: '{"type":"warn","code":"collision_near","arm":"left"}' } as MessageEvent,
      () => { throw new Error('state handler should not fire on text'); },
      (evt) => { captured = evt; },
    );
    expect((captured as any).code).toBe('collision_near');
  });
});
