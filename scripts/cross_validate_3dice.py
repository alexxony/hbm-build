#!/usr/bin/env python3
"""HBM2E 8-Hi 스택 Icepak 결과를 3D-ICE(EPFL 오픈소스 컴팩트 열해석 툴)로
교차검증하는 실행 진입점.

배경: vault research/04-validation-anchors.md §3 — "실측/타 툴 대비 평균
오차 <10%"가 3D-ICE 공인 합격선. 이 스크립트는 (1) hbm_thermal/export_3dice.py로
Icepak과 동일 경계조건의 3D-ICE 입력(.stk/.flp)을 생성하고, (2) 3D-ICE
바이너리(3D-ICE-Emulator)를 실행해 die별 온도를 얻고, (3) 기존 Icepak 결과
CSV와 비교해 PASS/FAIL을 판정한다.

⚠️ 3D-ICE 바이너리는 별도 빌드가 필요하다 (WSL에서 sudo 없이 빌드 가능,
docs/run-on-windows.md 또는 프로젝트 문서의 3D-ICE 빌드 절차 참고 — SuperLU_MT를
자체 번들 C BLAS로 빌드하면 gfortran/OpenBLAS 없이 gcc만으로 빌드된다).
이 스크립트는 빌드된 바이너리 경로를 --3dice-bin으로 받는다.

실행 예시:
    python3 scripts/cross_validate_3dice.py \\
        --3dice-bin /path/to/3D-ICE-Emulator \\
        --icepak-csv /path/to/hbm2e_die_temperatures.csv \\
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

from hbm_thermal.comparison import (  # noqa: E402
    COMPARISON_CSV_FIELDNAMES,
    build_comparison_csv_rows,
    compare_die_temperatures,
    judge_pass_fail,
)
from hbm_thermal.export_3dice import build_stack_description  # noqa: E402
from hbm_thermal.model_config import build_geometry_spec  # noqa: E402


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Icepak vs 3D-ICE 교차검증 (die별 온도 비교, PASS/FAIL 판정)"
    )
    parser.add_argument(
        "--3dice-bin",
        dest="threedice_bin",
        type=str,
        required=True,
        help="빌드된 3D-ICE-Emulator 바이너리 경로",
    )
    parser.add_argument(
        "--icepak-csv",
        type=str,
        required=True,
        help="기존 Icepak 결과 CSV 경로 (die,avg_temp_c,max_temp_c 컬럼)",
    )
    parser.add_argument(
        "--work-dir",
        type=str,
        default=None,
        help=".stk/.flp 입력 파일을 생성할 작업 디렉터리 (기본: --output-dir 하위 3dice_work/)",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="results",
        help="비교 CSV 출력 디렉터리 (기본: results/)",
    )
    parser.add_argument(
        "--total-power", type=float, default=16.0, help="스택 총 발열량 (W), Icepak과 동일해야 함"
    )
    parser.add_argument(
        "--base-die-fraction",
        type=float,
        default=0.55,
        help="base_die 전력 비율, Icepak과 동일해야 함",
    )
    parser.add_argument(
        "--footprint-mm",
        type=float,
        nargs=2,
        default=(11.0, 10.0),
        metavar=("X_MM", "Y_MM"),
        help="다이 풋프린트 (mm), Icepak과 동일해야 함",
    )
    parser.add_argument(
        "--ambient-c", type=float, default=40.0, help="주변 온도 (°C), Icepak과 동일해야 함"
    )
    parser.add_argument(
        "--htc-w-m2k", type=float, default=2500.0, help="히트싱크 HTC (W/m²K), Icepak과 동일해야 함"
    )
    return parser.parse_args()


def _read_icepak_csv(csv_path: Path) -> dict[str, tuple[float, float]]:
    """Icepak 결과 CSV(die,avg_temp_c,max_temp_c)를 dict로 읽는다."""
    results: dict[str, tuple[float, float]] = {}
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            results[row["die"]] = (float(row["avg_temp_c"]), float(row["max_temp_c"]))
    return results


def _write_3dice_inputs(work_dir: Path, args: argparse.Namespace) -> None:
    """3D-ICE .stk/.flp 입력 파일을 work_dir에 생성한다."""
    work_dir.mkdir(parents=True, exist_ok=True)
    files = build_stack_description(
        footprint_mm=tuple(args.footprint_mm),
        total_power_w=args.total_power,
        base_die_fraction=args.base_die_fraction,
        ambient_c=args.ambient_c,
        htc_w_m2k=args.htc_w_m2k,
    )
    for fname, content in files.items():
        (work_dir / fname).write_text(content, encoding="utf-8")
    print(f"[3D-ICE] 입력 파일 {len(files)}개 생성 완료: {work_dir}")


def _run_3dice(threedice_bin: Path, work_dir: Path) -> None:
    """3D-ICE-Emulator 바이너리를 실행한다."""
    result = subprocess.run(
        [str(threedice_bin), "stack.stk"],
        cwd=work_dir,
        capture_output=True,
        text=True,
    )
    print(result.stdout)
    if result.returncode != 0:
        print(result.stderr, file=sys.stderr)
        print(
            f"[오류] 3D-ICE 실행 실패 (exit={result.returncode}). "
            "stack.stk 문법 오류 또는 바이너리 경로 확인 필요."
        )
        sys.exit(1)
    print("[3D-ICE] 해석 완료")


def _kelvin_to_celsius(temp_k: float) -> float:
    return temp_k - 273.15


def _read_3dice_avg_output(work_dir: Path, die_name: str) -> float:
    """3D-ICE Tflp average 출력 파일(<die>_avg.txt)에서 마지막 온도값(K)을 읽어 °C로 반환한다."""
    out_path = work_dir / f"{die_name}_avg.txt"
    if not out_path.exists():
        raise FileNotFoundError(
            f"3D-ICE 출력 파일 없음: {out_path} — 해석이 정상 완료되었는지 확인 필요."
        )
    last_data_line = None
    for line in out_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("%"):
            continue
        last_data_line = stripped
    if last_data_line is None:
        raise ValueError(f"3D-ICE 출력 파일에 데이터 행이 없습니다: {out_path}")
    # 형식: "0.000 \t 371.361 \t"
    parts = last_data_line.split()
    temp_k = float(parts[1])
    return _kelvin_to_celsius(temp_k)


def _read_all_3dice_results(work_dir: Path, die_names: list[str]) -> dict[str, float]:
    return {name: _read_3dice_avg_output(work_dir, name) for name in die_names}


def _print_summary_table(rows) -> None:
    header = f"{'die':<14} {'icepak_avg':>10} {'icepak_max':>10} {'3dice_avg':>10} {'diff_C':>8} {'diff_%':>7}"
    print(header)
    print("-" * len(header))
    for r in rows:
        print(
            f"{r.die:<14} {r.icepak_avg_c:>10.2f} {r.icepak_max_c:>10.2f} "
            f"{r.threedice_avg_c:>10.2f} {r.diff_c:>8.2f} {r.diff_pct:>6.2f}%"
        )


def run_cross_validation(args: argparse.Namespace) -> None:
    threedice_bin = Path(args.threedice_bin).resolve()
    if not threedice_bin.exists():
        print(f"[오류] 3D-ICE 바이너리를 찾을 수 없습니다: {threedice_bin}")
        sys.exit(1)

    icepak_csv_path = Path(args.icepak_csv).resolve()
    if not icepak_csv_path.exists():
        print(f"[오류] Icepak CSV를 찾을 수 없습니다: {icepak_csv_path}")
        sys.exit(1)

    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    work_dir = Path(args.work_dir).resolve() if args.work_dir else output_dir / "3dice_work"

    icepak_results = _read_icepak_csv(icepak_csv_path)

    _write_3dice_inputs(work_dir, args)
    _run_3dice(threedice_bin, work_dir)

    geometry = build_geometry_spec(footprint_mm=tuple(args.footprint_mm))
    die_names = [layer["name"] for layer in geometry]
    threedice_results = _read_all_3dice_results(work_dir, die_names)

    # Icepak CSV에 있는 die만 비교 대상으로 (교집합 순서는 icepak 쪽 유지).
    icepak_subset = {k: v for k, v in icepak_results.items() if k in threedice_results}
    rows = compare_die_temperatures(icepak_subset, threedice_results)
    passed, mean_pct = judge_pass_fail(rows)

    _print_summary_table(rows)
    print()
    verdict = "PASS" if passed else "FAIL"
    print(f"[판정] 평균 절대 오차 {mean_pct:.3f}% -> {verdict} (합격선 10%)")

    comparison_csv_path = output_dir / "icepak_vs_3dice_comparison.csv"
    csv_rows = build_comparison_csv_rows(rows)
    with open(comparison_csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=COMPARISON_CSV_FIELDNAMES)
        writer.writeheader()
        writer.writerows(csv_rows)
    print(f"[결과] 비교 CSV 저장 완료: {comparison_csv_path}")

    if not passed:
        sys.exit(1)


def main() -> None:
    args = _parse_args()
    run_cross_validation(args)


if __name__ == "__main__":
    main()
