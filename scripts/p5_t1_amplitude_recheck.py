#!/usr/bin/env python3
"""P5 T1: G4 A계열 진폭비율 avg-vs-avg 재구성.

배경(설계: docs/09-p5-analysis-design.md §2 H_T1, §3 T1):
p4_t4_crossval_hypotheses.py의 G4 진폭비율(0.8905, FAIL)은 Icepak
base_die_phy **max**(hotspot)와 3D-ICE base_die_phy **avg**를 대조한 것이었다.
3D-ICE는 블록 단위 lumped RC 컴팩트 모델이라 avg==max로 항상 수렴하므로
(설계 문서에서 CSV 실측으로 이미 확인), "avg와 다른 max"라는 개념 자체가
3D-ICE 쪽에는 없다. H_T1은 이 통계량 불일치가 진폭비율 FAIL의 지배적
원인인지를 반증 가능한 형태로 검증한다: Icepak 쪽 지표만 max에서 avg로
바꿔(3D-ICE는 이미 avg이므로 그대로 두고) 진폭비율을 재계산하면 [0.9, 1.1]
합격선에 근접하는지 확인한다.

기존 p4_t4_crossval_hypotheses.py는 원본 무수정(완결된 리포트 산출
스크립트) — 이 스크립트는 별도 진입점으로 avg-avg 재계산만 수행하고,
3D-ICE 재실행은 하지 않는다(3D-ICE 출력은 이미 avg이므로 불필요).
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

# H_T1 반증 가능 판정 기준(설계 §2): avg-avg 진폭비율이 [0.9, 1.1] 안이면 확증.
AMPLITUDE_GATE_LO = 0.9
AMPLITUDE_GATE_HI = 1.1

ICEPAK_A_S0_CSV = REPO / "results/p4_icepak_scenarios/p4_icepak_a_s0.csv"
ICEPAK_A_S2_CSV = REPO / "results/p4_icepak_scenarios/p4_icepak_a_s2.csv"
THREEDICE_CSV = REPO / "results/p4_3dice_t4/p4_3dice_t4_results.csv"
CROSSVAL_CSV = REPO / "results/p4_t4_crossval.csv"

DIE = "base_die_phy"


def read_icepak_avg(path: Path, die: str = DIE) -> float:
    """Icepak die-level CSV(die,avg_temp_c,max_temp_c)에서 die의 avg_temp_c를 읽는다."""
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["die"] == die:
                return float(row["avg_temp_c"])
    raise KeyError(f"{path}에 die={die!r} 행이 없습니다.")


def read_3dice_avg(path: Path, series: str, scenario: str, die: str = DIE) -> float:
    """3D-ICE 결과 CSV(series,scenario,die,avg_c,max_c)에서 avg_c를 읽는다."""
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["series"] == series and row["scenario"] == scenario and row["die"] == die:
                return float(row["avg_c"])
    raise KeyError(f"{path}에 series={series!r} scenario={scenario!r} die={die!r} 행이 없습니다.")


def compute_amplitude_ratio_avg_avg(
    icepak_s0_avg: float,
    icepak_s2_avg: float,
    threedice_s0_avg: float,
    threedice_s2_avg: float,
) -> tuple[float, float, float]:
    """avg-avg 진폭비율 = 3D-ICE avg 진폭 / Icepak avg 진폭.

    Returns:
        (icepak_amp, threedice_amp, ratio) — ratio는 기존
        p4_t4_crossval_hypotheses.py의 amp_ratio_a와 동일한 방향
        (3D-ICE 진폭 / Icepak 진폭)으로 정의해 기존 열과 직접 비교 가능하게 함.
    """
    icepak_amp = icepak_s2_avg - icepak_s0_avg
    threedice_amp = threedice_s2_avg - threedice_s0_avg
    ratio = threedice_amp / icepak_amp
    return icepak_amp, threedice_amp, ratio


def judge_h_t1(ratio: float) -> tuple[bool, str]:
    """H_T1 판정: 비율이 [0.9, 1.1] 안이면 확증(비교축 문제가 지배적 원인)."""
    gate_pass = AMPLITUDE_GATE_LO <= ratio <= AMPLITUDE_GATE_HI
    verdict = "확증(비교축 문제가 지배적 원인)" if gate_pass else "반증(비교축 재구성으로 해결 안 됨)"
    return gate_pass, verdict


def append_crossval_row(icepak_amp: float, threedice_amp: float, ratio: float, gate_pass: bool) -> None:
    """results/p4_t4_crossval.csv에 신규 행 append (기존 행 변경 금지)."""
    with open(CROSSVAL_CSV, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "G4_A계열_진폭비율_avg대avg_T1",
            f"{ratio:.4f}",
            (
                f"합격선[0.9,1.1] -> {'PASS' if gate_pass else 'FAIL'} | "
                f"Icepak avg진폭{icepak_amp:.3f}K vs 3DICE avg진폭{threedice_amp:.3f}K | "
                "P5 T1 avg-avg 재구성(대안 비교축 결과 추가, 기존 max대avg 행은 불변)"
            ),
        ])


def main() -> None:
    icepak_s0_avg = read_icepak_avg(ICEPAK_A_S0_CSV)
    icepak_s2_avg = read_icepak_avg(ICEPAK_A_S2_CSV)
    threedice_s0_avg = read_3dice_avg(THREEDICE_CSV, "A", "s0_uniform")
    threedice_s2_avg = read_3dice_avg(THREEDICE_CSV, "A", "s2_phy_heavy")

    icepak_amp, threedice_amp, ratio = compute_amplitude_ratio_avg_avg(
        icepak_s0_avg, icepak_s2_avg, threedice_s0_avg, threedice_s2_avg
    )
    gate_pass, verdict = judge_h_t1(ratio)

    print("=== P5 T1: G4 A계열 진폭비율 avg-vs-avg 재구성 ===\n")
    print(f"Icepak base_die_phy avg: S0={icepak_s0_avg:.3f}C, S2={icepak_s2_avg:.3f}C, 진폭={icepak_amp:.3f}K")
    print(f"3D-ICE base_die_phy avg: S0={threedice_s0_avg:.3f}C, S2={threedice_s2_avg:.3f}C, 진폭={threedice_amp:.3f}K")
    print(f"avg-avg 진폭비율 = {ratio:.4f} (합격선[0.9,1.1]) -> {'PASS' if gate_pass else 'FAIL'}")
    print(f"H_T1 판정: {verdict}")

    append_crossval_row(icepak_amp, threedice_amp, ratio, gate_pass)
    print(f"\n[결과] {CROSSVAL_CSV}에 신규 행 append 완료")


if __name__ == "__main__":
    main()
