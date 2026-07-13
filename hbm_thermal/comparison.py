"""Icepak vs 3D-ICE 결과 비교 순수 로직 모듈.

두 솔버(Icepak FEM, 3D-ICE 컴팩트 RC망)의 die별 온도 결과를 비교해
절대차·백분율차를 계산하고, vault research/04-validation-anchors.md의
합격선(실측/타 툴 대비 평균 오차 ≤10%)으로 PASS/FAIL을 판정한다.
"""
from __future__ import annotations

from dataclasses import dataclass

# 3D-ICE 공인 교차검증 합격선(EPFL, 실측 대비 평균 오차 <10%).
# 근거: vault research/04-validation-anchors.md §3.
CROSS_VALIDATION_PASS_THRESHOLD_PCT = 10.0


@dataclass
class DieComparisonRow:
    """die 하나의 Icepak vs 3D-ICE 비교 결과."""

    die: str
    icepak_avg_c: float
    icepak_max_c: float
    threedice_avg_c: float
    diff_c: float
    diff_pct: float


def compare_die_temperatures(
    icepak_results: dict[str, tuple[float, float]],
    threedice_results: dict[str, float],
) -> list[DieComparisonRow]:
    """die별 Icepak(avg, max)와 3D-ICE(avg) 결과를 비교한다.

    3D-ICE는 layer-cake 균질화 모델에서 die별 floorplan이 단일 사각형
    영역(균일 전력)이므로 avg==max가 되어 max를 별도로 비교할 필요가 없다
    (avg만 비교 — 실측 확인, docs/03-cross-validation-3d-ice.md 참고).
    Icepak의 avg가 3D-ICE의(사실상 유일한) 온도값과 비교 대상이 된다.

    Args:
        icepak_results: die명 -> (avg_c, max_c).
        threedice_results: die명 -> avg_c (3D-ICE, °C 단위로 이미 변환됨).

    Returns:
        die명 순서를 icepak_results 순서대로 유지한 비교 행 목록.

    Raises:
        KeyError: threedice_results에 icepak_results의 die가 없는 경우.
    """
    rows = []
    for die, (icepak_avg, icepak_max) in icepak_results.items():
        if die not in threedice_results:
            raise KeyError(f"3D-ICE 결과에 die {die!r}가 없습니다.")
        threedice_avg = threedice_results[die]
        diff_c = threedice_avg - icepak_avg
        diff_pct = abs(diff_c) / icepak_avg * 100.0
        rows.append(
            DieComparisonRow(
                die=die,
                icepak_avg_c=icepak_avg,
                icepak_max_c=icepak_max,
                threedice_avg_c=threedice_avg,
                diff_c=diff_c,
                diff_pct=diff_pct,
            )
        )
    return rows


def mean_absolute_pct_diff(rows: list[DieComparisonRow]) -> float:
    """비교 행 목록의 평균 절대 백분율 오차를 계산한다."""
    if not rows:
        raise ValueError("빈 비교 행 목록의 평균을 계산할 수 없습니다.")
    return sum(r.diff_pct for r in rows) / len(rows)


def judge_pass_fail(
    rows: list[DieComparisonRow], threshold_pct: float = CROSS_VALIDATION_PASS_THRESHOLD_PCT
) -> tuple[bool, float]:
    """평균 절대 백분율 오차가 합격선 이하인지 판정한다.

    Args:
        rows: compare_die_temperatures() 결과.
        threshold_pct: 합격 임계값(%). 기본 10.0 (3D-ICE 공인 기준).

    Returns:
        (판정 결과 True=PASS, 평균 절대 백분율 오차) 튜플.
    """
    mean_pct = mean_absolute_pct_diff(rows)
    return mean_pct <= threshold_pct, mean_pct


def build_comparison_csv_rows(rows: list[DieComparisonRow]) -> list[dict]:
    """비교 행 목록을 CSV DictWriter에 바로 넘길 수 있는 dict 행 목록으로 변환한다."""
    return [
        {
            "die": r.die,
            "icepak_avg_c": r.icepak_avg_c,
            "icepak_max_c": r.icepak_max_c,
            "threedice_avg_c": r.threedice_avg_c,
            "diff_c": r.diff_c,
            "diff_pct": r.diff_pct,
        }
        for r in rows
    ]


COMPARISON_CSV_FIELDNAMES = [
    "die",
    "icepak_avg_c",
    "icepak_max_c",
    "threedice_avg_c",
    "diff_c",
    "diff_pct",
]
