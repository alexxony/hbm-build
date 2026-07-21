# P5+ 정리 3건 진행 상태

시작: 2026-07-21, WSL repo HEAD 1d2cb5b (착수 시점)

## 작업 A — T1 idempotency 가드 이식
상태: 완료
- `scripts/p5_t1_amplitude_recheck.py`에 T3와 동일 패턴 이식: argparse `--dry-run` + `ROW_LABEL` 상수 + `append_crossval_row`가 기존 라벨 스캔 후 skip(bool 반환).
- 계산 로직 무변경 확인: 실행 결과 비율 1.0137 동일(재검증 완료).
- `tests/test_p5_t1_amplitude_recheck.py`에 T3 패턴과 동일한 idempotent 스킵/dry-run 무쓰기/CSV 미존재 음성 케이스 3건 추가.
- pytest 34 passed(T1+T3 합산). 실행→재실행→dry-run 3연속 실측: `results/p4_t4_crossval.csv` git diff 0(스크립트/테스트 파일만 변경).

## 작업 B — 스테일 CSV 4건 (Windows 클론)
상태: 완료
- Windows 클론 HEAD=82aab40, WSL HEAD=1d2cb5b — 82aab40은 WSL HEAD의 ancestor(클론이 7커밋 뒤처짐, 발산 아님). untracked 4건 전부 실제 untracked 확인.
- `results/p3_icepak_s{0,1,2}.csv` (루트 아님, results/ 직속) — 추적본 `results/p3_icepak_scenarios/p3_icepak_s{0,1,2}.csv`와 CRLF 정규화 diff 완전 동일(IDENTICAL) 확인 → 삭제.
- `hbm2e_die_temperatures.csv`(루트) — 직접 추적 대응본 없음(mtime 2026-07-13). 값이 `results/icepak_vs_3dice_comparison.csv`(커밋 3dc945b, "Task 4: 3D-ICE 교차검증")의 icepak_avg_c/icepak_max_c 열과 14자리 이상 일치 확인 — 이미 병합·커밋된 P1~P4 시절 원시 Icepak 산출물로 판단, 완전 대체됨 → 삭제.
- 4건 모두 `git status --short` 재확인으로 삭제 완료 검증.

## 작업 C — 러너 로그 표준화
상태: 완료
- `scripts/run_icepak_case.sh`: `RESULTS_DIR="results/p4_icepak_scenarios"` → `LOG_DIR="logs"`(repo 루트), 로그 경로 `$LOG_DIR/${RUN_NAME}.log`로 변경. 헤더 주석 갱신.
- `.gitignore`에 `/logs/` 추가(신규 디렉터리, 기존 파일과 basename 충돌 없음 — 안전).
- `bash -n scripts/run_icepak_case.sh` 통과.
- `git ls-files | git check-ignore --stdin` = 0건(추적 파일 오염 없음).
- Windows 클론 레거시 untracked `run_*.log` 6건 확인, **삭제·ignore 미적용**(지시대로 유지): `results/p4_icepak_scenarios/run_a_s0_ctrl2.log`, `run_a_s1_run2.log`, `run_a_s2_run1.log`, `run_b_s0_run1.log`, `run_b_s1_run1.log`, `run_b_s2_run1.log`.

## 전체 검증
- `/usr/bin/python3 -m pytest tests/ -q` → 315 passed.
- 커밋 예정: WSL repo 변경분(스크립트 A/C, 테스트 A, .gitignore) + JOURNAL.md append.
