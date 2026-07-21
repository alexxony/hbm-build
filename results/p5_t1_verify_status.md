# P5 T1 검증 상태 (avg-avg 진폭비율 재구성)

검증 시각: 2026-07-20 (에이전트: p5-t1-verify)
검증 대상: G4 A계열 진폭비율 avg-avg 재구성 (H_T1), 리포트 §4.4

## 최종 판정: 전체 PASS

## 항목별 결과

### 1. pytest 실행 — PASS
`python3 -m pytest tests/test_p5_t1_amplitude_recheck.py -v`
결과: **11 passed** (0.03s)
- TestReadIcepakAvg: 2/2
- TestRead3diceAvg: 2/2
- TestComputeAmplitudeRatioAvgAvg: 2/2
- TestJudgeHT1: 4/4 (음성 케이스 포함 — 아래 5번 참조)
- TestAppendCrossvalRow: 1/1

주의: repo에 `.venv`가 없고 WSL의 `python`/`python3.11` 심은 Windows pyenv shim(CRLF 인터프리터 오류)이라 실행 불가. `/usr/bin/python3`(3.10.12, 시스템 설치)로 전환해 실행 — 스크립트/테스트 모두 표준 라이브러리(csv, pathlib)만 사용하므로 pandas 등 외부 의존성 없이 정상 동작 확인.

### 2. 스크립트 재현 실행 — PASS (부작용 발생 및 원상복구, 아래 참조)
`python3 scripts/p5_t1_amplitude_recheck.py` (CLI에 `--help`/dry-run 옵션 없음 — 인자 없이 그냥 실행됨)
출력:
```
Icepak base_die_phy avg: S0=183.659C, S2=215.318C, 진폭=31.659K
3D-ICE base_die_phy avg: S0=180.147C, S2=212.240C, 진폭=32.093K
avg-avg 진폭비율 = 1.0137 (합격선[0.9,1.1]) -> PASS
H_T1 판정: 확증(비교축 문제가 지배적 원인)
```
리포트 §4.4의 1.0137 수치와 완전 일치. **재현성 확인됨.**

**부작용 및 정정**: 스크립트에 idempotency 가드가 없어 재실행 시 `results/p4_t4_crossval.csv`에 동일 행이 중복 append됨(검증 중 실수로 1회 재실행하여 중복 발생). 원본 uncommitted 상태(단일 행)로 바이트 단위 복구 완료 — `git diff --stat`로 확인: `1 file changed, 1 insertion(+)`만 남음(중복 흔적 없음). **스크립트 결함으로 기록**: (a) `--help` 플래그가 무시되고 실제 실행됨(argparse 없음), (b) 재실행 시 append 중복 방지 로직 없음. P5 T1 마무리 전 스크립트에 `--dry-run` 또는 append 전 기존 행 존재 여부 체크 추가를 권고.

### 3. G2 원시 데이터 스팟 대조 (핵심) — PASS, 문서 서술과 로직 일치
`results/p4_icepak_scenarios/p4_icepak_a_s0.csv`:
```
base_die_phy,183.65861242320244,193.67861328125002
```
`results/p4_icepak_scenarios/p4_icepak_a_s2.csv`:
```
base_die_phy,215.3178073448489,230.19606933593752
```
183.659 / 215.318은 정확히 이 두 행의 `avg_temp_c` 컬럼에서 나온 값(반올림 일치). **중요**: 위임 프롬프트의 우려("A-S0은 base_die_phy 행이 없을 수 있음, JOURNAL 기준 base_die avg=180.12°C")는 오해였음 — `base_die_phy`(183.659)와 `base_die`(180.101)는 **서로 다른 die 라벨**이며 둘 다 CSV에 각자 존재한다. JOURNAL의 180.12°C는 `base_die` 행을 가리킨 것이고, 리포트 §4.4/스크립트는 처음부터 `base_die_phy` 행만 참조 — 혼동 없음, 불일치 아님.

스크립트 로직(`read_icepak_avg()`)도 `row["die"] == "base_die_phy"`인 행의 `avg_temp_c`를 그대로 반환하는 단순 조회이며, 리포트 서술("p4_icepak_a_s0.csv의 base_die_phy 행 avg_temp_c 사용")과 완전 일치.

### 4. 3D-ICE 값 대조 — PASS
커밋된 `results/p4_3dice_t4/p4_3dice_t4_results.csv`:
```
A,s0_uniform,base_die_phy,180.14700000000005,180.14700000000005
A,s2_phy_heavy,base_die_phy,212.24,212.24
```
리포트/스크립트의 180.147 / 212.240과 일치. 또한 모든 행에서 `avg_c == max_c`(lumped RC 모델 특성)임을 CSV 전체 스캔으로 확인 — 리포트 §4.4의 "3D-ICE는 avg=max로 항상 수렴" 주장도 데이터로 뒷받침됨.

### 5. 음성 케이스 확인 — 존재함(양호)
`TestJudgeHT1`에 아래 음성 케이스 포함:
- `test_ratio_below_gate_refutes`: 합격선 미만 비율 → 반증 판정 거부 확인
- `test_ratio_above_gate_refutes`: 합격선 초과 비율 → 반증 판정 거부 확인
- `test_gate_boundaries_pass`: 경계값(0.9, 1.1) 처리 확인

G2 요구(selfcheck 음성 케이스 필수) 충족.

## 독립 산술 재검증
```
icepak_amp = 215.317807 - 183.658612 = 31.659195
threedice_amp = 212.240000 - 180.147000 = 32.093000
ratio = 32.093000 / 31.659195 = 1.013702  →  반올림 1.0137
```
스크립트 출력과 완전 일치.

## 종합 결론
G4 T1 avg-avg 재구성 결과(1.0137, PASS, H_T1 확증)는 원시 데이터·스크립트 로직·리포트 서술 3자 모두 정합하며 조작이나 서술 오류 없음. 유일한 실무 이슈는 스크립트의 idempotency 부재(경미, 기능적 결함 아님 — append 전용 스크립트의 재실행 안전장치 누락)이며 이는 검증 결과 자체의 타당성에는 영향 없음.
