#!/usr/bin/env python3
"""HBM2E 8-Hi 스택 hotspot(base_die max) 기반 R을 기존 결과 CSV에서
재추출해 results/rc_params.csv에 r_hbm_sink_max 행을 append하는 실행 진입점.

배경: Compiler_Thermal 후보 B(hotspot ΔT 지표)가 이 자산을 기다림.
기존 avg 기반 r_hbm_sink 행(hbm_thermal.rc_extract.compute_r_hbm_sink_range)과
동일한 산식·냉각 케이스 쌍을 재사용하되 온도 컬럼만 base_die_max_c로
바꾼다. baseline_8hi 앵커값은 P4 T4/T5에서 이미 확립된 R=5.1386 K/W
(JOURNAL 2026-07-19T22:29:53+09:00, results/p4_report.md §5)와 정확히
일치해야 하며, 이 스크립트는 그 값을 별도 경로(param_study.csv 직접
재계산)로 재현해 교차검증한다.

이 스크립트는 순수 로직 모듈(hbm_thermal.rc_extract)만 사용하며
pyaedt에 의존하지 않는다 — Ansys/AEDT 실행 없이 기존 CSV만 재처리한다.

실행 예시:
    python3 scripts/extract_rc_hotspot.py \\
        --param-study-csv results/param_study.csv \\
        --p3-s0-csv results/p3_icepak_scenarios/p3_icepak_s0.csv \\
        --p3-s1-csv results/p3_icepak_scenarios/p3_icepak_s1.csv \\
        --p3-s2-csv results/p3_icepak_scenarios/p3_icepak_s2.csv \\
        --rc-params-csv results/rc_params.csv
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from hbm_thermal.rc_extract import (  # noqa: E402
    append_rc_params_csv,
    build_r_hbm_sink_max_row,
    compute_r_hbm_sink_max_anchor,
    compute_r_hbm_sink_max_p3_scenarios,
    load_p3_scenario_csv,
    load_param_study_csv,
)

_ANCHOR_EXPECTED_R_K_W = 5.1386
_ANCHOR_TOLERANCE_K_W = 0.0005


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "HBM FEM 결과(기존 CSV 재처리) -> hotspot(base_die max) 기반 "
            "r_hbm_sink_max 파라미터를 rc_params.csv에 append"
        )
    )
    parser.add_argument(
        "--param-study-csv",
        type=str,
        default=str(_REPO_ROOT / "results" / "param_study.csv"),
        help="Task 5 파라미터 스터디 결과 CSV 경로 (냉각BC 범위 앵커용)",
    )
    parser.add_argument(
        "--p3-s0-csv",
        type=str,
        default=str(_REPO_ROOT / "results" / "p3_icepak_scenarios" / "p3_icepak_s0.csv"),
    )
    parser.add_argument(
        "--p3-s1-csv",
        type=str,
        default=str(_REPO_ROOT / "results" / "p3_icepak_scenarios" / "p3_icepak_s1.csv"),
    )
    parser.add_argument(
        "--p3-s2-csv",
        type=str,
        default=str(_REPO_ROOT / "results" / "p3_icepak_scenarios" / "p3_icepak_s2.csv"),
    )
    parser.add_argument(
        "--rc-params-csv",
        type=str,
        default=str(_REPO_ROOT / "results" / "rc_params.csv"),
        help="append 대상 rc_params.csv 경로 (기존 c_hbm/r_hbm_sink 행 무변경)",
    )
    parser.add_argument(
        "--ambient-c",
        type=float,
        default=40.0,
        help="주변 온도 (°C), scripts/build_icepak_model.py의 _AMBIENT_TEMP_C와 동일해야 함",
    )
    parser.add_argument(
        "--p3-total-power-w",
        type=float,
        default=16.0,
        help="P3 시나리오 스택 총 전력 (W) — s0/s1/s2 전 시나리오 공통(base_die_fraction 0.55 고정)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="계산만 수행하고 rc_params.csv에 append하지 않음(검증용)",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()

    param_study_rows = load_param_study_csv(args.param_study_csv)
    anchor_cases, anchor_r_min, anchor_r_max = compute_r_hbm_sink_max_anchor(
        param_study_rows, ambient_c=args.ambient_c
    )

    p3_scenarios = {
        "s0_uniform": load_p3_scenario_csv(args.p3_s0_csv),
        "s1_phy_moderate": load_p3_scenario_csv(args.p3_s1_csv),
        "s2_phy_heavy": load_p3_scenario_csv(args.p3_s2_csv),
    }
    p3_cases = compute_r_hbm_sink_max_p3_scenarios(
        p3_scenarios, total_power_w=args.p3_total_power_w, ambient_c=args.ambient_c
    )

    print("=== r_hbm_sink_max 앵커 케이스 (냉각BC 범위) ===")
    for c in anchor_cases:
        print(f"  {c.case_name}: dT={c.delta_t_k:.3f}K, P={c.power_w:.3f}W, R={c.r_k_w:.6f}K/W")
    print(f"  범위 = [{anchor_r_min:.6f}, {anchor_r_max:.6f}] K/W")

    print("=== r_hbm_sink_max P3 전력맵 시나리오 (top-only, 16W 고정) ===")
    for c in p3_cases:
        print(f"  {c.case_name}: dT={c.delta_t_k:.3f}K, P={c.power_w:.3f}W, R={c.r_k_w:.6f}K/W")

    # 앵커 교차검증: baseline_8hi(top-only) max 기반 R이 P4 T4/T5에서 이미
    # 확립된 5.1386 K/W와 일치해야 함 — 불일치 시 원인 규명 전 append 금지.
    baseline_case = next(c for c in anchor_cases if c.case_name == "baseline_8hi")
    diff = abs(baseline_case.r_k_w - _ANCHOR_EXPECTED_R_K_W)
    print(
        f"=== 앵커 교차검증: baseline_8hi R={baseline_case.r_k_w:.6f}K/W vs "
        f"기대값 {_ANCHOR_EXPECTED_R_K_W}K/W (허용오차 {_ANCHOR_TOLERANCE_K_W}) ==="
    )
    if diff > _ANCHOR_TOLERANCE_K_W:
        print(
            f"앵커 불일치! 편차={diff:.6f}K/W > 허용오차={_ANCHOR_TOLERANCE_K_W}K/W. "
            "rc_params.csv append를 중단합니다 — 원인 규명 필요.",
            file=sys.stderr,
        )
        sys.exit(1)
    print(f"앵커 검증 PASS (편차={diff:.6f}K/W)")

    row = build_r_hbm_sink_max_row(anchor_cases, anchor_r_min, anchor_r_max, p3_cases)

    if args.dry_run:
        print("--dry-run 지정 — rc_params.csv 미변경. 산출 행:")
        print(row)
        return

    append_rc_params_csv(args.rc_params_csv, [row])
    print(f"append 완료: {args.rc_params_csv}")


if __name__ == "__main__":
    main()
