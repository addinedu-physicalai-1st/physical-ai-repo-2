import { describe, expect, it } from 'vitest';
import { errorReasonToTeacherText } from '../src/gogoping/errorReason';

describe('errorReasonToTeacherText', () => {
  it('maps known reasons to teacher text', () => {
    expect(errorReasonToTeacherText('user_emergency_stop')).toContain('비상 정지');
    expect(errorReasonToTeacherText('out_of_map')).toContain('구역 밖');
    expect(errorReasonToTeacherText('lidar_timeout')).toContain('라이다');
    expect(errorReasonToTeacherText('odom_timeout')).toContain('주행 센서');
  });

  it('falls back for unknown reason', () => {
    expect(errorReasonToTeacherText('something_new')).toContain('점검이 필요해요');
  });

  it('falls back for empty reason', () => {
    expect(errorReasonToTeacherText('')).toContain('점검이 필요해요');
  });
});
