"""convergence.py 단위 테스트.

mesh convergence 스터디의 순수 로직(레벨 파싱, 512K 가드, 발산 가드,
수렴 판정, CSV 행 구성)을 검증한다. pyaedt에 의존하지 않으므로
AEDT 없는 환경(WSL)에서도 전부 실행 가능.
"""
import pytest

from hbm_thermal.convergence import (
    CSV_FIELDNAMES,
    ConvergenceLevelResult,
    build_csv_rows,
    check_divergence,
    check_mesh_budget,
    compute_convergence_flags,
    parse_levels,
)


class TestParseLevels:
    def test_parses_comma_separated_ints(self):
        assert parse_levels("1,2,3") == [1, 2, 3]

    def test_parses_single_level(self):
        assert parse_levels("4") == [4]

    def test_strips_whitespace(self):
        assert parse_levels(" 1, 2 ,3 ") == [1, 2, 3]

    def test_none_returns_default_range(self):
        assert parse_levels(None) == [1, 2, 3, 4, 5]

    def test_empty_string_raises(self):
        with pytest.raises(ValueError):
            parse_levels("")

    def test_non_integer_raises(self):
        with pytest.raises(ValueError):
            parse_levels("1,a,3")

    def test_out_of_range_raises(self):
        with pytest.raises(ValueError):
            parse_levels("0,1,2")
        with pytest.raises(ValueError):
            parse_levels("1,2,6")

    def test_duplicate_levels_raises(self):
        with pytest.raises(ValueError):
            parse_levels("1,2,2,3")


class TestCheckMeshBudget:
    def test_under_budget_not_skipped(self):
        assert check_mesh_budget(511_999) is False

    def test_at_budget_not_skipped(self):
        assert check_mesh_budget(512_000) is False

    def test_over_budget_skipped(self):
        assert check_mesh_budget(512_001) is True

    def test_custom_limit(self):
        assert check_mesh_budget(100, limit=99) is True
        assert check_mesh_budget(99, limit=99) is False


class TestCheckDivergence:
    def test_below_threshold_not_diverged(self):
        assert check_divergence(122.2) is False

    def test_at_threshold_not_diverged(self):
        assert check_divergence(500.0) is False

    def test_above_threshold_diverged(self):
        assert check_divergence(500.1) is True

    def test_5000k_cap_diverged(self):
        assert check_divergence(4726.85) is True

    def test_custom_threshold(self):
        assert check_divergence(150.0, threshold=100.0) is True
        assert check_divergence(90.0, threshold=100.0) is False


class TestComputeConvergenceFlags:
    def _result(self, level, max_temp, skipped=False, diverged=False):
        return ConvergenceLevelResult(
            level=level,
            n_elements=level * 100_000,
            base_die_avg_c=max_temp - 5.0,
            base_die_max_c=max_temp,
            top_die_avg_c=max_temp - 10.0,
            top_die_max_c=max_temp - 8.0,
            solve_time_s=10.0 * level,
            skipped_over_budget=skipped,
            diverged=diverged,
            converged=False,
            change_pct=None,
        )

    def test_first_level_never_converged(self):
        results = [self._result(1, 122.2)]
        flagged = compute_convergence_flags(results)
        assert flagged[0].converged is False
        assert flagged[0].change_pct is None

    def test_large_change_not_converged(self):
        results = [self._result(1, 122.2), self._result(2, 110.0)]
        flagged = compute_convergence_flags(results)
        expected_pct = abs(110.0 - 122.2) / 122.2 * 100
        assert flagged[1].change_pct == pytest.approx(expected_pct)
        assert flagged[1].converged is False

    def test_small_change_converged(self):
        # 122.2 -> 122.5 : 변화율 ~0.245% < 1%
        results = [self._result(1, 122.2), self._result(2, 122.5)]
        flagged = compute_convergence_flags(results)
        assert flagged[1].converged is True

    def test_exactly_one_percent_converged(self):
        # 100.0 -> 101.0 : 변화율 정확히 1% (경계값, <=1%를 수렴으로 처리)
        results = [self._result(1, 100.0), self._result(2, 101.0)]
        flagged = compute_convergence_flags(results)
        assert flagged[1].converged is True

    def test_skipped_level_excluded_from_comparison_base(self):
        # 레벨2가 skip되면 레벨3은 레벨1과 비교해야 함.
        results = [
            self._result(1, 122.2),
            self._result(2, 999.0, skipped=True),
            self._result(3, 122.3),
        ]
        flagged = compute_convergence_flags(results)
        assert flagged[1].converged is False
        assert flagged[1].change_pct is None
        expected_pct = abs(122.3 - 122.2) / 122.2 * 100
        assert flagged[2].change_pct == pytest.approx(expected_pct)
        assert flagged[2].converged is True

    def test_diverged_level_excluded_from_comparison_base(self):
        results = [
            self._result(1, 122.2),
            self._result(2, 4726.85, diverged=True),
            self._result(3, 122.4),
        ]
        flagged = compute_convergence_flags(results)
        assert flagged[1].converged is False
        assert flagged[1].change_pct is None
        expected_pct = abs(122.4 - 122.2) / 122.2 * 100
        assert flagged[2].change_pct == pytest.approx(expected_pct)

    def test_skipped_level_itself_never_converged(self):
        results = [self._result(1, 122.2), self._result(2, 999.0, skipped=True)]
        flagged = compute_convergence_flags(results)
        assert flagged[1].converged is False

    def test_diverged_level_itself_never_converged(self):
        results = [self._result(1, 122.2), self._result(2, 4726.85, diverged=True)]
        flagged = compute_convergence_flags(results)
        assert flagged[1].converged is False

    def test_all_skipped_no_crash(self):
        results = [
            self._result(1, 999.0, skipped=True),
            self._result(2, 999.0, skipped=True),
        ]
        flagged = compute_convergence_flags(results)
        assert all(r.converged is False for r in flagged)
        assert all(r.change_pct is None for r in flagged)


class TestBuildCsvRows:
    def test_row_count_matches_results(self):
        results = [
            ConvergenceLevelResult(
                level=1,
                n_elements=100_000,
                base_die_avg_c=114.7,
                base_die_max_c=122.2,
                top_die_avg_c=112.7,
                top_die_max_c=118.0,
                solve_time_s=42.5,
                skipped_over_budget=False,
                diverged=False,
                converged=False,
                change_pct=None,
            )
        ]
        rows = build_csv_rows(results)
        assert len(rows) == 1

    def test_row_has_expected_fieldnames(self):
        results = [
            ConvergenceLevelResult(
                level=1,
                n_elements=100_000,
                base_die_avg_c=114.7,
                base_die_max_c=122.2,
                top_die_avg_c=112.7,
                top_die_max_c=118.0,
                solve_time_s=42.5,
                skipped_over_budget=False,
                diverged=False,
                converged=True,
                change_pct=0.5,
            )
        ]
        rows = build_csv_rows(results)
        assert set(rows[0].keys()) == set(CSV_FIELDNAMES)

    def test_skipped_row_preserves_flag(self):
        results = [
            ConvergenceLevelResult(
                level=5,
                n_elements=600_000,
                base_die_avg_c=None,
                base_die_max_c=None,
                top_die_avg_c=None,
                top_die_max_c=None,
                solve_time_s=None,
                skipped_over_budget=True,
                diverged=False,
                converged=False,
                change_pct=None,
            )
        ]
        rows = build_csv_rows(results)
        assert rows[0]["skipped_over_budget"] is True
        assert rows[0]["base_die_max_c"] is None
