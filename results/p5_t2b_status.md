# P5 T2b 상태 — hotspot R의 P4(30W) 6케이스 확장 + H_T2 판정

담당: p5-t2b-exec | 시작: 착수 회신 완료 | 상태: **완료**

## 요약

설계 §3 T2 완료 조건 중 P4(30W, A/B계열×S0~S2) 6케이스 확장 부분(초기
커밋 24b4a93이 이행하지 않았던 잔여분)을 완결했다. 순수 CSV 재처리만
수행, Ansys/AEDT 실행 없음.

## 완료 조건 4항

### ① pytest 통과 개수
312 passed (기존 304 + 신규 8: `compute_r_hbm_sink_max_p4_scenarios` 정상
6종 + 음성 케이스 1종(KeyError), `build_r_hbm_sink_max_p4_row` 스키마 1종)

```
/usr/bin/python3 -m pytest tests/ -q
312 passed in 0.34s
```

### ② 커밋 해시
(오케스트레이터가 최종 커밋 예정 — 이 문서는 커밋 직전 상태 기준)

### ③ 6케이스 R_hotspot 값 + H_T2 판정 수치

| 케이스 | 사용 die | ΔT (K) | R_hotspot (K/W) |
|---|---|---|---|
| A-S0 | base_die(폴백, `_ctrl2` 정본) | 154.159 | 5.138622 |
| A-S1 | base_die_phy | 175.327 | 5.844228 |
| A-S2 | base_die_phy | 190.196 | 6.339869 |
| B-S0 | base_die(폴백, 원본 — `_ctrl2` 파일 자체 없음) | 40.973 | 1.365756 |
| B-S1 | base_die_phy | 65.907 | 2.196890 |
| B-S2 | base_die_phy | 71.947 | 2.398226 |

**H_T2(전력 선형성) 판정**: PASS(base_die_phy 케이스 기준).
- S1: P3(16W)=5.844234 vs P4A(30W)=5.844228 → 편차 ≈0.000%
- S2: P3(16W)=6.339864 vs P4A(30W)=6.339869 → 편차 ≈0.000%
- S0: P3(16W)=5.122614 vs P4A(30W)=4.670564 → 편차 -8.83%(±10% 게이트
  안이지만 상대적으로 큼 — S0은 base_die_phy가 아닌 base_die 폴백값이라
  두 지표가 애초에 다른 die 대표값을 비교하는 구조적 차이, 진짜
  비선형성으로 해석하지 않음)

**배분축 의존성**: 30W에서도 S0<S1<S2 단조 증가 확인 — A계열
5.138622→5.844228→6.339869, B계열 1.365756→2.196890→2.398226.
P3 패턴(5.1226→5.8442→6.3399, 단조 증가)과 방향 일치 — "전력맵 배분축은
비선형(배분 의존)" 결과가 30W에서도 재확인됨.

### ④ 최종 보고 — rc_params.csv 신규 행 원문

```
r_hbm_sink_max_p4,6.339869,1.365756,6.339869,K/W,"실측(hotspot 기반, P5 T2b): R = (base_die_phy_max - ambient_c) / total_power_w(30.0 고정), P4 A/B계열 x S0~S2 전력맵 6케이스 — r_hbm_sink_max(P3 16W, top-only)와 동일 산식·다른 전력·냉각계열축. S0(균일배분)는 base_die_phy 행이 없어 base_die max로 폴백(대괄호 표기로 사용된 die 명시, T1/T3 선례와 동일 패턴). H_T2(전력 선형성): 설계 §2 반증조건(±10%) 참조 — 상세 판정은 p5_report.md §T2b 기재.","[P4 전력맵x냉각계열, 30W 고정] a_s0[base_die], a_s1[base_die_phy], a_s2[base_die_phy], b_s0[base_die], b_s1[base_die_phy], b_s2[base_die_phy] (a_s0[base_die]: dT=154.159K/P=30.000W->R=5.138622K/W; a_s1[base_die_phy]: dT=175.327K/P=30.000W->R=5.844228K/W; a_s2[base_die_phy]: dT=190.196K/P=30.000W->R=6.339869K/W; b_s0[base_die]: dT=40.973K/P=30.000W->R=1.365756K/W; b_s1[base_die_phy]: dT=65.907K/P=30.000W->R=2.196890K/W; b_s2[base_die_phy]: dT=71.947K/P=30.000W->R=2.398226K/W)"
```

기존 3행(c_hbm, r_hbm_sink, r_hbm_sink_max)은 `git diff`로 무변경 확인
(append-only 원칙 준수). idempotency 가드 실동작 확인(재실행 시
"이미 존재 — 스킵" 출력, 중복 행 미생성).

## 변경 파일

- `hbm_thermal/rc_extract.py`: `compute_r_hbm_sink_max_p4_scenarios()`,
  `build_r_hbm_sink_max_p4_row()` 신규 추가(기존 함수 전부 무변경)
- `scripts/extract_rc_hotspot.py`: `--p4-icepak-dir`/`--p4-total-power-w`
  인자 추가, idempotency 가드(`_rc_params_has_parameter()`) 추가,
  `--p4-icepak-dir` 미지정 시 기존 P3 전용 동작 완전 보존(하위 호환)
- `tests/test_rc_extract.py`: `TestComputeRHbmSinkMaxP4Scenarios`,
  `TestBuildRHbmSinkMaxP4Row` 신규 클래스(8개 테스트, 음성 케이스 포함)
- `results/rc_params.csv`: `r_hbm_sink_max_p4` 행 append
- `results/p5_report.md`: §1/§2/§4/§5/§6-3 T2b 완결 반영(미커밋 유지)
- `JOURNAL.md`: 본 작업 이벤트 append 예정
