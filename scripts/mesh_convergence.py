#!/usr/bin/env python3
"""HBM2E 8-Hi layer-cake Icepak 모델의 mesh convergence 스터디 실행 진입점.

⚠️ 이 스크립트는 Ansys Electronics Desktop(AEDT) + PyAEDT가 설치된
Windows 환경에서만 실제로 동작한다 (build_icepak_model.py와 동일한 제약).
WSL/Linux에서는 py_compile(문법 검사) + --dry-run(AEDT 연결 없이 config
출력만)까지만 가능하다.

흐름:
    0. Icepak 인스턴스를 **한 번만** 생성하고 지오메트리/재료/전력/BC/해석
       셋업도 한 번만 구성한다(scripts/build_icepak_model.py의
       build_geometry_materials_bcs()+create_conduction_setup()). 레벨마다
       새 인스턴스/새 프로젝트를 만들지 않는다 — Task 3 Windows 3차 크래시
       실측 확인: 레벨마다 새 프로젝트를 만드는 방식에서 두 번째 프로젝트의
       InsertDesign이 None을 반환하고 pyaedt의 active_design() 폴백 경로가
       AttributeError('NoneType' object has no attribute 'GetName')로 죽는
       내부 버그를 유발함(design.py:3538 -> desktop.py:1344). 인스턴스/
       프로젝트를 재사용해 이 경로 자체를 회피한다.
    1. 레벨(mesh resolution 1~5)마다 반복:
       - solve_at_mesh_resolution()으로 mesh resolution만 바꿔 재해석
       - 실제 mesh element 수 확인 -> 512K 초과 시 해당 레벨 skip 플래그
       - 최고 온도 확인 -> 500°C 초과 시 발산 플래그
       - die별 평균/최대 온도 + 해석 시간 기록
    2. 연속 유효 레벨 간 base_die max 온도 변화율로 수렴 판정
    3. results/mesh_convergence.csv 저장 + stdout 요약 테이블

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
    CSV_FIELDNAMES,
    ConvergenceLevelResult,
    build_csv_rows,
    build_error_result,
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
        "--project-name",
        type=str,
        default="hbm2e_8hi_meshconv",
        help="AEDT 프로젝트 이름 (전체 스위프가 이 프로젝트 하나를 재사용)",
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
    print(f"  project-name: {args.project_name}")
    print(f"  총 전력: {args.total_power} W (base_die_fraction={args.base_die_fraction})")
    print(f"  풋프린트: {tuple(args.footprint_mm)} mm")
    print(f"  레이어 수: {len(stack_geometry)}, 재료 수: {len(material_spec)}")
    print(f"  전력 배분 항목 수: {len(power_spec)}")
    print(f"  출력 CSV: {args.output_csv}")
    print("[dry-run] AEDT 연결/해석은 실행하지 않았습니다.")


def _get_mesh_element_count(ipk, setup_name: str) -> int:
    """해석 완료 후 실제 mesh element 수를 조회한다.

    ⚠️ Windows 첫 실행 크래시로 확인된 사실(2026-07-13): 이전 구현은
    `ipk.mesh.get_mesh_stats()`와 `ipk.odesign.GetProfile(...)`을 시도했는데,
    **둘 다 설치된 pyaedt(.venv/Lib/site-packages/ansys/aedt/core/)에 실존하지
    않는 API**였다(grep 0 matches). 특히 `GetProfile`은 `odesign`에 대한
    검증되지 않은 네이티브 메서드 직접 호출이라, 존재하지 않는 메서드를
    부르면 `InvokeAedtObjMethod`가 내부적으로 실패하면서 gRPC/필드계산기
    (oFieldsReporter) 상태를 오염시켰다 — 이 오염이 바로 다음에 실행되는
    `get_scalar_field_value`(CalculatorWrite 호출)의 GrpcApiError 크래시
    원인으로 실측 확인됨(bare `except Exception: pass`로 삼켜졌지만 상태
    오염은 막지 못함).

    실제로 존재하는 API로 교체: `Analysis3D.export_mesh_stats(setup, ...)`
    (`@pyaedt_function_handler()`로 감싸여 있어 내부 실패가 예외 대신 False/
    로그로 처리되는, 안전하게 검증된 wrapper — `odesign.ExportMeshStats`를
    호출). meshstats.ms 파일을 working_directory에 쓰고 그 안에서 element
    수를 파싱한다. 파일 포맷은 AEDT 버전에 따라 달라질 수 있어 파싱 실패는
    허용하되(-1 반환, 가드 스킵), **API 호출 자체는 실존 wrapper만 사용하므로
    gRPC 상태 오염 위험이 없다** — 이 함수가 실패해도 이후 후처리 호출은
    안전하다.

    Args:
        ipk: 해석 완료된 Icepak 인스턴스.
        setup_name: 방금 실행한 setup의 이름(ipk.create_setup() 반환값의 .name).
    """
    try:
        stats_path = ipk.export_mesh_stats(setup_name)
    except Exception as exc:
        print(f"[경고] export_mesh_stats 호출 실패({exc}) — 512K 가드를 건너뜁니다.")
        return -1

    try:
        text = Path(stats_path).read_text(encoding="utf-8", errors="ignore")
    except Exception as exc:
        print(f"[경고] mesh stats 파일 읽기 실패({exc}) — 512K 가드를 건너뜁니다.")
        return -1

    for line in text.splitlines():
        lowered = line.lower()
        if "element" in lowered or "cell" in lowered:
            digits = "".join(ch for ch in line if ch.isdigit())
            if digits:
                try:
                    return int(digits)
                except ValueError:
                    continue

    print(
        "[경고] mesh stats 파일에서 element 수 파싱 실패 — 512K 가드를 건너뜁니다. "
        f"AEDT GUI에서 Mesh > Statistics로 수동 확인 필요 (파일: {stats_path})."
    )
    return -1


def _run_level(ipk, level: int, args: argparse.Namespace, solve_at_mesh_resolution) -> ConvergenceLevelResult:
    """이미 구성된 Icepak 인스턴스에 대해 한 mesh resolution 레벨을 재해석하고 결과를 수집한다.

    Icepak 인스턴스/지오메트리/재료/BC/setup은 run_mesh_convergence()에서
    스위프 시작 전 한 번만 만들어지고, 이 함수는 mesh resolution 변경 +
    재해석 + 후처리만 담당한다(Task 3 Windows 3차 크래시 대응 — 레벨마다
    새 프로젝트를 만드는 방식이 pyaedt InsertDesign/active_design 내부
    버그를 유발했다, 모듈 docstring 참고).

    이 레벨 내부의 어떤 단계(재해석/후처리)가 실패해도 예외를 상위로
    전파하지 않는다 — 전체 스위프가 한 레벨의 문제로 죽지 않도록 error
    플래그가 세워진 결과를 대신 반환한다(Task 3 Windows 실행 크래시 대응,
    팀리드 필수 수정 사항).
    """
    try:
        return _run_level_body(ipk, level, args, solve_at_mesh_resolution)
    except Exception as exc:
        print(f"[레벨 {level}] [오류] 레벨 실행 중 예외 발생 — 스킵하고 다음 레벨 진행: {exc}")
        return build_error_result(level, str(exc))


def _run_level_body(ipk, level: int, args: argparse.Namespace, solve_at_mesh_resolution) -> ConvergenceLevelResult:
    """_run_level의 실제 재해석/후처리 본체. 예외 격리는 호출자(_run_level) 책임."""
    start_time = time.monotonic()
    analyze_ok = solve_at_mesh_resolution(ipk, level)
    solve_time_s = time.monotonic() - start_time

    # 해석 자체가 실패를 반환하면 후처리(get_scalar_field_value/CalculatorWrite)를
    # 절대 시도하지 않는다 — 실패한 해석 위에서 후처리 네이티브 호출을 하면
    # gRPC 오류로 죽는다(Task 3 Windows 실행 실측 크래시의 근본 원인).
    if not analyze_ok:
        print(f"[레벨 {level}] [오류] ipk.analyze()가 실패를 반환했습니다 — 후처리를 건너뜁니다.")
        return build_error_result(level, "ipk.analyze() returned False")

    setup_name = ipk.setups[0].name if ipk.setups else None
    n_elements = _get_mesh_element_count(ipk, setup_name) if setup_name else -1
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
        if r.error:
            flags.append("ERROR")
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

    from ansys.aedt.core import Icepak

    from build_icepak_model import (
        _apply_student_grpc_workarounds,
        build_geometry_materials_bcs,
        create_conduction_setup,
        solve_at_mesh_resolution,
    )

    _apply_student_grpc_workarounds()

    # Icepak 인스턴스와 지오메트리/재료/BC/setup은 스위프 전체에서 **한 번만**
    # 만든다 — 레벨마다 새 프로젝트를 만드는 방식이 pyaedt 내부 버그
    # (InsertDesign이 None 반환 -> active_design() 폴백에서 AttributeError)를
    # 유발한다는 것이 Task 3 Windows 3차 크래시로 실측 확인됐다(모듈
    # docstring 참고). 이 구성 단계 자체가 실패하면 레벨별 격리 대상이 아니라
    # 스위프 전체 실패로 간주하고 즉시 종료한다(팀리드 지시 — 인스턴스
    # 생성 실패와 레벨 내 실패는 구분).
    stack_geometry = build_geometry_spec(footprint_mm=tuple(args.footprint_mm))
    material_spec = build_material_spec()
    power_spec = build_power_spec(
        total_w=args.total_power, base_die_fraction=args.base_die_fraction
    )

    ipk = Icepak(
        project=args.project_name,
        non_graphical=args.non_graphical,
        new_desktop=True,
        close_on_exit=False,
        student_version=True,
    )

    # try 밖에서 미리 바인딩 — build_geometry_materials_bcs()/
    # create_conduction_setup()이 레벨 루프 진입 전에 실패해도 finally 이후
    # results가 정의되지 않은 상태로 참조되는 NameError를 방지한다.
    results: list[ConvergenceLevelResult] = []

    try:
        build_geometry_materials_bcs(ipk, stack_geometry, material_spec, power_spec)
        create_conduction_setup(ipk, args.transient)

        # 레벨 하나씩 실행 즉시 CSV에 반영 — 도중 크래시가 나도 완료된 레벨의
        # 결과가 보존된다(팀리드 필수 수정 사항). 수렴 판정(change_pct/converged)은
        # 직전 유효 레벨과의 비교가 필요해 레벨 실행 중에는 계산할 수 없으므로,
        # 매 레벨 직후에는 원시 결과로 CSV를 갱신하고, 전체 레벨 완료 후 마지막에
        # compute_convergence_flags()로 재계산한 최종 CSV를 한 번 더 덮어쓴다.
        for level in levels:
            result = _run_level(ipk, level, args, solve_at_mesh_resolution)
            results.append(result)
            _write_csv(results, args.output_csv)
            print(f"[레벨 {level}] 완료 — CSV 갱신됨 ({args.output_csv})")
    finally:
        try:
            ipk.release_desktop()
        except Exception as exc:
            print(f"[경고] release_desktop 실패(무시하고 진행): {exc}")

    if not results:
        print(
            "[오류] 인스턴스/지오메트리/setup 구성 단계에서 실패해 레벨 실행을 "
            "시작조차 못했습니다 — 위 로그의 예외 메시지를 확인할 것 (레벨별 "
            "격리 대상이 아닌 스위프 전체 실패)."
        )
        sys.exit(1)

    results = compute_convergence_flags(results)

    _print_summary_table(results)
    _write_csv(results, args.output_csv)


def main() -> None:
    args = _parse_args()
    run_mesh_convergence(args)


if __name__ == "__main__":
    main()
