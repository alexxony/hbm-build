#!/usr/bin/env python3
"""T4: 6케이스(A/B x S0/S1/S2) 3D-ICE 실행 + Icepak 대비 G4 교차검증.

3D-ICE-Emulator 바이너리 빌드 절차: docs/03-cross-validation-3d-ice.md §2.
빌드 산출물은 WSL 세션 스크래치패드 등 소멸 가능 경로에 있을 수 있으므로,
바이너리 경로를 --3dice-bin으로 받는다(재현성 확보 — 하드코딩 금지, T4에서
스크래치패드 경로 하드코딩으로 인한 재현 불가 문제 실측 확인 후 정정).
"""
from __future__ import annotations
import argparse
import csv
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from hbm_thermal.export_3dice import build_stack_description
from hbm_thermal.model_config import build_geometry_spec

OUT_DIR = REPO / "results" / "p4_3dice_t4"
OUT_DIR.mkdir(parents=True, exist_ok=True)

CASES = [
    ("A", "s0_uniform", None),
    ("A", "s1_phy_moderate", None),
    ("A", "s2_phy_heavy", None),
    ("B", "s0_uniform", 2500.0),
    ("B", "s1_phy_moderate", 2500.0),
    ("B", "s2_phy_heavy", 2500.0),
]

TOTAL_POWER_W = 30.0
BASE_DIE_FRACTION = 0.55
FOOTPRINT_MM = (11.0, 10.0)
AMBIENT_C = 40.0
HTC_W_M2K = 2500.0


def kelvin_to_c(k: float) -> float:
    return k - 273.15


def read_avg_output(work_dir: Path, die_name: str) -> float:
    out_path = work_dir / f"{die_name}_avg.txt"
    if not out_path.exists():
        raise FileNotFoundError(f"missing {out_path}")
    last = None
    for line in out_path.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("%"):
            continue
        last = s
    if last is None:
        raise ValueError(f"no data in {out_path}")
    parts = last.split()
    return kelvin_to_c(float(parts[1]))


import re

_TFLP_AVG_RE = re.compile(r'Tflp(?:el)?\s*\(\s*(\S+?)\s*,\s*"(\S+?)_avg\.txt"\s*,\s*average')


def die_names_from_stk(stk_text: str) -> list[tuple[str, str]]:
    """stack.stk의 output: 블록에서 실제 average 출력 대상을 파싱한다.

    power_scenario 지정 시 base_die가 Tflpel(base_die.phy, ...) 형태의
    3-way sub-element(phy/tsva/da)로 분할되므로 Tflp(일반 die)와 Tflpel(
    sub-element) 둘 다 매칭해야 한다 — 첫 시도에서 Tflp만 매칭해 phy/tsva/da
    3개 die가 조용히 누락됐던 것을 여기서 수정함(오매핑 방지 육안검증 중 발견).

    Returns: [(3dice_식별자, 출력파일_prefix), ...] — 예: ("base_die.phy", "base_die_phy")
    """
    return [(m.group(1), m.group(2)) for m in _TFLP_AVG_RE.finditer(stk_text)]


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--3dice-bin",
        dest="threedice_bin",
        type=str,
        required=True,
        help="빌드된 3D-ICE-Emulator 바이너리 경로 (docs/03-cross-validation-3d-ice.md §2 참고)",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    threedice_bin = Path(args.threedice_bin).resolve()
    if not threedice_bin.exists():
        print(f"[오류] 3D-ICE 바이너리를 찾을 수 없습니다: {threedice_bin}")
        sys.exit(1)

    all_rows = []
    for series, scenario, bottom_htc in CASES:
        case_id = f"{series}_{scenario}"
        work_dir = OUT_DIR / case_id
        work_dir.mkdir(parents=True, exist_ok=True)

        files = build_stack_description(
            footprint_mm=FOOTPRINT_MM,
            total_power_w=TOTAL_POWER_W,
            base_die_fraction=BASE_DIE_FRACTION,
            ambient_c=AMBIENT_C,
            htc_w_m2k=HTC_W_M2K,
            bottom_htc_w_m2k=bottom_htc,
            power_scenario=scenario,
        )
        for fname, content in files.items():
            (work_dir / fname).write_text(content, encoding="utf-8")

        die_names = die_names_from_stk(files["stack.stk"])

        result = subprocess.run(
            [str(threedice_bin), "stack.stk"],
            cwd=work_dir,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            print(f"[FAIL] {case_id}: exit={result.returncode}")
            print(result.stdout)
            print(result.stderr, file=sys.stderr)
            sys.exit(1)

        for _identifier, out_prefix in die_names:
            temp_c = read_avg_output(work_dir, out_prefix)
            all_rows.append({
                "series": series,
                "scenario": scenario,
                "die": out_prefix,
                "avg_c": temp_c,
                "max_c": temp_c,  # 3D-ICE lumped: avg==max (문서 §8 확인)
            })
        print(f"[OK] {case_id}: {len(die_names)} outputs (Tflp+Tflpel)")

    csv_path = OUT_DIR / "p4_3dice_t4_results.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["series", "scenario", "die", "avg_c", "max_c"])
        writer.writeheader()
        writer.writerows(all_rows)
    print(f"[결과] {csv_path}")


if __name__ == "__main__":
    main()
