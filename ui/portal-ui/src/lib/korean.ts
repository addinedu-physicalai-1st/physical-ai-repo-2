import { disassemble, josa } from 'es-hangul'

/** DB 전체 이름만 있을 때 보고서 호칭 추정 (서버 `report_address_name` 과 동일 규칙) */
export function defaultKoreanReportName(fullName: string): string {
  const n = fullName.trim()
  if (n.length < 2) return n
  if (!/^[\uac00-\ud7a3]+$/.test(n)) return n
  if (n.length === 2) return n
  return n.slice(1)
}

function escapeRegExp(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

/** CJK 통합 한자 등(모델 오삽입) 제거 — 서버 `strip_cjk_ideographs_from_report_text` 와 동일 범위 */
export function stripCjkIdeographs(text: string): string {
  if (!text) return text
  const t = text.replace(/[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]/g, '')
  return t.replace(/ {2,}/g, ' ').trim()
}

/** 이름+이의/가의 오타를 이름+의 로 통일 (서버 `korean_postprocess` 와 동일 규칙) */
export function fixPossessiveGlitch(name: string, text: string): string {
  const n = name.trim()
  if (!n || !text) return text
  return text.replace(new RegExp(`${escapeRegExp(n)}(이의|가의)`, 'g'), `${n}의`)
}

function levenshtein(a: string, b: string): number {
  if (a === b) return 0
  const la = a.length
  const lb = b.length
  const dp = Array.from({ length: lb + 1 }, (_, j) => j)
  for (let i = 1; i <= la; i++) {
    let prev = dp[0]
    dp[0] = i
    for (let j = 1; j <= lb; j++) {
      const cur = Math.min(dp[j] + 1, dp[j - 1] + 1, prev + (a[i - 1] !== b[j - 1] ? 1 : 0))
      prev = dp[j]
      dp[j] = cur
    }
  }
  return dp[lb]
}

function hangulSyllableTriplet(ch: string): [number, number, number] | null {
  if (ch.length !== 1 || ch < '가' || ch > '힣') return null
  const o = ch.charCodeAt(0) - 0xac00
  const jong = o % 28
  const jung = Math.floor(o / 28) % 21
  const cho = Math.floor(o / 28 / 21)
  return [cho, jung, jong]
}

function tripletHammingSyllables(a: string, b: string): number | null {
  const ta = hangulSyllableTriplet(a)
  const tb = hangulSyllableTriplet(b)
  if (!ta || !tb) return null
  return (ta[0] !== tb[0] ? 1 : 0) + (ta[1] !== tb[1] ? 1 : 0) + (ta[2] !== tb[2] ? 1 : 0)
}

function nearMissAddressSpelling(address: string, chunk: string): boolean {
  if (address.length !== chunk.length || address.length < 2) return false
  if (!/^[\uac00-\ud7a3]+$/.test(address + chunk)) return false
  if (address === chunk) return false
  const diffI: number[] = []
  for (let i = 0; i < address.length; i++) {
    if (address[i] !== chunk[i]) diffI.push(i)
  }
  if (diffI.length !== 1) return false
  const ca = address[diffI[0]]
  const cb = chunk[diffI[0]]
  try {
    const ja = disassemble(ca)
    const jb = disassemble(cb)
    return levenshtein(ja, jb) <= 2
  } catch {
    /* fall through */
  }
  const th = tripletHammingSyllables(ca, cb)
  return th !== null && th <= 2
}

const NAME_CHUNK_RIGHT_GUARD =
  /^(?:은|는|이|가|을|를|과|와|으로|로|만|도|이랑|랑|하고|과의|,|\.|\)|]|}|…|"|'|「|」|:|$)/

/** 서버 `fix_address_name_hangul_near_miss` 와 동일 — 한 음절 자모 근접 오타를 호칭으로 복구 */
export function fixAddressNameHangulNearMiss(address: string, text: string): string {
  const addr = address.trim()
  const k = addr.length
  if (k < 2 || !/^[\uac00-\ud7a3]+$/.test(addr)) return text
  const n = text.length
  const out: string[] = []
  let i = 0
  while (i < n) {
    if (i + k <= n) {
      const chunk = text.slice(i, i + k)
      const rest = text.slice(i + k)
      const leftCh = i > 0 ? text[i - 1]! : ''
      const prevIsHangul = leftCh >= '가' && leftCh <= '힣'
      if (
        /^[\uac00-\ud7a3]+$/.test(chunk) &&
        nearMissAddressSpelling(addr, chunk) &&
        NAME_CHUNK_RIGHT_GUARD.test(rest) &&
        !prevIsHangul
      ) {
        out.push(addr)
        i += k
        continue
      }
    }
    out.push(text[i])
    i += 1
  }
  return out.join('')
}

const COLLAPSED_NAME_PARTICLE_RE =
  /(?<![\uac00-\ud7a3])([\uac00-\ud7a3])(은|는|이|가|을|를)(?![\uac00-\ud7a3])/g

function oneSyllableJamoNearMiss(correct: string, typo: string): boolean {
  if (correct.length !== 1 || typo.length !== 1) return false
  if (correct < '가' || correct > '힣' || typo < '가' || typo > '힣') return false
  if (correct === typo) return false
  try {
    return levenshtein(disassemble(correct), disassemble(typo)) <= 2
  } catch {
    /* fall through */
  }
  const th = tripletHammingSyllables(correct, typo)
  return th !== null && th <= 2
}

/** 서버 `fix_garbled_first_syllable_name_particle` — 믞은→민성은 (둘째 음절 누락 + 첫 음절 오타) */
export function fixGarbledFirstSyllableNameParticle(address: string, text: string): string {
  const addr = address.trim()
  if (addr.length < 2 || !/^[\uac00-\ud7a3]+$/.test(addr)) return text
  const topicP = topicEunNeun(addr).slice(addr.length)
  const subjP = subjectIGA(addr).slice(addr.length)
  const objP = objectEulReul(addr).slice(addr.length)
  const allowed = new Set([topicP, subjP, objP])
  return text.replace(COLLAPSED_NAME_PARTICLE_RE, (full, c: string, p: string) => {
    if (!allowed.has(p)) return full
    if (c === addr[0]) return full
    if (!oneSyllableJamoNearMiss(addr[0], c)) return full
    return addr + p
  })
}

/** 문장 주제로 쓸 때 은/는 (es-hangul) */
export function topicEunNeun(name: string): string {
  return josa(name.trim(), '은/는')
}

/** 주어로 쓸 때 이/가 (es-hangul) */
export function subjectIGA(name: string): string {
  return josa(name.trim(), '이/가')
}

/** 목적어 을/를 (es-hangul) — 이중 조사 교정용 */
function objectEulReul(name: string): string {
  return josa(name.trim(), '을/를')
}

/** 서버 `korean_postprocess._SUBJECT_GAP_PREFIXES` 와 동기화 */
const SUBJECT_GAP_PREFIXES: readonly string[] = [
  '점심시간에',
  '점심을',
  '점심에',
  '오후 간식',
  '간식을',
  '간식에',
  '간식 시간에',
  '낮잠을',
  '낮잠에',
  '낮잠 시간에',
  '낮잠시간에',
  '자유놀이에',
  '자유놀이를',
  '자유놀이',
  '교실 활동',
  '바깥 놀이',
  '실내놀이',
  '참여했',
  '참여하',
  '참여',
  '즐겼',
  '즐기',
  '즐겨',
  '먹었',
  '먹고',
  '먹으며',
  '잤',
  '자고',
  '자며',
  '자면',
  '자지',
  '놀았',
  '놀며',
  '놀고',
  '배웠',
  '읽었',
  '그렸',
  '만들었',
  '만들고',
  '듣고',
  '말했',
  '웃었',
  '울었',
  '있었',
  '없었',
  '많았',
  '적었',
  '나왔',
  '나와',
  '돌아',
  '움직',
  '보였',
  '잠을',
  '등원',
  '하원',
  '교실',
  '바깥',
  '실내',
  '활동',
  '표정',
]

/** 「호칭 + 공백 + 서술」에서 빠진 주격(이/가)만 보수적으로 보완 */
export function fixMissingSubjectJosaAfterName(name: string, text: string): string {
  const n = name.trim()
  if (!n || !text || !text.includes(n)) return text
  const subj = subjectIGA(n)
  const prefs = [...SUBJECT_GAP_PREFIXES].sort((a, b) => b.length - a.length)
  let t = text
  for (const pref of prefs) {
    const old = `${n} ${pref}`
    if (!t.includes(old)) continue
    t = t.split(old).join(`${subj} ${pref}`)
  }
  return t
}

/** 이름 뒤에 이/가·은/는 중 반대 형만 쓴 경우 교정 (es-hangul `josa` 규칙과 동일). */
export function fixWrongJosaParticlePair(name: string, text: string): string {
  const n = name.trim()
  if (!n || !text || !text.includes(n)) return text
  const subj = subjectIGA(n)
  const topic = topicEunNeun(n)
  const wrongSubj = n + (subj.endsWith('이') ? '가' : '이')
  const wrongTopic = n + (topic.endsWith('은') ? '는' : '은')
  let t = text
  if (wrongSubj !== subj) {
    t = t.split(wrongSubj).join(subj)
  }
  if (wrongTopic !== topic) {
    t = t.split(wrongTopic).join(topic)
  }
  return t
}

const CLASS_SCOPE_CANNOT_JUDGE_PHRASE = 'DB 만으로는 판단할 수 없'
const CLASS_SCOPE_NO_INDIVIDUAL_DATA_TEXT = '데이터가 없습니다'

const FORMAL_TAIL_PAIRS: [string, string][] = [
  ['없었다', '없었습니다'],
  ['있었다', '있었습니다'],
  ['같았다', '같았습니다'],
  ['드러났다', '드러났습니다'],
  ['가졌다', '가졌습니다'],
  ['였다', '였습니다'],
  ['나눴다', '나누었습니다'],
  ['봤다', '보았습니다'],
  ['줬다', '주었습니다'],
  ['됐다', '되었습니다'],
  ['일어났다', '일어났습니다'],
  ['잤다', '잤습니다'],
  ['했다', '했습니다'],
  ['었다', '었습니다'],
  ['았다', '았습니다'],
  ['보냈다', '보냈습니다'],
  ['지냈다', '지냈습니다'],
  ['한다', '합니다'],
  ['된다', '됩니다'],
  ['인다', '입니다'],
  ['없다', '없습니다'],
  ['있다', '있습니다'],
  ['좋다', '좋습니다'],
  ['많다', '많습니다'],
  ['싶다', '싶습니다'],
  ['같다', '같습니다'],
  ['맞다', '맞습니다'],
]

/** 서버 `formalize_parent_facing_report_korean` 와 동기 — 보호자용 존댓말 종결 */
export function formalizeParentFacingReportKorean(text: string): string {
  const raw = text.trim()
  if (!raw) return text
  if (raw === CLASS_SCOPE_NO_INDIVIDUAL_DATA_TEXT) return raw

  const oneSentence = (seg: string): string => {
    const s = seg.trim()
    if (!s) return seg
    if (s.replace(/[.。]\s*$/u, '').trim() === CLASS_SCOPE_NO_INDIVIDUAL_DATA_TEXT) return s
    const hadPeriod = /[.。]\s*$/u.test(s)
    let core = s.replace(/[.。]\s*$/u, '').trimEnd()
    if (!core) return seg
    let parenRest = ''
    const mParen = /(\s*\([^)]*\))(\s*[.。])?\s*$/u.exec(core)
    if (mParen) {
      parenRest = mParen[1] + (mParen[2] ?? '')
      core = core.slice(0, mParen.index).trimEnd()
    }
    if (!core) return seg
    if (
      /(습니다|입니다|습니까|입니까|드립니다|드리겠습니다|있습니다|없습니다)$/u.test(core)
    ) {
      return core + parenRest + (hadPeriod ? '.' : '')
    }
    let out = core
    for (const [plain, polite] of FORMAL_TAIL_PAIRS) {
      if (out.endsWith(plain)) {
        out = out.slice(0, -plain.length) + polite
        break
      }
    }
    if (out === core && /참여 미확인$/u.test(out)) {
      out = out.replace(/참여 미확인$/u, '참여 미확인입니다')
    }
    return out + parenRest + (hadPeriod ? '.' : '')
  }

  const parts = raw.split(/(?<=[.。])\s+/u)
  if (parts.length === 1) return oneSentence(parts[0])
  return parts.filter((p) => p.trim()).map(oneSentence).join(' ')
}

/** 저장·조회된 긴 class_scope DB 안내를 한 줄로 (서버 `collapse_legacy_class_scope_disclaimer` 와 동기) */
export function collapseLegacyClassScopeDisclaimer(text: string): string {
  const t = text.trim()
  if (!t) return t
  if (
    t.includes(CLASS_SCOPE_CANNOT_JUDGE_PHRASE) &&
    t.includes('실제 참여와 같다고 볼 수 없다')
  ) {
    return CLASS_SCOPE_NO_INDIVIDUAL_DATA_TEXT
  }
  if (
    t.includes('개별 하원·참여는 DB에 없어 확인할 수 없다') &&
    t.includes('실제 하원·참여와 같다고 볼 수 없다')
  ) {
    return CLASS_SCOPE_NO_INDIVIDUAL_DATA_TEXT
  }
  if (
    t.includes('개별 하원은 DB에 없다') &&
    t.includes('실제 하원·참여와 같다고 볼 수 없다')
  ) {
    return CLASS_SCOPE_NO_INDIVIDUAL_DATA_TEXT
  }
  return t
}

/** 「점심시간은 지나」→「점심시간이 지나」 등 시간 명사+지나다 패턴 */
export function fixReportTimeJosaArtifacts(text: string): string {
  if (!text) return text
  const pairs: [string, string][] = [
    ['점심시간은 지나', '점심시간이 지나'],
    ['낮잠시간은 지나', '낮잠시간이 지나'],
    ['휴식시간은 지나', '휴식시간이 지나'],
    ['점심 시간은 지나', '점심 시간이 지나'],
    ['낮잠 시간은 지나', '낮잠 시간이 지나'],
    ['휴식 시간은 지나', '휴식 시간이 지나'],
  ]
  let t = text
  for (const [w, r] of pairs) t = t.split(w).join(r)
  const jinaha: [string, string][] = [
    ['점심시간을 지나했다', '점심시간을 지냈다'],
    ['낮잠시간을 지나했다', '낮잠시간을 지냈다'],
    ['휴식시간을 지나했다', '휴식시간을 지냈다'],
    ['점심 시간을 지나했다', '점심 시간을 지냈다'],
    ['낮잠 시간을 지나했다', '낮잠 시간을 지냈다'],
    ['휴식 시간을 지나했다', '휴식 시간을 지냈다'],
    ['점심시간이 지나했다', '점심시간을 지냈다'],
    ['낮잠시간이 지나했다', '낮잠시간을 지냈다'],
    ['휴식시간이 지나했다', '휴식시간을 지냈다'],
    ['점심 시간이 지나했다', '점심 시간을 지냈다'],
    ['낮잠 시간이 지나했다', '낮잠 시간을 지냈다'],
    ['휴식 시간이 지나했다', '휴식 시간을 지냈다'],
  ]
  for (const [w, r] of jinaha) t = t.split(w).join(r)
  return t
}

/** 「호칭과 다른 아이들」→ 주어 호칭+이/가 */
export function fixNameGwaDifferentChildrenGlitch(name: string, text: string): string {
  const n = name.trim()
  if (!n || !text || !text.includes(n)) return text
  const subj = subjectIGA(n)
  let t = text
  const suffixes = [
    '아이들이',
    '아이들을',
    '아이들과',
    '아이들',
    '아이가',
    '아이와',
    '아이',
    '친구들과',
    '친구들',
    '친구',
  ] as const
  for (const suf of suffixes) {
    for (const spacer of [' ', ''] as const) {
      const wrong = `${n}과 다른${spacer}${suf}`
      const right = `${subj} 다른${spacer}${suf}`
      if (t.includes(wrong)) t = t.split(wrong).join(right)
    }
  }
  return t
}

/** 「호칭가 표정이 기록」→「호칭의 표정이 기록」(소유격; 주격 이/가 아님) */
export function fixExpressionRecordPossessivePhrase(name: string, text: string): string {
  const n = name.trim()
  if (!n || !text) return text
  return text.split(`${n}가 표정이 기록`).join(`${n}의 표정이 기록`)
}

/** 마침표로 나뉜 각 문장이 이름+이/가로 시작하면 이름+은/는로 통일 (타임라인·요약 톤) */
export function normalizeSubjectSentenceOpenersToTopic(name: string, text: string): string {
  const n = name.trim()
  if (!n || !text.includes(n)) return text
  const subj = subjectIGA(n)
  const topic = topicEunNeun(n)

  const patchLeading = (seg: string): string => {
    const s = seg.trim()
    if (!s.startsWith(subj)) return s
    const tail = s.slice(subj.length)
    if (tail && tail[0] !== ' ' && tail[0] !== '\n') return s
    const rest = tail.trimStart()
    if (rest.startsWith('아니')) return s
    return rest ? `${topic} ${rest}` : topic
  }

  const raw = text.trim()
  if (!raw.includes('.')) return patchLeading(raw)
  const segs = raw.split(/(?<=\.)\s+/)
  const out: string[] = []
  for (const x0 of segs) {
    const x = x0.trim()
    if (!x) continue
    const endsDot = x.endsWith('.')
    const body = endsDot ? x.slice(0, -1).trim() : x
    const p = patchLeading(body)
    out.push(endsDot ? `${p}.` : p)
  }
  return out.join(' ')
}

/** 이가·가가 이중 조사, 「이름의 친구」→주어+친구 등 흔한 오류만 교정 */
export function fixSubjectJosaArtifacts(name: string, text: string): string {
  const n = name.trim()
  if (!n || !text) return text
  const correct = subjectIGA(n)
  let t = text
  t = t.replace(new RegExp(`${escapeRegExp(n)}이가`, 'g'), correct)
  t = t.replace(new RegExp(`${escapeRegExp(n)}가가`, 'g'), correct)
  t = t.replace(new RegExp(`${escapeRegExp(n)}의 친구`, 'g'), `${correct} 친구`)
  return t
}

/** 이는·이을 등 주격+다른 조사 중첩 → 은/는·을/를 한 번만 (서버 `fix_stacked_josa_glitch` 와 동일) */
export function fixStackedJosaArtifacts(name: string, text: string): string {
  const n = name.trim()
  if (!n || !text) return text
  const topic = topicEunNeun(n)
  const obj = objectEulReul(n)
  const pairs: [string, string][] = [
    [`${n}이는`, topic],
    [`${n}가는`, topic],
    [`${n}이은`, topic],
    [`${n}가은`, topic],
    [`${n}은는`, topic],
    [`${n}는은`, topic],
    [`${n}이을`, obj],
    [`${n}가을`, obj],
    [`${n}이를`, obj],
    [`${n}가를`, obj],
  ]
  let t = text
  for (const [wrong, right] of pairs) {
    t = t.split(wrong).join(right)
  }
  return t
}

/** 프롬프트 제목을 본문에 반복하는 '오늘 포착된 표정…' 잔재 제거 (서버 `strip_photo_capture_heading_echo` 와 동기) */
export function stripPhotoCaptureHeadingEcho(text: string): string {
  if (!text.includes('포착된 표정')) return text
  let t = text
  t = t.replace(
    /^[\s\u200b]*(?:\*{1,2}\s*)?오늘\s*포착된\s*표정(?:\s*\*{1,2})?\s*[：:]\s*/u,
    '',
  )
  t = t.replace(/(?<=[。.])\s*(?:\*{1,2}\s*)?오늘\s*포착된\s*표정(?:\s*\*{1,2})?\s*[：:]\s*/gu, ' ')
  t = t.replace(/\s+(?:\*{1,2}\s*)?오늘\s*포착된\s*표정(?:\s*\*{1,2})?\s*[：:]\s*/gu, ' ')
  t = t.replace(
    /,?\s*오늘\s*포착된\s*표정에서\s*가장\s*행복해\s*보였(?:다|으며|고|습니다|습니까)?\.?/g,
    '',
  )
  t = t.replace(
    /,?\s*(?:[\uac00-\ud7a3]{1,10}의\s*감정(?:은|이)\s*)?오늘\s*포착된\s*표정과\s*유사했(?:다|으며|고|습니다|습니까)?\.?/g,
    '',
  )
  t = t.replace(/,?\s*오늘\s*포착된\s*표정와\s*유사했(?:다|으며|고|습니다|습니까)?\.?/g, '')
  t = t.replace(/,?\s*오늘\s*포착된\s*표정과도?\s*비슷했(?:다|으며|고|습니다|습니까)?\.?/g, '')
  if (t.includes('오늘 포착된 표정')) {
    t = t.replace(/,?\s*오늘\s*포착된\s*표정[^.\n]{1,80}(?:유사|비슷|행복해\s*보였)[^.\n]{0,30}/g, '')
  }
  return t
    .replace(/\s{2,}/g, ' ')
    .replace(/^\s*[,.]\s*/, '')
    .replace(/\s+[,.]\s*$/, '')
    .trim()
    .replace(/^[,.\s]+/g, '')
    .trim()
}

/** 서버 `fix_truncated_class_name_ideul` 과 동기 — 「햇님이들」→「햇님반 아이들」 */
export function fixTruncatedClassNameIdeul(className: string, text: string): string {
  const cls = className.trim()
  if (cls.length < 2 || !cls.endsWith('반')) return text
  const stem = cls.slice(0, -1)
  if (!stem || !/^[\uac00-\ud7a3]+$/.test(stem)) return text
  const pat = new RegExp(
    `${stem.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}이들(과|와|의|은|는|이|가|을|를)?`,
    'g',
  )
  return text.replace(pat, (_m, g1?: string) => `${cls} 아이들${g1 ?? ''}`)
}

/** 서버 `fix_class_name_as_timeline_subject` — 햇님반이 → 민성은 (class_scope 생략 = 조회 보정) */
export function fixClassNameAsTimelineSubject(
  addressName: string,
  className: string,
  text: string,
  classScope?: boolean | null,
): string {
  const c = addressName.trim()
  const cl = className.trim()
  if (!text || !c || !cl) return text
  let t = text.replace(/\s+/g, ' ').trim()
  const topic = topicEunNeun(c)
  if (cl.endsWith('반') && c + '반' !== cl) {
    t = t.replace(new RegExp(`${escapeRegExp(c)}반(?=\\s*아이들)`, 'g'), cl)
  }
  const repl = (_full: string, pre: string, _clm: string, _j: string, sp: string) => {
    const atLineStart = pre === ''
    if (classScope === true) {
      if (atLineStart) return `${topic} 참여 미확인. 「${cl}」 일과로${sp}`
      return `${pre}${topic} 「${cl}」 일과로${sp}`
    }
    return `${pre}${topic}${sp}`
  }
  const stacked = new RegExp(
    `(^|[。.]\\s*)(${escapeRegExp(cl)})(이는|가는|은는|는은|이은|가은)(\\s+)`,
    'g',
  )
  t = t.replace(stacked, repl)
  const pat = new RegExp(`(^|[。.]\\s*)(${escapeRegExp(cl)})(이|가|은|는)(\\s+)`, 'g')
  return t.replace(pat, repl)
}

/** 서버 `scrub_stale_summary_memo_phrase` 와 동기 — 구버전 요약 메타 문구 제거 */
export function scrubStaleSummaryMemoPhrase(text: string): string {
  if (!text || !text.includes('메모에 적힌')) return text
  const t = text.replace(/\s*메모에 적힌 바와 겹치는 점도 있었다\.\s*/g, ' ')
  return t.replace(/\s{2,}/g, ' ').trim()
}

/** 서버 `scrub_llm_emotion_score_and_paren_tags` 와 동기 — 요약·본문의 영문 감정 메타 잔재 제거 */
export function scrubLlmEmotionScoreAndParenTags(text: string): string {
  if (!text) return text
  let t = text
  t = t.replace(
    /(?:,\s*)?\s*\b[a-z][a-z0-9_-]{0,24}\s*\(\s*강도\s*[\d.]+\)(?:\s*의\s*표정을\s*(?:지었(?:습니다|다|으며)|지으며))?/gi,
    '',
  )
  t = t.replace(
    /\s*\(\s*(?:basic|hello|happy|fun|interest|bored|sad|angry|sleep)(?:\s*,\s*[a-z0-9_-]+)*\s*\)/gi,
    '',
  )
  t = t.replace(/였고의\s*표정을\s*(?:지었(?:습니다|다|으며)|지으며)/gu, '였고')
  t = t.replace(/했고의\s*표정을\s*(?:지었(?:습니다|다|으며)|지으며)/gu, '했고')
  t = t.replace(/았고의\s*표정을\s*(?:지었(?:습니다|다|으며)|지으며)/gu, '았고')
  t = t.replace(/었고의\s*표정을\s*(?:지었(?:습니다|다|으며)|지으며)/gu, '었고')
  t = t.replace(/,\s*\./g, '.')
  t = t.replace(/\s+\./g, '.')
  t = t.replace(/\s{2,}/g, ' ')
  return t.trim()
}

/** 서버 `fix_common_report_korean_typos` 와 동기 */
export function fixCommonReportKoreanTypos(text: string): string {
  if (!text) return text
  let t = text.split('노았습니다').join('놀았습니다').split('노았으며').join('놀았으며').split('노았고').join('놀았고')
  t = t.split('표정우로').join('표정으로')
  t = t.replace(
    /(점심|오전 간식|오후 간식|간식)을\s*먹습니다(?=\s|[(.]|$)/gu,
    '$1을 먹었습니다',
  )
  return t
}

/** 서버 `scrub_participation_disclaimer_attendance_verbs` 와 동기 */
export function scrubParticipationDisclaimerAttendanceVerbs(text: string): string {
  if (!text || !text.includes('참여 미확인')) return text
  let t = text.replace(/\s+/g, ' ').trim()
  if (/등원했(?:습니다)?/u.test(t)) {
    t = t.replace(
      /일과로\s*등원했(?:습니다)?/u,
      '일과로 등원 시간대에 맞춰 반 친구들과 하루를 여는 흐름이 있었습니다',
    )
  }
  if (/하원했(?:습니다)?/u.test(t)) {
    t = t.replace(
      /일과로\s*하원했(?:습니다)?/u,
      '일과로 하원·통합 보육 시간에 맞춰 반에서 마무리를 준비하는 흐름이 있었습니다',
    )
  }
  return t
}

/** 서버 `dedupe_adjacent_name_subject_markers` 와 동기 — 지수는 지수는 → 지수는 */
export function dedupeAdjacentNameSubjectMarkers(name: string, text: string): string {
  const n = name.trim()
  if (!n || !text.includes(n)) return text
  const topic = topicEunNeun(n)
  const subj = subjectIGA(n)
  let t = text
  if (topic.length >= 2) {
    const reT = new RegExp(`${escapeRegExp(topic)}[,，]?\\s*${escapeRegExp(topic)}`)
    for (;;) {
      const next = t.replace(reT, topic)
      if (next === t) break
      t = next
    }
  }
  if (subj.length >= 2 && subj !== topic) {
    const reS = new RegExp(`${escapeRegExp(subj)}[,，]?\\s*${escapeRegExp(subj)}`)
    for (;;) {
      const next = t.replace(reS, subj)
      if (next === t) break
      t = next
    }
  }
  return t
}

/** 서버 `fix_garbled_meogeul_name_food_phrase` 와 동기 */
export function fixGarbledMeogeulNameFoodPhrase(name: string, text: string): string {
  const n = name.trim()
  if (!n || !text) return text
  return text.replace(new RegExp(`먹을\\s+${escapeRegExp(n)}(이|가)\\s+풍성`, 'g'), '먹거리가 풍성')
}

/** 보고서 본문용 — 소유격 오타 + 주격/친구 + 이중 조사 + 생략된 주격 + 한자 제거 (호칭 문자열과 동일하게 넘길 것) */
export function polishReportKorean(
  addressName: string,
  text: string,
  className: string = '',
  classScope?: boolean | null,
): string {
  const n = addressName.trim()
  if (!text) return text
  let t = collapseLegacyClassScopeDisclaimer(text)
  t = fixReportTimeJosaArtifacts(t)
  t = fixCommonReportKoreanTypos(t)
  t = scrubLlmEmotionScoreAndParenTags(t)
  t = scrubParticipationDisclaimerAttendanceVerbs(t)
  t = fixTruncatedClassNameIdeul(className, t)
  t = fixClassNameAsTimelineSubject(n, className, t, classScope)
  t = stripPhotoCaptureHeadingEcho(t)
  if (!n) {
    t = formalizeParentFacingReportKorean(t)
    return stripCjkIdeographs(fixPossessiveGlitch('', t))
  }
  t = fixExpressionRecordPossessivePhrase(n, t)
  t = fixAddressNameHangulNearMiss(n, t)
  t = fixGarbledFirstSyllableNameParticle(n, t)
  t = fixPossessiveGlitch(n, t)
  t = fixWrongJosaParticlePair(n, t)
  t = fixNameGwaDifferentChildrenGlitch(n, t)
  t = fixSubjectJosaArtifacts(n, t)
  t = fixStackedJosaArtifacts(n, t)
  t = fixMissingSubjectJosaAfterName(n, t)
  t = normalizeSubjectSentenceOpenersToTopic(n, t)
  t = fixGarbledMeogeulNameFoodPhrase(n, t)
  t = dedupeAdjacentNameSubjectMarkers(n, t)
  t = scrubStaleSummaryMemoPhrase(t)
  t = formalizeParentFacingReportKorean(t)
  return stripCjkIdeographs(t)
}
