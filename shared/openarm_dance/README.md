# shared/openarm_dance

율동 라이브러리. 한 율동 = 한 디렉토리 (`<slug>/`) 안에 곡(`song.{mp3,wav,m4a}`) + 모션(`motion.yaml`) + 메타(`meta.json`) 페어.

## 구조

```
openarm_dance/
└── <slug>/
    ├── song.mp3          # 곡 파일 (또는 .wav/.m4a)
    ├── motion.yaml       # 키프레임 trajectory (아래 형식)
    └── meta.json         # {display_name, duration_s, recorded_at, sample_hz}
```

`<slug>` 은 ASCII 소문자/숫자/하이픈만 (URL-safe). 표시명은 `meta.json.display_name` 에서.

## motion.yaml 형식

```yaml
name: bear
kind: dance
joint_names: [joint_1, joint_2, joint_3, joint_4, joint_5, joint_6, joint_7, gripper]
keyframes:
  - { t: 0.000, pos: [0.0, -0.5, 0.0, 1.2, 0.0, 0.7, 0.0, 0.3] }
  - { t: 0.050, pos: [0.0, -0.49, 0.0, 1.21, 0.01, 0.71, 0.0, 0.3] }
  # ... 50Hz 또는 키프레임 추출 후
```

좌표·단위: rad (gripper 만 0~1 정규화). 시간은 초.

## 추가/삭제

robot UI 의 "🎵 율동 등록" 화면에서. 직접 파일 편집 비권장.
