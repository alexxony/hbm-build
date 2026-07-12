# hbm_build — HBM2E 8-Hi 균질화 유효 열전도율 모듈

HBM2E 8-Hi 스택 열해석(향후 PyAEDT Icepak 스크립트 연동)을 위한
레이어별 이방성(anisotropic) 유효 열전도율(k_xy, k_z) 계산 모듈.

## 설치/실행

순수 Python 표준 라이브러리만 사용 (numpy 불필요).

```bash
python3 -m pytest tests/ -v
```

## 구조

```
hbm_thermal/
  materials.py    # 기본 물성 상수 (Si, Cu, SiO2, solder, underfill, EMC)
  homogenize.py   # 균질화 계산 핵심 (k_z_mixing, k_xy_hasselman_johnson, layer_stack_hbm2e)
tests/
  test_homogenize.py
```

## 수식 근거

### 1. 수직 방향 (k_z) — 부피가중 혼합법칙

```
k_z = Σ f_i · k_i
```

TSV(Cu)가 Si 매트릭스를 관통하거나, µbump(solder)가 underfill 사이에 박혀
있는 구조는 열류가 수직(z) 방향으로 각 물질을 병렬 경로로 통과한다고 보고
부피분율 가중 평균으로 근사한다.

### 2. 면내 방향 (k_xy) — Hasselman-Johnson / Maxwell-Eucken형

```
k_eff = k_m · [(k_i + k_m + f·(k_i − k_m)) / (k_i + k_m − f·(k_i − k_m))]
```

원통형 개재물(매트릭스 내 분산된 TSV/bump 단면)이 면내(xy) 방향 열전달을
방해/보조하는 정도를 근사하는 2D 복합재 유효 전도율 모델. 계면 열저항은
무시하는 단순형이며, f ∈ [0, 0.9] 범위에서 유효하다.

### 3. HBM2E 8-Hi 레이어 스택 기하 가정

- TSV: 지름 5.5 µm, pitch 48 µm, 정방 배열 → f_Cu = π·(d/2)²/pitch² ≈ 0.0103
- µbump: 지름 25 µm, 높이 20 µm, pitch 55 µm, staggered 배열(단위셀 면적은
  pitch²로 근사) → f_solder ≈ 0.1623
- DRAM die 두께 45 µm, base die 두께 60 µm, 최상단 die 위 EMC 100 µm
- TSV 라이너(SiO2)는 두께가 서브미크론 수준으로 무시 가능하여 계산에서 생략

레이어 구성: `base_die(TSV 함유 Si)` / `[bump_layer + dram_die(TSV 함유)] × 7`
/ `top_die(TSV 없음, 순수 Si)` / `EMC` → 총 17개 레이어.

## 제약 및 향후 계획

- 계면 열저항(TIM, 접합 저항) 미포함 — 1차 근사 모델
- 결과(레이어별 k_xy/k_z 텐서)는 PyAEDT Icepak 스크립트의 재료 정의 입력으로 사용 예정
