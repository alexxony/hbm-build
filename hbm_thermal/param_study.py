"""Task 5 파라미터 스터디(스택 높이/본딩 방식/냉각 BC) 순수 로직 모듈.

케이스 정의, 문헌 앵커 대비 방향 판정(정량 재현이 아니라 방향 일치 여부),
CSV 행 구성을 담당한다. pyaedt에 의존하지 않으므로 AEDT 없는 환경(WSL)에서도
전부 테스트 가능하다. 실제 AEDT 모델 빌드/해석은 scripts/param_study.py에서
이 모듈의 결과를 사용해 오케스트레이션한다.

문헌 앵커 (vault research/03-prior-art.md, PROGRESS.md §파라미터 스터디 추천 조합):
    #1 스택 높이: MDPI Electronics 2025 — 12단 이상에서 내부 열저항 급상승.
    #2 본딩 방식: AIP JAP — hybrid bonding 1.2 vs μ-bump+NCF 4.2 mm²·K/W
       (hybrid이 열저항 낮음 -> 온도 더 낮아야 방향 일치).
    #5 냉각 BC: imec IEDM 2025 — backside 냉각 추가 시 17°C 저감
       (top+bottom이 top-only보다 온도 더 낮아야 방향 일치).

전력 가정 (팀리드 지시 — die당 전력 고정):
    base_die 8.8W + DRAM die(dram_die_1..N + top_die) 장당 0.9W.
    스택 높이가 바뀌면 총 전력도 함께 바뀐다(4-Hi 12.4W / 8-Hi 16.0W / 12-Hi
    19.6W) — 문헌은 대개 총 전력을 고정한 비교이므로, 이 가정이 결론에
    미치는 영향(온도차가 다이 수 증가 자체의 열저항 효과인지, 총 발열량
    증가의 부가 효과인지 분리 안 됨)을 결과 보고 시 반드시 명시할 것.
"""
from __future__ import annotations

from dataclasses import dataclass

# 팀리드 지시: die당 전력 고정 가정.
_BASE_DIE_POWER_W = 8.8
_PER_DRAM_DIE_POWER_W = 0.9

# 본딩 방식 문헌 실측치 (AIP JAP, vault research/03-prior-art.md L71).
_UBUMP_RESISTANCE_MM2K_W = 4.2
_HYBRID_RESISTANCE_MM2K_W = 1.2

# 냉각 BC 파라미터 스터디: backside HTC 값. 상단과 동일값 사용(대칭 냉각 근사) —
# imec 문헌은 절대 HTC 수치를 특정하지 않으므로 top과 동일값이 가장 단순한
# "냉각 능력 대칭 확장" 가정. 결과 보고 시 이 가정을 명시할 것.
_BACKSIDE_HTC_W_M2K = 2500.0

CSV_FIELDNAMES = [
    "name",
    "n_dram_dies",
    "bump_thermal_resistance_mm2k_w",
    "bottom_htc_w_m2k",
    "total_power_w",
    "stack_height_mm",
    "base_die_avg_c",
    "base_die_max_c",
    "top_die_avg_c",
    "top_die_max_c",
    "solve_time_s",
    "error",
]


def _fixed_die_power(n_dram_dies: int) -> float:
    """die당 전력 고정 가정으로 총 전력을 계산한다.

    다이 총수 = base_die(1) + dram_die_1..n_dram_dies(n) + top_die(1)
             = n_dram_dies + 2. DRAM 그룹(dram_die.. + top_die)에 속하는
    다이 수는 n_dram_dies + 1.
    """
    n_dram_group_dies = n_dram_dies + 1
    return _BASE_DIE_POWER_W + n_dram_group_dies * _PER_DRAM_DIE_POWER_W


@dataclass
class ParamCase:
    """파라미터 스터디 케이스 하나의 정의."""

    name: str
    n_dram_dies: int
    bump_thermal_resistance_mm2k_w: float | None
    bottom_htc_w_m2k: float | None
    total_power_w: float


@dataclass
class ParamCaseResult:
    """케이스 하나의 해석 결과."""

    name: str
    n_dram_dies: int
    bump_thermal_resistance_mm2k_w: float | None
    bottom_htc_w_m2k: float | None
    total_power_w: float
    stack_height_mm: float | None
    base_die_avg_c: float | None
    base_die_max_c: float | None
    top_die_avg_c: float | None
    top_die_max_c: float | None
    solve_time_s: float | None
    error: str | None = None


def default_cases() -> list[ParamCase]:
    """PROGRESS.md 추천 조합(#1+#2+#5)의 기본 케이스 목록을 반환한다.

    baseline_8hi를 공통 기준선으로 두고, 각 축(스택 높이/본딩 방식/냉각 BC)을
    한 번에 하나씩만 바꾼 단일변수 비교 케이스로 구성한다(교란변수 배제).

    Returns:
        ParamCase 목록. baseline_8hi, stack_height_4hi, stack_height_12hi,
        bonding_ubump, bonding_hybrid, cooling_top_bottom.
    """
    return [
        ParamCase(
            name="baseline_8hi",
            n_dram_dies=7,
            bump_thermal_resistance_mm2k_w=None,
            bottom_htc_w_m2k=None,
            total_power_w=_fixed_die_power(7),
        ),
        ParamCase(
            name="stack_height_4hi",
            n_dram_dies=3,
            bump_thermal_resistance_mm2k_w=None,
            bottom_htc_w_m2k=None,
            total_power_w=_fixed_die_power(3),
        ),
        ParamCase(
            name="stack_height_12hi",
            n_dram_dies=11,
            bump_thermal_resistance_mm2k_w=None,
            bottom_htc_w_m2k=None,
            total_power_w=_fixed_die_power(11),
        ),
        ParamCase(
            name="bonding_ubump",
            n_dram_dies=7,
            bump_thermal_resistance_mm2k_w=_UBUMP_RESISTANCE_MM2K_W,
            bottom_htc_w_m2k=None,
            total_power_w=_fixed_die_power(7),
        ),
        ParamCase(
            name="bonding_hybrid",
            n_dram_dies=7,
            bump_thermal_resistance_mm2k_w=_HYBRID_RESISTANCE_MM2K_W,
            bottom_htc_w_m2k=None,
            total_power_w=_fixed_die_power(7),
        ),
        ParamCase(
            name="cooling_top_bottom",
            n_dram_dies=7,
            bump_thermal_resistance_mm2k_w=None,
            bottom_htc_w_m2k=_BACKSIDE_HTC_W_M2K,
            total_power_w=_fixed_die_power(7),
        ),
    ]


# 축별 문헌 방향: True면 "값이 증가하면 온도 증가가 문헌과 일치"(예: 스택
# 높이 증가 -> 열저항 증가 -> 온도 증가), False면 "값이 증가하면 온도 감소가
# 문헌과 일치"(예: 냉각 강화 -> 온도 감소). 여기서는 호출부가 이미 baseline
# 대비 comparison 값의 물리적 의미(더 나쁜 조건/더 나은 조건)를 알고
# 넘기므로, 세 축 모두 "comparison이 baseline보다 (스택높이=높아야|
# 본딩=낮아야|냉각=낮아야) CONFIRMED"로 판정한다.
_AXIS_EXPECTED_DIRECTION = {
    "stack_height": "higher",  # 12-Hi(comparison) > 8-Hi(baseline) 온도 -> CONFIRMED
    "bonding": "lower",  # hybrid(comparison) < ubump(baseline) 온도 -> CONFIRMED
    "cooling_bc": "lower",  # top+bottom(comparison) < top-only(baseline) 온도 -> CONFIRMED
}


def judge_literature_direction(
    axis: str, baseline_value: float | None, comparison_value: float | None
) -> str:
    """문헌 앵커가 예측하는 방향과 실측(시뮬레이션) 방향이 일치하는지 판정한다.

    정량적 재현(오차 %)이 아니라 방향(부호) 일치 여부만 판정한다 — Task 5는
    "12단 이상 열저항 급상승", "hybrid bonding이 더 낮은 온도", "backside
    냉각 추가 시 온도 저감" 같은 정성적 선례 재현이 목표이기 때문이다
    (vault research/03-prior-art.md 파라미터 스윕 표 참고).

    Args:
        axis: "stack_height" | "bonding" | "cooling_bc".
        baseline_value: 기준 케이스의 온도값 (예: base_die_max_c).
        comparison_value: 비교 케이스의 온도값.

    Returns:
        "CONFIRMED" | "NOT_CONFIRMED" | "NOT_EVALUATED"(둘 중 하나라도 None).

    Raises:
        ValueError: axis가 알려진 세 축 중 하나가 아닌 경우.
    """
    if axis not in _AXIS_EXPECTED_DIRECTION:
        raise ValueError(
            f"알 수 없는 axis={axis!r} (허용값: {list(_AXIS_EXPECTED_DIRECTION)})"
        )

    if baseline_value is None or comparison_value is None:
        return "NOT_EVALUATED"

    expected = _AXIS_EXPECTED_DIRECTION[axis]
    if expected == "higher":
        confirmed = comparison_value > baseline_value
    else:
        confirmed = comparison_value < baseline_value

    return "CONFIRMED" if confirmed else "NOT_CONFIRMED"


def build_case_result(
    case: ParamCase,
    base_die_avg_c: float,
    base_die_max_c: float,
    top_die_avg_c: float,
    top_die_max_c: float,
    stack_height_mm: float,
    solve_time_s: float,
) -> ParamCaseResult:
    """정상 해석 완료된 케이스의 결과 레코드를 만든다."""
    return ParamCaseResult(
        name=case.name,
        n_dram_dies=case.n_dram_dies,
        bump_thermal_resistance_mm2k_w=case.bump_thermal_resistance_mm2k_w,
        bottom_htc_w_m2k=case.bottom_htc_w_m2k,
        total_power_w=case.total_power_w,
        stack_height_mm=stack_height_mm,
        base_die_avg_c=base_die_avg_c,
        base_die_max_c=base_die_max_c,
        top_die_avg_c=top_die_avg_c,
        top_die_max_c=top_die_max_c,
        solve_time_s=solve_time_s,
        error=None,
    )


def build_error_result(case: ParamCase, error_message: str) -> ParamCaseResult:
    """케이스 실행 중 예외/발산/예산초과가 발생했을 때의 에러 레코드를 만든다."""
    return ParamCaseResult(
        name=case.name,
        n_dram_dies=case.n_dram_dies,
        bump_thermal_resistance_mm2k_w=case.bump_thermal_resistance_mm2k_w,
        bottom_htc_w_m2k=case.bottom_htc_w_m2k,
        total_power_w=case.total_power_w,
        stack_height_mm=None,
        base_die_avg_c=None,
        base_die_max_c=None,
        top_die_avg_c=None,
        top_die_max_c=None,
        solve_time_s=None,
        error=error_message,
    )


def build_csv_rows(results: list[ParamCaseResult]) -> list[dict]:
    """결과 목록을 CSV DictWriter에 바로 넘길 수 있는 dict 행 목록으로 변환한다."""
    return [
        {
            "name": r.name,
            "n_dram_dies": r.n_dram_dies,
            "bump_thermal_resistance_mm2k_w": r.bump_thermal_resistance_mm2k_w,
            "bottom_htc_w_m2k": r.bottom_htc_w_m2k,
            "total_power_w": r.total_power_w,
            "stack_height_mm": r.stack_height_mm,
            "base_die_avg_c": r.base_die_avg_c,
            "base_die_max_c": r.base_die_max_c,
            "top_die_avg_c": r.top_die_avg_c,
            "top_die_max_c": r.top_die_max_c,
            "solve_time_s": r.solve_time_s,
            "error": r.error,
        }
        for r in results
    ]
