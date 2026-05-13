# shared/openarm_greeting

등하원 인사 모션 슬롯. 두 개 고정: `morning.yaml`, `evening.yaml`. 곡 없음, 모션만.

## 형식

```yaml
name: morning
kind: greeting
joint_names: [joint_1, joint_2, joint_3, joint_4, joint_5, joint_6, joint_7, gripper]
keyframes:
  - { t: 0.000, pos: [0.0, -0.5, 0.0, 1.2, 0.0, 0.7, 0.0, 0.3] }
  - { t: 0.050, pos: [...] }
```

좌표·단위: rad (gripper 만 0~1 정규화). 시간은 초.

## 트리거

`useModeStore.currentMode` 가 `'등원'` 으로 바뀌면 → `POST /api/eduping/greeting/morning/play` 자동 호출. `'하원'` 도 동일.

## 재녹화

robot UI 의 "👋 등하원 인사 설정" 화면에서. 슬롯 덮어쓰기.
