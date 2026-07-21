# hotspot R 재추출 상태 — 완료

- 상태: 완료 (2026-07-20T19:06:45+09:00)
- 커밋: 24b4a93
- 산출물: scripts/extract_rc_hotspot.py, hbm_thermal/rc_extract.py(확장), results/rc_params.csv(r_hbm_sink_max 행 추가), JOURNAL.md
- 앵커 검증: baseline_8hi R=5.138620 K/W vs 기대값 5.1386 K/W, 편차 0.000020 K/W (PASS)
- 기존 avg 기반 r_hbm_sink=4.670561 무변경 확인
- 재현성: --dry-run 재실행 시 전 자릿수 동일 (결정론 확인)
