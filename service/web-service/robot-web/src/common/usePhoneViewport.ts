import { onBeforeUnmount, ref, type Ref } from 'vue';

const PHONE_QUERY = '(max-width: 768px), (pointer: coarse)';
const PORTRAIT_PHONE_QUERY =
  '((max-width: 768px) and (orientation: portrait)), ((pointer: coarse) and (orientation: portrait))';

function useMediaQuery(query: string): Ref<boolean> {
  const matches = ref(false);
  if (typeof window === 'undefined') return matches;
  const mql = window.matchMedia(query);
  matches.value = mql.matches;
  const handler = (e: MediaQueryListEvent): void => {
    matches.value = e.matches;
  };
  if (typeof mql.addEventListener === 'function') {
    mql.addEventListener('change', handler);
  } else {
    (mql as unknown as { addListener: (cb: (e: MediaQueryListEvent) => void) => void }).addListener(handler);
  }
  onBeforeUnmount(() => {
    if (typeof mql.removeEventListener === 'function') {
      mql.removeEventListener('change', handler);
    } else {
      (mql as unknown as { removeListener: (cb: (e: MediaQueryListEvent) => void) => void }).removeListener(handler);
    }
  });
  return matches;
}

/** 모든 휴대전화·터치 환경 (가로/세로 무관). */
export function usePhoneViewport(): Ref<boolean> {
  return useMediaQuery(PHONE_QUERY);
}

/** 세로 (portrait) 휴대전화 — pill strip 표시 여부 등. */
export function usePortraitPhone(): Ref<boolean> {
  return useMediaQuery(PORTRAIT_PHONE_QUERY);
}
