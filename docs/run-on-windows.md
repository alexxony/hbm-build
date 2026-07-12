# Windows에서 Icepak 모델 실행 가이드

이 문서는 `scripts/build_icepak_model.py`를 실제로 실행하기 위해 **Windows +
Ansys Electronics Desktop (AEDT) Student** 환경에서 준비해야 할 것을 설명한다.
WSL/Linux에는 AEDT가 설치되지 않으므로 이 스크립트는 Windows에서만 동작한다.

## 1. 사전 준비

1. **Ansys Electronics Desktop Student** 설치 확인 (이미 로컬 Windows에 설치됨 — Twin
   Builder 사용 이력 있음). Icepak은 Student 번들에 기본 포함되어 있다.
2. **Windows Python 환경** 준비 (3.9 이상 권장, AEDT 2023 R1 이후 버전과 함께 검증됨):
   ```powershell
   python -m venv .venv
   .venv\Scripts\activate
   ```
3. **PyAEDT 설치**:
   ```powershell
   pip install pyaedt
   ```
   - PyAEDT는 AEDT Student 2022 R1 이후 버전을 공식 지원한다 (근거:
     https://github.com/ansys/pyaedt/blob/main/README.md).
4. 이 저장소(`hbm_build`)를 Windows 파일시스템 경로로 클론하거나 WSL 경로를
   그대로 사용 (`\\wsl$\...` 마운트 경유 시 pyaedt-AEDT 프로세스 통신이
   불안정할 수 있으니, 가능하면 순수 Windows 경로 사용 권장).

## 2. 실행 명령

프로젝트 루트(`hbm_build/`)에서:

```powershell
python scripts\build_icepak_model.py --project-name hbm2e_8hi --total-power 16.0 --steady
```

주요 옵션:

| 옵션 | 설명 | 기본값 |
|---|---|---|
| `--project-name` | AEDT 프로젝트 이름 | `hbm2e_8hi_layercake` |
| `--total-power` | 스택 총 발열량 (W) | 16.0 |
| `--base-die-fraction` | base_die 전력 비율 [0,1] | 0.55 |
| `--footprint-mm X Y` | 다이 풋프린트 (mm) | 11.0 10.0 |
| `--steady` / `--transient` | 정상상태 / 과도 해석 | `--steady` (기본) |
| `--mesh-fraction` | Student 512K 한계 대비 사용 비율 (0~1) | 0.7 |
| `--non-graphical` | AEDT GUI 없이 백그라운드 실행 | 꺼짐 (GUI 표시) |
| `--output-csv` | 결과 CSV 경로 | `hbm2e_die_temperatures.csv` |

처음 실행할 때는 `--non-graphical` 없이 실행해 AEDT GUI에서 지오메트리/메시가
의도대로 생성되는지 눈으로 확인하는 것을 권장한다.

## 3. Student 라이선스 한계 및 대응

- **Icepak 메시 상한: 512,000 elements** (근거: vault
  `research/01-ansys-student-limits.md`). 스크립트는 실행 전 레이어 수 기반
  대략적 mesh 예상치를 로그로 출력하고, 예산 초과가 예상되면 경고를 띄운다.
  경고가 뜨면 `--mesh-fraction`을 낮추거나(예: 0.5) 로컬 refinement 영역을
  줄여야 한다.
- **4 core 제한**: HPC/분산 해석 불가, local solve만 가능. 별도 설정 불필요 —
  Student 라이선스가 자동으로 이를 강제한다.
- **Geometry export 불가**: 결과 검증/재사용은 CSV(die별 온도) 및 AEDT
  프로젝트 파일(`.aedt`) 자체로 한다.

## 4. 실행 후 확인할 것

1. 콘솔에 출력되는 `[mesh 예상치]` 로그에서 예상 element 수가 512K 예산 내에
   있는지 확인.
2. AEDT GUI에서 지오메트리 트리에 17개 레이어(base_die, bump_layer_1..7,
   dram_die_1..7, top_die, EMC)가 순서대로 쌓였는지 확인.
3. 해석 완료 후 `--output-csv`로 지정한 파일에 die별 평균/최대 온도가
   기록되는지 확인.
4. 결과 CSV를 vault(`/mnt/c/ObsidianVault/HBM_build/`)로 복사해 두면 다음
   단계(mesh convergence, 3D-ICE/CoMeT 교차검증)에서 참조하기 쉽다.

## 5. 문제 발생 시

- **"mesh size exceeding" 오류**: `--mesh-fraction`을 낮추거나 풋프린트를
  줄여본다 (Ansys Learning Forum에 다수 보고된 Student 공통 이슈).
- **AEDT 프로세스 연결 실패**: 기존 AEDT 프로세스를 모두 종료한 뒤 재시도.
  `Icepak(new_desktop=True, ...)` 호출이 매번 새 AEDT 인스턴스를 띄우므로
  좀비 프로세스가 남아 있으면 충돌할 수 있다.
- **재료/전력 스펙이 의도와 다르게 보임**: `hbm_thermal/model_config.py`의
  `build_geometry_spec`, `build_material_spec`, `build_power_spec`는 AEDT 없이도
  WSL/Linux에서 단독 실행/검증 가능하다 (`python3 -m pytest tests/ -v`).
  스펙 자체가 의심되면 먼저 여기서 디버깅한다.
