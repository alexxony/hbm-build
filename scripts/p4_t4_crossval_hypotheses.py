#!/usr/bin/env python3
"""T4 최종: G4(A계열 한정) + H1/H2/H3/Q2 전체 판정, results/p4_t4_crossval.csv 산출."""
from __future__ import annotations
import csv
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from hbm_thermal.comparison import compare_die_temperatures, judge_pass_fail, build_comparison_csv_rows, COMPARISON_CSV_FIELDNAMES

ICEPAK_FILES = {
    ("A", "s0_uniform"): "results/p4_icepak_scenarios/p4_icepak_a_s0_ctrl2.csv",
    ("A", "s1_phy_moderate"): "results/p4_icepak_scenarios/p4_icepak_a_s1.csv",
    ("A", "s2_phy_heavy"): "results/p4_icepak_scenarios/p4_icepak_a_s2.csv",
    ("B", "s0_uniform"): "results/p4_icepak_scenarios/p4_icepak_b_s0.csv",
    ("B", "s1_phy_moderate"): "results/p4_icepak_scenarios/p4_icepak_b_s1.csv",
    ("B", "s2_phy_heavy"): "results/p4_icepak_scenarios/p4_icepak_b_s2.csv",
}

THREEDICE_CSV = REPO / "results/p4_3dice_t4/p4_3dice_t4_results.csv"
OUT_CSV = REPO / "results/p4_t4_crossval.csv"


def read_icepak_csv(path: Path) -> dict[str, tuple[float, float]]:
    results = {}
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            results[row["die"]] = (float(row["avg_temp_c"]), float(row["max_temp_c"]))
    return results


def read_3dice_csv(path: Path) -> dict[tuple[str, str], dict[str, float]]:
    out: dict[tuple[str, str], dict[str, float]] = {}
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            key = (row["series"], row["scenario"])
            out.setdefault(key, {})[row["die"]] = float(row["avg_c"])
    return out


def main() -> None:
    threedice = read_3dice_csv(THREEDICE_CSV)
    icepak = {k: read_icepak_csv(REPO / v) for k, v in ICEPAK_FILES.items()}

    all_comparison_rows = []
    case_summaries = []

    print("=== G4: Icepak vs 3D-ICE 교차검증 (die avg 대 avg, 합격선 절대오차 10%) ===\n")
    for (series, scenario), icepak_path in ICEPAK_FILES.items():
        icepak_results = icepak[(series, scenario)]
        threedice_results = threedice[(series, scenario)]
        icepak_subset = {k: v for k, v in icepak_results.items() if k in threedice_results}
        rows = compare_die_temperatures(icepak_subset, threedice_results)
        passed, mean_pct = judge_pass_fail(rows)
        verdict = "PASS" if passed else "FAIL"
        print(f"[{series}-{scenario}] 평균 절대오차 {mean_pct:.4f}% -> {verdict} (die {len(rows)}개 비교)")
        for r in rows:
            all_comparison_rows.append({
                "series": series, "scenario": scenario,
                "die": r.die, "icepak_avg_c": r.icepak_avg_c, "icepak_max_c": r.icepak_max_c,
                "threedice_avg_c": r.threedice_avg_c, "diff_c": r.diff_c, "diff_pct": r.diff_pct,
            })
        case_summaries.append((series, scenario, mean_pct, passed))

    a_cases = [c for c in case_summaries if c[0] == "A"]
    b_cases = [c for c in case_summaries if c[0] == "B"]
    a_pass = all(p for _, _, _, p in a_cases)
    a_mean = sum(m for _, _, m, _ in a_cases) / len(a_cases)
    b_pass = all(p for _, _, _, p in b_cases)
    b_mean = sum(m for _, _, m, _ in b_cases) / len(b_cases)

    def base_die_max(series, scenario):
        d = icepak[(series, scenario)]
        if "base_die" in d:
            return d["base_die"][1]
        return d["base_die_phy"][1]

    def base_die_avg3dice(series, scenario, key):
        return threedice[(series, scenario)][key]

    # G4 amplitude ratio (A계열 PHY hotspot 진폭): S2-S0 max 비교
    a_s0_max = base_die_max("A", "s0_uniform")
    a_s2_max = base_die_max("A", "s2_phy_heavy")
    icepak_amp_a = a_s2_max - a_s0_max
    threedice_a_s0_phy = base_die_avg3dice("A", "s0_uniform", "base_die_phy")
    threedice_a_s2_phy = base_die_avg3dice("A", "s2_phy_heavy", "base_die_phy")
    threedice_amp_a = threedice_a_s2_phy - threedice_a_s0_phy
    amp_ratio_a = threedice_amp_a / icepak_amp_a

    print(f"\n[G4 A계열] 평균 절대오차 {a_mean:.4f}% -> {'PASS' if a_pass else 'FAIL'} (합격선 10%)")
    print(f"[G4 A계열] PHY ΔT(S2-S0) 진폭: Icepak {icepak_amp_a:.3f}K vs 3D-ICE {threedice_amp_a:.3f}K, 비율 {amp_ratio_a:.4f} (합격선 [0.9,1.1])")
    amp_gate_a = 0.9 <= amp_ratio_a <= 1.1
    print(f"[G4 A계열] 진폭 게이트: {'PASS' if amp_gate_a else 'FAIL'}")
    g4_a_verdict = "PASS" if (a_pass and amp_gate_a) else "FAIL"
    print(f"[G4 A계열 종합] {g4_a_verdict}")

    print(f"\n[G4 B계열, 참고] 평균 절대오차 {b_mean:.4f}% -> {'PASS' if b_pass else 'FAIL'} — **판정에서 제외**")
    print("[G4 B계열] 설계 문서 R1 완화 적용: bottom heat sink 3D-ICE 교차검증 최초 실측, 대폭 괴리(>18%) 확인.")
    print("[G4 B계열] 원인 후보(미확정, 후속 조사 필요): 3D-ICE 컴팩트 RC망에서 top+bottom 동시 HTC 인가 시")
    print("  등가 열저항 병렬화가 Icepak 3D FEM과 다르게 처리될 가능성 — 온도 상승분 비율 icepak 대비 약 2.13배(B-S0 top_die 기준).")
    print("  R1 완화 조항에 따라 G4는 A계열로 한정, B계열은 Icepak 단독 실측치로만 보고.\n")

    out_path = REPO / "results/p4_3dice_t4/g4_comparison_all_cases.csv"
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        fieldnames = ["series", "scenario"] + COMPARISON_CSV_FIELDNAMES
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(all_comparison_rows)
    print(f"[결과] G4 die별 비교 CSV: {out_path}\n")

    # ---- 가설 판정 ----
    print("=== 가설 판정 (Icepak 실측 6케이스 기준, 동일솔버) ===\n")

    dT_16w_p3 = 19.48
    ratio = icepak_amp_a / dT_16w_p3
    linear_expected = 30.0 / 16.0
    band_lo, band_hi = linear_expected * dT_16w_p3 * 0.85, linear_expected * dT_16w_p3 * 1.15
    if band_lo <= icepak_amp_a <= band_hi:
        h1_verdict = "H1a(선형)"
    elif icepak_amp_a > band_hi:
        h1_verdict = "H1b(초선형)"
    else:
        h1_verdict = "H1c(포화)"
    print(f"H1: dT_hotspot(A, 30W) = {a_s2_max:.2f} - {a_s0_max:.2f} = {icepak_amp_a:.3f}K")
    print(f"    P3 16W 실측 {dT_16w_p3}K 대비 비율 {ratio:.4f}x (기대 선형 {linear_expected:.4f}x)")
    print(f"    밴드 [{band_lo:.2f}, {band_hi:.2f}]K -> 판정: {h1_verdict}\n")

    # H2: base_die 합성 avg 시나리오 불변 (A계열, Icepak CSV의 die별 면적가중 없이
    # s0의 합성 base_die avg가 유일 앵커 — s1/s2는 phy/tsva/da 분할이라 직접 비교 불가.
    # 대신 s1/s2의 개별 die(dram_die 등, base_die 이외)의 avg 온도가 s0와 얼마나
    # 다른지로 "총 열수지 불변"을 방계 검증한다(동일 열원 배분 총합이면 dram_die
    # 온도도 s0/s1/s2 사이 거의 불변이어야 함 — base_die 내부 재배치만 있고 총
    # 발열은 30W로 고정이므로).
    a_s0 = icepak[("A", "s0_uniform")]
    a_s1 = icepak[("A", "s1_phy_moderate")]
    a_s2 = icepak[("A", "s2_phy_heavy")]
    dram_keys = [k for k in a_s0 if k.startswith("dram_die")]
    max_dev_pct = 0.0
    for k in dram_keys:
        vals = [a_s0[k][0], a_s1[k][0], a_s2[k][0]]
        dev_pct = (max(vals) - min(vals)) / min(vals) * 100.0
        max_dev_pct = max(max_dev_pct, dev_pct)
    h2_pass = max_dev_pct < 0.01
    print(f"H2: A계열 dram_die avg 온도 s0/s1/s2 간 최대 편차 {max_dev_pct:.6f}% (판정 기준 <0.01%) -> {'PASS(불변 확인)' if h2_pass else 'FAIL(변화 감지)'}")
    print("    (근거: base_die 내부 전력 재배치만 있고 총 30W·DRAM 개별 전력은 시나리오 불변 —")
    print("     열수지 항등식이 유지되면 DRAM 온도도 거의 불변이어야 함, P3 §6 메커니즘과 동일 논리)\n")

    # H3
    r_hbm_sink_p2 = 4.671
    ambient_c = 40.0
    r_a_s0 = (a_s0_max - ambient_c) / 30.0
    h3_dev_pct = abs(r_a_s0 - r_hbm_sink_p2) / r_hbm_sink_p2 * 100.0
    h3_pass = h3_dev_pct <= 5.0
    print(f"H3: A-S0 hotspot 기준 R = (max-ambient)/P = ({a_s0_max:.2f}-{ambient_c})/30 = {r_a_s0:.4f} K/W")
    print(f"    P2 실측 {r_hbm_sink_p2} K/W 대비 편차 {h3_dev_pct:.2f}% (합격선 ±5%) -> {'유효(선형 외삽 성립)' if h3_pass else '초과(온도의존성 논의 필요)'}\n")

    # Q2
    b_s0_max = base_die_max("B", "s0_uniform")
    b_s2_max = base_die_max("B", "s2_phy_heavy")
    dT_b = b_s2_max - b_s0_max
    q2_ratio = dT_b / icepak_amp_a
    suppression_pct = (1 - q2_ratio) * 100
    print(f"Q2: dT_hotspot(B, 30W) = {b_s2_max:.2f} - {b_s0_max:.2f} = {dT_b:.3f}K")
    print(f"    A 대비 비율 {q2_ratio:.4f} -> 하단 냉각이 증폭을 {suppression_pct:.1f}% 억제 (관찰 질문, 가설 아님)\n")

    # ---- 최종 CSV 출력 ----
    with open(OUT_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["항목", "판정/값", "근거수치"])
        writer.writerow(["G4_A계열_평균오차%", f"{a_mean:.4f}", f"합격선10% -> {'PASS' if a_pass else 'FAIL'}"])
        writer.writerow(["G4_A계열_진폭비율", f"{amp_ratio_a:.4f}", f"합격선[0.9,1.1] -> {'PASS' if amp_gate_a else 'FAIL'}"])
        writer.writerow(["G4_A계열_종합", g4_a_verdict, f"Icepak진폭{icepak_amp_a:.3f}K vs 3DICE진폭{threedice_amp_a:.3f}K"])
        writer.writerow(["G4_B계열_참고_평균오차%", f"{b_mean:.4f}", "판정제외(R1완화)-3D-ICE bottomsink 최초실측 대폭괴리"])
        writer.writerow(["H1_판정", h1_verdict, f"dT={icepak_amp_a:.3f}K, 비율{ratio:.4f}x, 밴드[{band_lo:.2f},{band_hi:.2f}]K"])
        writer.writerow(["H2_판정", "PASS" if h2_pass else "FAIL", f"DRAM온도 최대편차{max_dev_pct:.6f}%(기준<0.01%)"])
        writer.writerow(["H3_판정", "유효" if h3_pass else "초과", f"R={r_a_s0:.4f}K/W vs P2실측{r_hbm_sink_p2}K/W, 편차{h3_dev_pct:.2f}%(기준±5%)"])
        writer.writerow(["Q2_관찰", f"억제율{suppression_pct:.1f}%", f"dT_B={dT_b:.3f}K vs dT_A={icepak_amp_a:.3f}K, 비율{q2_ratio:.4f}"])
    print(f"[최종 결과] {OUT_CSV}")


if __name__ == "__main__":
    main()
