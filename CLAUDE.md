# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 프로젝트 개요

Addinedu 4기 최종 프로젝트 — **pingdergarten**. 유치원에서 아이와 놀아주고 교사를 보조하는 교육보조로봇 서비스. OpenArm(놀이·정리정돈), Pinky(등하원·교사 추종·운반·놀이), OMX 3대(교실 비치·Pinky 양팔)로 구성된 로봇이 등원부터 하원까지 하루 일과를 함께한다.

- 팀명: 사랑의 에듀핑
- 프로젝트명: pingdergarten
- 팀: 6명
- 기간: 2026-04-23 ~ 2026-06-04 (약 7주)
- 진행 단계: 시뮬레이션 검증 → 실물 이전
- 현재 상태: 요구사항 정의 단계 (코드 미작성)

## 구현 완료 항목 관리

[docs/implementation-plan.md](docs/implementation-plan.md) 의 SR 이 **완전히** 구현되면 다음을 같은 commit 으로 처리한다:

1. 해당 SR 행을 [docs/implemented.md](docs/implemented.md) 의 동일 섹션 헤딩 아래로 옮긴다.
2. 옮긴 행에 `구현 위치` (코드 경로) 와 `완료일` (YYYY-MM-DD) 컬럼을 추가한다.
3. `implementation-plan.md` 에서 해당 행을 삭제한다. 섹션의 모든 SR 이 옮겨졌다면 섹션 본문에 `> 구현 완료 — [implemented.md](implemented.md) 참조` 한 줄만 남긴다.

부분 구현은 옮기지 않는다. UI 만 완료, ROS2 publish 가 남은 식이라면 plan 에 그대로 두고, 모든 부분이 끝났을 때 한 번에 이동한다.

## ROS 환경

- 사용 가능한 ROS_DOMAIN_ID: **201 ~ 219**
- 팀원 간 충돌을 피하기 위해 각자 할당된 ID를 사용한다.

## Python 환경

의존성은 **루트 [pyproject.toml](pyproject.toml) 하나**로 통합 관리한다.

- 설치: `conda run -n jazzy pip install -e .` (프로젝트 루트에서 실행)
- 새 의존성 추가 시 `pyproject.toml` 의 `[project.dependencies]` 에 추가한다.
- `venv`, `uv` 등 별도 가상환경을 생성하지 않는다. `.venv/`, `uv.lock` 파일을 만들지 않는다.
- 서비스별 `requirements.txt` 나 `pyproject.toml` 을 새로 만들지 않는다.

## 테스트

유닛테스트를 새로 만들 때마다 [scripts/test.sh](scripts/test.sh) 에 해당 테스트 실행 명령을 추가한다. `test.sh` 는 프로젝트 전체 테스트를 한 번에 돌릴 수 있는 단일 진입점이다.

## 참조 문서

상세 문서 목록은 [docs/CLAUDE.md](docs/CLAUDE.md). Confluence 동기화는 [scripts/CLAUDE.md](scripts/CLAUDE.md).
