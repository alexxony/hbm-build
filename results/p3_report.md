# P3 최종 리포트 — base die 블록별 전력맵(MHS) 정량 검증

> 설계: `docs/07-p3-power-map-design.md` · 리서치: `research/06-base-die-power-map.md`
> 코드: `~/workspace/hbm_build` (T5 완료 시점 기준) · 작성: P3 T5

## 1. 요약

base die 8.8W 균일 배분(단일 발열체 근사)을 특허 근거 3분할 블록
(PHY/TSVA/DA)으로 세분화해 Icepak(FEM, 정본)로 실측하고 3D-ICE(컴팩트
모델)로 교차검증했다. **결과: 균일 근사는 base_die 대표(평균) 온도에는
영향이 없으나(따라서 r_hbm_sink 불변), hotspot(최대 온도)은 최대
+19.5K까지 과소평가한다** — 사전 등록 가설("8.8W는 KAIST 크로스오버 30W
미만이라 효과가 작을 것")은 **반증**되었다. DRAM die 최대 온도도 동반
상승(122→141°C)한다.

## 2. 균일 vs 블록 배분 정량 비교 (Icepak, 정본)

| 항목 | S0(균일 등가) | S1(PHY 완만) | S2(PHY 집중) | 비고 |
|---|---|---|---|---|
| base_die 합성 avg | 114.720°C | 114.721°C | 114.722°C | **불변**(편차 <0.001%) |
| base_die_phy avg | 116.62°C | 126.62°C | 133.50°C | **+16.88K**(S2-S0) |
| base_die_phy max | 121.96°C | 133.51°C | 141.44°C | **+19.48K**(S2-S0) |
| base_die_da avg | 117.08°C | 110.78°C | 106.03°C | **-11.05K**(S2-S0) |
| DRAM die max(전 die 범위) | 120.5~122.3°C | 130.6~133.6°C | 137.5~141.3°C | 동반 상승 |
| hotspot 위치 | base_die 중앙(TSVA 인근) 근사 | PHY 에지 띠로 이동 | PHY 에지 띠(뚜렷) | S0는 균일이라 위치 개념 자체가 없음 — S1/S2에서 PHY로 뚜렷이 국소화 |

**해석**: base die **평균** 온도(전력 보존 항등식이 지배)는 시나리오와
무관하게 거의 완전히 불변이지만, **국소(hotspot) 온도**는 전력 집중도에
비례해 최대 +19.48K(S2 PHY max, S0 대비) 상승한다. 균일 전력맵 근사는
평균 기반 지표(RC 등가회로의 r_hbm_sink 등)에는 안전하지만, **국소 신뢰성/
열화 평가에는 최대 20K 가까운 과소평가**를 낳는다.

## 3. 사전 등록 가설 반증

`docs/07-p3-power-map-design.md` §1.2: "8.8W는 KAIST 크로스오버(30W) 미만
영역 — 블록 배분 효과가 작게 나올 수 있음"을 사전 등록했다. 실측 결과
PHY 블록 하나만 놓고 보면 S2에서 +19.48K(max)/+16.88K(avg)의 뚜렷한
hotspot 상승이 확인되어, **효과가 작다는 가설은 반증**되었다(8.8W 수준
에서도 전력 집중이 국소 hotspot을 유의미하게 밀어올림). 다만 base die
**대표(평균) 온도**는 예상대로 거의 불변이었다 — 가설이 틀린 것은
"효과가 작다"는 부분이며, "평균 기반 지표는 영향받지 않는다"는 부분은
오히려 강하게 확인되었다.

## 4. 블록 폭/전력 비율 출처 라벨링

블록 위치(PHY 에지 띠/TSVA 중앙/DA 반대편 에지 띠)는 특허(Samsung
US11599458·US11232029, Intel US11854935B2)로 정합되는 신뢰도 상(고정)
가정이나, **정확한 폭 비율(0.20:0.65:0.15)과 전력 비율(S1/S2 값)은
출처 없는 가정**이다(`research/06-base-die-power-map.md` §3 — TechInsights
등 유료 다이 사진 분석 리포트 영역, 공개 1차 소스 없음). `model_config.py`의
`BASE_DIE_BLOCK_WIDTH_FRACTIONS`, `POWER_SCENARIOS` docstring에 이미
명시되어 있으며, 본 리포트의 모든 정량값은 이 가정 위에서 산출된 **민감도
스윕 결과**이지 단일 확정값이 아니다.

## 5. Icepak vs 3D-ICE 교차검증

| die | 시나리오 | Icepak avg(°C) | 3D-ICE avg(°C) | 차이(°C) | 차이(%) |
|---|---|---|---|---|---|
| base_die_phy | S0 | 116.62 | 114.75 | -1.87 | 1.61% |
| base_die_tsva | S0 | 113.59 | 114.75 | +1.15 | 1.02% |
| base_die_da | S0 | 117.08 | 114.75 | -2.34 | 2.00% |
| base_die_phy | S1 | 126.62 | 124.88 | -1.73 | 1.37% |
| base_die_tsva | S1 | 111.97 | 113.08 | +1.11 | 1.00% |
| base_die_da | S1 | 110.78 | 108.43 | -2.36 | 2.13% |
| base_die_phy | S2 | 133.50 | 131.86 | -1.64 | 1.23% |
| base_die_tsva | S2 | 112.04 | 110.95 | +1.09 | 0.98% |
| base_die_da | S2 | 106.03 | 103.65 | -2.38 | 2.25% |

**게이트 판정**:
- **(a) 방향 일치**: PASS — 두 툴 모두 PHY avg가 S0<S1<S2로 단조 증가,
  DA avg가 S0>S1>S2로 단조 감소(3D-ICE: PHY 114.75→124.88→131.86°C,
  DA 114.75→108.43→103.65°C; Icepak: PHY 116.62→126.62→133.50°C,
  DA 117.08→110.78→106.03°C).
- **(b) 진폭 자릿수 일치**: PASS — PHY ΔT(S2-S0): Icepak 16.88K vs
  3D-ICE 17.12K, 비율 1.014(설계 허용 ±50%를 크게 상회하는 정합, 사실상
  동일 자릿수를 넘어 거의 동일값).
- **(c) S0 합성 base_die avg 재현**: PASS — 3D-ICE 114.745°C(모든 블록
  동일값, 컴팩트 모델 특성 — avg=max, lumped 근사)로 기존 P2 기준선
  (114.745°C, `docs/03-cross-validation-3d-ice.md`)과 오차 0%로 정확히 일치.

전 항목 절대 오차 0.98~2.25%로 프로젝트 공인 합격선(10%, `research/
04-validation-anchors.md` §3)을 압도적으로 통과했다. 3D-ICE는 컴팩트
lumped 모델이라 블록 내부 공간 구배가 없어(avg=max) Icepak의 블록별
avg≠max(FEM 공간 분포)와는 다르지만, avg 대 avg 비교축에서는 정확히
정합한다.

## 6. r_hbm_sink 영향 판정

`hbm_thermal/rc_extract.py`의 `compute_r_hbm_sink_range()`는
`R = (base_die_avg_c - ambient_c) / total_power_w` — **base_die 단일
스칼라 평균 온도**를 대표값으로 쓴다(`base_die_avg_c` 인자). T4 Icepak
실측 결과 이 대표 온도가 시나리오 무관 **114.720/114.721/114.722°C
(S0/S1/S2, 편차 <0.001%)** 로 사실상 불변임을 확인했다(3D-ICE의 면적가중
합성값으로도 독립 재현: 114.7450/114.7452/114.7449°C, 편차 <0.0002%).

**판정: r_hbm_sink 재계산 불필요, compiler_thermal A/B 재계산 불필요.**
c_hbm은 이미 rho_cp×부피 항등식이라 전력 분포 무관임이 T1에서 확인됨 —
P3 전체가 P2에서 확정한 RC 파라미터에 영향을 주지 않는다.

## 7. 문헌 공백 기여

`research/06-base-die-power-map.md` §4가 지목한 문헌 공백(균일 vs 블록
배분의 base die 온도 정량 비교 부재)을 본 리포트가 메운다: 균일 근사가
**평균 기반 지표(R, C 등 RC 등가회로 파라미터)에는 안전**하지만 **국소
hotspot 평가에는 최대 +19.5K 과소평가**를 낳는다는 정량 트레이드오프를
Icepak FEM 실측 + 독립 컴팩트 모델(3D-ICE) 교차검증으로 확립했다 — 공개
문헌에 없던 정량 결과다.

## 8. T3 오매핑 사고 경위 및 수정

T3는 `export_3dice.py`의 시나리오 모드에서 `model_config.build_geometry_spec()`이
반환하는 `base_die_phy/tsva/da` 3개 geometry sub-box(x방향 분할, 동일
z 슬라이스 공유)를 3D-ICE die 3개로 그대로 매핑했다. 그러나
`build_floorplan_file()`은 항상 **전체 footprint**(`position 0, 0` /
`dimension 11000, 10000`)의 `.flp`를 만든다 — 그 결과 xy 평면 분할이던
3 sub-box가 **z축(수직) 적층 3층**으로 둔갑했다(base_die 60µm 1층 대신
60µm die 3개가 쌓여 180µm가 됨). 시나리오 간 온도 진폭이 0.03°C 수준으로
Icepak 실측(~17°C)과 3자릿수 이상 어긋났음에도 T3 커밋은 "회귀 PASS"로
기록됐다 — 회귀 게이트가 S0(면적비=균일 등가)만 검증했고 S0는 우연히
합성 평균이 맞아떨어져(모든 블록이 같은 재료·같은 대표온도로 수렴) 오매핑을
가리지 못했다.

**정정**: base_die를 항상 단일 die(60µm, None 경로와 동일 두께)로 유지하고,
그 die의 `.flp` 하나에 블록별 named element 3개(`phy`/`tsva`/`da`)를
올바른 x-offset·폭·전력으로 기입했다(3D-ICE 공식 예제 `bin/core.flp`가
파일 하나에 15개 named element를 담는 것으로 다중 element 문법을 실측
확인). 온도 출력도 die 단위 `Tflp` 대신 블록 단위 `Tflpel(die.element_id,
...)`로 교체했다.

**재발 방지**: 컴팩트 모델(3D-ICE 등) 입력을 지오메트리 확장 방식으로
수정할 때는, 생성된 `.stk`/`.flp` 텍스트를 실행 전 반드시 육안 검증할 것
— 특히 `position`/`dimension` 필드가 의도한 sub-box 좌표를 반영하는지
(전체 footprint로 뭉개지지 않았는지) 확인한다. 회귀 게이트는 최소
1개 이상의 "구조가 실제로 달라지는" 시나리오(S1/S2 등)에서 절대값
자릿수를 정본(Icepak)과 비교해야 하며, S0류 "물리적으로 등가" 시나리오
단독으로는 이런 유형의 오매핑을 검출하지 못한다.

## 9. 재현 절차

```bash
# WSL, 3D-ICE 빌드 필요(docs/03-cross-validation-3d-ice.md §2)
python3 -c "
from hbm_thermal.export_3dice import build_stack_description
for s in ['s0_uniform','s1_phy_moderate','s2_phy_heavy']:
    files = build_stack_description(power_scenario=s)
    # files를 작업 디렉터리에 쓴 뒤 3D-ICE-Emulator stack.stk 실행
"
```

Icepak 실측 원본: `results/p3_icepak_scenarios/p3_icepak_{s0,s1,s2}.csv`.
3D-ICE 재실행 결과: `results/p3_block_temperatures.csv`(본 T5에서 덮어씀).
