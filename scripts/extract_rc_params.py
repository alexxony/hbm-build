#!/usr/bin/env python3
"""HBM2E 8-Hi 스택 FEM 결과를 2노드 lumped RC 등가 파라미터로 축약해
results/rc_params.csv를 생성하는 실행 진입점.

배경: vault docs/06-p2-rc-backport-design.md (P2 T2). Compiler_Thermal
RcBackend A/B 캘리브레이션 투입용 — r_hbm_sink(냉각 케이스 범위),
c_hbm(레이어별 해석적 rho_cp*V 합산) 2개 파라미터만 산출한다(die 쪽
r_die_hbm/r_die_sink/c_die는 legacy 유지, 이 스크립트의 스코프 밖).

이 스크립트는 순수 로직 모듈(hbm_thermal.rc_extract, hbm_thermal.homogenize)만
사용하며 pyaedt에 의존하지 않는다.

실행 예시:
    python3 scripts/extract_rc_params.py \\
        --param-study-csv results/param_study.csv \\
        --output results/rc_params.csv
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from hbm_thermal.rc_extract import (  # noqa: E402
    build_rc_params_rows,
    compute_c_hbm,
    compute_r_hbm_sink_range,
    load_param_study_csv,
    write_rc_params_csv,
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="HBM FEM 결과 -> 2노드 lumped RC 파라미터(r_hbm_sink, c_hbm) 추출"
    )
    parser.add_argument(
        "--param-study-csv",
        type=str,
        default=str(_REPO_ROOT / "results" / "param_study.csv"),
        help="Task 5 파라미터 스터디 결과 CSV 경로",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=str(_REPO_ROOT / "results" / "rc_params.csv"),
        help="출력 rc_params.csv 경로",
    )
    parser.add_argument(
        "--ambient-c",
        type=float,
        default=40.0,
        help="주변 온도 (°C), Icepak build_icepak_model.py의 _AMBIENT_TEMP_C와 동일해야 함",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()

    c_hbm_j_k, contributions = compute_c_hbm()

    param_study_rows = load_param_study_csv(args.param_study_csv)
    r_cases, r_min, r_max = compute_r_hbm_sink_range(
        param_study_rows, ambient_c=args.ambient_c
    )

    rows = build_rc_params_rows(c_hbm_j_k, contributions, r_cases, r_min, r_max)
    write_rc_params_csv(args.output, rows)

    print(f"C_hbm = {c_hbm_j_k:.6e} J/K")
    for c in sorted(contributions, key=lambda x: x.capacitance_j_k, reverse=True)[:3]:
        print(f"  상위 기여: {c.name} = {c.capacitance_j_k:.6e} J/K")
    print(f"r_hbm_sink 범위 = [{r_min:.6f}, {r_max:.6f}] K/W")
    for case in r_cases:
        print(
            f"  {case.case_name}: dT={case.delta_t_k:.3f}K, P={case.power_w:.3f}W, "
            f"R={case.r_k_w:.6f}K/W"
        )
    print(f"출력 완료: {args.output}")


if __name__ == "__main__":
    main()
