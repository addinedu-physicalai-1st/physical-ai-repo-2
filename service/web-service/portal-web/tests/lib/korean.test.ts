import { describe, expect, it } from 'vitest'
import {
  collapseLegacyClassScopeDisclaimer,
  defaultKoreanReportName,
  formalizeParentFacingReportKorean,
  fixAddressNameHangulNearMiss,
  fixCommonReportKoreanTypos,
  fixExpressionRecordPossessivePhrase,
  fixMissingSubjectJosaAfterName,
  fixNameGwaDifferentChildrenGlitch,
  fixPossessiveGlitch,
  fixReportTimeJosaArtifacts,
  fixStackedJosaArtifacts,
  fixSubjectJosaArtifacts,
  fixWrongJosaParticlePair,
  fixGarbledFirstSyllableNameParticle,
  fixTruncatedClassNameIdeul,
  fixClassNameAsTimelineSubject,
  polishReportKorean,
  scrubLlmEmotionScoreAndParenTags,
  scrubParticipationDisclaimerAttendanceVerbs,
  stripPhotoCaptureHeadingEcho,
  stripCjkIdeographs,
  subjectIGA,
  topicEunNeun,
} from '@/lib/korean'

describe('fixPossessiveGlitch', () => {
  it('corrects 이의 after a consonant-final name', () => {
    expect(fixPossessiveGlitch('박우림', '박우림이의 일상은')).toBe('박우림의 일상은')
  })

  it('corrects 가의 after a vowel-final name', () => {
    expect(fixPossessiveGlitch('민주', '민주가의 하루')).toBe('민주의 하루')
  })

  it('leaves correct possessive alone', () => {
    expect(fixPossessiveGlitch('박우림', '박우림의 일상')).toBe('박우림의 일상')
  })
})

describe('defaultKoreanReportName', () => {
  it('strips one syllable when 3+ hangul', () => {
    expect(defaultKoreanReportName('박우림')).toBe('우림')
  })

  it('keeps two hangul', () => {
    expect(defaultKoreanReportName('지수')).toBe('지수')
  })
})

describe('topicEunNeun', () => {
  it('picks 은/는 from es-hangul', () => {
    expect(topicEunNeun('박우림')).toMatch(/박우림은$/)
  })
})

describe('subjectIGA', () => {
  it('uses 이 after batchim-final name', () => {
    expect(subjectIGA('민성')).toBe('민성이')
  })
})

describe('fixWrongJosaParticlePair', () => {
  it('fixes 받침 이름 + 가 → 이', () => {
    expect(fixWrongJosaParticlePair('우림', '우림가 등원했다.')).toBe('우림이 등원했다.')
  })

  it('fixes 무받침 이름 + 이 → 가', () => {
    expect(fixWrongJosaParticlePair('민주', '민주이 왔다.')).toBe('민주가 왔다.')
  })

  it('fixes 받침 이름 + 는 → 은', () => {
    expect(fixWrongJosaParticlePair('우림', '우림는 즐거웠다.')).toBe('우림은 즐거웠다.')
  })
})

describe('formalizeParentFacingReportKorean', () => {
  it('converts plain endings to 합쇼체 per sentence', () => {
    expect(formalizeParentFacingReportKorean('우림은 간식을 먹었다. 하루를 보냈다.')).toBe(
      '우림은 간식을 먹었습니다. 하루를 보냈습니다.',
    )
  })

  it('leaves 데이터가 없습니다 unchanged', () => {
    expect(formalizeParentFacingReportKorean('데이터가 없습니다')).toBe('데이터가 없습니다')
  })

  it('appends 입니다 after 참여 미확인 clause', () => {
    expect(formalizeParentFacingReportKorean('민성은 참여 미확인. 「햇님반」 일과로 놀았다.')).toBe(
      '민성은 참여 미확인입니다. 「햇님반」 일과로 놀았습니다.',
    )
  })

  it('handles irregular past stems and trailing parenthetical', () => {
    expect(formalizeParentFacingReportKorean('친구와 이야기도 나눴다.')).toBe(
      '친구와 이야기도 나누었습니다.',
    )
    expect(formalizeParentFacingReportKorean('낮잠을 잤다.')).toBe('낮잠을 잤습니다.')
    expect(formalizeParentFacingReportKorean('낮잠 시간이 지나 일어났다.')).toBe(
      '낮잠 시간이 지나 일어났습니다.',
    )
    expect(formalizeParentFacingReportKorean('활동을 마무리했다 (happy).')).toBe(
      '활동을 마무리했습니다 (happy).',
    )
    expect(formalizeParentFacingReportKorean('(메뉴) 점심시간을 가졌다.')).toBe(
      '(메뉴) 점심시간을 가졌습니다.',
    )
    expect(formalizeParentFacingReportKorean('두 모습이 번갈아 드러났다.')).toBe(
      '두 모습이 번갈아 드러났습니다.',
    )
  })
})

describe('fixReportTimeJosaArtifacts', () => {
  it('fixes 점심시간은 지나 → 점심시간이 지나', () => {
    expect(fixReportTimeJosaArtifacts('점심시간은 지나 휴식')).toBe('점심시간이 지나 휴식')
  })

  it('fixes 점심시간을 지나했다 → 점심시간을 지냈다', () => {
    expect(fixReportTimeJosaArtifacts('민성은 점심시간을 지나했다.')).toBe('민성은 점심시간을 지냈다.')
  })

  it('fixes 점심시간이 지나했다 → 점심시간을 지냈다', () => {
    expect(
      fixReportTimeJosaArtifacts('우림은 참여 미확인. 「햇님반」 일과로 점심시간이 지나했다.'),
    ).toBe('우림은 참여 미확인. 「햇님반」 일과로 점심시간을 지냈다.')
  })
})

describe('collapseLegacyClassScopeDisclaimer', () => {
  it('collapses long DB disclaimer to a single line', () => {
    const long =
      '오늘 … DB 만으로는 판단할 수 없다. … 실제 참여와 같다고 볼 수 없다.'
    expect(collapseLegacyClassScopeDisclaimer(long)).toBe('데이터가 없습니다')
  })

  it('collapses legacy class-scope dismissal block', () => {
    const long =
      '민성은 개별 하원·참여는 DB에 없어 확인할 수 없다. … 실제 하원·참여와 같다고 볼 수 없다.'
    expect(collapseLegacyClassScopeDisclaimer(long)).toBe('데이터가 없습니다')
  })

  it('leaves normal sentences alone', () => {
    expect(collapseLegacyClassScopeDisclaimer('민성은 놀았다.')).toBe('민성은 놀았다.')
  })
})

describe('fixNameGwaDifferentChildrenGlitch', () => {
  it('fixes 호칭과 다른 아이들 → 주격 + 다른 아이들', () => {
    expect(fixNameGwaDifferentChildrenGlitch('민성', '민성과 다른 아이들과 놀았다.')).toBe(
      '민성이 다른 아이들과 놀았다.',
    )
  })
})

describe('fixSubjectJosaArtifacts', () => {
  it('fixes 이가 doubling', () => {
    expect(fixSubjectJosaArtifacts('민성', '민성이가 놀았다.')).toBe('민성이 놀았다.')
  })

  it('replaces 의 친구 with subject + 친구', () => {
    expect(fixSubjectJosaArtifacts('민성', '민성의 친구들과')).toBe('민성이 친구들과')
  })
})

describe('fixExpressionRecordPossessivePhrase', () => {
  it('uses possessive 의 before 표정이 기록', () => {
    expect(fixExpressionRecordPossessivePhrase('정우', '정우가 표정이 기록되었다.')).toBe(
      '정우의 표정이 기록되었다.',
    )
  })
})

describe('fixAddressNameHangulNearMiss', () => {
  it('fixes 므성 → 민성 (one-syllable jamo typo)', () => {
    const s = '점심시간이 지나 므성은 햇님반 친구들과 놀이를 했다.'
    expect(fixAddressNameHangulNearMiss('민성', s)).toBe(
      '점심시간이 지나 민성은 햇님반 친구들과 놀이를 했다.',
    )
  })

  it('does not corrupt 표정으로 inside a compound when address is 정우', () => {
    const s = '정우는 행복한 표정으로 마무리했습니다.'
    expect(fixAddressNameHangulNearMiss('정우', s)).toBe(s)
  })
})

describe('polishReportKorean', () => {
  it('fixes 가 표정이 기록 → 의 표정이 기록 in chain', () => {
    expect(polishReportKorean('정우', '정우가 표정이 기록되었다 (happy).')).toBe(
      '정우의 표정이 기록되었습니다.',
    )
  })

  it('chains possessive and subject fixes', () => {
    const raw = '민성이의 날에 민성의 친구들과'
    expect(polishReportKorean('민성', raw)).toBe('민성의 날에 민성이 친구들과')
  })

  it('inserts missing 이/가 then unifies sentence opener to 은/는', () => {
    expect(polishReportKorean('민성', '민성 참여했습니다.')).toBe('민성은 참여했습니다.')
  })

  it('fixes 과 다른 아이들 and time+jina', () => {
    const s = '민성과 다른 아이들과 놀았다. 민성은 점심시간은 지나 쉬었다.'
    expect(polishReportKorean('민성', s)).toBe(
      '민성은 다른 아이들과 놀았습니다. 민성은 점심시간이 지나 쉬었습니다.',
    )
  })
})

describe('fixCommonReportKoreanTypos', () => {
  it('rewrites meal present polite to past (server parity)', () => {
    expect(fixCommonReportKoreanTypos('점심을 먹습니다 (닭).')).toBe('점심을 먹었습니다 (닭).')
    expect(fixCommonReportKoreanTypos('오후 간식을 먹습니다.')).toBe('오후 간식을 먹었습니다.')
  })

  it('repairs 표정우로 → 표정으로 (near-miss merge artifact)', () => {
    expect(fixCommonReportKoreanTypos('행복한 표정우로 마무리했습니다.')).toBe(
      '행복한 표정으로 마무리했습니다.',
    )
  })
})

describe('scrubLlmEmotionScoreAndParenTags', () => {
  it('removes inline grade and 지으며 tail (server parity)', () => {
    const s =
      '자유놀이와 교실 활동을 하였고 happy (강도 1.00)의 표정을 지으며 즐거운 낮잠을 잤습니다.'
    expect(scrubLlmEmotionScoreAndParenTags(s)).toBe(
      '자유놀이와 교실 활동을 하였고 즐거운 낮잠을 잤습니다.',
    )
  })
})

describe('scrubParticipationDisclaimerAttendanceVerbs', () => {
  it('removes contradictory 등원 completion when disclaimer is present', () => {
    const s = '참여 미확인입니다. 「햇님반」 일과로 등원했습니다.'
    expect(scrubParticipationDisclaimerAttendanceVerbs(s)).not.toContain('등원했습니다')
  })

  it('chains through polishReportKorean', () => {
    expect(
      polishReportKorean('영주', '참여 미확인입니다. 「햇님반」 일과로 등원했습니다.'),
    ).not.toContain('등원했습니다')
  })
})

describe('fixMissingSubjectJosaAfterName', () => {
  it('uses es-hangul josa for the subject form', () => {
    expect(fixMissingSubjectJosaAfterName('민주', '민주 참여')).toBe('민주가 참여')
  })
})

describe('stripPhotoCaptureHeadingEcho', () => {
  it('removes leading **오늘 포착된 표정:** section title', () => {
    const raw = '**오늘 포착된 표정:** 영주는 친구들과 뛰었습니다.'
    const out = stripPhotoCaptureHeadingEcho(raw)
    expect(out).not.toContain('포착')
    expect(out).toContain('영주')
  })

  it('removes 행복해 보였으며 clause (보였 and ending split)', () => {
    const s =
      '정우는 점심을 먹었다. 정우는 오늘 포착된 표정에서 가장 행복해 보였으며 식사에 집중했다.'
    expect(stripPhotoCaptureHeadingEcho(s)).toBe('정우는 점심을 먹었다. 정우는 식사에 집중했다.')
  })

  it('removes emotion+유사 clause without eating rest of sentence', () => {
    const s =
      '정우의 감정은 오늘 포착된 표정과 유사했다. 정우는 오후 놀이를 즐겼다.'
    expect(stripPhotoCaptureHeadingEcho(s)).toBe('정우는 오후 놀이를 즐겼다.')
  })
})

describe('stripCjkIdeographs', () => {
  it('removes CJK ideographs from mixed text', () => {
    expect(stripCjkIdeographs('안详하게')).toBe('안하게')
  })
})

describe('fixStackedJosaArtifacts', () => {
  it('collapses 이는 into 은/는 only', () => {
    expect(fixStackedJosaArtifacts('민성', '민성이는 간식을')).toBe('민성은 간식을')
  })

  it('chains in polishReportKorean after 이가 fix and dedupes repeated topic', () => {
    expect(polishReportKorean('민성', '민성이가 민성이는')).toBe('민성은')
  })
})

describe('fixClassNameAsTimelineSubject', () => {
  it('rewrites 햇님반이 to child topic', () => {
    expect(fixClassNameAsTimelineSubject('민성', '햇님반', '햇님반이 점심을 먹었다')).toBe(
      '민성은 점심을 먹었다',
    )
    expect(polishReportKorean('민성', '햇님반이 점심을 먹었다', '햇님반')).toContain('민성은')
  })

  it('rewrites 햇님반이는 (stacked particles) in class_scope mode', () => {
    expect(
      fixClassNameAsTimelineSubject(
        '우림',
        '햇님반',
        '햇님반이는 낮잠을 자고 휴식을 했다.',
        true,
      ),
    ).toBe('우림은 참여 미확인. 「햇님반」 일과로 낮잠을 자고 휴식을 했다.')
  })
})

describe('fixTruncatedClassNameIdeul', () => {
  it('expands 햇님이들 to 햇님반 아이들 when class ends with 반', () => {
    expect(fixTruncatedClassNameIdeul('햇님반', '민성은 햇님이들과 점심')).toBe(
      '민성은 햇님반 아이들과 점심',
    )
    expect(polishReportKorean('민성', '민성은 햇님이들과 점심', '햇님반')).toContain('햇님반 아이들')
  })
})

describe('fixGarbledFirstSyllableNameParticle', () => {
  it('restores 믞은 → 민성은 when address is two syllables', () => {
    const s = '점심시간이 지나 믞은 점심을 먹었다'
    expect(fixGarbledFirstSyllableNameParticle('민성', s)).toBe(
      '점심시간이 지나 민성은 점심을 먹었다',
    )
  })

  it('chains in polishReportKorean', () => {
    expect(
      polishReportKorean('민성', '점심시간이 지나 믞은 점심을 먹었다'),
    ).toContain('민성은')
  })
})

describe('polishReportKorean summary scrub', () => {
  it('drops stale memo-meta phrase from display polish', () => {
    const s =
      '지수는 하원했다. 지수는 햇님반에서 메모에 적힌 바와 겹치는 점도 있었다. 엘리베이터를 좋아한다.'
    expect(polishReportKorean('지수', s)).not.toContain('메모에 적힌')
    expect(polishReportKorean('지수', s)).toContain('엘리베이터')
  })

  it('dedupes 지수는 지수는 in summary-style text', () => {
    const s = '엘리베이터를 좋아하는 경향이 지수는 지수는 활동에 적극적이었다.'
    const out = polishReportKorean('지수', s)
    expect(out).not.toContain('지수는 지수는')
    expect(out).toContain('지수는 활동에')
  })

  it('fixes 노았습니다 → 놀았습니다', () => {
    expect(polishReportKorean('강택', '강택은 떡을 좋아하며 노았습니다.')).toContain('놀았습니다')
  })

  it('fixes 먹을 강택이 풍성 glitch', () => {
    const s =
      '점심과 오후 간식에는 닭곰탕, 쌀밥 등 먹을 강택이 풍성했지만, 등원과 하원의 정확한 시간은 확인되지 않았습니다.'
    expect(polishReportKorean('강택', s)).toContain('먹거리가 풍성')
    expect(polishReportKorean('강택', s)).not.toContain('먹을 강택이')
  })
})
