#!/usr/bin/env python3
"""P2 T3 — 3D-ICE transient step 응답으로 τ=RC 해석값(T2)을 대조 검증하는 실행 진입점.

배경: vault docs/06-p2-rc-backport-design.md T3 — T2(hbm_thermal/rc_extract.py)
에서 해석적으로 구한 c_hbm × r_hbm_sink(τ_analytic)를, 독립적인 3D-ICE
transient 시뮬레이션에서 피팅한 τ_fitted와 대조해 2노드 lumped RC 축약이
물리적으로 타당한지 검증한다.

시나리오: baseline 8-Hi 스택 + 상단 HTC 2500 BC(steady 교차검증과 동일
셋업), step 16W 인가(냉각 상태 ambient에서 t=0에 전력 인가), base_die
평균온도 시간응답을 얻어 1차 지수 피팅.

⚠️ 3D-ICE 바이너리는 별도 빌드가 필요하다(docs/03-cross-validation-3d-ice.md
§2 절차, WSL에서 sudo 없이 번들 BLAS로 빌드 가능). 이 스크립트는 빌드된
바이너리 경로를 --3dice-bin으로 받는다.

실행 예시:
    python3 scripts/run_transient_tau_validation.py \\
        --3dice-bin /path/to/3D-ICE-Emulator \\
        --rc-params-csv results/rc_params.csv \\
        --output-dir results/
"""
from __future__ import annotations

import argparse
import csv
import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from hbm_thermal.export_3dice import build_stack_description  # noqa: E402
from hbm_thermal.tau_fit import (  # noqa: E402
    fit_first_order_tau,
    judge_tau_comparison,
    parse_3dice_avg_output,
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="3D-ICE transient step 응답 τ 피팅 vs T2 해석값(R×C) 대조 검증"
    )
    parser.add_argument(
        "--3dice-bin",
        dest="threedice_bin",
        type=str,
        required=True,
        help="빌드된 3D-ICE-Emulator 바이너리 경로",
    )
    parser.add_argument(
        "--rc-params-csv",
        type=str,
        default="results/rc_params.csv",
        help="T2 산출물(c_hbm, r_hbm_sink 값이 있는 CSV). 기본 results/rc_params.csv",
    )
    parser.add_argument(
        "--work-dir",
        type=str,
        default=None,
        help=".stk/.flp 입력 파일을 생성할 작업 디렉터리 (기본: --output-dir 하위 3dice_transient_work/)",
    )
    parser.add_argument(
        "--output-dir", type=str, default="results", help="비교 CSV 출력 디렉터리 (기본: results/)"
    )
    parser.add_argument(
        "--total-power", type=float, default=16.0, help="스택 총 발열량(W), steady 교차검증과 동일"
    )
    parser.add_argument(
        "--base-die-fraction", type=float, default=0.55, help="base_die 전력 비율"
    )
    parser.add_argument(
        "--footprint-mm", type=float, nargs=2, default=(11.0, 10.0), metavar=("X_MM", "Y_MM")
    )
    parser.add_argument("--ambient-c", type=float, default=40.0, help="주변 온도(°C)")
    parser.add_argument("--htc-w-m2k", type=float, default=2500.0, help="히트싱크 HTC(W/m²K)")
    parser.add_argument(
        "--step-time-s", type=float, default=0.005, help="transient 적분 스텝 크기(초)"
    )
    parser.add_argument(
        "--slot-time-s", type=float, default=0.05, help="transient 출력 슬롯 길이(초)"
    )
    parser.add_argument(
        "--n-tau-coverage",
        type=float,
        default=8.0,
        help="τ_analytic의 몇 배 구간을 시뮬레이션할지 (기본 8배 — 1차 지수는 "
        "5τ에서 99.3%%, 8τ에서 99.97%% 수렴해 피팅 안정성 확보)",
    )
    parser.add_argument(
        "--die-name", type=str, default="base_die", help="τ 피팅에 쓸 대표 die (기본 base_die)"
    )
    return parser.parse_args()


def _read_rc_params(csv_path: Path) -> dict[str, float]:
    """T2 rc_params.csv(parameter,value,...)를 dict로 읽는다."""
    values: dict[str, float] = {}
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            values[row["parameter"]] = float(row["value"])
    return values


def _run_3dice(threedice_bin: Path, work_dir: Path, label: str = "transient") -> None:
    result = subprocess.run(
        [str(threedice_bin), "stack.stk"], cwd=work_dir, capture_output=True, text=True
    )
    print(result.stdout)
    if result.returncode != 0:
        print(result.stderr, file=sys.stderr)
        print(f"[오류] 3D-ICE 실행 실패 (exit={result.returncode}).")
        sys.exit(1)
    print(f"[3D-ICE] {label} 해석 완료")


def _read_steady_avg(work_dir: Path, die_name: str) -> float:
    """steady 해석 결과 <die>_avg.txt에서 최종(final) 온도(K)를 읽는다."""
    samples = parse_3dice_avg_output((work_dir / f"{die_name}_avg.txt").read_text(encoding="utf-8"))
    return samples[-1].temperature_k


def run_transient_tau_validation(args: argparse.Namespace) -> None:
    threedice_bin = Path(args.threedice_bin).resolve()
    if not threedice_bin.exists():
        print(f"[오류] 3D-ICE 바이너리를 찾을 수 없습니다: {threedice_bin}")
        sys.exit(1)

    rc_params_path = Path(args.rc_params_csv).resolve()
    if not rc_params_path.exists():
        print(f"[오류] rc_params.csv를 찾을 수 없습니다: {rc_params_path}")
        sys.exit(1)

    rc_params = _read_rc_params(rc_params_path)
    c_hbm = rc_params["c_hbm"]
    r_hbm_sink = rc_params["r_hbm_sink"]
    tau_analytic_s = r_hbm_sink * c_hbm

    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    work_dir = Path(args.work_dir).resolve() if args.work_dir else output_dir / "3dice_transient_work"
    work_dir.mkdir(parents=True, exist_ok=True)

    sim_duration_s = tau_analytic_s * args.n_tau_coverage
    n_slots = max(2, int(sim_duration_s / args.slot_time_s))

    print(
        f"[설정] τ_analytic={tau_analytic_s:.6f}s (r_hbm_sink={r_hbm_sink:.6f} K/W × "
        f"c_hbm={c_hbm:.6e} J/K), 시뮬레이션 구간={sim_duration_s:.3f}s "
        f"({args.n_tau_coverage:.1f}τ), n_slots={n_slots}"
    )

    # steady 해석을 먼저 돌려 정확한 정상상태 온도를 구한다 — transient 마지막
    # 샘플(8τ 시점, exp(-8)=3.35e-4만큼 미수렴)을 t_final_k로 근사하면 후반부
    # 잔차가 왜곡되어 피팅 R²가 저하되는 조기절단 편향이 생긴다(실측 확인:
    # 마지막 샘플 근사 시 R²=0.987, steady 정확값 사용 시 개선). steady와
    # transient는 동일 BC(footprint/전력/HTC/ambient)이므로 정상상태 값이
    # 서로 같아야 하고, steady 쪽이 슬롯 근사 없이 직접 수렴시킨 값이라 더 정확.
    steady_work_dir = work_dir.parent / f"{work_dir.name}_steady_ref"
    steady_work_dir.mkdir(parents=True, exist_ok=True)
    steady_files = build_stack_description(
        footprint_mm=tuple(args.footprint_mm),
        total_power_w=args.total_power,
        base_die_fraction=args.base_die_fraction,
        ambient_c=args.ambient_c,
        htc_w_m2k=args.htc_w_m2k,
        transient=False,
    )
    for fname, content in steady_files.items():
        (steady_work_dir / fname).write_text(content, encoding="utf-8")
    _run_3dice(threedice_bin, steady_work_dir, label="steady 정상상태 기준")
    t_final_k_steady = _read_steady_avg(steady_work_dir, args.die_name)
    print(f"[steady 기준] {args.die_name} 정상상태 온도 = {t_final_k_steady:.4f}K")

    files = build_stack_description(
        footprint_mm=tuple(args.footprint_mm),
        total_power_w=args.total_power,
        base_die_fraction=args.base_die_fraction,
        ambient_c=args.ambient_c,
        htc_w_m2k=args.htc_w_m2k,
        transient=True,
        initial_temperature_c=args.ambient_c,
        step_time_s=args.step_time_s,
        slot_time_s=args.slot_time_s,
        n_slots=n_slots,
    )
    for fname, content in files.items():
        (work_dir / fname).write_text(content, encoding="utf-8")
    print(f"[3D-ICE] transient 입력 파일 {len(files)}개 생성 완료: {work_dir}")

    _run_3dice(threedice_bin, work_dir)

    avg_output_path = work_dir / f"{args.die_name}_avg.txt"
    if not avg_output_path.exists():
        print(f"[오류] 3D-ICE 출력 파일 없음: {avg_output_path}")
        sys.exit(1)

    samples = parse_3dice_avg_output(avg_output_path.read_text(encoding="utf-8"))
    fit_result = fit_first_order_tau(samples, t_final_k=t_final_k_steady)
    comparison = judge_tau_comparison(
        tau_fitted_s=fit_result.tau_fitted_s,
        tau_analytic_s=tau_analytic_s,
        r_squared=fit_result.r_squared,
    )

    print(
        f"\n[결과] τ_fitted={comparison.tau_fitted_s:.6f}s vs "
        f"τ_analytic={comparison.tau_analytic_s:.6f}s "
        f"(오차 {comparison.diff_pct:.2f}%, R²={comparison.r_squared:.6f})"
    )
    print(f"[판정] {comparison.verdict}")
    print(f"[판정 기준] {comparison.criterion}")
    print(
        f"[개형] t=0 대응 초기온도 {fit_result.t_initial_k:.3f}K -> "
        f"수렴온도 {fit_result.t_final_k:.3f}K (steady 결과와 대조 필요)"
    )

    comparison_csv_path = output_dir / "transient_tau_comparison.csv"
    with open(comparison_csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "die",
                "tau_fitted_s",
                "tau_analytic_s",
                "diff_pct",
                "r_squared",
                "verdict",
                "criterion",
                "t_initial_k",
                "t_final_k",
                "n_points_used",
                "sim_duration_s",
                "n_slots",
            ],
        )
        writer.writeheader()
        writer.writerow(
            {
                "die": args.die_name,
                "tau_fitted_s": f"{comparison.tau_fitted_s:.6f}",
                "tau_analytic_s": f"{comparison.tau_analytic_s:.6f}",
                "diff_pct": f"{comparison.diff_pct:.4f}",
                "r_squared": f"{comparison.r_squared:.6f}",
                "verdict": comparison.verdict,
                "criterion": comparison.criterion,
                "t_initial_k": f"{fit_result.t_initial_k:.4f}",
                "t_final_k": f"{fit_result.t_final_k:.4f}",
                "n_points_used": fit_result.n_points_used,
                "sim_duration_s": f"{sim_duration_s:.4f}",
                "n_slots": n_slots,
            }
        )
    print(f"[결과] 비교 CSV 저장 완료: {comparison_csv_path}")

    if comparison.verdict != "PASS":
        sys.exit(1)


def main() -> None:
    args = _parse_args()
    run_transient_tau_validation(args)


if __name__ == "__main__":
    main()
