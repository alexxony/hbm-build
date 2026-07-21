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

import csv  # noqa: E402

from hbm_thermal.rc_extract import (  # noqa: E402
    append_rc_params_csv,
    build_r_hbm_sink_max_p4_row,
    build_r_hbm_sink_max_row,
    compute_r_hbm_sink_max_anchor,
    compute_r_hbm_sink_max_p3_scenarios,
    compute_r_hbm_sink_max_p4_scenarios,
    load_p3_scenario_csv,
    load_param_study_csv,
)

_ANCHOR_EXPECTED_R_K_W = 5.1386
_ANCHOR_TOLERANCE_K_W = 0.0005

_P4_SERIES = ("a", "b")
_P4_SCENARIOS = ("s0", "s1", "s2")
_P4_S0_CTRL2_SUFFIX = "_ctrl2"  # 설계 §3 T2 작업1: S0은 _ctrl2 버전이 정본


def _rc_params_has_parameter(path: str, parameter: str) -> bool:
    """rc_params.csv에 parameter 컬럼값이 이미 존재하는지 확인(idempotency guard).

    T3(p5_t3_bottomsink_avgavg.py append_crossval_row)의 기존-행 스킵 패턴과
    동일 — 재실행 시 중복 append 방지.
    """
    p = Path(path)
    if not p.exists():
        return False
    with open(p, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    return any(row.get("parameter") == parameter for row in rows)


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
        "--p4-icepak-dir",
        type=str,
        default=None,
        help=(
            "P4(30W, A/B계열x S0~S2) Icepak 시나리오 CSV 디렉터리(지정 시 P4 6케이스도 "
            "처리해 r_hbm_sink_max_p4 행 append, 미지정 시 P3만 처리하는 기존 동작 유지). "
            "파일명 규약: p4_icepak_{a,b}_{s0,s1,s2}.csv, S0은 p4_icepak_{a,b}_s0_ctrl2.csv "
            "정본 사용(설계 §3 T2 작업1)."
        ),
    )
    parser.add_argument(
        "--p4-total-power-w",
        type=float,
        default=30.0,
        help="P4 시나리오 스택 총 전력 (W) — A/B계열 x S0~S2 전 시나리오 공통",
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

    rows_to_append: list[dict] = []
    if _rc_params_has_parameter(args.rc_params_csv, row["parameter"]):
        print(
            f"[스킵] {args.rc_params_csv}에 {row['parameter']!r} 행이 이미 존재 — "
            "중복 append 방지(idempotent)."
        )
    else:
        rows_to_append.append(row)

    # P4(30W, A/B계열 x S0~S2) 확장 — 설계 §3 T2 작업1·4. --p4-icepak-dir
    # 미지정 시 기존 P3 전용 동작 그대로 유지(하위 호환).
    if args.p4_icepak_dir:
        p4_dir = Path(args.p4_icepak_dir)
        p4_scenarios: dict[str, dict[str, dict[str, float]]] = {}
        for series in _P4_SERIES:
            for scenario in _P4_SCENARIOS:
                # _ctrl2 정본은 A계열 S0에만 존재(설계 §3 T2 작업1) — B계열은
                # 해당 파일이 없으므로(실측 확인) 원본 파일을 그대로 사용한다.
                suffix = (
                    _P4_S0_CTRL2_SUFFIX
                    if scenario == "s0" and series == "a"
                    else ""
                )
                csv_path = p4_dir / f"p4_icepak_{series}_{scenario}{suffix}.csv"
                p4_scenarios[f"{series}_{scenario}"] = load_p3_scenario_csv(str(csv_path))

        p4_cases = compute_r_hbm_sink_max_p4_scenarios(
            p4_scenarios, total_power_w=args.p4_total_power_w, ambient_c=args.ambient_c
        )

        print("=== r_hbm_sink_max_p4 P4 전력맵x냉각계열 시나리오 (30W 고정) ===")
        for c in p4_cases:
            print(f"  {c.case_name}: dT={c.delta_t_k:.3f}K, P={c.power_w:.3f}W, R={c.r_k_w:.6f}K/W")

        p4_row = build_r_hbm_sink_max_p4_row(p4_cases)
        if _rc_params_has_parameter(args.rc_params_csv, p4_row["parameter"]):
            print(
                f"[스킵] {args.rc_params_csv}에 {p4_row['parameter']!r} 행이 이미 존재 — "
                "중복 append 방지(idempotent)."
            )
        else:
            rows_to_append.append(p4_row)

    if args.dry_run:
        print("--dry-run 지정 — rc_params.csv 미변경. 산출 행(스킵분 제외):")
        for r in rows_to_append:
            print(r)
        return

    if not rows_to_append:
        print("append할 신규 행 없음(전부 이미 존재) — rc_params.csv 미변경.")
        return

    append_rc_params_csv(args.rc_params_csv, rows_to_append)
    print(f"append 완료: {args.rc_params_csv} ({len(rows_to_append)}행)")


if __name__ == "__main__":
    main()
