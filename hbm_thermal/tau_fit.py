"""3D-ICE transient step-응답에서 1차 RC 시상수(τ)를 피팅하는 순수 로직 모듈.

배경: P2 T3(vault docs/06-p2-rc-backport-design.md T3) — T2에서 해석적으로
구한 c_hbm·r_hbm_sink의 곱(τ_analytic = R×C)을, 독립적인 3D-ICE transient
step-response 시뮬레이션에서 얻은 시상수(τ_fitted)와 대조해 2노드 lumped RC
축약이 물리적으로 타당한지 검증한다.

이 모듈은 3D-ICE 바이너리에도 pyaedt에도 의존하지 않는다 — 입력은 3D-ICE
Tflp 출력 파일(<die>_avg.txt, 이미 텍스트로 파싱 가능한 시계열)이며, 피팅은
1차 지수 모델의 선형화(로그 변환) 최소제곱으로 수행해 numpy/scipy 없이도
순수 Python으로 결정적으로 계산한다.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

_KELVIN_OFFSET = 273.15


@dataclass(frozen=True)
class StepResponseSample:
    """시간축 온도 샘플 1개."""

    time_s: float
    temperature_k: float


def parse_3dice_avg_output(text: str) -> list[StepResponseSample]:
    """3D-ICE Tflp average 출력 텍스트(<die>_avg.txt)를 시계열로 파싱한다.

    형식: "% "로 시작하는 헤더/주석 행을 건너뛰고, 나머지 행을
    "<time_s> <temp_k>" 두 컬럼(탭/공백 구분)으로 읽는다.

    Args:
        text: <die>_avg.txt 파일 전체 내용.

    Returns:
        시간 오름차순 StepResponseSample 목록.

    Raises:
        ValueError: 데이터 행이 하나도 없는 경우.
    """
    samples: list[StepResponseSample] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("%"):
            continue
        parts = stripped.split()
        if len(parts) < 2:
            continue
        samples.append(StepResponseSample(time_s=float(parts[0]), temperature_k=float(parts[1])))

    if not samples:
        raise ValueError("3D-ICE 출력에서 유효한 데이터 행을 찾지 못했습니다.")

    return samples


@dataclass(frozen=True)
class TauFitResult:
    """1차 RC 지수 피팅 결과."""

    tau_fitted_s: float
    t_initial_k: float
    t_final_k: float
    n_points_used: int
    r_squared: float


def fit_first_order_tau(
    samples: list[StepResponseSample],
    t_final_k: float | None = None,
) -> TauFitResult:
    """스텝 응답 시계열에 1차 RC 지수 모델을 피팅해 τ를 구한다.

    모델: T(t) = T_inf - (T_inf - T0) * exp(-t/τ)
    선형화: ln(T_inf - T(t)) = ln(T_inf - T0) - t/τ
    즉 y(t) = ln(T_inf - T(t))를 t에 대해 최소제곱 직선 피팅하면 기울기가
    -1/τ다. 이 방법은 2노드 lumped RC(1차 시스템)를 정확히 가정하는 대조
    시나리오에 적합하며(설계 문서 §3 리스크1 — 17레이어를 1노드로 축약),
    scipy curve_fit 없이 순수 Python으로 결정적 계산이 가능하다.

    Args:
        samples: parse_3dice_avg_output() 결과(시간 오름차순).
        t_final_k: 정상상태 온도(K, 점근값). None이면 samples의 마지막 값을
            근사 사용한다(호출측이 steady 해석 결과를 넘기면 더 정확 —
            transient 시뮬레이션이 완전 수렴하지 않았을 때의 오차를 줄임).

    Returns:
        TauFitResult(τ_fitted, 초기/최종 온도, 사용된 점 개수, 피팅 R²).

    Raises:
        ValueError: 샘플이 2개 미만이거나, T(t)가 t_final_k에 도달/초과해
            로그가 정의되지 않는 경우(0 이하 값 발생).
    """
    if len(samples) < 2:
        raise ValueError(f"피팅에는 최소 2개 샘플이 필요합니다 (입력={len(samples)}개).")

    t_inf = samples[-1].temperature_k if t_final_k is None else t_final_k
    t0 = samples[0].temperature_k

    xs: list[float] = []
    ys: list[float] = []
    for s in samples:
        residual = t_inf - s.temperature_k
        if residual <= 0.0:
            # 정상상태를 초과한 노이즈성 샘플(수치오차)은 피팅에서 제외한다 —
            # 로그가 정의되지 않으므로 스킵(전부 스킵되면 아래에서 에러).
            continue
        xs.append(s.time_s)
        ys.append(math.log(residual))

    if len(xs) < 2:
        raise ValueError(
            "로그 변환 가능한 유효 샘플이 2개 미만입니다 "
            "(t_final_k가 실제 정상상태보다 낮게 주어졌을 가능성)."
        )

    n = len(xs)
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    cov_xy = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    var_x = sum((x - mean_x) ** 2 for x in xs)

    if var_x == 0.0:
        raise ValueError("시간축 샘플에 변동이 없어 기울기를 피팅할 수 없습니다.")

    slope = cov_xy / var_x
    intercept = mean_y - slope * mean_x

    if slope >= 0.0:
        raise ValueError(
            f"피팅된 기울기가 음수가 아닙니다({slope:.6g}) — 온도가 정상상태로 "
            "수렴하지 않는 데이터입니다(τ 정의 불가)."
        )

    tau_fitted_s = -1.0 / slope

    ss_res = sum((y - (intercept + slope * x)) ** 2 for x, y in zip(xs, ys))
    ss_tot = sum((y - mean_y) ** 2 for y in ys)
    r_squared = 1.0 - (ss_res / ss_tot) if ss_tot > 0.0 else 1.0

    return TauFitResult(
        tau_fitted_s=tau_fitted_s,
        t_initial_k=t0,
        t_final_k=t_inf,
        n_points_used=n,
        r_squared=r_squared,
    )


@dataclass(frozen=True)
class TauComparisonRow:
    """τ_fitted vs τ_analytic 대조 판정 1건."""

    tau_fitted_s: float
    tau_analytic_s: float
    diff_pct: float
    r_squared: float
    verdict: str
    criterion: str


# 판정 기준(설계 문서 §"판정 기준은 설계 문서 따름" — 문서에 정량 기준이
# 명시되지 않아 T3 요구사항 원문의 1차 합격선 채택: "분포 RC계의 1차 근사라
# 수십% 오차 허용 — 자릿수 일치 + 방향 정합". 자릿수 일치를 오차 ≤50%로,
# R² 하한(피팅 자체가 1차 지수를 잘 설명하는지)을 함께 본다.
TAU_DIFF_PASS_THRESHOLD_PCT = 50.0
TAU_FIT_R_SQUARED_MIN = 0.99


def judge_tau_comparison(
    tau_fitted_s: float,
    tau_analytic_s: float,
    r_squared: float,
) -> TauComparisonRow:
    """τ_fitted를 τ_analytic(=R×C, T2 해석값)과 대조해 PASS/FAIL을 판정한다.

    판정 기준(자릿수 일치 + 방향 정합, 위 모듈 상수 TAU_DIFF_PASS_THRESHOLD_PCT
    참고): (1) 상대오차 ≤50% (분포 RC계를 2노드로 축약한 1차 근사이므로
    steady 교차검증의 10% 합격선보다 훨씬 관대하게 잡음 — 자릿수가 같은지가
    핵심), (2) 지수 피팅 R² ≥0.99(3D-ICE 데이터가 실제로 1차 지수 형태를
    따르는지 확인 — 이게 낮으면 애초에 τ 자체가 의미 없음).

    Args:
        tau_fitted_s: fit_first_order_tau() 결과의 τ.
        tau_analytic_s: T2 R×C 해석값(초).
        r_squared: fit_first_order_tau() 결과의 R².

    Returns:
        TauComparisonRow(판정 근거 문자열 포함).
    """
    diff_pct = abs(tau_fitted_s - tau_analytic_s) / tau_analytic_s * 100.0

    diff_ok = diff_pct <= TAU_DIFF_PASS_THRESHOLD_PCT
    fit_ok = r_squared >= TAU_FIT_R_SQUARED_MIN
    passed = diff_ok and fit_ok

    criterion = (
        f"|Δτ|/τ_analytic ≤ {TAU_DIFF_PASS_THRESHOLD_PCT:.0f}% "
        f"(분포 RC->2노드 lumped 축약 1차 근사 허용오차, steady 10%보다 완화) "
        f"AND R² ≥ {TAU_FIT_R_SQUARED_MIN} (1차 지수 적합도)"
    )

    if passed:
        verdict = "PASS"
    elif not fit_ok:
        verdict = f"FAIL(피팅 부적합, R²={r_squared:.6f})"
    else:
        verdict = f"FAIL(오차 {diff_pct:.2f}% > {TAU_DIFF_PASS_THRESHOLD_PCT:.0f}%)"

    return TauComparisonRow(
        tau_fitted_s=tau_fitted_s,
        tau_analytic_s=tau_analytic_s,
        diff_pct=diff_pct,
        r_squared=r_squared,
        verdict=verdict,
        criterion=criterion,
    )


def celsius_to_kelvin(temp_c: float) -> float:
    """섭씨를 켈빈으로 변환한다(export_3dice.celsius_to_kelvin과 동일 로직,
    이 모듈 단독 사용 시 순환 import를 피하기 위해 중복 정의)."""
    return temp_c + _KELVIN_OFFSET
