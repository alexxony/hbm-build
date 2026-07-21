# P5 리포트 — 진폭 괴리 원인 규명 + hotspot R 정식화

> 설계: [[09-p5-analysis-design]] (vault `docs/09-p5-analysis-design.md`)
> 코드 repo HEAD(본 리포트 작성 시점): 65df3b6
> 신규 AEDT/Icepak/3D-ICE 실행 없음 — 전 태스크가 P3(16W)·P4(30W) 기존
> CSV 재분석(설계 §1 명시 스코프)

## 1. 요약

P5는 P4에서 정직하게 FAIL로 남긴 G4(3D-ICE 교차검증) 게이트의 원인을
신규 실측 없이 재분석했다. 결론:

- **A계열 FAIL(0.8905)의 지배 원인은 물리 모델 불일치가 아니라 비교축
  (통계량) 문제였다** — Icepak(max, hotspot)과 3D-ICE(avg, lumped 모델
  구조상 avg=max)를 대조한 것이 원인. avg-avg로 재구성하면 1.0137로
  PASS(T1, H_T1 확증).
- **B계열은 반대로 진짜 물리 문제로 확정됐다** — 평균오차가 애초에
  avg-avg 비교축이었음에도(재구성 여지 없음) 대폭 FAIL 유지, 진폭비율도
  avg-avg 재구성 후 0.7616으로 FAIL. bottomsink 근본 원인 조사는 P5+로
  이월(T3).
- **T2(hotspot R 정식화)는 T2b로 완결됐다**: 앵커(baseline_8hi
  R=5.138620 K/W) 재현 검증 PASS에 더해, 설계가 요구한 **P4(30W,
  A/B×S0~S2) 6케이스 확장을 T2b에서 완료**했다 —
  `rc_params.csv`에 `r_hbm_sink_max_p4` 신규 행(append-only)으로
  6케이스 개별 R_hotspot(A: 5.138622/5.844228/6.339869, B:
  1.365756/2.196890/2.398226 K/W)이 기재됐다. H_T2(전력 선형성)는
  base_die_phy 케이스(S1/S2)에서 편차 ≈0.000%, S0(폴백 케이스)도
  +0.31%로 전 케이스 확증(§2 T2b 상세 — 초안의 "S0 -8.83%"는 축 혼용
  오류로 독립 검증에서 발견·정정됨). 초기 커밋(24b4a93)이 P3 앵커
  부분만 수행하고 P4 확장을 누락했던 결함은 T4 검수로 발견된 후
  T2b에서 해소됐다.
- T1·T2b·T3 전부 team-lead 배정 독립 검증 에이전트(p5-t1-verify,
  p5-t2b-verify, p5-t3-verify)에 의해 별도로 재현·대조 완료됨(§2 인용).
  T2b 검증은 H_T2 S0 서술의 축 혼용 오류 1건을 발견했고 본 리포트에
  정정 반영됐다(수치 자산 rc_params.csv 자체는 무결).

## 2. T1~T3 판정 종합

| 태스크 | 판정 | 핵심 수치 | 커밋 |
|---|---|---|---|
| T1(A계열 진폭비율 avg-avg 재구성) | **PASS, H_T1 확증** | 1.0137(Icepak avg진폭 31.659K vs 3D-ICE avg진폭 32.093K) | 8cc8238 |
| T2(hotspot R, 앵커 검증 + P4 확장) | 앵커 재현 **PASS**, P4 6케이스 확장 **완료(T2b)**, H_T2 **PASS(전 케이스)** | baseline_8hi R=5.138620 K/W(편차 0.000020) / P4 6케이스: A=5.138622·5.844228·6.339869, B=1.365756·2.196890·2.398226 K/W / 편차 S0 +0.31%·S1 ≈0.000%·S2 ≈0.000% | 24b4a93(앵커) + T2b(P4 확장, 본 세션) |
| T3(B계열 bottomsink, 조건부 축소 경로) | **FAIL, "근본 재설계 필요"** | 0.7616(Icepak avg진폭 32.298K vs 3D-ICE avg진폭 24.597K) | 65df3b6 |

**T1** (`p4_report.md` §4.4): 3D-ICE는 블록 단위 lumped RC 컴팩트 모델이라
블록 내부 공간 분포가 없어 항상 avg=max로 수렴한다(3D-ICE 출력 CSV
전 행에서 avg_c==max_c 실측 확인). §4.1의 A계열 진폭비율 FAIL(0.8905)은
Icepak **max**(hotspot 지표)와 3D-ICE **avg**를 대조한 데서 온 통계량
불일치였다. 3D-ICE 값은 그대로 두고 Icepak 쪽만 avg로 바꿔 재계산하면
비율 1.0137 — 합격선 [0.9, 1.1] PASS이며 P3(16W)의 avg-avg 선례(1.014)와
사실상 동일 수준으로 정합한다. 단, 이 결과는 §4.1의 "hotspot(max) 기준
G4 A계열 종합 FAIL" 판정을 취소하지 않는다 — hotspot 재현이라는 원래
검증 목적에는 3D-ICE 컴팩트 모델의 구조적 한계(블록 내부 분포 없음)가
여전히 남아 있다. T1이 밝힌 것은 FAIL의 **원인**이지 FAIL 자체의 철회가
아니다.

독립 검증(`results/p5_t1_verify_status.md`, 에이전트 p5-t1-verify):
pytest 11/11 통과, 스크립트 재현 1.0137 일치, 원시 CSV 스팟 대조 PASS
(`p4_icepak_a_s0.csv` base_die_phy avg=183.65861, `p4_icepak_a_s2.csv`
동일 행 215.31781), 3D-ICE 측 180.147/212.240 대조 일치, 음성 케이스
(gate 상/하한 반증) 존재 확인. 경미 결함 1건: `p5_t1_amplitude_recheck.py`에
idempotency 가드 부재(재실행 시 `p4_t4_crossval.csv` 중복 append 위험) —
검증 중 실제 중복 발생을 바이트 단위 원상복구로 처리, 판정 자체에는
영향 없음(§6 잔여 이슈 참조).

**T2** (`results/rc_params.csv` r_hbm_sink_max 행): 기존 P3(16W, top-only)
3케이스 R_hotspot(s0=5.1226/s1=5.8442/s2=6.3399 K/W)에 냉각BC 범위 앵커
(baseline_8hi=5.138620, cooling_top_bottom=1.365791 K/W)를 유지한 채,
동일 행의 `basis_case` 컬럼 서술에 P4 데이터가 basis로 명시돼 있다(설계
§3 T2 완료 조건대로 앵커 재현 게이트만 충족 확인 — `hotspot_extract_status.md`).
앵커 값은 P4 T4/T5 기확립 R=5.1386 K/W(JOURNAL 2026-07-19T22:29:53+09:00)와
편차 0.000020 K/W로 정합. avg 기반 기존 `r_hbm_sink`=4.670561은 무변경.

**T2b(P4 6케이스 확장, 본 세션 재오픈)**: `hbm_thermal/rc_extract.py`에
`compute_r_hbm_sink_max_p4_scenarios()`를 P3 전용 함수와 동형으로 신규
추가(기존 함수 무변경), `scripts/extract_rc_hotspot.py`에
`--p4-icepak-dir` 인자를 추가해 P4 A/B×S0~S2 6케이스를 처리했다.
R = (base_die_phy_max − 40.0) / 30.0 산식으로 6케이스 모두 계산:

| 케이스 | 사용 die | R_hotspot (K/W) |
|---|---|---|
| A-S0 | base_die(폴백, `_ctrl2` 정본) | 5.138622 |
| A-S1 | base_die_phy | 5.844228 |
| A-S2 | base_die_phy | 6.339869 |
| B-S0 | base_die(폴백) | 1.365756 |
| B-S1 | base_die_phy | 2.196890 |
| B-S2 | base_die_phy | 2.398226 |

S0(균일배분) 두 계열 모두 `base_die_phy` 행이 없어 `base_die`(합성 행)로
폴백했다(T1/T3 선례와 동일 패턴). A계열 S0은 설계 §3 T2 작업1이 명시한
대로 `p4_icepak_a_s0_ctrl2.csv`(정본)를 사용했고, B계열은 `_ctrl2` 파일
자체가 존재하지 않아(실측 확인) 원본 `p4_icepak_b_s0.csv`를 사용했다.

**H_T2(전력 선형성) 판정**: P3(16W, top-only)와 P4 A계열(30W)의 동일
시나리오 R_hotspot을 대조 — S1: 5.844234(P3) vs 5.844228(P4A), 편차
≈0.000%. S2: 6.339864 vs 6.339869, 편차 ≈0.000%. **base_die_phy 기준
케이스(S1/S2)는 전력에 대해 사실상 완전 선형**(±10% 게이트 여유롭게
PASS) — H_T2 확증. S0 편차는 **+0.31%**(P3=5.122614 vs P4A=5.138622,
max-vs-max 동일 정의) — S1/S2와 같은 계열의 미소 편차로, 전 케이스가
강한 전력 선형성을 지지한다. **정정 기록**: T2b 초안은 S0 편차를
"-8.83%(P4A=4.670564)"로 기재했으나, 독립 검증(p5-t2b-verify)이 이
값의 출처를 역추적한 결과 P4A 쪽에 avg 기반 R(base_die avg_temp_c
180.117 사용)을 잘못 대입해 P3(max 기반)과 대조한 **축 혼용 오류**로
확정됐다 — 본 문단은 max-vs-max 재계산값(+0.31%)으로 정정됐고, 이에
따라 초안의 "구조적 비교축 차이로 큰 편차" 해석 문단도 폐기됐다
(폴백 자체는 유효하나 편차가 크다는 전제가 틀렸음). 배분축 의존성은
설계 §2 예상대로 30W에서도 S0<S1<S2 단조 증가(A: 5.14→5.84→6.34,
B: 1.37→2.20→2.40)로 P3 패턴(5.12→5.84→6.34)과 방향 일치 —
"전력맵 배분축은 비선형(배분 의존)"이 30W에서도 재확인됐다.

신규 `rc_params.csv` 행(append, 기존 3행 무변경 — `git diff --stat`으로
+1행만 확인):

```
r_hbm_sink_max_p4,6.339869,1.365756,6.339869,K/W,"실측(hotspot 기반, P5 T2b): R = (base_die_phy_max - ambient_c) / total_power_w(30.0 고정), P4 A/B계열 x S0~S2 전력맵 6케이스 — r_hbm_sink_max(P3 16W, top-only)와 동일 산식·다른 전력·냉각계열축. S0(균일배분)는 base_die_phy 행이 없어 base_die max로 폴백(대괄호 표기로 사용된 die 명시, T1/T3 선례와 동일 패턴). H_T2(전력 선형성): 설계 §2 반증조건(±10%) 참조 — 상세 판정은 p5_report.md §T2b 기재.","[P4 전력맵x냉각계열, 30W 고정] a_s0[base_die], a_s1[base_die_phy], a_s2[base_die_phy], b_s0[base_die], b_s1[base_die_phy], b_s2[base_die_phy] (a_s0[base_die]: dT=154.159K/P=30.000W->R=5.138622K/W; a_s1[base_die_phy]: dT=175.327K/P=30.000W->R=5.844228K/W; a_s2[base_die_phy]: dT=190.196K/P=30.000W->R=6.339869K/W; b_s0[base_die]: dT=40.973K/P=30.000W->R=1.365756K/W; b_s1[base_die_phy]: dT=65.907K/P=30.000W->R=2.196890K/W; b_s2[base_die_phy]: dT=71.947K/P=30.000W->R=2.398226K/W)"
```

값 재현성은 독립 손계산(파이썬 인라인 스크립트로 CSV 원시값에서 직접
R = (max_temp_c − 40.0)/30.0 재계산)으로 6케이스 전부 스크립트 출력과
일치 확인(허용오차 없이 소수 6자리까지 일치). `extract_rc_hotspot.py`는
`--p4-icepak-dir` 미지정 시 기존 P3 전용 동작을 그대로 유지하며(하위
호환), idempotency 가드(`_rc_params_has_parameter()`)를 추가해 재실행
시 `r_hbm_sink_max`/`r_hbm_sink_max_p4` 두 행 모두 중복 append를 방지한다
(재실행 테스트로 "이미 존재 — 스킵" 동작 확인).

**T3** (`p4_report.md` §4.5): T1이 H_T1을 확증했으므로 설계 §3 T3 조건부
스코프 규칙에 따라 1차로 avg-avg 재비교만 수행하는 축소 경로로 진행했다.
사전 확인 결과 B계열 평균오차(47.46%/18.75%/18.64%, §4.2)는 애초에
`comparison.py`의 `compare_die_temperatures()`가 Icepak avg_temp_c와
3D-ICE avg_c를 비교해 산출한 것으로, **이미 avg-avg 비교축**이라 재구성
여지가 없다(A계열과 달리 통계량 불일치가 없음). 재구성 가능한 것은 T1과
동일 방법론의 진폭비율(S2−S0)뿐이며, B계열에 대해 P4에서 한 번도
계산된 적이 없어 T3에서 최초 산출했다. B-S0은 균일 시나리오라
`base_die_phy` 분할이 없어 `base_die` avg(67.871°C)로 폴백, S2는
`base_die_phy` avg(100.169°C) 사용 — 진폭 32.298K. 3D-ICE avg 진폭은
24.597K(101.004→125.601°C). 비율 0.7616 — FAIL. 평균오차·진폭비율 둘 다
avg-avg인데도 대폭 FAIL이므로 **B계열 괴리는 비교축 문제로 설명되지
않는 진짜 물리 문제**로 확정하고, 3D-ICE bottomsink 파라미터 딥다이브
(`.stk` 육안 검증 등 근본 원인 조사)는 설계 §3 T3 조건부 규칙에 따라
본 P5 스코프에서 제외, P5+ 후보로 이월했다. 신규 3D-ICE 실행 없음.

독립 검증(`results/p5_t3_verify_status.md`, 에이전트 p5-t3-verify): 5개
핵심 주장 전 항목 PASS — 진폭비율 0.7616 독립 재계산 일치, S0 앵커 폴백
구조가 Icepak·3D-ICE 양쪽에서 대칭(비대칭 우려 기각), `comparison.py:28-66`
소스 직접 열람으로 avg-avg 비교축 확인, pytest 304/304 통과, CSV +1행만
확인(기존 행 무변경). idempotency 가드 실동작(`--dry-run` 확인, T1의
결함이 T3 스크립트에서는 재발하지 않음)도 확인됨.

## 3. G4 재판정 최종 상태

설계 §2.3 정의(이원 합격 조건: 진폭비율 [0.9,1.1] AND 절대오차 ≤10%)
기준, **§4.1~4.3의 기존 FAIL 기재는 정정하지 않고 그대로 유지한다** —
아래는 T1/T3 결과로 보완된 최종 종합이다.

| 계열 | 기존(P4) 판정 | 기존 원인 서술 | P5 보완 결과 |
|---|---|---|---|
| A(top-only) | 진폭비율 0.8905 **FAIL**(hotspot max vs 3D-ICE avg) | 원인 미상, 3개 후보(비교축/HTC매핑/전력집중 비선형) 나열, 확정 못함 | **원인 확정: 비교축 문제가 지배적**(H_T1 확증). avg-avg 재구성 시 1.0137 PASS. die 평균 온도 수준에서는 두 솔버가 잘 정합함. 단, hotspot(max) 기준 원판정 FAIL 자체는 유효(3D-ICE 컴팩트 모델 구조적 한계는 남음) |
| B(top+bottom) | 평균오차 47.46/18.75/18.64% **FAIL**, R1 완화 적용(Icepak 단독 채택) | bottomsink BC 과소 작동(dT 억제비 Icepak 0.199 vs 3D-ICE 0.435) | **원인 확정: 비교축 문제 아님, 진짜 물리 문제**(avg-avg 진폭비율도 0.7616 FAIL). 근본 원인 조사(bottomsink 파라미터 딥다이브)는 P5+ 이월 |

**종합**: G4는 여전히 A/B 양계열 모두 원판정(hotspot/평균오차 기준) FAIL
상태를 유지한다 — P5는 판정을 뒤집지 않고 **원인을 계열별로 분리·확정**
했다. A계열은 "비교축을 맞추면 해소되는 문제"(공학적으로 die 평균
수준에서는 두 솔버가 신뢰할 만큼 정합), B계열은 "비교축을 맞춰도
해소되지 않는 진짜 모델 괴리"라는 질적으로 다른 결론이다. 이 구분은
후속 3D-ICE 활용 판단(A계열은 평균 온도 트렌드 예측에 활용 가능,
B계열은 bottomsink BC 보정 전까지 정량 신뢰 불가)에 실질적 함의를 가진다.

## 4. rc_params.csv 최종 스키마 변경 요약

현재 `results/rc_params.csv`(5행, 헤더 포함)는 P5 이전(T2, 커밋 24b4a93)에
추가된 상태(4행)에서, 본 세션 T2b가 `r_hbm_sink_max_p4` 1행을
append했다(append-only 원칙 준수 — 기존 4행은 `git diff`로 무변경 확인,
T1/T3는 `rc_params.csv`가 아니라 `p4_t4_crossval.csv`와 `p4_report.md`를
갱신했다).

| parameter | value | value_min/max | 용도 |
|---|---|---|---|
| `c_hbm` | 0.1240170 J/K | — | 열용량, 레이어 균질화 해석적 산출(P2) |
| `r_hbm_sink` | 4.670561 K/W | [0.929032, 4.670561] | avg 기반 열저항, 냉각BC 범위 앵커 2케이스(P2) |
| `r_hbm_sink_max` | 5.138620 K/W | [1.365791, 5.138620] | **hotspot(max) 기반** 열저항, 냉각BC 범위 앵커 2케이스(P4 T2) + `basis_case`에 P3 3-시나리오(top-only, 16W) 개별값 병기: s0=5.122614, s1=5.844234, s2=6.339864 K/W |
| `r_hbm_sink_max_p4` | 6.339869 K/W | [1.365756, 6.339869] | **P4(30W) hotspot 기반** 열저항, A/B계열×S0~S2 6케이스 개별값 `basis_case`에 병기(T2b, 본 세션 신규) — H_T2 전력 선형성 확증(S1/S2 편차≈0.000%) |

**Compiler_Thermal RcBackend 역수입 관점**: `r_hbm_sink_max` 행은 die
평균이 아니라 hotspot(PHY 블록 최고온) 대표값이 필요한 국소 신뢰성
평가(예: PHY 블록 직하 접합 온도 스펙 검증)에 쓸 수 있는 RC 파라미터
후보다. 다만 `basis_case` 서술이 명시하듯 hotspot R은 **전력맵 배분축에
의존**(P3 16W: s0→s1→s2로 5.12→5.84→6.34 K/W 단조 증가, P4 30W에서도
동일 패턴 재확인 — A: 5.14→5.84→6.34, B: 1.37→2.20→2.40, T2b로 확정)
하므로, `r_hbm_sink`(avg 기반, 전력맵 무관 안정값)와 달리 **단일
대표값으로 역수입하면 안 되고 반드시 전력맵 시나리오와 짝지어 사용해야
한다**는 것이 avg 기반 R과의 결정적 차이다. 반면 **전력축에 대해서는
선형**임이 T2b에서 확증됐다(base_die_phy 기준 S1/S2 편차≈0.000%) —
RcBackend가 hotspot 기준 국소 열해석을 지원하려면 배분(전력맵) 의존성만
흡수하면 되고, 전력 자체는 단순 스케일링으로 다뤄도 된다는 뜻이다.

## 5. PROGRESS.md/MOC 갱신 항목 체크리스트

(오케스트레이터 실제 갱신용 — 이 태스크는 목록만 작성, 실행하지 않음)

**vault `/mnt/c/ObsidianVault/HBM_build/PROGRESS.md`**:
1. `## P4 — 30W급 고전력 시나리오` 섹션 바로 뒤(또는 최상단 진행 현황
   요약)에 신규 `## P5 — 진폭 괴리 원인 규명 + hotspot R 정식화` 섹션
   추가. 내용: T1(H_T1 확증, avg-avg 1.0137 PASS)/T2(hotspot R 앵커
   재현 PASS + **T2b로 P4 6케이스 확장 완료, H_T2 PASS**)/T3(B계열 근본
   재설계 필요, P5+ 이월) 3줄 요약 + 커밋 해시(8cc8238/24b4a93/T2b 신규
   커밋/65df3b6) + 리포트 링크(`results/p5_report.md`). T2는 이제
   "완료"로 표기해도 된다 — 설계 §3 T2 완료 조건 (a)~(d) 전항 충족
   (T2b, 본 세션).
2. 세션 로그 항목(`### 세션 로그/마감 2026-07-21 — P5 완결`) 신규 추가 —
   T1/T2/T2b/T3/T4 각 담당 에이전트(p5-t1-exec, p5-t2b-exec 등)와
   독립검증 에이전트(p5-t1-verify, p5-t3-verify) 실행 이력 요약, 이
   리포트의 §2~§6 핵심 결론 재인용. T2b의 독립 검증은 본 리포트
   작성 시점 기준 아직 배정되지 않았다는 점도 명시(§6 신규 항목 참조).
3. 재개 절차(맨 아래) 갱신 — P5+ 후보(B계열 bottomsink 딥다이브,
   T1 idempotency 수정)를 다음 세션 선택지로 명시. T2/T2b는 완결됐으므로
   재개 절차에서 제외.

**vault `/mnt/c/ObsidianVault/HBM_build/HBM_build-MOC.md`**:
1. `## 문서` 표에 P5 설계 문서 행 추가: `| 09 | [[09-p5-analysis-design]] |
   P5 설계 — 진폭 괴리 원인 규명(비교축 문제 vs 물리 문제 분리)·hotspot
   R 정식화, T1~T4 | P5 |`.
2. `## 단계 요약`에 P4 항목 뒤 신규 P5 줄 추가 — H_T1 확증(비교축 문제,
   A계열 avg-avg PASS 1.0137)·B계열 근본 물리 문제 확정(P5+ 이월)·
   hotspot R 앵커 재현 PASS + P4 6케이스 확장 완료(T2b, H_T2 PASS) 3줄
   요약, 리포트 경로 `results/p5_report.md` 명시. **완료 마크(✅)는
   "T1·T2(T2b 포함)·T3 완결"로 붙여도 된다** — T2가 §3 T2 완료 조건
   (a)~(d) 전항을 T2b로 충족했으므로 다른 단계(P0~P4)의 ✅ 관례와 동일
   기준. B계열 bottomsink 근본 조사만 P5+ 이월로 별도 표기.
3. 상단 "**목표**" 문단의 Compiler_Thermal 역수입 언급 문장에 각주 또는
   1문장 추가 검토(선택) — `r_hbm_sink_max`가 전력맵 의존적이라 단일값
   역수입 불가하다는 §4 결론을 MOC 레벨에서도 요약할지는 오케스트레이터
   판단.

## 6. 잔여 이슈·P5+ 이월 목록

1. **B계열 bottomsink 딥다이브(P5+ 이월, 최우선)** — T3 조건부 규칙에
   따라 스코프 제외됨. 근본 원인 조사 대상: 3D-ICE `.stk` 파일의
   bottomsink 열저항 정의 방식·topsink 대칭성 가정 육안 검증(신규
   3D-ICE 실행 없이 기존 P4 T2 사전 스윕·T4 재실행 산출물 `.stk`만
   재검토, `results/3dice_p3_work/*.stk`는 P3 T3 오매핑 잔재이므로
   사용 금지 — 설계 §3 T3 명시).
2. **T1 스크립트 idempotency 가드 부재** — `scripts/p5_t1_amplitude_recheck.py`
   는 argparse도 `--dry-run`도 없이 무조건 append(JOURNAL
   2026-07-20T23:50:08+09:00 기재, `p5_t1_verify_status.md` §2 상세).
   T3 스크립트(`p5_t3_bottomsink_avgavg.py`)는 이미 가드가 있어 대조군
   역할 — T1에도 동일 패턴(CSV 라벨 중복 체크) 이식 권고.
3. **T2 미완결 사항 — 해소됨(T2b, 본 세션).** 초기 커밋 24b4a93은 설계
   §3 T2 완료 조건 (a)(P4 6케이스 표)·(b)(전력 선형성 판정)를 이행하지
   않고 P3 앵커 부분만 수행했다는 점이 T4 검수 및 오케스트레이터 원시
   대조로 확정됐었다(`git show 24b4a93 --stat` 열람 시 diff에 "P4"
   문자열이 전혀 없었음). 본 세션에서 team-lead가 T2b로 재오픈 —
   `hbm_thermal/rc_extract.py`에 `compute_r_hbm_sink_max_p4_scenarios()`
   신규 추가(기존 함수 무변경), `scripts/extract_rc_hotspot.py`에
   `--p4-icepak-dir` 인자 추가, `rc_params.csv`에 `r_hbm_sink_max_p4`
   행 append(idempotency 가드 포함, 재실행 스킵 동작 확인)로 P4 6케이스
   R_hotspot 산출·H_T2 전력 선형성 판정(PASS, 전 케이스)까지
   완료했다. §2 T2b 절 참조.
4. **T2b 독립 검증 — 완료(해소).** `p5-t2b-verify`(상태 파일
   `results/p5_t2b_verify_status.md`)가 6케이스 값 원시 CSV 재계산
   전부 일치(소수 6자리), rc_params.csv append-only, 앵커 정합성
   (독립 소스 확인 포함), idempotency·하위호환 실동작을 확인(PASS).
   동시에 H_T2 S0 서술의 축 혼용 오류(-8.83%)를 발견 — §2 T2b에
   정정 기록과 함께 +0.31%로 수정 반영됨. T1/T3에 이어 T2b에서도
   검증 단계가 실결함을 잡아낸 세 번째 사례(검증 게이트 실효성 근거).
5. **run_*.log glob 보류** — P4 세션 마감(2026-07-20) 인프라 3 항목에서
   이월된 별건. Windows 클론 `.gitignore` 패턴에 `run_*.log` 신구
   로그 혼재로 보류됨(러너 로그명 표준화 후 재검토 필요, 본 P5와 직접
   관련 없으나 다음 실측 캠페인 전 정리 권고).
6. **스테일 CSV 4건 정리 판단 대기** — 루트 `hbm2e_die_temperatures.csv`,
   `results/p3_icepak_s{0,1,2}.csv`. P4 마감부터 이월(2026-07-20),
   본 P5 스코프 밖.

## 7. 코드 검증 (pytest)

```
/usr/bin/python3 -m pytest tests/ -q
312 passed in 0.34s
```

(.venv 심 CRLF 인터프리터 문제로 시스템 `/usr/bin/python3` 사용 —
표준 라이브러리만 의존하는 테스트라 영향 없음, T1/T3 검증 에이전트와
동일 관례.) 전체 pytest는 T1(8cc8238)·T3(65df3b6) 두 커밋 각각에서
독립적으로 304/304(§2 인용) 확인됐고, 본 T4 시점 재실행도 동일하게
304/304 — 회귀 0건. **T2b(본 세션) 추가 후 312/312**(신규 8개 테스트:
`compute_r_hbm_sink_max_p4_scenarios` 정상 6종 + 음성 케이스 1종,
`build_r_hbm_sink_max_p4_row` 스키마 1종). 커밋 해시는 오케스트레이터
커밋 예정.
