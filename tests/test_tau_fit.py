"""tau_fit.py 단위 테스트.

3D-ICE transient 출력 파싱 + 1차 RC 지수 τ 피팅 순수 로직을 검증한다.
3D-ICE 바이너리에 의존하지 않으므로 WSL 등 3D-ICE 없는 환경에서도 실행 가능.
"""
import math

import pytest

from hbm_thermal.tau_fit import (
    TAU_DIFF_PASS_THRESHOLD_PCT,
    TAU_FIT_R_SQUARED_MIN,
    celsius_to_kelvin,
    fit_first_order_tau,
    judge_tau_comparison,
    parse_3dice_avg_output,
)


class TestParse3diceAvgOutput:
    def test_parses_data_rows_skips_header(self):
        text = (
            "% Average temperatures for the floorplan of the die base_die\n"
            "% Time(s) \t Whole(K) \t \n"
            "0.050 \t 320.196 \t \n"
            "0.100 \t 326.024 \t \n"
        )
        samples = parse_3dice_avg_output(text)
        assert len(samples) == 2
        assert samples[0].time_s == pytest.approx(0.05)
        assert samples[0].temperature_k == pytest.approx(320.196)
        assert samples[1].time_s == pytest.approx(0.10)

    def test_skips_blank_lines(self):
        text = "% header\n\n0.0 300.0\n\n0.1 305.0\n"
        samples = parse_3dice_avg_output(text)
        assert len(samples) == 2

    def test_raises_on_no_data(self):
        with pytest.raises(ValueError):
            parse_3dice_avg_output("% only header\n% Time(s) Whole(K)\n")


class TestFitFirstOrderTau:
    def _synthetic_step_response(self, tau_s: float, t0_k: float, t_inf_k: float, n: int = 50):
        """해석적으로 정확한 1차 RC 지수 곡선을 합성해 피팅 정확도를 검증한다."""
        dt = tau_s * 5.0 / n  # 5*tau 구간을 n개 점으로 커버
        samples = []
        for i in range(0, n + 1):
            t = i * dt
            temp = t_inf_k - (t_inf_k - t0_k) * math.exp(-t / tau_s)
            samples.append((t, temp))
        return samples

    def test_recovers_known_tau_from_synthetic_curve(self):
        from hbm_thermal.tau_fit import StepResponseSample

        tau_true = 0.579
        t0, t_inf = 313.15, 387.895
        raw = self._synthetic_step_response(tau_true, t0, t_inf)
        samples = [StepResponseSample(time_s=t, temperature_k=v) for t, v in raw]

        result = fit_first_order_tau(samples, t_final_k=t_inf)

        assert result.tau_fitted_s == pytest.approx(tau_true, rel=1e-6)
        assert result.r_squared > 0.999999
        assert result.t_initial_k == pytest.approx(t0)
        assert result.t_final_k == pytest.approx(t_inf)

    def test_uses_last_sample_as_t_final_when_not_given(self):
        from hbm_thermal.tau_fit import StepResponseSample

        tau_true = 1.0
        t0, t_inf = 300.0, 350.0
        raw = self._synthetic_step_response(tau_true, t0, t_inf, n=80)
        samples = [StepResponseSample(time_s=t, temperature_k=v) for t, v in raw]

        # t_final_k 미지정 -> 마지막 샘플(5*tau 지점, t_inf에 완전히 도달하지
        # 않음 — exp(-5)=0.0067만큼 차이)을 근사 사용. 이 근사는 조기절단
        # 편향(마지막 잔차를 0으로 취급 -> 초반 잔차 상대적으로 부풀려짐 ->
        # 기울기 과소평가 -> tau 과소평가)을 구조적으로 가지므로 정확히
        # 맞지 않는 것이 기대 동작 — t_final_k를 명시로 준 위 테스트가
        # 정확도 검증 담당이고, 이 테스트는 "폴백이 작동하고 같은 방향으로
        # 합리적 범위 안에 있다"만 확인한다.
        result = fit_first_order_tau(samples)
        assert result.tau_fitted_s == pytest.approx(tau_true, rel=0.25)
        assert result.tau_fitted_s < tau_true  # 조기절단 편향 방향 확인

    def test_raises_on_fewer_than_two_samples(self):
        from hbm_thermal.tau_fit import StepResponseSample

        with pytest.raises(ValueError):
            fit_first_order_tau([StepResponseSample(time_s=0.0, temperature_k=300.0)])

    def test_raises_when_t_final_below_actual_steady_state(self):
        from hbm_thermal.tau_fit import StepResponseSample

        # t_final_k를 실제보다 낮게 주면 후반 샘플의 residual이 음수가 되어
        # 로그 정의 불가 -> 유효 샘플 부족 에러.
        samples = [
            StepResponseSample(time_s=0.0, temperature_k=300.0),
            StepResponseSample(time_s=1.0, temperature_k=340.0),
            StepResponseSample(time_s=2.0, temperature_k=349.0),
        ]
        with pytest.raises(ValueError):
            fit_first_order_tau(samples, t_final_k=310.0)


class TestJudgeTauComparison:
    def test_pass_when_within_threshold_and_good_fit(self):
        row = judge_tau_comparison(tau_fitted_s=0.60, tau_analytic_s=0.579, r_squared=0.9999)
        assert row.verdict == "PASS"
        assert row.diff_pct == pytest.approx(abs(0.60 - 0.579) / 0.579 * 100.0)

    def test_fail_when_diff_exceeds_threshold(self):
        # analytic 0.579의 200% 이상 벗어난 값
        row = judge_tau_comparison(tau_fitted_s=3.0, tau_analytic_s=0.579, r_squared=0.9999)
        assert row.verdict.startswith("FAIL")
        assert "오차" in row.verdict

    def test_fail_when_r_squared_too_low(self):
        row = judge_tau_comparison(tau_fitted_s=0.58, tau_analytic_s=0.579, r_squared=0.5)
        assert row.verdict.startswith("FAIL")
        assert "피팅 부적합" in row.verdict

    def test_criterion_string_mentions_both_thresholds(self):
        row = judge_tau_comparison(tau_fitted_s=0.58, tau_analytic_s=0.579, r_squared=0.9999)
        assert f"{TAU_DIFF_PASS_THRESHOLD_PCT:.0f}%" in row.criterion
        assert str(TAU_FIT_R_SQUARED_MIN) in row.criterion

    def test_boundary_at_exact_threshold_passes(self):
        # 정확히 50% 오차 -> <= 이므로 PASS 경계 포함
        tau_analytic = 1.0
        tau_fitted = 1.5  # |1.5-1.0|/1.0 = 50%
        row = judge_tau_comparison(tau_fitted, tau_analytic, r_squared=0.9999)
        assert row.verdict == "PASS"


class TestCelsiusToKelvin:
    def test_zero_celsius(self):
        assert celsius_to_kelvin(0.0) == pytest.approx(273.15)

    def test_forty_celsius(self):
        assert celsius_to_kelvin(40.0) == pytest.approx(313.15)
