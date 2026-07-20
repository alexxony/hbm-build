#!/usr/bin/env python3
"""P5 T3: B계열(bottomsink) avg-vs-avg 재비교 — 조건부 축소 경로.

배경(설계: docs/09-p5-analysis-design.md §3 T3):
T1이 H_T1을 확증(A계열 진폭비율 FAIL 0.8905의 지배 원인 = Icepak max
vs 3D-ICE avg 비교축 불일치, avg-avg 재구성 시 1.0137 PASS)했으므로,
T3은 설계 문서의 조건부 스코프 규칙에 따라 **1차 avg-avg 재비교만
수행**하는 축소 경로로 확정됐다.

**중요한 사전 확인(본 스크립트 작성 전 조사)**: B계열의 기존 평균오차
지표(47.46%/18.75%/18.64%, `p4_t4_crossval_hypotheses.py`)는
`hbm_thermal/comparison.py`의 `compare_die_temperatures()`가
`icepak_avg_c` vs `threedice_avg_c`를 비교해 산출한 것으로, **이미
avg-avg 비교축**이다(A계열 진폭비율처럼 max-vs-avg 불일치가 없음).
따라서 평균오차 자체는 "avg-avg로 재구성"할 여지가 없다 — 이미
그 축이다. 본 스크립트가 재구성하는 것은 T1과 동일한 방법론인
**진폭비율(S2-S0)** 이며, 이는 기존 P4 스크립트에서 B계열에 대해
한 번도 계산된 적이 없다(A계열만 `amp_ratio_a`로 계산됨).

B-S0(`s0_uniform`)는 균일 전력 시나리오라 `base_die_phy`/`base_die_tsva`/
`base_die_da` 분할이 없고 `base_die` 단일 행만 존재한다(CSV 실측 확인).
S1/S2는 `base_die_phy` 행이 있다. T1과 동일 방법론(S2-S0 진폭)을
적용하려면 S0 앵커가 필요하므로, 기존 `p4_t4_crossval_hypotheses.py`의
`base_die_max()` fallback 로직(`base_die_phy` 없으면 `base_die` 사용)과
동일한 패턴으로 S0에는 `base_die`의 avg_temp_c를 사용한다.

idempotent 설계: argparse + --dry-run + CROSSVAL_CSV 중복 행 방지
(동일 `항목` 명이 이미 있으면 재실행 시 append하지 않고 스킵).
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

# T1과 동일 게이트(설계 §2): avg-avg 진폭비율이 [0.9, 1.1] 안이면
# "비교축 문제로 설명됨"(PASS권). 평균오차는 기존 게이트 10% 그대로.
AMPLITUDE_GATE_LO = 0.9
AMPLITUDE_GATE_HI = 1.1
MEAN_ERROR_GATE_PCT = 10.0

ICEPAK_B_S0_CSV = REPO / "results/p4_icepak_scenarios/p4_icepak_b_s0.csv"
ICEPAK_B_S1_CSV = REPO / "results/p4_icepak_scenarios/p4_icepak_b_s1.csv"
ICEPAK_B_S2_CSV = REPO / "results/p4_icepak_scenarios/p4_icepak_b_s2.csv"
THREEDICE_CSV = REPO / "results/p4_3dice_t4/p4_3dice_t4_results.csv"
CROSSVAL_CSV = REPO / "results/p4_t4_crossval.csv"

DIE_PHY = "base_die_phy"
DIE_S0_FALLBACK = "base_die"

# 기존 crossval.csv의 B계열 케이스별 평균오차(정본, comparison.py로
# 이미 avg-avg 산출됨) — 재계산 없이 그대로 인용(재구성 여지 없음을
# 명시하기 위해 상수로 고정, 출처: p4_t4_crossval_hypotheses.py 실행 로그
# / results/p4_3dice_t4/g4_comparison_all_cases.csv).
B_CASE_MEAN_ERROR_PCT = {
    "s0_uniform": 47.46,
    "s1_phy_moderate": 18.75,
    "s2_phy_heavy": 18.64,
}

ROW_LABEL = "G4_B계열_진폭비율_avg대avg_T3"


def read_icepak_avg(path: Path, die: str) -> float:
    """Icepak die-level CSV(die,avg_temp_c,max_temp_c)에서 die의 avg_temp_c를 읽는다."""
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["die"] == die:
                return float(row["avg_temp_c"])
    raise KeyError(f"{path}에 die={die!r} 행이 없습니다.")


def read_icepak_b_s0_anchor(path: Path) -> tuple[float, str]:
    """B-S0의 진폭 앵커 avg 온도를 읽는다.

    B-S0는 균일 시나리오라 base_die_phy 행이 없다(실측 확인) — base_die
    행으로 폴백한다. Returns (avg_temp_c, 사용한_die명).
    """
    with open(path, newline="", encoding="utf-8") as f:
        rows = {row["die"]: row for row in csv.DictReader(f)}
    if DIE_PHY in rows:
        return float(rows[DIE_PHY]["avg_temp_c"]), DIE_PHY
    if DIE_S0_FALLBACK in rows:
        return float(rows[DIE_S0_FALLBACK]["avg_temp_c"]), DIE_S0_FALLBACK
    raise KeyError(f"{path}에 {DIE_PHY!r}도 {DIE_S0_FALLBACK!r}도 없습니다.")


def read_3dice_avg(path: Path, series: str, scenario: str, die: str) -> float:
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
    """avg-avg 진폭비율 = 3D-ICE avg 진폭 / Icepak avg 진폭 (T1과 동일 정의)."""
    icepak_amp = icepak_s2_avg - icepak_s0_avg
    threedice_amp = threedice_s2_avg - threedice_s0_avg
    ratio = threedice_amp / icepak_amp
    return icepak_amp, threedice_amp, ratio


def judge_amplitude_gate(ratio: float) -> bool:
    return AMPLITUDE_GATE_LO <= ratio <= AMPLITUDE_GATE_HI


def classify_verdict(mean_errors_still_fail: bool, amp_gate_pass: bool) -> str:
    """설계 §3 T3 3분류(조건부 스코프 축소 경로 내에서의 판정).

    스코프 축소 규칙(§3): avg-avg로도 평균오차가 대폭 FAIL이면
    "통계량 불일치로 설명 안 되는 진짜 물리 문제"로 판정하고 근본
    조사는 스코프 제외·P5+ 이월. 여기서는 평균오차(이미 avg-avg,
    변경 불가)가 여전히 대폭 FAIL이므로 이 분기가 적용된다.
    """
    if mean_errors_still_fail:
        return "근본 재설계 필요(스코프 축소 확정 — 근본 조사는 P5+ 이월)"
    return "보정 가능성 있음"


def append_crossval_row(icepak_amp: float, threedice_amp: float, ratio: float, gate_pass: bool, dry_run: bool) -> bool:
    """results/p4_t4_crossval.csv에 신규 행 append (기존 행 변경 금지).

    idempotent: 이미 ROW_LABEL 행이 존재하면 append하지 않고 False 반환.
    """
    if CROSSVAL_CSV.exists():
        with open(CROSSVAL_CSV, newline="", encoding="utf-8") as f:
            existing_labels = {row[0] for row in csv.reader(f) if row}
        if ROW_LABEL in existing_labels:
            print(f"[스킵] {CROSSVAL_CSV}에 {ROW_LABEL!r} 행이 이미 존재 — 중복 append 방지(idempotent).")
            return False

    if dry_run:
        print(f"[dry-run] {CROSSVAL_CSV}에 append할 행(실제 쓰기 없음):")
        print(f"  {ROW_LABEL}, {ratio:.4f}, ...")
        return False

    with open(CROSSVAL_CSV, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            ROW_LABEL,
            f"{ratio:.4f}",
            (
                f"합격선[0.9,1.1] -> {'PASS' if gate_pass else 'FAIL'} | "
                f"Icepak avg진폭{icepak_amp:.3f}K vs 3DICE avg진폭{threedice_amp:.3f}K | "
                "P5 T3 avg-avg 진폭비율 재구성(B계열, S0 앵커=base_die 폴백) | "
                "평균오차는 기존 comparison.py가 이미 avg-avg 산출(재구성 여지 없음, §4.2 FAIL 유지)"
            ),
        ])
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="CSV에 쓰지 않고 계산 결과만 출력")
    args = parser.parse_args()

    icepak_s0_avg, s0_die_used = read_icepak_b_s0_anchor(ICEPAK_B_S0_CSV)
    icepak_s2_avg = read_icepak_avg(ICEPAK_B_S2_CSV, DIE_PHY)
    threedice_s0_avg = read_3dice_avg(THREEDICE_CSV, "B", "s0_uniform", DIE_PHY)
    threedice_s2_avg = read_3dice_avg(THREEDICE_CSV, "B", "s2_phy_heavy", DIE_PHY)

    icepak_amp, threedice_amp, ratio = compute_amplitude_ratio_avg_avg(
        icepak_s0_avg, icepak_s2_avg, threedice_s0_avg, threedice_s2_avg
    )
    amp_gate_pass = judge_amplitude_gate(ratio)

    mean_errors_still_fail = any(v > MEAN_ERROR_GATE_PCT for v in B_CASE_MEAN_ERROR_PCT.values())
    verdict = classify_verdict(mean_errors_still_fail, amp_gate_pass)

    print("=== P5 T3: B계열(bottomsink) avg-vs-avg 재비교 — 조건부 축소 경로 ===\n")
    print(f"[스코프] T1이 H_T1 확증 -> 1차 avg-avg 재비교만 수행(설계 §3 T3 조건부 규칙).\n")

    print("1) 평균오차(기존 comparison.py, 이미 avg-avg — 재구성 여지 없음):")
    for scenario, pct in B_CASE_MEAN_ERROR_PCT.items():
        verdict_str = "PASS" if pct <= MEAN_ERROR_GATE_PCT else "FAIL"
        print(f"   B-{scenario}: {pct:.2f}% -> {verdict_str} (합격선 {MEAN_ERROR_GATE_PCT}%)")
    print(f"   -> {'전부 FAIL 유지' if mean_errors_still_fail else '변화 없음'}"
          f"(비교축이 이미 avg-avg이므로 T1과 달리 재구성으로 개선되지 않음)\n")

    print("2) 진폭비율(S2-S0) avg-avg 재구성 — T1과 동일 방법론, B계열 최초 계산:")
    print(f"   S0 앵커 die = {s0_die_used!r}({'base_die_phy 없어 폴백' if s0_die_used == DIE_S0_FALLBACK else '정상'})")
    print(f"   Icepak avg: S0={icepak_s0_avg:.3f}C, S2={icepak_s2_avg:.3f}C, 진폭={icepak_amp:.3f}K")
    print(f"   3D-ICE avg: S0={threedice_s0_avg:.3f}C, S2={threedice_s2_avg:.3f}C, 진폭={threedice_amp:.3f}K")
    print(f"   비율 = {ratio:.4f} (합격선[0.9,1.1]) -> {'PASS' if amp_gate_pass else 'FAIL'}\n")

    print(f"[판정] {verdict}")
    print("[근거] 평균오차는 이미 avg-avg 비교축이었으므로 통계량 불일치로 설명되지 않는다 —")
    print("       설계 §3 T3 조건부 규칙에 따라 근본 원인 조사(bottomsink 파라미터 딥다이브)는")
    print("       스코프 제외, P5+ 후보로 이월한다. 신규 3D-ICE 실행 없음(기존 산출물만 사용).\n")

    appended = append_crossval_row(icepak_amp, threedice_amp, ratio, amp_gate_pass, args.dry_run)
    if appended:
        print(f"[결과] {CROSSVAL_CSV}에 신규 행 append 완료: {ROW_LABEL}")


if __name__ == "__main__":
    main()
