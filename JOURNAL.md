# JOURNAL — hbm_build 원장

> 규약: 상태 변화마다 1~2줄 즉시 append + 커밋. 시각은 ISO 8601+09:00(24h).
> 요약은 vault PROGRESS.md(마감 전용). 기계 판정은 epoch 초 산술만.

- 2026-07-17T22:17:10+09:00 — P4 T3 1차: A-S0 케이스 완주, `results/p4_icepak_scenarios/p4_icepak_a_s0.csv` 생성 (base_die avg 180.10 / max 193.68°C). 직후 ~22:20 오케스트레이터가 cp949 오전/오후 오독으로 solve 프로세스 오살 — 1차 중단의 실제 원인.
- 2026-07-17T22:31:32+09:00 — P4 T3 2차: AEDT 이중 기동(22:31:18 + 22:31:32) → 2번째 인스턴스 FlexNet -5 `icepak_gui` 라이선스 획득 실패로 배치 사망. 증거: `results/p4_icepak_scenarios/t3_attempt2_batch.log`. 교훈: Student 라이선스는 단일 인스턴스 — 동시 기동 금지.
- 2026-07-18T20:58:33+09:00 — P4 T3 3차 착수: 포렌식으로 위 2건 원인 확정, A-S0 CSV 유효 판정(ΔT비 1.8750 = 30/16 정확, H1a 선형 정합) → 회수 커밋. 잔여 5케이스(A-S1·A-S2·B-S0·B-S1·B-S2) executor 위임.
