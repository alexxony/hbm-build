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


def build_icepak_model(args: argparse.Namespace) -> None:
    """PyAEDT로 Icepak 모델을 생성하고 해석을 실행한다.

    pyaedt import를 함수 내부에 두어, AEDT가 없는 환경에서 이 모듈을
    import하거나 py_compile 하는 것만으로는 실패하지 않도록 한다.
    """
    import os

    from ansys.aedt.core import Icepak, settings  # pyaedt Icepak 앱. Student도 공식 지원.

    # AEDT Student 2025 R2 이하는 기본 secure gRPC transport(wnua)로 기동이 실패한다
    # ("Failed to start on gRPC port" 반복 후 예외). insecure TCP 모드로 강제 전환 필요.
    # 반드시 Icepak()/Desktop() 생성 전에 설정해야 효과가 있다.
    # 근거: https://aedt.docs.pyansys.com/version/stable/Getting_started/Troubleshooting.html
    #       ("AEDT Student version fails to start via the default gRPC transport")
    os.environ["PYAEDT_USE_PRE_GRPC_ARGS"] = "True"
    settings.grpc_secure_mode = False

    # Student 버전은 콜드 스타트가 느려 기본 대기시간(120s) 안에 gRPC 서버가
    # 준비되지 못할 수 있다. batch.log상 서버는 요청 포트에 실제로 뜨는데
    # 클라이언트가 먼저 포기하는 패턴이 관찰됨 → 대기시간을 넉넉히 연장.
    settings.desktop_launch_timeout = 600

    stack_geometry = build_geometry_spec(footprint_mm=tuple(args.footprint_mm))
    material_spec = build_material_spec()
    power_spec = build_power_spec(
        total_w=args.total_power, base_die_fraction=args.base_die_fraction
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

        # 3) base_die/DRAM die에 source power 할당.
        for layer_name, power_w in power_spec.items():
            ipk.assign_source(
                assignment=layer_name,
                thermal_condition="Total Power",
                assignment_value=f"{power_w}W",
                boundary_name=f"source_{layer_name}",
            )

        # 4) 최상단 면(top_die 상부)에 히트싱크 근사 BC + 주변 온도.
        top_die = ipk.modeler[stack_geometry[-2]["name"]]  # top_die (EMC 이전 레이어)
        top_face = max(top_die.faces, key=lambda f: f.center[2])
        ipk.assign_conducting_plate(
            assignment=top_face.id,
            boundary_name="heatsink_approx",
            thermal_specification="Heat Transfer Coefficient",
            input_value=f"{_HEATSINK_HTC_W_M2K}W_per_m2_Kel",
        )
        ipk.edit_design_settings(ambient_temperature=_AMBIENT_TEMP_C)

        # 5) 메시 설정 (Student 512K 한계 대비 안전율 적용).
        global_mesh = ipk.mesh.global_mesh_region
        global_mesh.manual_settings = True
        global_mesh.settings["MeshRegionResolution"] = max(
            1, round(3 * args.mesh_fraction)
        )
        global_mesh.update()

        # 6) 해석 셋업 (steady 기본, --transient 지정 시 과도).
        setup = ipk.create_setup(MaxIterations=20)
        if args.transient:
            setup.props["Transient"] = True

        ipk.analyze()

        # 7) die별 평균/최대 온도 추출 -> CSV export.
        die_layer_names = [
            layer["name"]
            for layer in stack_geometry
            if layer["name"] == "base_die" or layer["name"].startswith(("dram_die", "top_die"))
        ]
        _export_die_temperatures(ipk, die_layer_names, args.output_csv)

    finally:
        ipk.release_desktop()


def _export_die_temperatures(ipk, die_layer_names: list[str], output_csv: str) -> None:
    """die별 평균/최대 온도를 post-processing에서 추출해 CSV로 저장한다."""
    rows = []
    for name in die_layer_names:
        avg_temp = ipk.post.get_scalar_field_value(
            quantity="Temperature", scalar_function="Mean", solution=name
        )
        max_temp = ipk.post.get_scalar_field_value(
            quantity="Temperature", scalar_function="Maximum", solution=name
        )
        rows.append({"die": name, "avg_temp_c": avg_temp, "max_temp_c": max_temp})

    with open(output_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["die", "avg_temp_c", "max_temp_c"])
        writer.writeheader()
        writer.writerows(rows)

    print(f"[결과] die별 온도 CSV 저장 완료: {output_csv}")


def main() -> None:
    args = _parse_args()
    build_icepak_model(args)


if __name__ == "__main__":
    main()
