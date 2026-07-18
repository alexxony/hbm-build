#!/usr/bin/env python3
"""HBM2E 8-Hi layer-cake Icepak 모델을 PyAEDT로 생성하는 실행 진입점.

⚠️ 이 스크립트는 Ansys Electronics Desktop(AEDT) + PyAEDT가 설치된
Windows 환경에서만 실제로 동작한다. WSL/Linux에는 AEDT가 없으므로
여기서는 py_compile(문법 검사)까지만 가능하며, pyaedt import는 함수
내부로 격리해 모듈을 그냥 import/문법검사 하는 것만으로는 실패하지 않게 한다.

흐름:
    1. hbm_thermal.model_config 의 순수 스펙 함수로 지오메트리/재료/전력 스펙 계산
    2. Icepak 프로젝트 생성
    3. 이방성 재료 등록 (재료명 -> k_x, k_y, k_z)
    4. 레이어별 box 생성 + 재료 할당 (스택 z 방향 적층)
    5. base_die/DRAM die에 source power 할당 (총 전력 = --total-power)
    6. 최상단 면(top_die 상부)에 히트싱크 근사 BC(고정 HTC) + 주변 40°C
    7. 메시 설정 (Student 512K element 한계 대비 --mesh-fraction 안전율 적용,
       예상치 로그 출력 + 초과 예상 시 경고)
    8. steady-state 또는 transient 해석 실행
    9. die별 평균/최대 온도를 CSV로 export

실행 예시 (Windows, AEDT 설치 후):
    python build_icepak_model.py --project-name hbm2e_8hi --total-power 16.0 --steady
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

# hbm_thermal 패키지를 스크립트 위치 기준으로 import 가능하게 경로 추가.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from hbm_thermal.model_config import (  # noqa: E402
    BASE_DIE_BLOCK_NAMES,
    BASE_DIE_BLOCK_WIDTH_FRACTIONS,
    POWER_SCENARIOS,
    build_geometry_spec,
    build_material_spec,
    build_power_spec,
)

# Icepak Student 라이선스 mesh 상한 (elements). 근거: vault research/01-ansys-student-limits.md
_ICEPAK_STUDENT_MESH_LIMIT = 512_000

# 레이어 1개당 대략적인 element 예상치(경험적 근사, box당 육면체 메시 가정).
# 실제 값은 mesh-fraction/geometry에 따라 달라지므로 "안전율 경고용" 추정치일 뿐이다.
_ESTIMATED_ELEMENTS_PER_LAYER = 20_000

# 주변 온도(°C) — JEDEC/업계 통상 앰비언트 기준.
_AMBIENT_TEMP_C = 40.0

# 히트싱크 근사 경계조건: 최상단 면 고정 HTC (W/m^2K). 방열판 부착 근사치.
_HEATSINK_HTC_W_M2K = 2500.0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="HBM2E 8-Hi layer-cake Icepak 모델 생성 (PyAEDT, Windows+AEDT 필요)"
    )
    parser.add_argument(
        "--project-name", type=str, default="hbm2e_8hi_layercake", help="AEDT 프로젝트 이름"
    )
    parser.add_argument(
        "--total-power", type=float, default=16.0, help="스택 총 발열량 (W), 기본 16.0"
    )
    parser.add_argument(
        "--base-die-fraction",
        type=float,
        default=0.55,
        help="base_die가 차지하는 전력 비율 [0,1], 기본 0.55",
    )
    parser.add_argument(
        "--power-scenario",
        type=str,
        choices=sorted(POWER_SCENARIOS),
        default=None,
        help=(
            "base_die 블록별 전력맵(MHS) 시나리오. 지정 시 base_die를 "
            "base_die_phy/tsva/da 3 sub-box로 분할하고 시나리오 비율대로 전력을 "
            "배분한다. 기본 None = 기존 단일 base_die 동작(하위 호환, P3 T1/T2)."
        ),
    )
    parser.add_argument(
        "--bottom-htc",
        type=float,
        default=None,
        help=(
            "스택 최하단(base_die 하부면)에 추가할 고정 HTC (W/m^2K). "
            "기본 None = 기존 top-only 냉각(하위 호환). 지정 시 top+bottom "
            "양면 냉각 BC로 해석한다 (P4 B계열, docs/08-p4-highpower-design.md §2.1)."
        ),
    )
    parser.add_argument(
        "--footprint-mm",
        type=float,
        nargs=2,
        default=(11.0, 10.0),
        metavar=("X_MM", "Y_MM"),
        help="다이 풋프린트 (x, y) mm, 기본 11.0 10.0",
    )
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument(
        "--transient", action="store_true", help="과도(transient) 해석으로 실행"
    )
    mode_group.add_argument(
        "--steady", action="store_true", help="정상상태(steady-state) 해석으로 실행 (기본값)"
    )
    parser.add_argument(
        "--mesh-fraction",
        type=float,
        default=0.7,
        help="Student 512K 한계 대비 사용할 메시 예산 비율 (0~1), 기본 0.7 (안전율)",
    )
    parser.add_argument(
        "--non-graphical",
        action="store_true",
        help="AEDT를 GUI 없이 백그라운드로 실행",
    )
    parser.add_argument(
        "--output-csv",
        type=str,
        default="hbm2e_die_temperatures.csv",
        help="die별 온도 결과 CSV 출력 경로",
    )
    return parser.parse_args()


def _estimate_mesh_elements(n_layers: int) -> int:
    """레이어 수 기반 대략적 mesh element 예상치 (경고용 근사)."""
    return n_layers * _ESTIMATED_ELEMENTS_PER_LAYER


def _warn_if_mesh_exceeds_budget(n_layers: int, mesh_fraction: float) -> None:
    """Student 512K 한계 대비 예상 mesh가 예산을 초과하면 경고 로그를 출력한다."""
    budget = _ICEPAK_STUDENT_MESH_LIMIT * mesh_fraction
    estimated = _estimate_mesh_elements(n_layers)
    print(
        f"[mesh 예상치] 레이어 {n_layers}개 -> 예상 elements ≈ {estimated:,} "
        f"(Student 한계 {_ICEPAK_STUDENT_MESH_LIMIT:,} × 안전율 {mesh_fraction} "
        f"= 예산 {budget:,.0f})"
    )
    if estimated > budget:
        print(
            f"[경고] 예상 mesh element 수({estimated:,})가 안전 예산({budget:,.0f})을 "
            "초과할 것으로 보입니다. mesh-fraction을 낮추거나 로컬 refinement 영역을 "
            "줄이는 것을 고려하세요 (Icepak Student 상한: 512,000 elements)."
        )


def _apply_student_grpc_workarounds() -> None:
    """AEDT Student 접속에 필요한 gRPC/세션 감지 몽키패치를 적용한다.

    Icepak()/Desktop() 생성 전에 호출해야 효과가 있다. build_icepak_model()과
    mesh_convergence.py의 스윕 루프 양쪽에서 공유하는 진입점.
    """
    import os

    from ansys.aedt.core import settings

    # AEDT Student 2025 R2 이하는 기본 secure gRPC transport(wnua)로 기동이 실패한다
    # ("Failed to start on gRPC port" 반복 후 예외). insecure TCP 모드로 강제 전환 필요.
    # 근거: https://aedt.docs.pyansys.com/version/stable/Getting_started/Troubleshooting.html
    #       ("AEDT Student version fails to start via the default gRPC transport")
    os.environ["PYAEDT_USE_PRE_GRPC_ARGS"] = "True"
    settings.grpc_secure_mode = False

    # Student 버전은 콜드 스타트가 느려 기본 대기시간(120s) 안에 gRPC 서버가
    # 준비되지 못할 수 있다. batch.log상 서버는 요청 포트에 실제로 뜨는데
    # 클라이언트가 먼저 포기하는 패턴이 관찰됨 → 대기시간을 넉넉히 연장.
    settings.desktop_launch_timeout = 600

    # pyaedt의 @pyaedt_function_handler 기본 동작(generic/general_methods.py
    # raise_exception_or_return_false): enable_error_handler=False(기본)이면
    # 예외를 재발생시키기 전에 release_on_exception=True(기본)에 따라
    # **활성 AEDT 데스크톱 세션 전체(_desktop_sessions 전부)를 release_desktop()
    # 한다** — 특정 인스턴스가 아니라 프로세스 전역. mesh_convergence.py처럼
    # 레벨마다 새 Icepak 인스턴스를 만드는 스윕에서, 레벨 N의 API 호출 하나가
    # 예외를 던지면 레벨 N뿐 아니라 그 순간 존재하는 모든 데스크톱 세션이
    # 조용히 닫히고, 다음 레벨의 Icepak() 생성자 호출이 깨진 상태 위에서
    # 실행돼 스윕 전체가 죽는다(Task 3 Windows 2차 크래시 실측 확인:
    # 레벨1 GetSetups 예외 -> 레벨2 이후 행 자체가 CSV에 없음, 즉
    # try/except가 있는 코드에 도달하지도 못하고 Icepak() 생성자에서 죽음).
    # 레벨별 예외 격리는 스크립트 쪽 코드(mesh_convergence.py _run_level)가
    # 이미 책임지므로, pyaedt의 전역 자동 해제는 꺼서 레벨 간 세션을 서로
    # 침범하지 않게 한다.
    settings.release_on_exception = False

    # pyaedt(1.1.0/1.2.0 확인) 세션 감지 버그 우회: is_grpc_session_active()가
    # active_sessions()를 인자 없이 호출해 student_version=False 기본값으로
    # ansysedt.exe만 찾는다 → Student(ansysedtsv.exe)가 gRPC 포트를 물고 있어도
    # 영원히 "세션 없음" 판정(업스트림 이슈 #7891 계통). 이 머신은 Student 전용이므로
    # 감지 시 student_version=True를 강제한다.
    import ansys.aedt.core.desktop as _desktop_mod
    from ansys.aedt.core.generic import general_methods as _gm

    _orig_active_sessions = _gm.active_sessions

    def _active_sessions_student(version=None, student_version=False, non_graphical=None):
        return _orig_active_sessions(
            version=version, student_version=True, non_graphical=non_graphical
        )

    _gm.active_sessions = _active_sessions_student
    _desktop_mod.active_sessions = _active_sessions_student


def build_geometry_materials_bcs(
    ipk,
    stack_geometry: list[dict],
    material_spec: dict,
    power_spec: dict,
    bottom_htc_w_m2k: float | None = None,
) -> None:
    """이방성 재료·레이어 지오메트리·전력원·히트싱크 BC를 한 번만 구성한다.

    이 함수는 Icepak 인스턴스당 **정확히 한 번**만 호출해야 한다 — 같은
    이름의 재료/박스/BC를 다시 만들려고 하면 AEDT가 중복으로 취급해 실패
    하거나 예기치 않은 상태가 된다. mesh resolution을 바꿔가며 재해석하는
    스위프(scripts/mesh_convergence.py)는 이 함수를 딱 한 번 호출한 뒤
    solve_at_mesh_resolution()만 레벨마다 반복 호출해야 한다(Task 3 Windows
    3차 크래시 실측 확인: 레벨마다 새 Icepak 인스턴스+새 프로젝트를 만드는
    방식에서 두 번째 프로젝트의 InsertDesign이 None을 반환하며
    active_design() 폴백 경로가 AttributeError로 죽는 pyaedt 내부 버그를
    유발함 — 인스턴스/프로젝트 재사용으로 이 경로 자체를 피한다).

    Args:
        ipk: 생성된 ansys.aedt.core.Icepak 인스턴스 (빈 프로젝트).
        stack_geometry: build_geometry_spec() 결과.
        material_spec: build_material_spec() 결과.
        power_spec: build_power_spec() 결과.
        bottom_htc_w_m2k: 주어지면 스택 최하단(base_die 하부면)에도 고정 HTC
            BC를 추가한다(Task 5 #5 냉각 BC 파라미터 스터디 — top-only vs
            top+bottom, imec IEDM 2025 "backside 냉각 추가 시 17°C 저감"
            방향 재현 목표, vault research/03-prior-art.md L22). None이면
            기존 동작(top-only)과 완전히 동일.
    """
    # 1) 이방성 재료 등록 (재료명 -> k_x, k_y, k_z).
    for mat_name, props in material_spec.items():
        material = ipk.materials.add_material(mat_name)
        material.thermal_conductivity = [
            props["k_x"],
            props["k_y"],
            props["k_z"],
        ]

    # 2) 레이어별 box 생성 + 재료 할당 (스택 z 방향 적층).
    for layer in stack_geometry:
        ipk.modeler.create_box(
            origin=layer["origin_mm"],
            sizes=layer["size_mm"],
            name=layer["name"],
            material=layer["material_name"],
        )

    # 2.5) Region(공기 박스)을 스택 bbox에 밀착 — 패딩 전부 0.
    # Icepak의 HTC 외부조건(Stationary Wall)은 계산 도메인 경계와 일치하는
    # 면에서만 유효하다. Region이 스택보다 크면 EMC 상면이 도메인 내부면이
    # 되어 HTC가 무시되고, 16W의 출구가 없는 특이계가 되어 온도가 솔버
    # 기본 상한 5000K(=4726.85°C)까지 발산한다(실측 3회 재현).
    # 패딩 0이면 EMC 상면 = 도메인 경계 → HTC가 진짜 경계조건이 된다.
    ipk.modeler.edit_region_dimensions([0, 0, 0, 0, 0, 0])

    # 3) base_die/DRAM die에 source power 할당.
    for layer_name, power_w in power_spec.items():
        ipk.assign_source(
            assignment=layer_name,
            thermal_condition="Total Power",
            assignment_value=f"{power_w}W",
            boundary_name=f"source_{layer_name}",
        )

    # 4) 스택 최상면(EMC 상부, 공기에 노출된 외곽면)에 히트싱크 근사 BC(고정 HTC).
    # 주의: top_die 윗면은 EMC에 덮인 매몰 내부면이라 거기에 HTC를 걸면
    # 유효 방열 경로가 없어져 해가 발산한다(전 die 5000K 캡, 실측 2회 재현).
    # pyaedt 1.1.0: HTC 면 BC는 assign_stationary_wall_with_htc가 정석.
    top_layer = ipk.modeler[stack_geometry[-1]["name"]]  # EMC (스택 최상단)
    top_face = max(top_layer.faces, key=lambda f: f.center[2])
    ipk.assign_stationary_wall_with_htc(
        top_face.id,
        name="heatsink_approx",
        htc=_HEATSINK_HTC_W_M2K,  # float -> w_per_m2kel 단위로 해석됨
    )

    # 4.5) (선택) 스택 최하단(base_die 하부, 공기에 노출된 외곽면)에 추가
    # HTC BC — Task 5 #5 냉각 BC 파라미터 스터디(top-only vs top+bottom).
    # base_die는 스택 최하단이므로 그 최소 z면이 Region 경계와 밀착한다
    # (2.5단계에서 Region 패딩을 전부 0으로 맞췄으므로 top_face와 동일한
    # 근거로 이 면도 유효 외부 경계면이다).
    #
    # P3 T2 주의: power_scenario 모드에서는 stack_geometry[0]이 base_die
    # 전체가 아니라 base_die_phy(3 sub-box 중 첫 번째, x방향 폭의 일부)만
    # 가리킨다 — 그 하나에만 BC를 걸면 TSVA/DA 구간 바닥면이 방열 경로 없이
    # 남는다. 최하단 z 슬라이스를 공유하는 모든 레이어(단일 base_die 또는
    # base_die_phy/tsva/da 3개)를 찾아 각각에 BC를 건다.
    if bottom_htc_w_m2k is not None:
        first_name = stack_geometry[0]["name"]
        if first_name in BASE_DIE_BLOCK_NAMES:
            # power_scenario 모드: base_die가 3 sub-box로 나뉘어 stack_geometry
            # 앞쪽에 연달아 나온다 — 전부 base_die 하부 z슬라이스이므로 모두 대상.
            bottom_layer_names = [
                layer["name"] for layer in stack_geometry if layer["name"] in BASE_DIE_BLOCK_NAMES
            ]
        else:
            bottom_layer_names = [first_name]  # 기존 동작: base_die 단일 box.
        for idx, layer_name in enumerate(bottom_layer_names):
            bottom_layer = ipk.modeler[layer_name]
            bottom_face = min(bottom_layer.faces, key=lambda f: f.center[2])
            ipk.assign_stationary_wall_with_htc(
                bottom_face.id,
                name=f"backside_cooling_{idx}" if len(bottom_layer_names) > 1 else "backside_cooling",
                htc=bottom_htc_w_m2k,
            )

    ipk.edit_design_settings(ambient_temperature=_AMBIENT_TEMP_C)


def create_conduction_setup(ipk, transient: bool):
    """전도 전용(Include Flow=False) 해석 셋업을 한 번만 생성한다.

    build_geometry_materials_bcs()와 마찬가지로 Icepak 인스턴스당 한 번만
    호출한다. mesh resolution 변경만으로 재해석하는 스위프는 이 setup
    객체를 solve_at_mesh_resolution()에 재사용한다.

    Args:
        ipk: build_geometry_materials_bcs() 완료된 Icepak 인스턴스.
        transient: True면 과도 해석 모드로 전환.

    Returns:
        생성된 SetupIcepak 객체.
    """
    # 전도 전용(Temperature-only)으로 강제: 기본 셋업은 유동 ON인데
    # 밀폐 Region에서 유동을 20회 반복으로 돌리면 수렴 실패 → 전 노드가
    # AEDT 온도 상한 5000K(=4726.85°C)로 캡되는 쓰레기 결과가 나온다(실측).
    # layer-cake 고체 스택 + 고정 HTC 방열 경로에는 전도 전용이 표준.
    setup = ipk.create_setup(MaxIterations=200)
    setup.props["Include Flow"] = False
    setup.update()
    if transient:
        setup.props["Transient"] = True
    return setup


def solve_at_mesh_resolution(ipk, mesh_region_resolution: int) -> bool:
    """global mesh region의 MeshRegionResolution만 바꿔 재해석한다.

    build_geometry_materials_bcs()/create_conduction_setup()이 이미 끝난
    Icepak 인스턴스에 대해, mesh resolution만 바꿔가며 여러 번 안전하게
    반복 호출할 수 있다(SetupIcepak.update()/mesh 영역 update()는 기존
    설정을 덮어쓰는 멱등적 호출 — pyaedt 소스에서 update() 시그니처 확인).

    Args:
        ipk: build_geometry_materials_bcs()+create_conduction_setup() 완료된 인스턴스.
        mesh_region_resolution: global mesh region의 MeshRegionResolution (정수 1~5).

    Returns:
        ipk.analyze()의 반환값(bool) — True면 해석 성공. 호출자는 이 값을 보고
        후처리(get_scalar_field_value 등) 실행 여부를 결정해야 한다. 해석 실패/
        미완료 상태에서 후처리를 시도하면 CalculatorWrite 등 후속 네이티브 호출이
        gRPC 오류로 죽을 수 있다(Task 3 Windows 실행 크래시 실측 확인).
    """
    # 메시 설정. automatic 모드 + MeshRegionResolution(1~5)이 1.1.0에서 검증된 경로.
    global_mesh = ipk.mesh.global_mesh_region
    global_mesh.manual_settings = False
    global_mesh.settings["MeshRegionResolution"] = mesh_region_resolution
    global_mesh.update()

    analyze_ok = ipk.analyze()
    if not analyze_ok:
        # P4 T3 3차 A-S1 실측 확인: ipk.analyze() 내부(analysis.py analyze_setup())가
        # setup=None일 때 self.odesign.AnalyzeAll(blocking)을 호출하는데, 이 native
        # 호출이 예외를 던지면 pyaedt가 `except Exception: logger.error("Error in
        # solving all setups (AnalyzeAll).")`로 **원래 예외 메시지를 버리고** 제네릭
        # 텍스트만 남긴다(analysis.py L1819-1821). "Design setup None solved
        # correctly in ...s" 로그도 name=None을 그대로 찍는 상시 출력이라 진짜
        # 실패 원인과 무관 — setup 이름 미등록을 의미하지 않는다.
        # AEDT 네이티브 메시지 매니저(oDesktop.GetMessages)를 직접 조회해 pyaedt가
        # 삼킨 실제 네이티브 오류 텍스트를 회수한다.
        try:
            native_messages = ipk.odesktop.GetMessages("", "", 0)
            print(f"[진단] AEDT 네이티브 메시지 매니저 회수 (analyze() 실패 직후): {native_messages}")
        except Exception as diag_exc:  # noqa: BLE001 - 진단 전용, 원 실패를 가리면 안 됨
            print(f"[진단] GetMessages() 조회 자체가 실패: {diag_exc!r}")
        try:
            setup_names = ipk.setup_names
            print(f"[진단] 현재 등록된 setup 이름 목록: {setup_names!r}")
        except Exception as diag_exc:  # noqa: BLE001
            print(f"[진단] setup_names 조회 자체가 실패: {diag_exc!r}")
    return analyze_ok


def build_and_solve(
    ipk,
    stack_geometry: list[dict],
    material_spec: dict,
    power_spec: dict,
    mesh_region_resolution: int,
    transient: bool,
    bottom_htc_w_m2k: float | None = None,
) -> bool:
    """단발성 해석(Task 2, build_icepak_model())용 편의 래퍼.

    build_geometry_materials_bcs() + create_conduction_setup() +
    solve_at_mesh_resolution()을 순서대로 한 번씩 호출한다. 인스턴스 하나로
    끝나는 단발 실행에서만 사용할 것 — 같은 인스턴스에 이 함수를 두 번
    호출하면 지오메트리/재료/BC가 중복 생성돼 실패한다. 여러 mesh
    resolution을 반복 시도하려면(mesh_convergence.py처럼) 이 함수 대신
    build_geometry_materials_bcs()+create_conduction_setup()을 한 번,
    solve_at_mesh_resolution()을 레벨마다 호출할 것.

    Args:
        ipk: 생성된 ansys.aedt.core.Icepak 인스턴스 (빈 프로젝트).
        stack_geometry: build_geometry_spec() 결과.
        material_spec: build_material_spec() 결과.
        power_spec: build_power_spec() 결과.
        mesh_region_resolution: global mesh region의 MeshRegionResolution (정수 1~5).
        transient: True면 과도 해석 모드로 전환.
        bottom_htc_w_m2k: 주어지면 스택 최하단에도 HTC BC를 추가한다
            (P4 B계열, top+bottom 냉각). None이면 기존 top-only 동작.

    Returns:
        ipk.analyze()의 반환값(bool) — True면 해석 성공.
    """
    build_geometry_materials_bcs(
        ipk, stack_geometry, material_spec, power_spec, bottom_htc_w_m2k=bottom_htc_w_m2k
    )
    create_conduction_setup(ipk, transient)
    return solve_at_mesh_resolution(ipk, mesh_region_resolution)


def build_icepak_model(args: argparse.Namespace) -> None:
    """PyAEDT로 Icepak 모델을 생성하고 해석을 실행한다.

    pyaedt import를 함수 내부에 두어, AEDT가 없는 환경에서 이 모듈을
    import하거나 py_compile 하는 것만으로는 실패하지 않도록 한다.
    """
    from ansys.aedt.core import Icepak  # pyaedt Icepak 앱. Student도 공식 지원.

    _apply_student_grpc_workarounds()

    stack_geometry = build_geometry_spec(
        footprint_mm=tuple(args.footprint_mm), power_scenario=args.power_scenario
    )
    material_spec = build_material_spec()
    power_spec = build_power_spec(
        total_w=args.total_power,
        base_die_fraction=args.base_die_fraction,
        power_scenario=args.power_scenario,
    )

    _warn_if_mesh_exceeds_budget(len(stack_geometry), args.mesh_fraction)

    ipk = Icepak(
        project=args.project_name,
        non_graphical=args.non_graphical,
        new_desktop=True,
        close_on_exit=False,
        student_version=True,
    )

    try:
        mesh_region_resolution = max(1, round(3 * args.mesh_fraction))
        analyze_ok = build_and_solve(
            ipk,
            stack_geometry=stack_geometry,
            material_spec=material_spec,
            power_spec=power_spec,
            mesh_region_resolution=mesh_region_resolution,
            transient=args.transient,
            bottom_htc_w_m2k=args.bottom_htc,
        )
        if not analyze_ok:
            print(
                "[오류] ipk.analyze()가 실패를 반환했습니다 — 후처리를 건너뜁니다. "
                "해석 셋업/BC를 확인할 것."
            )
            sys.exit(1)

        # die별 평균/최대 온도 추출 -> CSV export.
        # power_scenario 지정 시 base_die 대신 base_die_phy/tsva/da 3블록이
        # stack_geometry에 들어있다 — 둘 다 자연스럽게 걸리도록 base_die로
        # 시작하는 이름(단일 base_die 및 3블록 전부)을 포함한다.
        die_layer_names = [
            layer["name"]
            for layer in stack_geometry
            if layer["name"].startswith(("base_die", "dram_die", "top_die"))
        ]
        _export_die_temperatures(
            ipk,
            die_layer_names,
            args.output_csv,
            base_die_block_width_fractions=(
                BASE_DIE_BLOCK_WIDTH_FRACTIONS if args.power_scenario is not None else None
            ),
        )

    finally:
        ipk.release_desktop()


def _export_die_temperatures(
    ipk,
    die_layer_names: list[str],
    output_csv: str,
    base_die_block_width_fractions: dict[str, float] | None = None,
) -> None:
    """die별 평균/최대 온도를 post-processing에서 추출해 CSV로 저장한다.

    Args:
        ipk: 해석 완료된 Icepak 인스턴스.
        die_layer_names: 온도를 추출할 오브젝트(레이어)명 목록.
        output_csv: 결과 CSV 경로.
        base_die_block_width_fractions: 지정되면(P3 T2, power_scenario 모드)
            die_layer_names에 BASE_DIE_BLOCK_NAMES(base_die_phy/tsva/da)가
            포함된 것으로 보고, 3블록 온도 행에 더해 면적가중 합성 base_die
            행을 추가한다 — avg는 폭 비율 가중평균(면적가중, y·z 동일이므로
            폭 비율=면적 비율), max는 3블록 max 중 최댓값(hotspot 근사).
            None이면(기존 단일 base_die 동작) 이 로직을 건너뛴다.
    """
    rows = []
    temps_by_name: dict[str, dict[str, float]] = {}
    for name in die_layer_names:
        # pyaedt 1.1.0 시그니처: quantity="Temp", 대상 지정은 object_name=
        # (solution=은 해석 셋업 이름 자리 — 오브젝트명 넣으면 안 됨).
        avg_temp = ipk.post.get_scalar_field_value(
            quantity="Temp", scalar_function="Mean", object_name=name
        )
        max_temp = ipk.post.get_scalar_field_value(
            quantity="Temp", scalar_function="Maximum", object_name=name
        )
        temps_by_name[name] = {"avg_temp_c": avg_temp, "max_temp_c": max_temp}
        rows.append({"die": name, "avg_temp_c": avg_temp, "max_temp_c": max_temp})

    if base_die_block_width_fractions is not None:
        block_names_present = [
            name for name in base_die_block_width_fractions if name in temps_by_name
        ]
        if block_names_present:
            total_frac = sum(base_die_block_width_fractions[n] for n in block_names_present)
            composite_avg = sum(
                temps_by_name[n]["avg_temp_c"] * base_die_block_width_fractions[n]
                for n in block_names_present
            ) / total_frac
            composite_max = max(temps_by_name[n]["max_temp_c"] for n in block_names_present)
            rows.append(
                {"die": "base_die", "avg_temp_c": composite_avg, "max_temp_c": composite_max}
            )

    with open(output_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["die", "avg_temp_c", "max_temp_c"])
        writer.writeheader()
        writer.writerows(rows)

    print(f"[결과] die별 온도 CSV 저장 완료: {output_csv}")

    # 발산 감지 가드: AEDT는 해가 발산해도 "solved correctly"를 찍고
    # 온도를 상한 5000K(=4726.85°C)로 캡해서 내보낸다. 물리 범위 밖이면 즉시 경고.
    max_seen = max(row["max_temp_c"] for row in rows)
    if max_seen > 500.0:
        print(
            f"[경고] 최고 온도 {max_seen:.1f}°C — 물리적으로 불가능한 값. "
            "해가 발산했을 가능성이 높다 (유효 방열 BC 부재/수렴 실패 의심). "
            "결과를 신뢰하지 말 것."
        )
    else:
        print(f"[검증] 최고 온도 {max_seen:.1f}°C — 물리 범위 내.")


def main() -> None:
    args = _parse_args()
    build_icepak_model(args)


if __name__ == "__main__":
    main()
