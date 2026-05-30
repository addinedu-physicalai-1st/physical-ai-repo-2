/**
 * GogoPing 현재 상태(한국어 mode 라벨) → 아이 친화 말풍선 메시지.
 *
 * robot-web 의 gogoping 화면은 모드 선택 버튼이 없고(admin/BT/음성이 모드 제어), 로봇은
 * 상태를 따라가기만 한다. 그래서 말풍선이 "지금 뭐 하는지"를 아이에게 항상 알려주는
 * 유일한 채널 — 모드별로 상냥한 한 마디를 띄운다.
 *
 * 매핑 키는 modeStore.currentMode 의 한국어 라벨(snapshotToModeLabel 결과)과 1:1.
 * ERROR(오류)는 별도 오버레이 메시지(ERROR_CHILD_MESSAGE)가 우선하지만, 폴백으로 함께 둔다.
 */
const STATE_MESSAGE: Record<string, string> = {
  대기: '심심해요, 말 걸어주세요!',
  충전: '기운을 충전하고 있어요',
  이동: '어디로 가볼까요?',
  추종: '선생님, 같이 가요!',
  자장가: '쉿, 자장가를 불러줄게요',
  숨바꼭질: '꼭꼭 숨어라, 찾으러 간다!',
  수동: '선생님이 도와주고 있어요',
  복귀: '제자리로 돌아가는 중이에요',
  오류: '앗, 잠깐 쉬고 있어요. 선생님을 불러주세요!',
};

const FALLBACK = '안녕하세요!';

/** 한국어 mode 라벨 → 말풍선 메시지. 미매핑/빈 값은 폴백. */
export function gogopingStateMessage(mode: string): string {
  return STATE_MESSAGE[mode] ?? FALLBACK;
}
