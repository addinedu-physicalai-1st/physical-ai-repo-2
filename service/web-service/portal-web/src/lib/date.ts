// 로컬 시간대 기준 'YYYY-MM-DD'.
// new Date().toISOString().slice(0,10) 는 UTC 라 KST 자정 직후 "어제" 가 되는 문제 회피용.
export function localDateKey(d: Date = new Date()): string {
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
}

/** 서버 보고서·사진 일자와 맞추기 위한 KST 달력 'YYYY-MM-DD'. */
export function seoulDateKey(d: Date = new Date()): string {
  return new Intl.DateTimeFormat('sv-SE', {
    timeZone: 'Asia/Seoul',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  })
    .format(d)
    .slice(0, 10)
}
