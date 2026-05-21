import type { Participant } from './useHideAndSeekState';

/**
 * 숨바꼭질 mock 용 등록 아이 5명.
 * 실제 운영에서는 server/control 의 children 테이블에서 받아오게 된다.
 */
export const REGISTERED_CHILDREN: ReadonlyArray<
  Pick<Participant, 'id' | 'name' | 'color'>
> = [
  { id: 'c1', name: '지유', color: '#ffb4c2' },
  { id: 'c2', name: '서연', color: '#a8d8ea' },
  { id: 'c3', name: '하준', color: '#fce38a' },
  { id: 'c4', name: '도윤', color: '#b5ead7' },
  { id: 'c5', name: '예린', color: '#c9b5e0' },
];
