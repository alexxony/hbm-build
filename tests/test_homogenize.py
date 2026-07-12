"""homogenize.py 단위 테스트.

혼합법칙(수직 k_z), Hasselman-Johnson(면내 k_xy), HBM2E 8-Hi 레이어 스택
생성 함수를 검증한다.
"""
import math

import pytest

from hbm_thermal.homogenize import (
    k_z_mixing,
    k_xy_hasselman_johnson,
    layer_stack_hbm2e,
    total_stack_height_um,
)
from hbm_thermal.materials import K_CU, K_SI


class TestKZMixing:
    def test_known_hand_calc_value(self):
        # f={Cu:0.01, Si:0.99} -> 0.01*385 + 0.99*148 = 150.37
        fractions = {"Cu": 0.01, "Si": 0.99}
        k_values = {"Cu": 385.0, "Si": 148.0}
        result = k_z_mixing(fractions, k_values)
        assert result == pytest.approx(150.37, abs=1e-9)

    def test_single_material_returns_its_k(self):
        fractions = {"Si": 1.0}
        k_values = {"Si": 148.0}
        assert k_z_mixing(fractions, k_values) == pytest.approx(148.0)

    def test_fractions_sum_not_one_raises(self):
        fractions = {"Cu": 0.5, "Si": 0.6}  # 합 1.1
        k_values = {"Cu": 385.0, "Si": 148.0}
        with pytest.raises(ValueError):
            k_z_mixing(fractions, k_values)

    def test_fractions_sum_within_tolerance_ok(self):
        # 1 ± 1e-6 이내는 허용
        fractions = {"Cu": 0.5, "Si": 0.5 + 5e-7}
        k_values = {"Cu": 385.0, "Si": 148.0}
        # 예외 없이 계산되어야 함
        result = k_z_mixing(fractions, k_values)
        assert result > 0


class TestHasselmanJohnson:
    def test_zero_fraction_returns_matrix_k(self):
        result = k_xy_hasselman_johnson(k_matrix=148.0, k_inclusion=385.0, volume_fraction=0.0)
        assert result == pytest.approx(148.0)

    def test_monotonic_increase_with_higher_conductivity_inclusion(self):
        km, ki = 148.0, 385.0
        k_low = k_xy_hasselman_johnson(km, ki, 0.05)
        k_high = k_xy_hasselman_johnson(km, ki, 0.3)
        assert km < k_low < k_high

    def test_monotonic_decrease_with_lower_conductivity_inclusion(self):
        # 개재물 전도율이 매트릭스보다 낮으면 f 증가시 k_eff 감소
        km, ki = 50.0, 0.5
        k_low = k_xy_hasselman_johnson(km, ki, 0.05)
        k_high = k_xy_hasselman_johnson(km, ki, 0.3)
        assert k_high < k_low < km

    def test_symmetry_sanity_equal_conductivities(self):
        # k_matrix == k_inclusion이면 f와 무관하게 결과는 그 값과 같아야 함
        result = k_xy_hasselman_johnson(k_matrix=100.0, k_inclusion=100.0, volume_fraction=0.4)
        assert result == pytest.approx(100.0)

    def test_fraction_out_of_range_raises(self):
        with pytest.raises(ValueError):
            k_xy_hasselman_johnson(148.0, 385.0, -0.1)
        with pytest.raises(ValueError):
            k_xy_hasselman_johnson(148.0, 385.0, 0.91)

    def test_fraction_boundary_values_ok(self):
        k_xy_hasselman_johnson(148.0, 385.0, 0.0)
        k_xy_hasselman_johnson(148.0, 385.0, 0.9)


class TestLayerStackHbm2e:
    def test_layer_count(self):
        # 1(base) + 7*2(bump+die) + 1(top) + 1(EMC) = 17
        layers = layer_stack_hbm2e()
        assert len(layers) == 17

    def test_all_conductivities_positive(self):
        layers = layer_stack_hbm2e()
        for layer in layers:
            assert layer["k_xy"] > 0
            assert layer["k_z"] > 0

    def test_tsv_die_layers_kz_greater_than_kxy(self):
        # Cu가 수직으로 관통하므로 k_z가 k_xy보다 커야 함 (base_die, dram_die)
        layers = layer_stack_hbm2e()
        tsv_layers = [
            l for l in layers if l["name"] in ("base_die",) or l["name"].startswith("dram_die")
        ]
        assert len(tsv_layers) == 8  # base_die 1 + dram_die 7
        for layer in tsv_layers:
            assert layer["k_z"] > layer["k_xy"]

    def test_bump_layers_kz_below_rough_bound(self):
        # underfill 지배 확인용 합리 범위 (스펙: k_z < 10)
        layers = layer_stack_hbm2e()
        bump_layers = [l for l in layers if l["name"].startswith("bump_layer")]
        assert len(bump_layers) == 7
        for layer in bump_layers:
            assert layer["k_z"] < 10

    def test_top_die_has_no_tsv_and_uses_bulk_si(self):
        layers = layer_stack_hbm2e()
        top = next(l for l in layers if l["name"] == "top_die")
        assert top["k_xy"] == pytest.approx(K_SI)
        assert top["k_z"] == pytest.approx(K_SI)

    def test_total_stack_height_matches_sum(self):
        layers = layer_stack_hbm2e()
        expected = sum(l["thickness_um"] for l in layers)
        assert total_stack_height_um(layers) == pytest.approx(expected)

    def test_total_stack_height_reasonable_range(self):
        # base 60 + 7*(bump~20+die45) + top(die 45?) ... EMC 100 대략 범위 확인
        layers = layer_stack_hbm2e()
        height = total_stack_height_um(layers)
        assert 400 < height < 900
