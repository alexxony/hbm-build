"""param_study.py 단위 테스트.

Task 5 파라미터 스터디(스택 높이/본딩 방식/냉각 BC) 순수 로직을 검증한다.
pyaedt에 의존하지 않으므로 AEDT 없는 환경(WSL)에서도 전부 실행 가능.
"""
import pytest

from hbm_thermal.param_study import (
    CSV_FIELDNAMES,
    ParamCase,
    ParamCaseResult,
    build_case_result,
    build_csv_rows,
    build_error_result,
    default_cases,
    judge_literature_direction,
)


class TestDefaultCases:
    def test_seven_cases_present(self):
        # baseline(8-Hi) + 스택높이 2(4-Hi,12-Hi) + 본딩 1(hybrid) + 냉각BC 1(top+bottom)
        # = 최소 5개 이상. 정확한 구성은 아래 개별 테스트로 확인.
        cases = default_cases()
        assert len(cases) >= 5

    def test_case_names_unique(self):
        cases = default_cases()
        names = [c.name for c in cases]
        assert len(names) == len(set(names))

    def test_baseline_case_present(self):
        cases = default_cases()
        baseline = next(c for c in cases if c.name == "baseline_8hi")
        assert baseline.n_dram_dies == 7
        assert baseline.bump_thermal_resistance_mm2k_w is None
        assert baseline.bottom_htc_w_m2k is None
        assert baseline.total_power_w == pytest.approx(16.0)

    def test_stack_height_cases_present(self):
        cases = default_cases()
        case_4hi = next(c for c in cases if c.name == "stack_height_4hi")
        case_12hi = next(c for c in cases if c.name == "stack_height_12hi")
        assert case_4hi.n_dram_dies == 3
        assert case_12hi.n_dram_dies == 11

    def test_stack_height_cases_use_fixed_per_die_power(self):
        # 팀리드 지시: die당 전력 고정 가정(base 8.8W + DRAM 장당 0.9W) 명시.
        # 4-Hi: base_die 1 + dram_die 3 + top_die 1 = 5개 다이 -> 8.8 + 4*0.9 = 12.4W
        # 12-Hi: base_die 1 + dram_die 11 + top_die 1 = 13개 다이 -> 8.8 + 12*0.9 = 19.6W
        cases = default_cases()
        case_4hi = next(c for c in cases if c.name == "stack_height_4hi")
        case_8hi = next(c for c in cases if c.name == "baseline_8hi")
        case_12hi = next(c for c in cases if c.name == "stack_height_12hi")
        assert case_4hi.total_power_w == pytest.approx(12.4)
        assert case_8hi.total_power_w == pytest.approx(16.0)
        assert case_12hi.total_power_w == pytest.approx(19.6)

    def test_bonding_case_present(self):
        cases = default_cases()
        hybrid = next(c for c in cases if c.name == "bonding_hybrid")
        assert hybrid.bump_thermal_resistance_mm2k_w == pytest.approx(1.2)
        assert hybrid.n_dram_dies == 7  # 8-Hi 기준선에서 본딩만 변경

    def test_bonding_baseline_uses_ubump_resistance_explicitly(self):
        # baseline_8hi의 기본 μ-bump 지오메트리 근사가 문헌 μ-bump 실측치(4.2)와
        # 별도 경로임을 명확히 대조하기 위한 명시적 μ-bump 케이스도 있어야 한다.
        cases = default_cases()
        ubump = next(c for c in cases if c.name == "bonding_ubump")
        assert ubump.bump_thermal_resistance_mm2k_w == pytest.approx(4.2)

    def test_cooling_bc_case_present(self):
        cases = default_cases()
        top_bottom = next(c for c in cases if c.name == "cooling_top_bottom")
        assert top_bottom.bottom_htc_w_m2k is not None
        assert top_bottom.bottom_htc_w_m2k > 0
        assert top_bottom.n_dram_dies == 7  # 8-Hi 기준선에서 냉각 BC만 변경

    def test_all_cases_have_positive_power(self):
        cases = default_cases()
        for c in cases:
            assert c.total_power_w > 0


class TestJudgeLiteratureDirection:
    def test_stack_height_higher_resistance_direction_confirmed(self):
        # MDPI: 12단 이상에서 내부 열저항 급상승 -> 12-Hi의 base_die max가
        # 8-Hi보다 높아야 방향 일치(문헌 재현). 정량 비교 아님 — 방향만.
        result = judge_literature_direction(
            axis="stack_height",
            baseline_value=100.0,
            comparison_value=120.0,
        )
        assert result == "CONFIRMED"

    def test_stack_height_direction_not_confirmed(self):
        result = judge_literature_direction(
            axis="stack_height",
            baseline_value=100.0,
            comparison_value=90.0,
        )
        assert result == "NOT_CONFIRMED"

    def test_bonding_hybrid_lower_temp_direction_confirmed(self):
        # AIP: hybrid bonding이 열저항 낮음 -> 온도 더 낮아야 방향 일치.
        result = judge_literature_direction(
            axis="bonding",
            baseline_value=100.0,
            comparison_value=95.0,
        )
        assert result == "CONFIRMED"

    def test_bonding_direction_not_confirmed(self):
        result = judge_literature_direction(
            axis="bonding",
            baseline_value=100.0,
            comparison_value=105.0,
        )
        assert result == "NOT_CONFIRMED"

    def test_cooling_top_bottom_lower_temp_direction_confirmed(self):
        # imec: backside 냉각 추가 시 17°C 저감 -> top+bottom이 더 낮아야 방향 일치.
        result = judge_literature_direction(
            axis="cooling_bc",
            baseline_value=100.0,
            comparison_value=83.0,
        )
        assert result == "CONFIRMED"

    def test_unknown_axis_raises(self):
        with pytest.raises(ValueError):
            judge_literature_direction(axis="unknown_axis", baseline_value=1.0, comparison_value=2.0)

    def test_none_values_return_not_evaluated(self):
        # 실패/스킵된 케이스(온도 None)는 판정 불가 -> NOT_EVALUATED.
        result = judge_literature_direction(
            axis="stack_height", baseline_value=None, comparison_value=120.0
        )
        assert result == "NOT_EVALUATED"
        result2 = judge_literature_direction(
            axis="stack_height", baseline_value=100.0, comparison_value=None
        )
        assert result2 == "NOT_EVALUATED"


class TestBuildCaseResult:
    def test_basic_fields_populated(self):
        case = ParamCase(
            name="test_case",
            n_dram_dies=7,
            bump_thermal_resistance_mm2k_w=None,
            bottom_htc_w_m2k=None,
            total_power_w=16.0,
        )
        result = build_case_result(
            case=case,
            base_die_avg_c=100.0,
            base_die_max_c=110.0,
            top_die_avg_c=90.0,
            top_die_max_c=95.0,
            stack_height_mm=0.66,
            solve_time_s=120.0,
        )
        assert result.name == "test_case"
        assert result.base_die_max_c == pytest.approx(110.0)
        assert result.error is None

    def test_error_result_has_none_temps(self):
        case = ParamCase(
            name="test_case",
            n_dram_dies=11,
            bump_thermal_resistance_mm2k_w=None,
            bottom_htc_w_m2k=None,
            total_power_w=19.6,
        )
        result = build_error_result(case, "512K 초과")
        assert result.base_die_max_c is None
        assert result.error == "512K 초과"


class TestBuildCsvRows:
    def test_row_count_matches_results(self):
        case = ParamCase(
            name="c1",
            n_dram_dies=7,
            bump_thermal_resistance_mm2k_w=None,
            bottom_htc_w_m2k=None,
            total_power_w=16.0,
        )
        results = [build_error_result(case, "테스트 에러")]
        rows = build_csv_rows(results)
        assert len(rows) == 1
        assert set(CSV_FIELDNAMES).issubset(rows[0].keys())

    def test_csv_fieldnames_include_core_columns(self):
        for col in ("name", "n_dram_dies", "total_power_w", "base_die_max_c", "error"):
            assert col in CSV_FIELDNAMES
