#!/usr/bin/env python3
"""Regenerate charts/linearity_deltat.svg from committed ledger CSVs.

Loads base_die_phy max_temp_c for the S0 (uniform) and S2 (PHY-heavy) power-map
scenarios at four measured power points, computes the hotspot delta-T (S2-S0)
at each, and plots it against the 16W-anchored linear expectation
(1.2175 K/W, see results/p4_report.md Section 3). No hardcoded delta-T values —
every point is re-derived from the CSVs on each run.

Run: python3 charts/make_linearity.py
Output: charts/linearity_deltat.svg (falls back to .png if kaleido SVG export fails)
"""
import csv
import os

import plotly.graph_objects as go

HERE = os.path.dirname(os.path.abspath(__file__))
RESULTS = os.path.join(HERE, "..", "results")

# (power_W, s0_csv, s2_csv)
CASES = [
    (16, "p3_icepak_scenarios/p3_icepak_s0.csv", "p3_icepak_scenarios/p3_icepak_s2.csv"),
    (20, "psweep_icepak_a_20w_s0.csv", "psweep_icepak_a_20w_s2.csv"),
    (24, "psweep_icepak_a_24w_s0.csv", "psweep_icepak_a_24w_s2.csv"),
    (30, "p4_icepak_scenarios/p4_icepak_a_s0_ctrl2.csv", "p4_icepak_scenarios/p4_icepak_a_s2.csv"),
]

# Linear trend anchored at the 16W measured endpoint (results/psweep_status.md
# "Linearity spot-check" section uses a 2-point regression slope of 1.1826 K/W;
# the headline anchor slope quoted in README/index.html is the simpler 16W-anchor
# ratio 1.2175 K/W (=19.48K/16W), used here for the reference trend line.
ANCHOR_SLOPE_KW = 1.2175  # K/W, = 19.48K / 16W


def base_die_phy_max(csv_path):
    """Return base_die_phy max_temp_c. S0 (uniform power-map) scenarios have no
    PHY/TSVA/DA sub-block split, so base_die_phy == base_die there — fall back
    to the base_die row (see results/p4_report.md Section 2.2)."""
    rows = {}
    with open(csv_path, newline="") as f:
        for row in csv.DictReader(f):
            rows[row["die"]] = float(row["max_temp_c"])
    if "base_die_phy" in rows:
        return rows["base_die_phy"]
    if "base_die" in rows:
        return rows["base_die"]
    raise ValueError(f"neither base_die_phy nor base_die found in {csv_path}")


def main():
    powers = []
    deltas = []
    for power_w, s0_rel, s2_rel in CASES:
        s0_path = os.path.join(RESULTS, s0_rel)
        s2_path = os.path.join(RESULTS, s2_rel)
        t_s0 = base_die_phy_max(s0_path)
        t_s2 = base_die_phy_max(s2_path)
        delta_t = t_s2 - t_s0
        powers.append(power_w)
        deltas.append(delta_t)
        print(f"{power_w}W: S0={t_s0:.5f}C S2={t_s2:.5f}C dT={delta_t:.4f}K")

    trend_x = [0, 32]
    trend_y = [p * ANCHOR_SLOPE_KW for p in trend_x]

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=trend_x, y=trend_y, mode="lines", name="16W-anchor linear expectation",
        line=dict(color="#b0b0b0", width=1.5, dash="dash"),
    ))
    fig.add_trace(go.Scatter(
        x=powers, y=deltas, mode="markers+text", name="Measured ΔT_hotspot (S2-S0)",
        marker=dict(color="#b8860b", size=11, symbol="circle"),
        text=[f"{d:.2f} K" for d in deltas], textposition="top center",
        textfont=dict(size=12),
    ))

    fig.update_layout(
        title=None,
        xaxis_title="Total stack power (W)",
        yaxis_title="ΔT_hotspot, S2-S0 (K)",
        font=dict(family="-apple-system, Helvetica, Arial, sans-serif", size=13, color="#1a1a1a"),
        plot_bgcolor="white",
        paper_bgcolor="white",
        width=680,
        height=420,
        margin=dict(l=60, r=24, t=20, b=50),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
        xaxis=dict(showgrid=True, gridcolor="#e2e2e2", range=[14, 32], dtick=2),
        yaxis=dict(showgrid=True, gridcolor="#e2e2e2", rangemode="tozero"),
    )

    out_svg = os.path.join(HERE, "linearity_deltat.svg")
    try:
        fig.write_image(out_svg)
        print(f"wrote {out_svg}")
    except Exception as e:
        out_png = os.path.join(HERE, "linearity_deltat.png")
        fig.write_image(out_png)
        print(f"SVG export failed ({e}); wrote fallback {out_png}")


if __name__ == "__main__":
    main()
