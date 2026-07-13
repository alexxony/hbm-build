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

## 4.5 Task 3: mesh convergence 스터디

`scripts/mesh_convergence.py`는 `build_icepak_model.py`와 동일한 빌드 로직
(`build_and_solve()`, `scripts/build_icepak_model.py`에서 import)을 재사용해
mesh resolution 레벨(1~5, `MeshRegionResolution` 정수)을 순차 스윕하고
element 수·die별 온도·해석 시간·수렴 여부를 기록한다.

실행 명령 (프로젝트 루트 `hbm_build/`에서):

```powershell
python scripts\mesh_convergence.py --levels 1,2,3,4,5
```

주요 옵션 (build_icepak_model.py와 공통인 `--total-power`, `--base-die-fraction`,
`--footprint-mm`, `--transient`, `--non-graphical`는 동일하게 지원):

| 옵션 | 설명 | 기본값 |
|---|---|---|
| `--levels` | 스윕할 mesh resolution 레벨, 콤마 구분 (예: `1,2,3`) | `1,2,3,4,5` (전체) |
| `--project-name-prefix` | 레벨별 AEDT 프로젝트 이름 접두어 (`_L{level}` 접미어 자동 부여) | `hbm2e_8hi_meshconv` |
| `--output-csv` | 결과 CSV 경로 | `results/mesh_convergence.csv` |
| `--dry-run` | AEDT 연결 없이 스윕 설정만 출력하고 종료 (WSL에서도 검증 가능) | 꺼짐 |

**중단 후 재개**: 한 레벨이 오래 걸리거나 중간에 끊기면 `--levels`로 남은
레벨만 지정해 재실행할 수 있다 (예: 1,2 완료 후 `--levels 3,4,5`). CSV는
매 실행마다 전체를 새로 쓰므로, 재개 시 이전 레벨 결과를 CSV에 이어붙이려면
각 실행의 CSV를 레벨 구간별로 별도 파일(`--output-csv`)로 저장한 뒤 합칠 것.

**512K 가드**: 레벨별 실제 element 수는 실행 후에만 확인 가능하므로, 스크립트는
해석 완료 후 element 수를 조회해 512K 초과 시 해당 레벨을 `skipped_over_budget`
플래그로 CSV에 기록하고 온도 값은 비워둔다.

**발산 가드**: 각 레벨의 base_die max 온도가 500°C를 넘으면 `diverged` 플래그를
세우고 경고를 출력한다 (§5.0.1 런북 참고).

**수렴 판정**: 유효한(skip/발산 아닌) 연속 레벨 간 base_die max 온도 변화율이
1% 이하면 `converged=True`로 표시한다. skip/발산 레벨은 비교 기준에서 제외되고
다음 유효 레벨은 그 이전 유효 레벨과 비교한다.

**⚠️ Windows 첫 실행 검증 필요**: mesh element 수 조회(`_get_mesh_element_count`,
`scripts/mesh_convergence.py`)는 pyaedt 공식 문서에 convergence 스터디 전용
API가 명시되어 있지 않아 두 가지 경로(글로벌 메시 통계 → 해석 프로파일 텍스트
파싱)를 순서대로 시도하고, 둘 다 실패하면 경고만 출력하고 512K 가드를
건너뛰도록 방어적으로 작성했다. 첫 실행 시 element 수가 정상적으로 찍히는지
반드시 콘솔에서 확인할 것 — 조회 실패 시 AEDT GUI의 Mesh Statistics 창에서
수동 확인 후 이슈로 남겨 다음 정비 때 반영.

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

### 5.0.2 "레벨 N에서 예외 → 그 다음 레벨들이 CSV에 흔적도 없이 사라짐" (mesh_convergence.py 다중 인스턴스 스위프 전용)

증상: 스위프 도중 레벨 하나에서 gRPC 오류(`Failed to execute gRPC AEDT
command: <아무 메서드>`, 예: `GetSetups`)가 나면 그 레벨은 CSV에 `error` 행으로
정상 기록되는데, **그 다음 레벨들은 아예 실행 시도조차 안 된 것처럼 CSV에
행이 없다**(실측 확인, 2026-07-13, mesh_convergence.py 2차 크래시).

**근본 원인**: pyaedt의 `@pyaedt_function_handler` 데코레이터 기본 동작
(`generic/general_methods.py`의 `raise_exception_or_return_false`) —
`settings.enable_error_handler`가 기본값 `False`이면 예외를 재발생시키기
전에 `settings.release_on_exception`(기본값 `True`)에 따라 **그 순간
존재하는 활성 AEDT 데스크톱 세션 전체**(`_desktop_sessions`의 모든 항목)를
`release_desktop()`한다. 즉 pyaedt API 호출 하나의 실패가 스크립트 코드와
무관하게 프로세스 전역 데스크톱 세션을 조용히 정리해버린다.

`build_icepak_model.py`처럼 인스턴스 하나만 쓰는 스크립트(Task 2)는 이
전역 정리가 문제되지 않는다 — 애초에 그 하나뿐인 세션이 정리되고 나면
스크립트가 곧 끝나기 때문. 하지만 `mesh_convergence.py`처럼 레벨마다
**새 Icepak 인스턴스**를 만드는 스위프에서는, 레벨 N의 예외가 레벨 N+1의
`Icepak()` 생성자가 실행되기 *전에* 이미 데스크톱 세션 인프라를 건드려
놓는다 → 레벨 N+1의 `Icepak()` 생성자 자체가 깨진 상태 위에서 실행돼
예외를 던지는데, 이 생성자 호출이 (수정 전 코드에서는) try 블록 **밖**에
있어서 `_run_level` 함수 자체를 뚫고 나가 전체 `for` 루프를 죽였다.

**해결** (커밋 참고, 두 부분):
1. `build_icepak_model.py`의 `_apply_student_grpc_workarounds()`에
   `settings.release_on_exception = False`를 추가 — pyaedt의 전역 자동
   해제를 끄고, 레벨별 예외 격리는 스크립트 코드가 전담하게 함.
2. `mesh_convergence.py`의 `_run_level()`: `Icepak(...)` 생성자 호출을
   try 블록 **안**으로 이동 — 생성자 자체가 실패해도 error 플래그 행으로
   기록되고 다음 레벨로 넘어가도록 함.

**진단 팁**: 레벨 N에서 크래시 후 CSV에 레벨 N+1부터 행이 없다면, 이
실패 모드를 의심할 것 — `_run_level`의 try 블록 범위(특히 `Icepak(...)`
생성자가 안에 있는지)와 `settings.release_on_exception` 설정을 먼저
확인한다.

**미확인 대안/보조 가설**: 애초에 레벨 1에서 `GetSetups`가 왜 실패했는지
(위 흐름은 "그 이후 레벨들이 사라진 이유"만 설명함) 자체는 이번 수정으로
확정되지 않았다. 후보: (a) `new_desktop=True`로 레벨마다 새 인스턴스를
띄우는 방식이 Student 라이선스의 동시 프로젝트 추적 제약과 충돌해
`desktop.active_design()`이 `None`을 반환하는 경우, (b) 이전 레벨(또는
이전 실행)의 좀비 AEDT 프로세스가 남아 세션 식별이 꼬이는 경우(§5.1
"AEDT 프로세스 연결 실패"와 동일 계열). 다음 Windows 실행에서 레벨 1이
또 실패하면 `GetSetups` 자체의 원인을 이 각도로 추가 진단할 것 — 인스턴스
재사용(레벨마다 새로 만들지 않고 프로젝트/디자인만 갈아끼우는 방식)으로
바꾸는 것도 고려 대상.

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
