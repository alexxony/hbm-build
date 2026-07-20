# P5 T3 상태 파일

- **시작**: 2026-07-20, HEAD 8cc8238
- **단계**: 착수 — 설계 문서(§3 T3) 확인 완료, 배경 조사 완료
- **핵심 발견(배경 조사)**:
  - B계열 평균오차(47.46%/18.75%/18.64%)는 `compare_die_temperatures()`가
    `icepak_avg_c` vs `threedice_avg_c`로 **이미 avg-avg** 비교임을
    `hbm_thermal/comparison.py:50-65` 확인 — A계열 진폭비율(max vs avg)과
    달리 평균오차 자체는 비교축 문제가 아님.
  - B-S0는 `base_die_phy` 행이 없음(균일 시나리오라 `base_die` 단일 행) —
    T1과 동일한 진폭비율(S2-S0) 방식을 B계열에 적용하려면 S0 앵커로
    `base_die`(avg)를 사용해야 함(기존 `p4_t4_crossval_hypotheses.py`의
    `base_die_max()` fallback 로직과 동일 패턴).
  - §4.2의 "억제비 Icepak 0.199 vs 3D-ICE 0.435"는 스크립트화되지 않은
    JOURNAL 전용 수치(별도 side-metric, Q2류) — T3 게이트 지표(진폭비율)와
    다름.
- **완료**: 2026-07-21T01:21:28+09:00
- **최종 판정**: "근본 재설계 필요"(3분류) — B계열 진폭비율(S2-S0)
  avg-avg 재구성 = **0.7616**(합격선[0.9,1.1] FAIL). 평균오차도 이미
  avg-avg였으므로(재구성 여지 없음) 여전히 47.46/18.75/18.64% FAIL.
  비교축 문제로 설명 안 되는 진짜 물리 문제로 확정 — 근본 조사는
  스코프 제외, P5+ 이월.
- **산출물**: `scripts/p5_t3_bottomsink_avgavg.py`(argparse+--dry-run+
  idempotent 라벨 중복 체크), `tests/test_p5_t3_bottomsink_avgavg.py`
  (20 tests, 음성 케이스 4종 포함), `results/p4_t4_crossval.csv`
  (+1행 `G4_B계열_진폭비율_avg대avg_T3`, 기존 행 무변경 diff 확인),
  `results/p4_report.md` §4.5 신규.
- **검증**: pytest 304/304 통과(/usr/bin/python3), idempotency
  실행→재실행 실측 확인(2차 실행 스킵 로그 확인, 중복 행 없음).
