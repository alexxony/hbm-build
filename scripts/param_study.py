#!/usr/bin/env python3
"""HBM2E layer-cake Icepak 모델의 파라미터 스터디 실행 진입점 (Task 5).

⚠️ 이 스크립트는 Ansys Electronics Desktop(AEDT) + PyAEDT가 설치된
Windows 환경에서만 실제로 동작한다 (build_icepak_model.py/mesh_convergence.py와
동일한 제약). WSL/Linux에서는 py_compile(문법 검사) + --dry-run(AEDT 연결 없이
케이스 목록/설정 출력만)까지만 가능하다.

목적: 문헌 선례 3종(PROGRESS.md §파라미터 스터디 추천 조합) 재현.
    #1 스택 높이 4/8/12-Hi — MDPI: 12단↑ 열저항 급상승
    #2 본딩 방식 μ-bump 4.2 vs hybrid 1.2 mm²·K/W — AIP JAP 실측치 방향 재현
    #5 냉각 BC top-only vs top+bottom — imec: 17°C 저감 방향 재현

구조 (Task 3 mesh_convergence.py 검증 패턴 적용, 단 케이스 간 지오메트리가
바뀐다는 차이 반영):
    - mesh_convergence.py는 레벨(mesh resolution)만 바뀌므로 Icepak 인스턴스
      하나를 스위프 전체에서 재사용했다. Task 5는 케이스마다 스택 높이가
      바뀌어 **지오메트리 자체가 다르다**(레이어 수/두께/재료 배치 전부
      변경) — 같은 인스턴스에 같은 이름의 box/재료/BC를 다시 만들 수 없다.
    - 그렇다고 한 AEDT 프로세스 안에서 두 번째 프로젝트를 만들면 Task 3
      Windows 3차 크래시의 근본 원인(pyaedt InsertDesign이 두 번째 project에서
      None을 반환 -> active_design() 폴백이 AttributeError로 죽는 내부 버그,
      design.py:3538 -> desktop.py:1344)을 다시 밟는다.
    - 따라서 케이스마다 **완전히 새로운 Icepak 인스턴스(new_desktop=True)를
      생성하고, 그 인스턴스에서 정확히 하나의 프로젝트만 다룬 뒤 즉시
      release_desktop()한다.** 이는 Task 2/Task 3 1차 성공 경로("인스턴스당
      정확히 1 프로젝트")와 동일한 패턴이며, 크래시를 유발했던 "한 인스턴스
      안에서 여러 프로젝트를 연속 생성"하는 경로 자체를 타지 않는다.
      AEDT 프로세스가 케이스 수만큼 뜨고 닫히는 콜드스타트 비용을 감수하는
      대신, 검증된 안전한 경로만 사용한다.

흐름 (케이스마다):
    1. ParamCase -> layer_stack_hbm2e(n_dram_dies, bump_thermal_resistance_mm2k_w)
       -> build_geometry_spec/build_material_spec/build_power_spec(stack=...)
    2. 새 Icepak(new_desktop=True) 인스턴스 생성
    3. build_geometry_materials_bcs(..., bottom_htc_w_m2k=case.bottom_htc_w_m2k)
       + create_conduction_setup() + solve_at_mesh_resolution()
    4. 512K 예산/500°C 발산 가드 -> die별 온도 추출
    5. release_desktop() -> 다음 케이스로
    6. 전 케이스 완료 후 문헌 방향(judge_literature_direction) 대조표 출력

실행 예시 (Windows, AEDT 설치 후):
    python scripts\\param_study.py
    python scripts\\param_study.py --cases baseline_8hi,stack_height_12hi
    python scripts\\param_study.py --dry-run
"""
from __future__ import annotations

import argparse
import csv
import sys
import time
import traceback
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))
sys.path.insert(0, str(_REPO_ROOT / "scripts"))

from hbm_thermal.convergence import check_divergence, check_mesh_budget  # noqa: E402
from hbm_thermal.homogenize import layer_stack_hbm2e  # noqa: E402
from hbm_thermal.model_config import (  # noqa: E402
    build_geometry_spec,
    build_material_spec,
    build_power_spec,
    total_stack_height_mm,
)
from hbm_thermal.param_study import (  # noqa: E402
    CSV_FIELDNAMES,
    ParamCase,
    ParamCaseResult,
    build_case_result,
    build_csv_rows,
    build_error_result,
    default_cases,
    judge_literature_direction,
)

_DEFAULT_OUTPUT_CSV = "results/param_study.csv"

# 문헌 대조 축과 baseline/comparison 케이스명 매핑 (요약표 출력용).
_LITERATURE_COMPARISONS = [
    ("stack_height", "baseline_8hi", "stack_height_12hi", "MDPI: 12단↑ 열저항 급상승"),
    ("bonding", "bonding_ubump", "bonding_hybrid", "AIP JAP: hybrid bonding이 더 낮은 온도"),
    ("cooling_bc", "baseline_8hi", "cooling_top_bottom", "imec: backside 냉각 추가 시 17°C 저감"),
]


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="HBM2E layer-cake Icepak 모델 파라미터 스터디 "
        "(스택 높이/본딩 방식/냉각 BC, PyAEDT, Windows+AEDT 필요)"
    )
    parser.add_argument(
        "--cases",
        type=str,
        default=None,
        help="실행할 케이스명, 콤마 구분 (예: baseline_8hi,stack_height_12hi). "
        "기본값: default_cases() 전체",
    )
    parser.add_argument(
        "--project-name-prefix",
        type=str,
        default="hbm2e_paramstudy",
        help="AEDT 프로젝트 이름 접두어 (케이스마다 새 인스턴스+새 프로젝트를 만들므로 "
        "케이스명을 접미어로 붙인다)",
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
        "--base-die-fraction",
        type=float,
        default=0.55,
        help="base_die가 차지하는 전력 비율 [0,1], 기본 0.55",
    )
    parser.add_argument(
        "--mesh-region-resolution",
        type=int,
        default=2,
        help="global mesh region resolution (Task 3 수렴 확인된 기준선), 기본 2",
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
        help="AEDT 연결 없이 케이스 목록/설정만 출력하고 종료",
    )
    return parser.parse_args()


def _select_cases(cases_arg: str | None) -> list[ParamCase]:
    all_cases = default_cases()
    if cases_arg is None:
        return all_cases

    requested = [name.strip() for name in cases_arg.split(",") if name.strip()]
    by_name = {c.name: c for c in all_cases}
    unknown = [name for name in requested if name not in by_name]
    if unknown:
        raise ValueError(
            f"알 수 없는 케이스명: {unknown} (사용 가능: {list(by_name)})"
        )
    return [by_name[name] for name in requested]


def _run_dry_run(cases: list[ParamCase], args: argparse.Namespace) -> None:
    """AEDT 연결 없이 케이스 설정을 출력한다 (WSL 등 AEDT 없는 환경에서 검증용)."""
    print("[dry-run] 파라미터 스터디 케이스 설정")
    for case in cases:
        stack = layer_stack_hbm2e(
            n_dram_dies=case.n_dram_dies,
            bump_thermal_resistance_mm2k_w=case.bump_thermal_resistance_mm2k_w,
        )
        geometry = build_geometry_spec(stack, footprint_mm=tuple(args.footprint_mm))
        height_mm = total_stack_height_mm(geometry)
        power_spec = build_power_spec(
            stack=stack, total_w=case.total_power_w, base_die_fraction=args.base_die_fraction
        )
        print(
            f"  {case.name}: n_dram_dies={case.n_dram_dies} "
            f"레이어수={len(stack)} 스택높이={height_mm:.4f}mm "
            f"총전력={case.total_power_w}W(항목수={len(power_spec)}) "
            f"본딩R={case.bump_thermal_resistance_mm2k_w} "
            f"bottom_htc={case.bottom_htc_w_m2k}"
        )
    print(f"  출력 CSV: {args.output_csv}")
    print("[dry-run] AEDT 연결/해석은 실행하지 않았습니다.")


def _run_case(case: ParamCase, args: argparse.Namespace) -> ParamCaseResult:
    """케이스 하나를 완전히 새로운 Icepak 인스턴스로 처리한다.

    인스턴스 생성부터 release_desktop()까지 이 함수 안에서 전부 끝난다 —
    "인스턴스당 정확히 1 프로젝트" 원칙(모듈 docstring 참고)을 지키기 위해
    다음 케이스는 반드시 새 함수 호출(=새 인스턴스)로 시작한다.

    이 함수 내부의 어떤 단계가 실패해도 예외를 상위로 전파하지 않는다 —
    스위프 전체가 한 케이스의 문제로 죽지 않도록 error 플래그가 세워진
    결과를 대신 반환한다(Task 3에서 검증된 레벨별 예외 격리 패턴과 동일).
    """
    ipk = None
    try:
        from ansys.aedt.core import Icepak

        from build_icepak_model import (
            _apply_student_grpc_workarounds,
            build_geometry_materials_bcs,
            create_conduction_setup,
            solve_at_mesh_resolution,
        )

        _apply_student_grpc_workarounds()

        stack = layer_stack_hbm2e(
            n_dram_dies=case.n_dram_dies,
            bump_thermal_resistance_mm2k_w=case.bump_thermal_resistance_mm2k_w,
        )
        stack_geometry = build_geometry_spec(stack, footprint_mm=tuple(args.footprint_mm))
        material_spec = build_material_spec(stack)
        power_spec = build_power_spec(
            stack=stack, total_w=case.total_power_w, base_die_fraction=args.base_die_fraction
        )

        project_name = f"{args.project_name_prefix}_{case.name}"
        ipk = Icepak(
            project=project_name,
            non_graphical=args.non_graphical,
            new_desktop=True,
            close_on_exit=False,
            student_version=True,
        )

        build_geometry_materials_bcs(
            ipk,
            stack_geometry,
            material_spec,
            power_spec,
            bottom_htc_w_m2k=case.bottom_htc_w_m2k,
        )
        create_conduction_setup(ipk, args.transient)

        start_time = time.monotonic()
        analyze_ok = solve_at_mesh_resolution(ipk, args.mesh_region_resolution)
        solve_time_s = time.monotonic() - start_time

        if not analyze_ok:
            print(f"[케이스 {case.name}] [오류] ipk.analyze()가 실패를 반환했습니다.")
            return build_error_result(case, "ipk.analyze() returned False")

        # mesh element 수 가드 (mesh_convergence.py와 동일한 검증된 API 경로).
        setup_name = ipk.setups[0].name if ipk.setups else None
        n_elements = -1
        if setup_name:
            try:
                stats_path = ipk.export_mesh_stats(setup_name)
                text = Path(stats_path).read_text(encoding="utf-8", errors="ignore")
                for line in text.splitlines():
                    lowered = line.lower()
                    if "element" in lowered or "cell" in lowered:
                        digits = "".join(ch for ch in line if ch.isdigit())
                        if digits:
                            n_elements = int(digits)
                            break
            except Exception as exc:
                print(f"[케이스 {case.name}] [경고] mesh element 수 확인 실패({exc}) — 가드 스킵.")

        if n_elements >= 0 and check_mesh_budget(n_elements):
            print(
                f"[케이스 {case.name}] element 수 {n_elements:,} > 512K 예산 초과 — "
                "결과를 error로 기록합니다 (Student 라이선스가 거부했을 가능성)."
            )
            return build_error_result(case, f"mesh element 수 초과 ({n_elements:,} > 512,000)")

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

        if check_divergence(base_max):
            print(
                f"[케이스 {case.name}] [경고] base_die max {base_max:.1f}°C — 발산 의심."
            )
            return build_error_result(case, f"발산 의심 (base_die max={base_max:.1f}°C)")

        stack_height_mm = total_stack_height_mm(stack_geometry)
        return build_case_result(
            case=case,
            base_die_avg_c=base_avg,
            base_die_max_c=base_max,
            top_die_avg_c=top_avg,
            top_die_max_c=top_max,
            stack_height_mm=stack_height_mm,
            solve_time_s=solve_time_s,
        )

    except Exception as exc:
        # str(exc)만 남기면 발생 파일:라인을 알 수 없어 원인 특정이 불가능하다
        # (Task 5 실측: stack_height_4hi가 "argument should be a str or an
        # os.PathLike object ... not 'NoneType'" 한 줄만 남기고 실패, 어느
        # 호출에서 났는지 코드 정적 추적만으로는 확정 불가했음). CSV의 error
        # 필드에 전체 traceback을 실어 다음 실행에서 정확한 지점을 특정한다.
        tb = traceback.format_exc()
        print(f"[케이스 {case.name}] [오류] 케이스 실행 중 예외 발생:\n{tb}")
        return build_error_result(case, f"{exc}\n{tb}")

    finally:
        if ipk is not None:
            try:
                ipk.release_desktop()
            except Exception as exc:
                print(f"[케이스 {case.name}] [경고] release_desktop 실패(무시하고 진행): {exc}")


def _write_csv(results: list[ParamCaseResult], output_csv: str) -> None:
    output_path = Path(output_csv)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    rows = build_csv_rows(results)
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)

    print(f"[결과] 파라미터 스터디 CSV 저장 완료: {output_path}")


def _print_literature_comparison_table(results: list[ParamCaseResult]) -> None:
    by_name = {r.name: r for r in results}
    header = f"{'축':>14} {'baseline':>18} {'comparison':>20} {'판정':>15}  근거"
    print(header)
    print("-" * len(header))
    for axis, baseline_name, comparison_name, note in _LITERATURE_COMPARISONS:
        baseline = by_name.get(baseline_name)
        comparison = by_name.get(comparison_name)
        if baseline is None or comparison is None:
            print(f"{axis:>14} {'(미실행)':>18} {'(미실행)':>20} {'SKIPPED':>15}  {note}")
            continue
        verdict = judge_literature_direction(
            axis=axis,
            baseline_value=baseline.base_die_max_c,
            comparison_value=comparison.base_die_max_c,
        )
        print(f"{axis:>14} {baseline_name:>18} {comparison_name:>20} {verdict:>15}  {note}")


def run_param_study(args: argparse.Namespace) -> None:
    try:
        cases = _select_cases(args.cases)
    except ValueError as exc:
        print(f"[오류] --cases 파싱 실패: {exc}")
        sys.exit(1)

    if args.dry_run:
        _run_dry_run(cases, args)
        return

    results: list[ParamCaseResult] = []
    for case in cases:
        result = _run_case(case, args)
        results.append(result)
        _write_csv(results, args.output_csv)
        print(f"[케이스 {case.name}] 완료 — CSV 갱신됨 ({args.output_csv})")

    if not results:
        print("[오류] 실행된 케이스가 없습니다.")
        sys.exit(1)

    _write_csv(results, args.output_csv)
    print()
    _print_literature_comparison_table(results)


def main() -> None:
    args = _parse_args()
    run_param_study(args)


if __name__ == "__main__":
    main()
