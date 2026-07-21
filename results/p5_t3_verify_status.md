# P5 T3 검증 상태 (독립 검증, commit 65df3b6)

검증자: p5-t3-verify (sonnet)
검증 완료: 2026-07-21

## 판정: 전 항목 PASS

| # | 주장 | 판정 | 증거 |
|---|------|------|------|
| 1 | 진폭비율 avg-avg = 0.7616, FAIL | PASS(주장 확인됨) | 독립 재계산: Icepak amp=100.16903221-67.87095023=32.298082K, 3D-ICE amp=125.601-101.004=24.597K, ratio=threedice_amp/icepak_amp=0.761562 (T1 `amp_ratio_a = threedice_amp_a/icepak_amp_a` 정의와 방향 일치, `scripts/p4_t4_crossval_hypotheses.py:90`) |
| 2 | B-S0는 base_die_phy 없어 base_die로 폴백 | PASS | `results/p4_icepak_scenarios/p4_icepak_b_s0.csv` 실측: base_die_phy 행 없음, base_die avg=67.8709502314613만 존재. b_s2.csv에는 base_die_phy=100.16903221022895 존재 |
| 2b | (추가 검증) 라벨 페어링 대칭성 — 3D-ICE도 동일 패턴인지 | PASS | `p4_3dice_t4_results.csv` series=B,s0_uniform: base_die_phy 행 없음(균일시나리오라 phy/tsva/da 분할 없음), base_die=101.004 단일행. s2_phy_heavy: base_die_phy=125.601 존재. 양쪽 솔버 모두 S0=합성/균일 앵커, S2=physical 앵커로 **동일 구조** — 비대칭 아님 |
| 3 | comparison.py의 compare_die_temperatures()는 이미 avg-avg 비교축 | PASS | 소스 직접 열람(`hbm_thermal/comparison.py:28-66`): `diff_c = threedice_avg - icepak_avg`, `icepak_avg`는 `icepak_results[die]`의 튜플 중 avg만 사용 — max 미사용 확인 |
| 4 | pytest 304/304 통과, 회귀 0 | PASS | `/usr/bin/python3 -m pytest tests/ -q` → "304 passed in 2.23s", 에러/실패 0 |
| 5 | p4_t4_crossval.csv는 +1행만 | PASS | `git show 65df3b6 -- results/p4_t4_crossval.csv` diff: `+G4_B계열_진폭비율_avg대avg_T3,0.7616,...` 1행만 추가, 기존 행 무변경 |

## 추가 확인
- `scripts/p5_t3_bottomsink_avgavg.py --dry-run` 실행 결과: 콘솔 출력 0.7616 재현 완전 일치, "[스킵] ... 이미 존재 — 중복 append 방지" 메시지로 idempotent 가드 실동작 확인, `git status --short` 실행 전후 트리 무변경(스크립트 관련 파일 diff 없음)
- 음성 케이스 테스트 존재: `test_missing_die_raises`, `test_raises_when_neither_present`(S0 앵커 둘다 없을때), `test_idempotent_skip_when_row_already_exists`, `test_dry_run_does_not_write`, `test_appends_when_csv_does_not_exist_yet`, gate 경계값(0.9/1.1 양끝 PASS) — 형식적 테스트 아님, 실질 커버리지

## 특기사항
- 팀리드가 주의하라고 지시한 "S0 앵커 비대칭성" 우려는 조사 결과 기각됨: Icepak과 3D-ICE 양쪽 모두 S0에서 동일하게 "합성/균일 base_die" 폴백을 쓰고 S2에서 동일하게 "base_die_phy"를 씀 — 페어링 일치, FAIL 사유 아님.
- 비율 계산 방향(threedice_amp/icepak_amp)이 T1과 일관되므로 0.7616 수치 자체의 타당성은 방법론적으로 이상 없음. B계열의 FAIL은 통계축 문제가 아니라 실제 물리/모델 불일치로 보는 스크립트의 결론이 타당.

## 최종 판정
전체 PASS. commit 65df3b6의 5개 핵심 주장 모두 독립 재현·검증됨. 파일 수정/커밋 없음(본 상태 파일만 신규 작성).
