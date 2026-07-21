"""rc_extract.py 단위 테스트.

HBM 스택 FEM 결과 -> 2노드 lumped RC 등가 파라미터(r_hbm_sink, c_hbm) 축약
로직을 검증한다. AEDT/pyaedt에 의존하지 않으므로 WSL에서도 전부 실행 가능.
"""
import pytest

from hbm_thermal.homogenize import layer_stack_hbm2e
from hbm_thermal.rc_extract import (
    LayerCContribution,
    RHbmSinkCase,
    build_r_hbm_sink_max_p4_row,
    build_rc_params_rows,
    compute_c_hbm,
    compute_r_hbm_sink_max_p3_scenarios,
    compute_r_hbm_sink_max_p4_scenarios,
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


class TestComputeRHbmSinkMaxP4Scenarios:
    """P5 T2b: P4(30W, A/B계열 x S0~S2) hotspot R 확장 — 기존
    compute_r_hbm_sink_max_p3_scenarios()와 동형 함수 회귀 테스트."""

    def test_hand_calc_base_die_phy_present(self):
        # base_die_phy 행이 있는 일반 케이스(S1/S2 상당)
        p4_scenarios = {
            "a_s1": {"base_die_phy": {"avg_temp_c": 202.4, "max_temp_c": 215.32683715820315}},
            "a_s2": {"base_die_phy": {"avg_temp_c": 215.3, "max_temp_c": 230.19606933593752}},
        }
        cases = compute_r_hbm_sink_max_p4_scenarios(p4_scenarios, total_power_w=30.0, ambient_c=40.0)
        assert len(cases) == 2
        # 정렬 순서(sorted): a_s1 -> a_s2
        assert cases[0].case_name == "a_s1[base_die_phy]"
        expected_r_s1 = (215.32683715820315 - 40.0) / 30.0
        assert cases[0].r_k_w == pytest.approx(expected_r_s1, rel=1e-9)
        assert cases[1].case_name == "a_s2[base_die_phy]"
        expected_r_s2 = (230.19606933593752 - 40.0) / 30.0
        assert cases[1].r_k_w == pytest.approx(expected_r_s2, rel=1e-9)

    def test_fallback_to_base_die_when_phy_missing(self):
        # S0(균일배분)처럼 base_die_phy 행이 없고 base_die만 있는 경우 폴백
        p4_scenarios = {
            "a_s0": {"base_die": {"avg_temp_c": 180.117, "max_temp_c": 194.15865478515627}},
        }
        cases = compute_r_hbm_sink_max_p4_scenarios(p4_scenarios, total_power_w=30.0, ambient_c=40.0)
        assert len(cases) == 1
        # 폴백된 die명이 케이스명에 명시돼야 함(대괄호 표기)
        assert cases[0].case_name == "a_s0[base_die]"
        expected_r = (194.15865478515627 - 40.0) / 30.0
        assert cases[0].r_k_w == pytest.approx(expected_r, rel=1e-9)

    def test_actual_p4_a_series_csv_values_anchor_a_s0_ctrl2(self):
        # results/p4_icepak_scenarios/p4_icepak_a_s0_ctrl2.csv 실측값(정본)
        # 회귀 방지 고정값 — S0은 base_die 폴백(합성 base_die 행만 존재).
        p4_scenarios = {
            "a_s0": {"base_die": {"avg_temp_c": 180.11690692335023, "max_temp_c": 194.15865478515627}},
            "a_s1": {"base_die_phy": {"avg_temp_c": 202.40879771596306, "max_temp_c": 215.32683715820315}},
            "a_s2": {"base_die_phy": {"avg_temp_c": 215.3178073448489, "max_temp_c": 230.19606933593752}},
        }
        cases = compute_r_hbm_sink_max_p4_scenarios(p4_scenarios, total_power_w=30.0, ambient_c=40.0)
        by_name = {c.case_name: c for c in cases}
        assert by_name["a_s0[base_die]"].r_k_w == pytest.approx(5.138622, abs=1e-5)
        assert by_name["a_s1[base_die_phy]"].r_k_w == pytest.approx(5.844228, abs=1e-5)
        assert by_name["a_s2[base_die_phy]"].r_k_w == pytest.approx(6.339869, abs=1e-5)

    def test_actual_p4_b_series_csv_values(self):
        # results/p4_icepak_scenarios/p4_icepak_b_{s0,s1,s2}.csv 실측값
        # 고정값 — B-S0도 base_die 폴백(균일 전력이라 base_die_phy 분리 없음).
        p4_scenarios = {
            "b_s0": {"base_die": {"avg_temp_c": 67.8709502314613, "max_temp_c": 80.97268066406252}},
            "b_s1": {"base_die_phy": {"avg_temp_c": 95.03762053436704, "max_temp_c": 105.90670166015627}},
            "b_s2": {"base_die_phy": {"avg_temp_c": 100.16903221022895, "max_temp_c": 111.9467712402344}},
        }
        cases = compute_r_hbm_sink_max_p4_scenarios(p4_scenarios, total_power_w=30.0, ambient_c=40.0)
        by_name = {c.case_name: c for c in cases}
        assert by_name["b_s0[base_die]"].r_k_w == pytest.approx(1.365756, abs=1e-5)
        assert by_name["b_s1[base_die_phy]"].r_k_w == pytest.approx(2.196890, abs=1e-5)
        assert by_name["b_s2[base_die_phy]"].r_k_w == pytest.approx(2.398226, abs=1e-5)

    def test_missing_both_die_and_fallback_raises_keyerror(self):
        # base_die_phy도 base_die도 없으면(비정상 입력) KeyError로 실패해야 함
        # — 조용히 잘못된 값을 반환하면 안 됨(음성 케이스).
        p4_scenarios = {"broken": {"dram_die_1": {"avg_temp_c": 100.0, "max_temp_c": 110.0}}}
        with pytest.raises(KeyError):
            compute_r_hbm_sink_max_p4_scenarios(p4_scenarios, total_power_w=30.0, ambient_c=40.0)

    def test_default_total_power_is_30w(self):
        # 설계 §3 T2: P4는 30W 고정. total_power_w 인자를 생략해도 30.0이어야 함.
        p4_scenarios = {
            "x": {"base_die_phy": {"avg_temp_c": 100.0, "max_temp_c": 130.0}},
        }
        cases = compute_r_hbm_sink_max_p4_scenarios(p4_scenarios, ambient_c=40.0)
        assert cases[0].power_w == pytest.approx(30.0)
        assert cases[0].r_k_w == pytest.approx((130.0 - 40.0) / 30.0)

    def test_p3_function_unchanged_still_uses_16w_default(self):
        # 기존 함수 무변경 회귀 확인(설계 §3 T2 작업1: "기존 함수는 무변경").
        p3_scenarios = {
            "s0_uniform": {"base_die": {"avg_temp_c": 180.0, "max_temp_c": 195.0}},
        }
        cases = compute_r_hbm_sink_max_p3_scenarios(p3_scenarios)
        assert cases[0].power_w == pytest.approx(16.0)


class TestBuildRHbmSinkMaxP4Row:
    def test_produces_expected_row_schema_and_range(self):
        from hbm_thermal.rc_extract import RHbmSinkMaxCase

        p4_cases = [
            RHbmSinkMaxCase(case_name="a_s0[base_die]", delta_t_k=154.159, power_w=30.0, r_k_w=5.138622),
            RHbmSinkMaxCase(case_name="a_s1[base_die_phy]", delta_t_k=175.327, power_w=30.0, r_k_w=5.844228),
            RHbmSinkMaxCase(case_name="a_s2[base_die_phy]", delta_t_k=190.196, power_w=30.0, r_k_w=6.339869),
            RHbmSinkMaxCase(case_name="b_s0[base_die]", delta_t_k=40.973, power_w=30.0, r_k_w=1.365756),
            RHbmSinkMaxCase(case_name="b_s1[base_die_phy]", delta_t_k=65.907, power_w=30.0, r_k_w=2.196890),
            RHbmSinkMaxCase(case_name="b_s2[base_die_phy]", delta_t_k=71.947, power_w=30.0, r_k_w=2.398226),
        ]
        row = build_r_hbm_sink_max_p4_row(p4_cases)
        assert row["parameter"] == "r_hbm_sink_max_p4"
        expected_fields = {"parameter", "value", "value_min", "value_max", "unit", "method", "basis_case"}
        assert set(row.keys()) == expected_fields
        assert row["unit"] == "K/W"
        # 범위는 6케이스 중 최소/최대(min=b_s0, max=a_s2)
        assert float(row["value_min"]) == pytest.approx(1.365756, abs=1e-5)
        assert float(row["value_max"]) == pytest.approx(6.339869, abs=1e-5)
        assert float(row["value"]) == pytest.approx(6.339869, abs=1e-5)
        for c in p4_cases:
            assert c.case_name in row["basis_case"]
