# Task 4: 3D-ICE 교차검증

목표: Icepak(FEM) 결과를 독립 오픈소스 컴팩트 열해석 툴 3D-ICE(EPFL,
https://github.com/esl-epfl/3d-ice)로 재구성해 ≤10% 오차(vault
`research/04-validation-anchors.md` §3 공인 기준)로 교차검증한다. 전 과정
WSL 로컬 실행, 과금 없음.

## 결과 요약

**PASS** — die별 평균 절대 오차 **0.004%** (합격선 10% 대비 압도적 여유).
die-to-die 온도 구배 방향도 일치(base_die 최고온 → top_die로 갈수록 감소).

비교 CSV: `results/icepak_vs_3dice_comparison.csv`

| die | Icepak avg(°C) | Icepak max(°C) | 3D-ICE avg(°C) | 차이(°C) | 차이(%) |
|---|---|---|---|---|---|
| base_die | 114.73 | 122.22 | 114.75 | 0.02 | 0.01% |
| dram_die_1..7 | 114.52→112.79 | 122.55→120.64 | 114.51→112.79 | ~0.00 | ~0.00% |
| top_die | 112.74 | 120.36 | 112.75 | 0.01 | 0.01% |

## 1. 툴 선정: 3D-ICE (vault §03-prior-art 추천 기준 채택)

- EPFL 공식 오픈소스, "실측 대비 평균 오차 <10%" 공인 수치(vault
  `research/04-validation-anchors.md` §3).
- Stack Description File(.stk)로 레이어 스택을 자유롭게 정의 가능 —
  `hbm_thermal/model_config.py`의 17레이어 구조와 1:1 매핑 가능.
- v4.0에서 **이방성(anisotropic) 열전도율 직접 지원** — `thermal
  conductivity kx, ky, kz` 문법. 균질화 물성(k_xy/k_z)을 손실 없이 그대로
  전달 가능(등가 등방성으로 뭉갤 필요 없음).
- 대안(CoMeT, HotSpot)은 이방성 문법이 3D-ICE만큼 직접적이지 않거나
  빌드 복잡도가 더 높아 보류. HotSpot 폴백은 불필요했음(3D-ICE 빌드 성공).

## 2. WSL 빌드 (sudo 없이, gfortran/OpenBLAS 없이)

WSL에는 `gfortran`, `libopenblas-dev`가 없고 `sudo apt install`도 불가능한
환경(비밀번호 필요)이었다. 3D-ICE는 SuperLU_MT(희소 선형시스템 솔버)에
의존하는데, 저장소 동봉 `install-superlumt.sh`는 OpenBLAS+gfortran을
요구해 그대로는 실패한다.

**해결**: SuperLU_MT 자체에 순수 C로 작성된 참조 BLAS(`CBLAS/` 디렉터리,
`.f` 파일 0개 확인)가 번들되어 있다 — 이걸 그대로 빌드해 링크하면
gfortran/OpenBLAS 없이 gcc만으로 전체 빌드가 끝난다.

```bash
git clone https://github.com/esl-epfl/3d-ice.git
cd 3d-ice
unzip superlu_mt-4.0.0.zip
cd superlu_mt-4.0.0
cp MAKE_INC/make.linux.openmp make.inc   # BLASLIB이 이미 ../lib/libblas_OPENMP.a(번들 C BLAS) 참조
make blaslib      # 번들 C BLAS 빌드 (gcc만 사용)
make superlulib    # SuperLU_MT 코어 빌드
cd ..
```

두 가지 추가 패치 필요:

1. **`makefile.def`의 `SLU_LIBS`가 `-lopenblas`를 하드코딩** — 없는 라이브러리라
   링크 실패. `-lblas_OPENMP$(PLAT) -lgomp`(방금 빌드한 번들 BLAS)로 교체:
   ```
   SLU_LIBS = -L$(SLU_LIB) -lsuperlu_mt_OPENMP$(PLAT) -lblas_OPENMP$(PLAT) -lgomp
   ```
2. **`sources/thermal_data.c`가 `<cblas.h>`를 include하지만 실제로 `cblas_*`
   심볼은 하나도 호출하지 않음**(grep 확인, 0 matches) — 시스템에 CBLAS
   헤더가 없어 컴파일 실패. 빈 스텁 헤더로 해결 가능(내용 불필요, include만
   충족하면 됨). 동일 파일이 `openblas_set_num_threads(1)`을 무조건
   호출하는데, 이는 OpenBLAS 전용 스레드 수 조정 API(성능/결정성 목적,
   해석 정확도와 무관) — 번들 BLAS 사용 시 no-op으로 스텁 처리:
   ```c
   // superlu_mt-4.0.0/SRC/cblas.h (신규 생성)
   #ifndef HBM_BUILD_CBLAS_STUB_H
   #define HBM_BUILD_CBLAS_STUB_H
   static inline void openblas_set_num_threads(int n) { (void)n; }
   #endif
   ```

이후 정상 빌드:
```bash
make lib   # libthreed-ice-4.0.0.a
make bin   # 3D-ICE-Emulator, 3D-ICE-Client, 3D-ICE-Server
```

스모크 테스트(저장소 동봉 예제):
```bash
cd bin
./3D-ICE-Emulator example_steady.stk
```
정상 출력 시 factorization/solve 시간과 결과 파일이 생성된다.

## 3. 단위계 검증 (실측)

3D-ICE 내부 단위계는 **길이=마이크로미터(µm) 기준 파생 단위**를 쓴다.
공식 문서(PDF)를 WSL에서 렌더링할 수 없어(poppler-utils 미설치, sudo 불가),
예제 `.stk`의 알려진 물성값(Si 열전도율 등)을 역산해 확인했다:

- 열전도율: W/(µm·K) = W/(m·K) × 1e-6 (예제 SILICON k=1.30e-4 ≈ 130
  W/m·K × 1e-6 — 실제 Si 벌크 148과 근사)
- 체적비열: J/(µm³·K) = J/(m³·K) × 1e-18 (예제 값 1.628e-12가 Si
  1.63e6 J/(m³·K)와 정확히 일치, 오차 0.12%)
- HTC: W/(µm²·K) = W/(m²·K) × 1e-12
- 온도: 켈빈(K)

**최종 검증**: 단일 Si층(100µm 두께, 1mm×1mm) + 상단 HTC 2500 W/m²K,
전력 0.01W인 1D 사례를 3D-ICE로 풀고 손계산(HTC 저항 + 절반두께 전도저항
직렬)과 비교 — 3D-ICE 4.0030K vs 손계산 4.0034K, 오차 0.01% 이내로 확인.
`hbm_thermal/export_3dice.py`의 단위 변환 함수(`conductivity_w_mk_to_3dice`,
`htc_w_m2k_to_3dice`, `celsius_to_kelvin`)가 이 검증을 근거로 한다.

## 4. 스택 순서 함정 (실측 확인, 코드에 반영됨)

3D-ICE는 `stack:` 블록에서 **먼저 나열된 die를 "최상단(히트싱크에 가장
가까움)"으로 해석**한다(`bison/stack_description_parser.y` 주석 "parser
processes elements in the stack from the top most" + 파서 코드
`tmost = ...list_begin(...)`로 확인). `model_config.py`의 geometry는 반대로
`base_die`(스택 최하단)가 첫 원소다.

첫 시도에서 geometry 순서 그대로 `stack:` 블록을 채웠더니 **base_die가
히트싱크 바로 아래 배치되어 온도 구배가 반전**됐다(base_die가 top_die보다
낮은 온도로 나옴, Icepak과 반대 방향 — 오차도 14~20%로 합격선 초과).
`hbm_thermal/export_3dice.py`의 `build_die_blocks_and_stack()`는 `stack:`
블록만 geometry 역순(EMC 먼저, base_die 마지막)으로 쓰도록 수정해 해결.

## 5. 3D-ICE 문법 제약: 모든 die는 source 층 필수

`die` 문법은 `DIE IDENTIFIER ':' die_top_layers_list die_source_layer
die_bottom_layers_list`이며 `die_source_layer`는 선택이 아니라 필수다.
순수 `layer`만으로 구성된 die는 문법 오류("unexpected keyword die,
expecting keyword layer or keyword source", 실측 확인). 따라서 비전력
레이어(bump_layer_1..7, EMC)도 `source`로 선언하되 해당 .flp에서
`power values 0.0`으로 지정한다 — 물리적으로 layer와 동등.

## 6. 경계조건 매핑 (Icepak ↔ 3D-ICE)

| 조건 | Icepak | 3D-ICE |
|---|---|---|
| 상단 냉각 | `assign_stationary_wall_with_htc` (EMC 상면, 2500 W/m²K) | `top heat sink: heat transfer coefficient` (스택 최상단 자동 적용) |
| 주변온도 | `edit_design_settings(ambient_temperature=40)` | `top heat sink: temperature` (Kelvin) |
| 측면/하단 | Region 패딩 0 → 사실상 단열 | 기본값 단열(명시적 BC 없으면 adiabatic) — 별도 설정 불요, 동등 |
| 전력 | `assign_source` (base_die 8.8W + DRAM 8×0.9W) | die별 `.flp`의 `power values` |
| 해석 모드 | 전도 전용(Include Flow=False) | 3D-ICE는 애초에 컴팩트 열전도 모델(유동 없음) — 자동 등가 |

## 7. 실행 절차 (재현용)

```bash
# 1) 3D-ICE 빌드 (위 §2 참고, 최초 1회)
# 2) 교차검증 실행
python3 scripts/cross_validate_3dice.py \
    --3dice-bin /path/to/3d-ice/bin/3D-ICE-Emulator \
    --icepak-csv /path/to/hbm2e_die_temperatures.csv \
    --output-dir results/
```

`--total-power`, `--base-die-fraction`, `--footprint-mm`, `--ambient-c`,
`--htc-w-m2k`는 Icepak 실행 시 사용한 값과 반드시 동일해야 한다(기본값은
`build_icepak_model.py` 기본값과 일치).

## 8. 차이 원인 분석 (PASS했지만 주목할 차이 요인)

1. **avg==max (3D-ICE) vs avg≠max (Icepak)**: 3D-ICE는 균질화 layer-cake
   모델에서 die별 floorplan을 단일 사각형 균일 전력 영역으로 취급 —
   면내(in-plane) 온도 분포가 없는 lumped 모델이라 평균=최대. Icepak은
   3D FEM으로 실제 공간 구배(중심부 vs 가장자리)를 포착해 avg<max.
   본 비교는 avg 대 avg만 사용해 이 차이의 영향을 배제했다.
2. **셀 격자 해상도**: 3D-ICE dimensions 블록은 4×4 셀 조대 격자(균질화
   모델은 층내 물성이 균일하므로 세분화 이득이 적음) — Icepak의 mesh
   resolution과 직접 비교 대상은 아님(Task 3 mesh convergence와 별개 축).
3. **솔버 알고리즘 차이**: Icepak은 유한요소(FEM) 반복 솔버, 3D-ICE는
   컴팩트 RC망을 SuperLU_MT 희소 직접해법으로 풂 — 완전히 다른 수치 경로임에도
   0.004% 수준으로 수렴한 것은 두 모델이 동일 물리(균질화 이방성 전도 +
   HTC 경계조건)를 정확히 인코딩했다는 강한 증거.

## 참고

- 3D-ICE 리포지토리: https://github.com/esl-epfl/3d-ice (GPL v3)
- 순수 로직 모듈: `hbm_thermal/export_3dice.py` (단위 변환, .stk/.flp 생성),
  `hbm_thermal/comparison.py` (비교/판정)
- 테스트: `tests/test_export_3dice.py`, `tests/test_comparison.py`
