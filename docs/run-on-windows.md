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

### 5.0 "AEDT 창은 뜨는데 아무것도 안 만들어짐" (연결 실패)

전형적 원인 2가지. 순서대로 진단:

1. **pyaedt 버전 확인** (가장 유력):
   ```powershell
   pip show pyaedt
   ```
   **pyaedt 1.2.0에 Student판 회귀 버그가 있다** (GitHub 이슈
   [#7891](https://github.com/ansys/pyaedt/issues/7891), 2026-07 기준 미해결).
   세션 감지 함수 `active_sessions()`가 `student_version` 인자를 전달받지
   못해 정규판 프로세스명(`ansysedt.exe`)만 찾고 Student 프로세스
   (`ansysedtsv.exe`)를 못 본다 → AEDT 창은 뜨지만 PyAEDT는 "세션 없음"으로
   판단, 연결 실패. **버전이 1.2.0 이상이면 다운그레이드**:
   ```powershell
   pip install "pyaedt<1.2"
   ```
2. **연결 스모크 테스트** (모델 로직 배제, 연결만 검증):
   ```powershell
   python scripts\smoke_test_aedt.py
   ```
   - `[4/6]`에서 실패 → gRPC 연결 문제. 아래 3단계로.
   - `[5-6/6]`에서 실패 → 연결은 정상, 모델 생성 API 문제. 에러 전문을 가져올 것.
3. **수동 기동 + attach 분리 테스트** (서버 문제 vs 클라이언트 문제 분리):
   ```powershell
   # Student판 gRPC 서버 수동 기동 (경로는 설치 위치에 맞게;
   # 통상 C:\Program Files\ANSYS Inc\ANSYS Student\v252\AnsysEM\Win64\)
   ansysedtsv.exe -grpcsrv 50051
   # 다른 터미널에서:
   python scripts\smoke_test_aedt.py --attach-port 50051
   ```
   attach가 성공하면 서버는 정상이고 PyAEDT의 기동/감지 경로만 문제 —
   pyaedt 다운그레이드(1번)로 해결된다. attach도 실패하면 콘솔 출력 전문 +
   `%TEMP%`의 최신 `pyaedt_*.log`를 가져올 것.

참고: 현재 스크립트의 `PYAEDT_USE_PRE_GRPC_ARGS=True` + `grpc_secure_mode=False`는
공식 워크어라운드가 맞다 (Student ≤2025 R2는 기본 secure(wnua) transport 미지원,
[공식 트러블슈팅 문서](https://aedt.docs.pyansys.com/version/stable/Getting_started/Troubleshooting.html),
이슈 [#7842](https://github.com/ansys/pyaedt/issues/7842)). 이 설정은 유지한 채
버전만 맞추면 된다.

### 5.0.1 "전 die 온도가 4726.85°C" (해석 발산 런북)

4726.85°C = 정확히 5000 K = 솔버 기본 온도 상한. **AEDT는 발산해도
"solved correctly"를 출력하므로** 스크립트의 `[검증]`/`[경고]` 줄로 판정한다.
원인 우선순위 (P1 디버깅에서 실측 확정, 커밋 e20eb32→5888fda):

1. **Region이 스택보다 큼** (실제 근본 원인이었음): HTC 외부조건(Stationary
   Wall)은 계산 도메인 경계면에서만 유효. Region(공기 박스)이 스택을 감싸면
   EMC 상면이 내부면이 되어 HTC가 조용히 무시됨 → 16W 출구 없음 → 발산.
   해결: `ipk.modeler.edit_region_dimensions([0]*6)` (스크립트 반영됨).
2. **HTC를 매몰면에 할당**: top_die 상면은 EMC에 덮인 내부면 — HTC는 반드시
   스택 최외곽 노출면(EMC 상면)에 걸 것 (스크립트 반영됨).
3. **유동 ON + 밀폐 Region**: 기본 셋업은 SteadyTemperatureAndFlow. 전도 전용
   모델에선 `setup.props["Include Flow"] = False` + MaxIterations 200 (반영됨).

진단 팁: BC가 실제로 기록됐는지는 프로젝트 파일(텍스트)을 직접 확인 —
`grep -n "BoundarySetup\|Stationary Wall\|Total Power" <프로젝트>.aedt`.

### 5.1 기타

- **"mesh size exceeding" 오류**: `--mesh-fraction`을 낮추거나 풋프린트를
  줄여본다 (Ansys Learning Forum에 다수 보고된 Student 공통 이슈).
- **AEDT 프로세스 연결 실패**: 기존 AEDT 프로세스를 모두 종료한 뒤 재시도.
  `Icepak(new_desktop=True, ...)` 호출이 매번 새 AEDT 인스턴스를 띄우므로
  좀비 프로세스가 남아 있으면 충돌할 수 있다.
- **재료/전력 스펙이 의도와 다르게 보임**: `hbm_thermal/model_config.py`의
  `build_geometry_spec`, `build_material_spec`, `build_power_spec`는 AEDT 없이도
  WSL/Linux에서 단독 실행/검증 가능하다 (`python3 -m pytest tests/ -v`).
  스펙 자체가 의심되면 먼저 여기서 디버깅한다.
