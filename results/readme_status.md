# README 재정비 상태 (2026-07-22, readme-hbm 에이전트)

## 완료
- README.md 전면 재작성 — portfolio/공개 수준, 형제 repo(compiler-thermal/loop,
  gpu-solver-loop) 스타일 미러링, 영어.
- 수치 전수 아티팩트 대조 완료(아래 "인용 수치" 참조).
- Negative result 절 신설(형제 repo 관례): G4 B계열 FAIL, Student 라이선스
  mesh L4/L5 거부, `n_elements` 미회수 3건 정직 기재.
- Compiler_Thermal RcBackend 역수입 상호 링크 추가.
- 예제 CLI 커맨드 2건을 실제 argparse 소스와 대조해 정정
  (`extract_rc_params.py`는 `--icepak-csv`를 받지 않음 — 발견 후 수정).
- 테스트 315 passed / 0 failed 직접 재실행 확인(`/usr/bin/python3 -m pytest tests/ -q`).

## 인용 수치와 소스
| 수치 | 소스 파일 |
|---|---|
| base_die 114.7/122.2°C (baseline_8hi avg/max) | `results/param_study.csv` |
| mesh convergence L1→L3 변화율 ≤0.024% | `results/mesh_convergence.csv` |
| 3D-ICE 교차검증 오차 0.004%(die avg) | `results/icepak_vs_3dice_comparison.csv`, `docs/03-cross-validation-3d-ice.md` |
| transient τ 오차 4.04%, R²=0.999996 | `results/transient_tau_comparison.csv` |
| 파라미터 스터디 6케이스(스택높이/본딩/냉각BC) | `results/param_study.csv` |
| c_hbm=0.1240 J/K, r_hbm_sink [0.929,4.671] K/W | `results/rc_params.csv` |
| P3 균일vs블록 hotspot +19.5K(불변 avg) | `results/p3_report.md` §2 |
| P4 H1a 선형 1.850× vs 기대 1.875×, R 선형성 0.01% | `results/p4_report.md` §3 |
| P4 Tj 스펙(95°C) 초과 100~135K(A계열) | `results/p4_report.md` §6 |
| P5 A계열 avg-avg 1.0137 PASS / B계열 0.7616 FAIL | `results/p5_report.md` §2 |
| 테스트 315 passed/0 failed | 본 세션 직접 재실행(`/usr/bin/python3 -m pytest tests/ -q`) |
| LICENSE MIT, Copyright 2026 alexxony | `LICENSE` |

## 기재하지 않은 것 (소스에서 확인 못함)
- P1 정확 다이 치수 일부(TSV/µbump 정밀 치수)는 JEDEC 원문 미확인, 공개 소스
  기반 — 기존 문서 톤 유지, README에 "literature-informed" 수준으로만 서술.
- `mesh_convergence.csv`의 실제 `n_elements` 값 — 애초에 회수되지 않아
  (`export_mesh_stats` 파싱 미회수, 컬럼 전 레벨 공란) 기재할 수치 자체가 없음.
  README에는 "column is empty" 사실만 negative result로 기재.

## 커밋
(오케스트레이터가 커밋 직후 여기에 해시 갱신 예정 — 본 파일은 커밋에 포함)
