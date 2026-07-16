"""rc_extract.py 단위 테스트.

HBM 스택 FEM 결과 -> 2노드 lumped RC 등가 파라미터(r_hbm_sink, c_hbm) 축약
로직을 검증한다. AEDT/pyaedt에 의존하지 않으므로 WSL에서도 전부 실행 가능.
"""
import pytest

from hbm_thermal.homogenize import layer_stack_hbm2e
from hbm_thermal.rc_extract import (
    LayerCContribution,
    RHbmSinkCase,
    build_rc_params_rows,
    compute_c_hbm,
    compute_r_hbm_sink_range,
)


class TestComputeCHbm:
    def test_single_layer_hand_calc(self):
        # 손계산: rho_cp=1e6 J/m^3K, footprint=1mm x 1mm=1e-6 m^2, thickness=100um=1e-4m
        # V = 1e-6 * 1e-4 = 1e-10 m^3 -> C = 1e6 * 1e-10 = 1e-4 J/K
        stack = [{"name": "layer1", "thickness_um": 100.0, "rho_cp": 1e6}]
        c_hbm, contributions = compute_c_hbm(stack=stack, footprint_mm=(1.0, 1.0))
        assert c_hbm == pytest.approx(1e-4, rel=1e-9)
        assert len(contributions) == 1
        assert contributions[0].name == "layer1"
        assert contributions[0].capacitance_j_k == pytest.approx(1e-4, rel=1e-9)

    def test_two_layers_sum(self):
        stack = [
            {"name": "a", "thickness_um": 100.0, "rho_cp": 1e6},
            {"name": "b", "thickness_um": 200.0, "rho_cp": 2e6},
        ]
        c_hbm, contributions = compute_c_hbm(stack=stack, footprint_mm=(1.0, 1.0))
        # a: 1e6 * (1e-6*1e-4) = 1e-4
        # b: 2e6 * (1e-6*2e-4) = 4e-4
        expected = 1e-4 + 4e-4
        assert c_hbm == pytest.approx(expected, rel=1e-9)
        assert len(contributions) == 2

    def test_default_stack_matches_layer_stack_hbm2e(self):
        # 인자 없이 호출하면 layer_stack_hbm2e() 기본(8-Hi, 17레이어)을 사용해야 함
        default_stack = layer_stack_hbm2e()
        c_hbm_default, contributions_default = compute_c_hbm()
        c_hbm_explicit, contributions_explicit = compute_c_hbm(stack=default_stack)
        assert c_hbm_default == pytest.approx(c_hbm_explicit)
        assert len(contributions_default) == len(default_stack) == 17

    def test_c_hbm_is_positive_and_reasonable_order_of_magnitude(self):
        # 8-Hi 스택 총 두께 0.66mm, footprint 11x10mm 수준이므로
        # C_hbm은 대략 1e-3~1 J/K 오더가 물리적으로 타당(과도하게 크거나
        # 작으면 단위 변환 실수를 의심해야 함).
        c_hbm, _ = compute_c_hbm()
        assert 1e-4 < c_hbm < 10.0

    def test_footprint_scales_linearly(self):
        stack = [{"name": "a", "thickness_um": 100.0, "rho_cp": 1e6}]
        c_small, _ = compute_c_hbm(stack=stack, footprint_mm=(1.0, 1.0))
        c_large, _ = compute_c_hbm(stack=stack, footprint_mm=(2.0, 1.0))
        assert c_large == pytest.approx(2 * c_small)


class TestComputeRHbmSinkRange:
    def test_hand_calc_two_cases(self):
        rows = [
            {"name": "baseline_8hi", "total_power_w": "16.0", "base_die_avg_c": "114.72897662789141"},
            {"name": "cooling_top_bottom", "total_power_w": "16.0", "base_die_avg_c": "54.86451648227201"},
        ]
        cases, r_min, r_max = compute_r_hbm_sink_range(rows, ambient_c=40.0)
        # baseline: (114.72897662789141 - 40) / 16.0
        # cooling: (54.86451648227201 - 40) / 16.0
        expected_baseline_r = (114.72897662789141 - 40.0) / 16.0
        expected_cooling_r = (54.86451648227201 - 40.0) / 16.0
        assert len(cases) == 2
        assert cases[0].case_name == "baseline_8hi"
        assert cases[0].r_k_w == pytest.approx(expected_baseline_r)
        assert cases[1].case_name == "cooling_top_bottom"
        assert cases[1].r_k_w == pytest.approx(expected_cooling_r)
        assert r_min == pytest.approx(min(expected_baseline_r, expected_cooling_r))
        assert r_max == pytest.approx(max(expected_baseline_r, expected_cooling_r))
        # cooling 케이스가 냉각이 더 강하므로 R이 더 작아야 함
        assert expected_cooling_r < expected_baseline_r

    def test_missing_case_raises_keyerror(self):
        rows = [{"name": "baseline_8hi", "total_power_w": "16.0", "base_die_avg_c": "100.0"}]
        with pytest.raises(KeyError):
            compute_r_hbm_sink_range(rows, ambient_c=40.0)

    def test_actual_param_study_csv_values(self):
        # results/param_study.csv 실측값 그대로 사용 (회귀 방지 고정값)
        rows = [
            {
                "name": "baseline_8hi",
                "total_power_w": "16.0",
                "base_die_avg_c": "114.72897662789141",
            },
            {
                "name": "cooling_top_bottom",
                "total_power_w": "16.0",
                "base_die_avg_c": "54.86451648227201",
            },
        ]
        cases, r_min, r_max = compute_r_hbm_sink_range(rows)
        assert r_min == pytest.approx(0.9290322801420006, rel=1e-6)
        assert r_max == pytest.approx(4.670561039243213, rel=1e-6)

    def test_custom_case_names_and_temperature_column(self):
        rows = [
            {"name": "x", "total_power_w": "10.0", "top_die_avg_c": "90.0"},
            {"name": "y", "total_power_w": "10.0", "top_die_avg_c": "50.0"},
        ]
        cases, r_min, r_max = compute_r_hbm_sink_range(
            rows,
            ambient_c=40.0,
            case_names=("x", "y"),
            temperature_column="top_die_avg_c",
        )
        assert r_min == pytest.approx(1.0)  # y: (50-40)/10
        assert r_max == pytest.approx(5.0)  # x: (90-40)/10


class TestBuildRcParamsRows:
    def test_produces_two_rows_with_expected_parameters(self):
        contributions = [
            LayerCContribution(name="EMC", rho_cp_j_m3k=1.71e6, volume_m3=1e-9, capacitance_j_k=1.71e-3),
            LayerCContribution(name="base_die", rho_cp_j_m3k=1.64e6, volume_m3=5e-10, capacitance_j_k=8.2e-4),
        ]
        r_cases = [
            RHbmSinkCase(case_name="baseline_8hi", delta_t_k=74.7, power_w=16.0, r_k_w=4.67),
            RHbmSinkCase(case_name="cooling_top_bottom", delta_t_k=14.9, power_w=16.0, r_k_w=0.93),
        ]
        rows = build_rc_params_rows(
            c_hbm_j_k=2.53e-3,
            c_contributions=contributions,
            r_cases=r_cases,
            r_min_k_w=0.93,
            r_max_k_w=4.67,
        )
        assert len(rows) == 2
        params = {row["parameter"] for row in rows}
        assert params == {"c_hbm", "r_hbm_sink"}

        c_row = next(row for row in rows if row["parameter"] == "c_hbm")
        assert c_row["unit"] == "J/K"
        assert c_row["value_min"] == ""
        assert c_row["value_max"] == ""
        assert "EMC" in c_row["basis_case"]

        r_row = next(row for row in rows if row["parameter"] == "r_hbm_sink")
        assert r_row["unit"] == "K/W"
        assert float(r_row["value_min"]) == pytest.approx(0.93)
        assert float(r_row["value_max"]) == pytest.approx(4.67)
        assert "baseline_8hi" in r_row["basis_case"]
        assert "cooling_top_bottom" in r_row["basis_case"]

    def test_all_fieldnames_present(self):
        contributions = [
            LayerCContribution(name="a", rho_cp_j_m3k=1.0, volume_m3=1.0, capacitance_j_k=1.0)
        ]
        r_cases = [RHbmSinkCase(case_name="c1", delta_t_k=1.0, power_w=1.0, r_k_w=1.0)]
        rows = build_rc_params_rows(1.0, contributions, r_cases, 1.0, 1.0)
        expected_fields = {"parameter", "value", "value_min", "value_max", "unit", "method", "basis_case"}
        for row in rows:
            assert set(row.keys()) == expected_fields
