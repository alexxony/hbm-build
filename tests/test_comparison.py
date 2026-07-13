"""comparison.py 단위 테스트.

Icepak vs 3D-ICE 비교 순수 로직(비교 행 계산, 평균 오차, PASS/FAIL 판정,
CSV 행 구성)을 검증한다.
"""
import pytest

from hbm_thermal.comparison import (
    COMPARISON_CSV_FIELDNAMES,
    CROSS_VALIDATION_PASS_THRESHOLD_PCT,
    build_comparison_csv_rows,
    compare_die_temperatures,
    judge_pass_fail,
    mean_absolute_pct_diff,
)


class TestCompareDieTemperatures:
    def test_matching_values_zero_diff(self):
        icepak = {"base_die": (100.0, 105.0)}
        threedice = {"base_die": 100.0}
        rows = compare_die_temperatures(icepak, threedice)
        assert rows[0].diff_c == pytest.approx(0.0)
        assert rows[0].diff_pct == pytest.approx(0.0)

    def test_positive_diff_when_threedice_higher(self):
        icepak = {"base_die": (100.0, 105.0)}
        threedice = {"base_die": 101.0}
        rows = compare_die_temperatures(icepak, threedice)
        assert rows[0].diff_c == pytest.approx(1.0)
        assert rows[0].diff_pct == pytest.approx(1.0)

    def test_negative_diff_when_threedice_lower(self):
        icepak = {"base_die": (100.0, 105.0)}
        threedice = {"base_die": 95.0}
        rows = compare_die_temperatures(icepak, threedice)
        assert rows[0].diff_c == pytest.approx(-5.0)
        assert rows[0].diff_pct == pytest.approx(5.0)  # 항상 절대값

    def test_preserves_icepak_order(self):
        icepak = {"top_die": (90.0, 95.0), "base_die": (100.0, 105.0)}
        threedice = {"top_die": 90.0, "base_die": 100.0}
        rows = compare_die_temperatures(icepak, threedice)
        assert [r.die for r in rows] == ["top_die", "base_die"]

    def test_missing_die_in_threedice_raises(self):
        icepak = {"base_die": (100.0, 105.0)}
        threedice = {}
        with pytest.raises(KeyError):
            compare_die_temperatures(icepak, threedice)

    def test_row_keeps_icepak_max(self):
        icepak = {"base_die": (100.0, 122.2)}
        threedice = {"base_die": 100.0}
        rows = compare_die_temperatures(icepak, threedice)
        assert rows[0].icepak_max_c == pytest.approx(122.2)


class TestMeanAbsolutePctDiff:
    def test_single_row(self):
        icepak = {"base_die": (100.0, 105.0)}
        threedice = {"base_die": 105.0}
        rows = compare_die_temperatures(icepak, threedice)
        assert mean_absolute_pct_diff(rows) == pytest.approx(5.0)

    def test_averages_across_rows(self):
        icepak = {"a": (100.0, 100.0), "b": (200.0, 200.0)}
        threedice = {"a": 110.0, "b": 190.0}  # +10%, -5%
        rows = compare_die_temperatures(icepak, threedice)
        assert mean_absolute_pct_diff(rows) == pytest.approx((10.0 + 5.0) / 2)

    def test_empty_rows_raises(self):
        with pytest.raises(ValueError):
            mean_absolute_pct_diff([])


class TestJudgePassFail:
    def test_under_threshold_passes(self):
        icepak = {"base_die": (100.0, 100.0)}
        threedice = {"base_die": 100.02}  # 0.02% -- 우리 실측 사례와 유사
        rows = compare_die_temperatures(icepak, threedice)
        passed, mean_pct = judge_pass_fail(rows)
        assert passed is True
        assert mean_pct == pytest.approx(0.02)

    def test_over_threshold_fails(self):
        icepak = {"base_die": (100.0, 100.0)}
        threedice = {"base_die": 115.0}  # 15%
        rows = compare_die_temperatures(icepak, threedice)
        passed, mean_pct = judge_pass_fail(rows)
        assert passed is False
        assert mean_pct == pytest.approx(15.0)

    def test_exactly_at_threshold_passes(self):
        icepak = {"base_die": (100.0, 100.0)}
        threedice = {"base_die": 100.0 + CROSS_VALIDATION_PASS_THRESHOLD_PCT}
        rows = compare_die_temperatures(icepak, threedice)
        passed, _ = judge_pass_fail(rows)
        assert passed is True

    def test_custom_threshold(self):
        icepak = {"base_die": (100.0, 100.0)}
        threedice = {"base_die": 102.0}
        rows = compare_die_temperatures(icepak, threedice)
        passed, _ = judge_pass_fail(rows, threshold_pct=1.0)
        assert passed is False


class TestBuildComparisonCsvRows:
    def test_row_count_and_fields(self):
        icepak = {"base_die": (114.73, 122.22)}
        threedice = {"base_die": 114.75}
        rows = compare_die_temperatures(icepak, threedice)
        csv_rows = build_comparison_csv_rows(rows)
        assert len(csv_rows) == 1
        assert set(csv_rows[0].keys()) == set(COMPARISON_CSV_FIELDNAMES)
