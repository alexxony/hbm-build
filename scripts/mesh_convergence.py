#!/usr/bin/env python3
"""HBM2E 8-Hi layer-cake Icepak 모델의 mesh convergence 스터디 실행 진입점.

⚠️ 이 스크립트는 Ansys Electronics Desktop(AEDT) + PyAEDT가 설치된
Windows 환경에서만 실제로 동작한다 (build_icepak_model.py와 동일한 제약).
WSL/Linux에서는 py_compile(문법 검사) + --dry-run(AEDT 연결 없이 config
출력만)까지만 가능하다.

흐름 (레벨마다 반복):
    1. mesh resolution 레벨(1~5)별로 새 Icepak 프로젝트 생성
    2. scripts/build_icepak_model.py 의 build_and_solve()로 지오메트리/재료/
       전력/BC/메시/해석을 동일 로직으로 실행 (중복 구현 없음)
    3. 실제 mesh element 수 확인 -> 512K 초과 시 해당 레벨 skip 플래그
    4. 최고 온도 확인 -> 500°C 초과 시 발산 플래그
    5. die별 평균/최대 온도 + 해석 시간 기록
    6. 연속 유효 레벨 간 base_die max 온도 변화율로 수렴 판정
    7. results/mesh_convergence.csv 저장 + stdout 요약 테이블

실행 예시 (Windows, AEDT 설치 후):
    python scripts\\mesh_convergence.py --levels 1,2,3
    python scripts\\mesh_convergence.py --dry-run
"""
from __future__ import annotations

import argparse
import csv
import sys
import time
from pathlib import Path

# hbm_thermal 패키지 및 scripts 패키지를 스크립트 위치 기준으로 import 가능하게 경로 추가.
_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))
sys.path.insert(0, str(_REPO_ROOT / "scripts"))

from hbm_thermal.convergence import (  # noqa: E402
    ConvergenceLevelResult,
    build_csv_rows,
    check_divergence,
    check_mesh_budget,
    compute_convergence_flags,
    parse_levels,
)
from hbm_thermal.model_config import (  # noqa: E402
    build_geometry_spec,
    build_material_spec,
    build_power_spec,
)

_DEFAULT_OUTPUT_CSV = "results/mesh_convergence.csv"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="HBM2E 8-Hi layer-cake Icepak 모델 mesh convergence 스터디 "
        "(PyAEDT, Windows+AEDT 필요)"
    )
    parser.add_argument(
        "--levels",
        type=str,
        default=None,
        help="스윕할 mesh resolution 레벨, 콤마 구분 (예: 1,2,3). 기본값: 1~5 전체",
    )
    parser.add_argument(
        "--project-name-prefix",
        type=str,
        default="hbm2e_8hi_meshconv",
        help="레벨별 AEDT 프로젝트 이름 접두어 (레벨 번호가 접미어로 붙음)",
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
    parser.add_argument(
        "--transient", action="store_true", help="과도(transient) 해석으로 실행"
    )
    parser.add_argument(
        "--non-graphical",
        action="store_true",
        help="AEDT를 GUI 없이 백그라운드로 실행",
    )
    parser.add_argument(
        "--output-csv",
        type=str,
        default=_DEFAULT_OUTPUT_CSV,
        help=f"결과 CSV 출력 경로, 기본 {_DEFAULT_OUTPUT_CSV}",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="AEDT 연결 없이 스윕할 레벨/설정만 출력하고 종료",
    )
    return parser.parse_args()


def _run_dry_run(levels: list[int], args: argparse.Namespace) -> None:
    """AEDT 연결 없이 스윕 설정을 출력한다 (WSL 등 AEDT 없는 환경에서 검증용)."""
    stack_geometry = build_geometry_spec(footprint_mm=tuple(args.footprint_mm))
    material_spec = build_material_spec()
    power_spec = build_power_spec(
        total_w=args.total_power, base_die_fraction=args.base_die_fraction
    )

    print("[dry-run] mesh convergence 스윕 설정")
    print(f"  levels: {levels}")
    print(f"  project-name-prefix: {args.project_name_prefix}")
    print(f"  총 전력: {args.total_power} W (base_die_fraction={args.base_die_fraction})")
    print(f"  풋프린트: {tuple(args.footprint_mm)} mm")
    print(f"  레이어 수: {len(stack_geometry)}, 재료 수: {len(material_spec)}")
    print(f"  전력 배분 항목 수: {len(power_spec)}")
    print(f"  출력 CSV: {args.output_csv}")
    print("[dry-run] AEDT 연결/해석은 실행하지 않았습니다.")


def _get_mesh_element_count(ipk) -> int:
    """해석 완료 후 실제 mesh element 수를 조회한다.

    ⚠️ Windows 첫 실행에서 검증 필요: pyaedt 1.1.0 공식 문서에 mesh convergence
    스터디용 element-count API가 명시적으로 문서화되어 있지 않아, 아래 경로를
    우선순위대로 시도한다. 전부 실패하면 -1을 반환하고 512K 가드는 건너뛴다
    (경고 로그 출력). 검증 후 이 함수는 실측 성공 경로만 남기고 단순화할 것.
    """
    # 경로 1: global mesh region 통계 (pyaedt 문서 mesh.rst 기준 존재 확인된 객체).
    try:
        stats = ipk.mesh.get_mesh_stats()
        if stats:
            return int(stats[0].get("Num Elements", stats[0].get("NumElements")))
    except Exception:
        pass

    # 경로 2: 해석 프로파일 텍스트에서 element 수 파싱.
    try:
        profile = ipk.odesign.GetProfile(ipk.solution_setups[0].name)
        for line in str(profile).splitlines():
            if "element" in line.lower() and any(ch.isdigit() for ch in line):
                digits = "".join(ch for ch in line if ch.isdigit())
                if digits:
                    return int(digits)
    except Exception:
        pass

    print(
        "[경고] mesh element 수 조회 실패 — 512K 가드를 건너뜁니다. "
        "AEDT GUI에서 Mesh > Statistics로 수동 확인 필요."
    )
    return -1


def _run_level(level: int, args: argparse.Namespace) -> ConvergenceLevelResult:
    """한 mesh resolution 레벨에 대해 모델 빌드+해석을 실행하고 결과를 수집한다."""
    from ansys.aedt.core import Icepak

    from build_icepak_model import _apply_student_grpc_workarounds, build_and_solve

    _apply_student_grpc_workarounds()

    stack_geometry = build_geometry_spec(footprint_mm=tuple(args.footprint_mm))
    material_spec = build_material_spec()
    power_spec = build_power_spec(
        total_w=args.total_power, base_die_fraction=args.base_die_fraction
    )
    die_layer_names = [
        layer["name"]
        for layer in stack_geometry
        if layer["name"] == "base_die" or layer["name"].startswith(("dram_die", "top_die"))
    ]

    ipk = Icepak(
        project=f"{args.project_name_prefix}_L{level}",
        non_graphical=args.non_graphical,
        new_desktop=True,
        close_on_exit=False,
        student_version=True,
    )

    try:
        start_time = time.monotonic()
        build_and_solve(
            ipk,
            stack_geometry=stack_geometry,
            material_spec=material_spec,
            power_spec=power_spec,
            mesh_region_resolution=level,
            transient=args.transient,
        )
        solve_time_s = time.monotonic() - start_time

        n_elements = _get_mesh_element_count(ipk)
        skipped = n_elements >= 0 and check_mesh_budget(n_elements)

        if skipped:
            print(
                f"[레벨 {level}] element 수 {n_elements:,} > 512K 예산 초과 — "
                "결과를 skip으로 기록합니다 (Student 라이선스가 거부했을 가능성)."
            )
            return ConvergenceLevelResult(
                level=level,
                n_elements=n_elements,
                base_die_avg_c=None,
                base_die_max_c=None,
                top_die_avg_c=None,
                top_die_max_c=None,
                solve_time_s=solve_time_s,
                skipped_over_budget=True,
                diverged=False,
                converged=False,
                change_pct=None,
            )

        base_avg = ipk.post.get_scalar_field_value(
            quantity="Temp", scalar_function="Mean", object_name="base_die"
        )
        base_max = ipk.post.get_scalar_field_value(
            quantity="Temp", scalar_function="Maximum", object_name="base_die"
        )
        top_avg = ipk.post.get_scalar_field_value(
            quantity="Temp", scalar_function="Mean", object_name="top_die"
        )
        top_max = ipk.post.get_scalar_field_value(
            quantity="Temp", scalar_function="Maximum", object_name="top_die"
        )

        diverged = check_divergence(base_max)
        if diverged:
            print(
                f"[레벨 {level}] [경고] base_die max {base_max:.1f}°C — 발산 의심. "
                "docs/run-on-windows.md §5.0.1 런북 참고."
            )

        return ConvergenceLevelResult(
            level=level,
            n_elements=n_elements if n_elements >= 0 else None,
            base_die_avg_c=base_avg,
            base_die_max_c=base_max,
            top_die_avg_c=top_avg,
            top_die_max_c=top_max,
            solve_time_s=solve_time_s,
            skipped_over_budget=False,
            diverged=diverged,
            converged=False,
            change_pct=None,
        )
    finally:
        ipk.release_desktop()


def _print_summary_table(results: list[ConvergenceLevelResult]) -> None:
    header = (
        f"{'level':>5} {'elements':>10} {'base_avg':>9} {'base_max':>9} "
        f"{'top_avg':>9} {'top_max':>9} {'time_s':>8} {'change%':>8} {'flags':>20}"
    )
    print(header)
    print("-" * len(header))
    for r in results:
        flags = []
        if r.skipped_over_budget:
            flags.append("SKIP(>512K)")
        if r.diverged:
            flags.append("DIVERGED")
        if r.converged:
            flags.append("CONVERGED")
        flags_str = ",".join(flags) if flags else "-"

        def _fmt(v, spec=".1f"):
            return format(v, spec) if v is not None else "-"

        print(
            f"{r.level:>5} {_fmt(r.n_elements, ',') if r.n_elements else '-':>10} "
            f"{_fmt(r.base_die_avg_c):>9} {_fmt(r.base_die_max_c):>9} "
            f"{_fmt(r.top_die_avg_c):>9} {_fmt(r.top_die_max_c):>9} "
            f"{_fmt(r.solve_time_s):>8} {_fmt(r.change_pct):>8} {flags_str:>20}"
        )


def _write_csv(results: list[ConvergenceLevelResult], output_csv: str) -> None:
    from hbm_thermal.convergence import CSV_FIELDNAMES

    output_path = Path(output_csv)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    rows = build_csv_rows(results)
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)

    print(f"[결과] mesh convergence CSV 저장 완료: {output_path}")


def run_mesh_convergence(args: argparse.Namespace) -> None:
    try:
        levels = parse_levels(args.levels)
    except ValueError as exc:
        print(f"[오류] --levels 파싱 실패: {exc}")
        sys.exit(1)

    if args.dry_run:
        _run_dry_run(levels, args)
        return

    results = [_run_level(level, args) for level in levels]
    results = compute_convergence_flags(results)

    _print_summary_table(results)
    _write_csv(results, args.output_csv)


def main() -> None:
    args = _parse_args()
    run_mesh_convergence(args)


if __name__ == "__main__":
    main()
