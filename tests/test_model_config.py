"""model_config.py 단위 테스트.

Icepak 입력 스펙 변환(지오메트리/전력/재료) 순수 로직을 검증한다.
pyaedt에 의존하지 않으므로 AEDT 없는 환경(WSL)에서도 전부 실행 가능.
"""
import pytest

from hbm_thermal.homogenize import layer_stack_hbm2e, total_stack_height_um
from hbm_thermal.model_config import (
    BASE_DIE_BLOCK_NAMES,
    BASE_DIE_BLOCK_WIDTH_FRACTIONS,
    POWER_SCENARIOS,
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

    def test_stack_arg_drives_dram_die_count_4hi(self):
        # 4-Hi 스택(n_dram_dies=3) 전달 시 base_die + dram_die_1..3 + top_die = 5개 항목
        stack = layer_stack_hbm2e(n_dram_dies=3)
        power = build_power_spec(stack=stack, total_w=12.4, base_die_fraction=0.55)
        assert len(power) == 5
        assert set(power.keys()) == {"base_die", "dram_die_1", "dram_die_2", "dram_die_3", "top_die"}
        assert sum(power.values()) == pytest.approx(12.4)

    def test_stack_arg_drives_dram_die_count_12hi(self):
        stack = layer_stack_hbm2e(n_dram_dies=11)
        power = build_power_spec(stack=stack, total_w=19.6, base_die_fraction=0.55)
        assert len(power) == 13  # base_die + dram_die_1..11 + top_die
        assert sum(power.values()) == pytest.approx(19.6)

    def test_stack_arg_none_defaults_to_8hi(self):
        # 기존 동작 회귀 방지: stack 인자 없으면 8-Hi(9개 항목) 그대로.
        power = build_power_spec(total_w=16.0, base_die_fraction=0.55)
        assert len(power) == 9


class TestBuildPowerSpecBlockScenarios:
    """P3 T1: power_scenario 지정 시 base_die 블록별(PHY/TSVA/DA) 전력 배분."""

    def test_power_scenario_none_is_unchanged_legacy_behavior(self):
        # 하위 호환: power_scenario=None이면 기존 dict(base_die 단일 키)와 동일.
        legacy = build_power_spec(total_w=16.0, base_die_fraction=0.55)
        explicit_none = build_power_spec(
            total_w=16.0, base_die_fraction=0.55, power_scenario=None
        )
        assert legacy == explicit_none
        assert "base_die" in explicit_none
        for block_name in BASE_DIE_BLOCK_NAMES:
            assert block_name not in explicit_none

    def test_unknown_power_scenario_raises(self):
        with pytest.raises(ValueError):
            build_power_spec(total_w=16.0, base_die_fraction=0.55, power_scenario="bogus")

    @pytest.mark.parametrize("scenario", sorted(POWER_SCENARIOS))
    def test_block_sum_equals_base_power_and_total_preserved(self, scenario):
        # 전력 보존 불변식: 블록 합 = base_power_w, 총합 = total_w.
        total_w = 16.0
        base_die_fraction = 0.55
        power = build_power_spec(
            total_w=total_w, base_die_fraction=base_die_fraction, power_scenario=scenario
        )
        base_power_w = total_w * base_die_fraction
        block_sum = sum(power[name] for name in BASE_DIE_BLOCK_NAMES)
        assert block_sum == pytest.approx(base_power_w)
        assert sum(power.values()) == pytest.approx(total_w)
        assert "base_die" not in power

    def test_s0_uniform_matches_area_proportional_split(self):
        # S0 uniform 시나리오는 폭 비율(면적 비례)과 동일한 블록별 전력 배분이어야 한다
        # (기존 균일 배분과 물리적으로 등가라는 §1.2 회귀 게이트).
        total_w = 16.0
        base_die_fraction = 0.55
        power = build_power_spec(
            total_w=total_w, base_die_fraction=base_die_fraction, power_scenario="s0_uniform"
        )
        base_power_w = total_w * base_die_fraction
        for block_name in BASE_DIE_BLOCK_NAMES:
            expected = base_power_w * BASE_DIE_BLOCK_WIDTH_FRACTIONS[block_name]
            assert power[block_name] == pytest.approx(expected)

    def test_s1_and_s2_scenarios_favor_phy_block(self):
        # 문헌 방향성(PHY 우세) 확인: s1/s2에서 PHY 블록 전력이 TSVA/DA보다 크다.
        for scenario in ("s1_phy_moderate", "s2_phy_heavy"):
            power = build_power_spec(
                total_w=16.0, base_die_fraction=0.55, power_scenario=scenario
            )
            assert power["base_die_phy"] > power["base_die_tsva"]
            assert power["base_die_phy"] > power["base_die_da"]

    def test_dram_die_power_unaffected_by_power_scenario(self):
        # base_die 블록 분할은 DRAM/top_die 배분에 영향을 주지 않아야 한다.
        legacy = build_power_spec(total_w=16.0, base_die_fraction=0.55)
        scenario_power = build_power_spec(
            total_w=16.0, base_die_fraction=0.55, power_scenario="s1_phy_moderate"
        )
        dram_names = [f"dram_die_{i}" for i in range(1, 8)] + ["top_die"]
        for name in dram_names:
            assert scenario_power[name] == pytest.approx(legacy[name])


class TestBuildGeometrySpecBlockScenarios:
    """P3 T1: power_scenario 지정 시 base_die 지오메트리 x방향 3분할."""

    def test_power_scenario_none_is_unchanged_legacy_behavior(self):
        legacy = build_geometry_spec()
        explicit_none = build_geometry_spec(power_scenario=None)
        assert legacy == explicit_none
        names = [layer["name"] for layer in explicit_none]
        assert "base_die" in names
        for block_name in BASE_DIE_BLOCK_NAMES:
            assert block_name not in names

    def test_unknown_power_scenario_raises(self):
        with pytest.raises(ValueError):
            build_geometry_spec(power_scenario="bogus")

    @pytest.mark.parametrize("scenario", sorted(POWER_SCENARIOS))
    def test_base_die_replaced_by_three_sub_boxes(self, scenario):
        geometry = build_geometry_spec(power_scenario=scenario)
        names = [layer["name"] for layer in geometry]
        assert "base_die" not in names
        for block_name in BASE_DIE_BLOCK_NAMES:
            assert block_name in names
        # 레이어 총 개수는 base_die 1개가 3개로 늘어난 만큼 +2.
        assert len(geometry) == len(build_geometry_spec()) + 2

    @pytest.mark.parametrize("scenario", sorted(POWER_SCENARIOS))
    def test_sub_box_widths_sum_to_footprint_x(self, scenario):
        footprint_mm = (11.0, 10.0)
        geometry = build_geometry_spec(footprint_mm=footprint_mm, power_scenario=scenario)
        blocks = {layer["name"]: layer for layer in geometry if layer["name"] in BASE_DIE_BLOCK_NAMES}
        width_sum = sum(blocks[name]["size_mm"][0] for name in BASE_DIE_BLOCK_NAMES)
        assert width_sum == pytest.approx(footprint_mm[0])

    @pytest.mark.parametrize("scenario", sorted(POWER_SCENARIOS))
    def test_sub_boxes_share_same_z_slice_and_yz_dims(self, scenario):
        footprint_mm = (11.0, 10.0)
        geometry = build_geometry_spec(footprint_mm=footprint_mm, power_scenario=scenario)
        legacy_base = next(
            layer for layer in build_geometry_spec(footprint_mm=footprint_mm) if layer["name"] == "base_die"
        )
        for block_name in BASE_DIE_BLOCK_NAMES:
            block = next(layer for layer in geometry if layer["name"] == block_name)
            assert block["origin_mm"][2] == pytest.approx(legacy_base["origin_mm"][2])
            assert block["size_mm"][2] == pytest.approx(legacy_base["size_mm"][2])
            assert block["size_mm"][1] == pytest.approx(footprint_mm[1])
            assert block["material_name"] == legacy_base["material_name"]

    @pytest.mark.parametrize("scenario", sorted(POWER_SCENARIOS))
    def test_sub_boxes_are_contiguous_non_overlapping_in_x(self, scenario):
        geometry = build_geometry_spec(power_scenario=scenario)
        blocks = [layer for layer in geometry if layer["name"] in BASE_DIE_BLOCK_NAMES]
        # BASE_DIE_BLOCK_NAMES 순서(PHY, TSVA, DA)대로 x가 이어 붙는지 확인.
        blocks_by_name = {layer["name"]: layer for layer in blocks}
        ordered = [blocks_by_name[name] for name in BASE_DIE_BLOCK_NAMES]
        for i in range(1, len(ordered)):
            prev = ordered[i - 1]
            cur = ordered[i]
            prev_right_edge = prev["origin_mm"][0] + prev["size_mm"][0]
            assert cur["origin_mm"][0] == pytest.approx(prev_right_edge)

    def test_stack_z_height_unchanged_by_power_scenario(self):
        # z 스택 높이 불변: base_die 분할이 총 높이에 영향을 주지 않는다.
        # 주의: total_stack_height_mm()은 레이어별 dz를 단순 합산하므로
        # 동일 z 슬라이스를 공유하는 x분할 sub-box가 여러 개면 중복 합산된다
        # (레이어=z 스택 1개라는 기존 가정 전제) — 여기서는 실제 물리적
        # 최상단 z(마지막 레이어의 origin_mm[2] + size_mm[2])로 직접 비교한다.
        def top_z_mm(geometry):
            return max(layer["origin_mm"][2] + layer["size_mm"][2] for layer in geometry)

        legacy_top = top_z_mm(build_geometry_spec())
        scenario_top = top_z_mm(build_geometry_spec(power_scenario="s2_phy_heavy"))
        assert scenario_top == pytest.approx(legacy_top)

    def test_layers_after_base_die_still_stack_cumulatively(self):
        # base_die 분할 후에도 나머지 레이어(bump_layer 등)의 z 누적이 끊기지 않는지 확인.
        geometry = build_geometry_spec(power_scenario="s0_uniform")
        da_block = next(layer for layer in geometry if layer["name"] == "base_die_da")
        da_top_z = da_block["origin_mm"][2] + da_block["size_mm"][2]
        next_layer_index = geometry.index(da_block) + 1
        next_layer = geometry[next_layer_index]
        assert next_layer["origin_mm"][2] == pytest.approx(da_top_z, abs=1e-9)
