"""model_config.py 단위 테스트.

Icepak 입력 스펙 변환(지오메트리/전력/재료) 순수 로직을 검증한다.
pyaedt에 의존하지 않으므로 AEDT 없는 환경(WSL)에서도 전부 실행 가능.
"""
import pytest

from hbm_thermal.homogenize import layer_stack_hbm2e, total_stack_height_um
from hbm_thermal.model_config import (
    build_geometry_spec,
    build_material_spec,
    build_power_spec,
    total_stack_height_mm,
)


class TestBuildGeometrySpec:
    def test_layer_count_matches_stack(self):
        stack = layer_stack_hbm2e()
        geometry = build_geometry_spec(stack)
        assert len(geometry) == len(stack)

    def test_footprint_applied_to_all_layers(self):
        geometry = build_geometry_spec(footprint_mm=(11.0, 10.0))
        for layer in geometry:
            assert layer["size_mm"][0] == pytest.approx(11.0)
            assert layer["size_mm"][1] == pytest.approx(10.0)

    def test_z_stacking_is_cumulative_and_non_overlapping(self):
        geometry = build_geometry_spec()
        for i in range(1, len(geometry)):
            prev = geometry[i - 1]
            cur = geometry[i]
            prev_top = prev["origin_mm"][2] + prev["size_mm"][2]
            assert cur["origin_mm"][2] == pytest.approx(prev_top, abs=1e-9)

    def test_first_layer_starts_at_z_zero(self):
        geometry = build_geometry_spec()
        assert geometry[0]["origin_mm"][2] == pytest.approx(0.0)

    def test_um_to_mm_conversion(self):
        stack = layer_stack_hbm2e()
        geometry = build_geometry_spec(stack)
        # base_die thickness_um=60 -> 0.06 mm
        base = next(l for l in geometry if l["name"] == "base_die")
        assert base["size_mm"][2] == pytest.approx(0.06)

    def test_total_height_matches_homogenize_module(self):
        stack = layer_stack_hbm2e()
        geometry = build_geometry_spec(stack)
        expected_mm = total_stack_height_um(stack) * 1e-3
        assert total_stack_height_mm(geometry) == pytest.approx(expected_mm)

    def test_all_layers_have_material_name(self):
        geometry = build_geometry_spec()
        for layer in geometry:
            assert layer["material_name"]


class TestBuildMaterialSpec:
    def test_expected_material_names_present(self):
        materials = build_material_spec()
        assert set(materials.keys()) == {
            "hbm_tsv_die_mat",
            "hbm_bump_mat",
            "hbm_top_die_mat",
            "hbm_emc_mat",
        }

    def test_tsv_die_material_kz_greater_than_kxy(self):
        materials = build_material_spec()
        tsv = materials["hbm_tsv_die_mat"]
        assert tsv["k_z"] > tsv["k_x"]
        assert tsv["k_x"] == tsv["k_y"]

    def test_bump_material_anisotropic_ratio(self):
        materials = build_material_spec()
        bump = materials["hbm_bump_mat"]
        assert bump["k_z"] > bump["k_x"]

    def test_top_die_isotropic(self):
        materials = build_material_spec()
        top = materials["hbm_top_die_mat"]
        assert top["k_x"] == pytest.approx(top["k_z"])

    def test_emc_isotropic(self):
        materials = build_material_spec()
        emc = materials["hbm_emc_mat"]
        assert emc["k_x"] == pytest.approx(emc["k_z"])

    def test_all_conductivities_positive(self):
        materials = build_material_spec()
        for props in materials.values():
            assert props["k_x"] > 0
            assert props["k_y"] > 0
            assert props["k_z"] > 0


class TestBuildPowerSpec:
    def test_sums_to_total(self):
        power = build_power_spec(total_w=16.0, base_die_fraction=0.55)
        assert sum(power.values()) == pytest.approx(16.0)

    def test_base_die_fraction_applied(self):
        power = build_power_spec(total_w=16.0, base_die_fraction=0.55)
        assert power["base_die"] == pytest.approx(16.0 * 0.55)

    def test_eight_dram_group_entries_equal_share(self):
        power = build_power_spec(total_w=16.0, base_die_fraction=0.55)
        dram_names = [f"dram_die_{i}" for i in range(1, 8)] + ["top_die"]
        assert len(dram_names) == 8
        remaining = 16.0 * 0.45
        expected_each = remaining / 8
        for name in dram_names:
            assert power[name] == pytest.approx(expected_each)

    def test_total_entry_count(self):
        power = build_power_spec()
        # base_die + dram_die_1..7 + top_die = 9
        assert len(power) == 9

    def test_default_total_power(self):
        power = build_power_spec()
        assert sum(power.values()) == pytest.approx(16.0)

    def test_fraction_out_of_range_raises(self):
        with pytest.raises(ValueError):
            build_power_spec(total_w=16.0, base_die_fraction=-0.1)
        with pytest.raises(ValueError):
            build_power_spec(total_w=16.0, base_die_fraction=1.1)

    def test_fraction_boundary_values_ok(self):
        power_zero = build_power_spec(total_w=16.0, base_die_fraction=0.0)
        assert power_zero["base_die"] == pytest.approx(0.0)
        power_one = build_power_spec(total_w=16.0, base_die_fraction=1.0)
        assert power_one["base_die"] == pytest.approx(16.0)
