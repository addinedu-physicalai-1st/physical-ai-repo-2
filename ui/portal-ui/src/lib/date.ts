// 로컬 시간대 기준 'YYYY-MM-DD'.
// new Date().toISOString().slice(0,10) 는 UTC 라 KST 자정 직후 "어제" 가 되는 문제 회피용.
export function localDateKey(d: Date = new Date()): string {
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
}
