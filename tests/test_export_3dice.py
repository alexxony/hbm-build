"""export_3dice.py 단위 테스트.

HBM 레이어 스택 -> 3D-ICE .stk/.flp 텍스트 변환 순수 로직을 검증한다.
3D-ICE 바이너리에 의존하지 않으므로 AEDT/3D-ICE 없는 환경(WSL)에서도 실행 가능.
"""
import pytest

from hbm_thermal.export_3dice import (
    build_die_blocks_and_stack,
    build_dimensions_block,
    build_floorplan_file,
    build_heat_sink_block,
    build_materials_block,
    build_output_block,
    build_solver_block,
    build_stack_description,
    celsius_to_kelvin,
    conductivity_w_mk_to_3dice,
    htc_w_m2k_to_3dice,
)
from hbm_thermal.model_config import (
    BASE_DIE_BLOCK_NAMES,
    BASE_DIE_BLOCK_WIDTH_FRACTIONS,
    POWER_SCENARIOS,
    build_geometry_spec,
    build_material_spec,
    build_power_spec,
)


class TestUnitConversions:
    def test_celsius_to_kelvin(self):
        assert celsius_to_kelvin(0.0) == pytest.approx(273.15)
        assert celsius_to_kelvin(40.0) == pytest.approx(313.15)

    def test_conductivity_conversion(self):
        # 148 W/(m.K) (Si 벌크) -> 1.48e-4 W/(um.K)
        assert conductivity_w_mk_to_3dice(148.0) == pytest.approx(1.48e-4)

    def test_htc_conversion(self):
        # 2500 W/(m^2.K) -> 2.5e-9 W/(um^2.K)
        assert htc_w_m2k_to_3dice(2500.0) == pytest.approx(2.5e-9)


class TestBuildMaterialsBlock:
    def test_all_materials_present(self):
        material_spec = build_material_spec()
        text = build_materials_block(material_spec)
        for mat_name in material_spec:
            assert f"material {mat_name} :" in text

    def test_anisotropic_three_values(self):
        material_spec = build_material_spec()
        text = build_materials_block(material_spec)
        # 각 material 블록에 "thermal conductivity kx, ky, kz ;" 형식 3개 값이 있어야 함
        for line in text.splitlines():
            if "thermal conductivity" in line:
                values_part = line.split("thermal conductivity")[1].rstrip(" ;")
                values = [v.strip() for v in values_part.split(",")]
                assert len(values) == 3

    def test_volumetric_heat_capacity_present(self):
        material_spec = build_material_spec()
        text = build_materials_block(material_spec)
        assert text.count("volumetric heat capacity") == len(material_spec)

    def test_scaled_values_match_conversion(self):
        material_spec = {
            "test_mat": {"k_x": 148.0, "k_y": 148.0, "k_z": 150.0, "rho_cp": 1.63e6}
        }
        text = build_materials_block(material_spec)
        assert "1.480000e-04" in text
        assert "1.500000e-04" in text
        # rho_cp 1.63e6 J/(m3.K) -> 1.63e-12 J/(um3.K) (T1 실값 변환 확인, placeholder 아님)
        assert "1.630000e-12" in text


class TestBuildHeatSinkBlock:
    def test_contains_htc_and_temperature(self):
        text = build_heat_sink_block(htc_w_m2k=2500.0, ambient_c=40.0)
        assert "top heat sink" in text
        assert "2.500000e-09" in text
        assert "313.1500" in text


class TestBuildDimensionsBlock:
    def test_footprint_converted_to_um(self):
        text = build_dimensions_block(footprint_mm=(11.0, 10.0))
        assert "chip length 11000.0000, width 10000.0000" in text

    def test_cell_division_default(self):
        text = build_dimensions_block(footprint_mm=(11.0, 10.0), cell_divisions=4)
        assert "cell length 2750.0000, width 2500.0000" in text

    def test_non_uniform_false(self):
        text = build_dimensions_block(footprint_mm=(11.0, 10.0))
        assert "non-uniform false ;" in text


class TestBuildDieBlocksAndStack:
    def test_die_count_matches_layers(self):
        geometry = build_geometry_spec()
        power_spec = build_power_spec()
        die_blocks, _ = build_die_blocks_and_stack(geometry, power_spec)
        assert die_blocks.count("die die_") == len(geometry)

    def test_power_bearing_layers_use_source(self):
        geometry = build_geometry_spec()
        power_spec = build_power_spec()
        die_blocks, _ = build_die_blocks_and_stack(geometry, power_spec)
        assert "die die_base_die :\n   source" in die_blocks
        assert "die die_dram_die_1 :\n   source" in die_blocks
        assert "die die_top_die :\n   source" in die_blocks

    def test_non_power_layers_also_use_source(self):
        # 3D-ICE 문법상 모든 die는 source 층 정확히 하나가 필수(순수 layer die는
        # 문법 오류 — 실측 확인). 비전력 레이어도 source로 선언하고 전력은
        # .flp에서 0으로 지정한다.
        geometry = build_geometry_spec()
        power_spec = build_power_spec()
        die_blocks, _ = build_die_blocks_and_stack(geometry, power_spec)
        assert "die die_bump_layer_1 :\n   source" in die_blocks
        assert "die die_EMC :\n   source" in die_blocks

    def test_stack_block_lists_all_layers_in_reverse_order(self):
        # 3D-ICE는 stack: 블록의 첫 die를 "최상단(히트싱크에 가장 가까움)"으로
        # 해석한다(bison 파서 확인). model_config.py의 geometry는 base_die(실제
        # 최하단)가 첫 원소이므로, stack: 블록에는 역순(EMC 먼저, base_die
        # 마지막)으로 써야 물리적으로 올바른 배치가 된다.
        geometry = build_geometry_spec()
        power_spec = build_power_spec()
        _, stack_block = build_die_blocks_and_stack(geometry, power_spec)
        lines = [l for l in stack_block.splitlines() if l.strip().startswith("die ")]
        assert len(lines) == len(geometry)
        for line, layer in zip(lines, reversed(geometry)):
            assert f"die {layer['name']} die_{layer['name']}" in line

    def test_stack_block_first_entry_is_emc_last_is_base_die(self):
        geometry = build_geometry_spec()
        power_spec = build_power_spec()
        _, stack_block = build_die_blocks_and_stack(geometry, power_spec)
        lines = [l for l in stack_block.splitlines() if l.strip().startswith("die ")]
        assert "die EMC " in lines[0]
        assert "die base_die " in lines[-1]

    def test_stack_block_floorplan_refs_power_vs_nopower(self):
        geometry = build_geometry_spec()
        power_spec = build_power_spec()
        _, stack_block = build_die_blocks_and_stack(geometry, power_spec)
        assert '"./base_die.flp"' in stack_block
        assert '"./EMC_nopower.flp"' in stack_block


class TestBuildFloorplanFile:
    def test_power_value_written(self):
        text = build_floorplan_file(footprint_mm=(11.0, 10.0), power_w=8.8)
        assert "power values 8.800000 ;" in text

    def test_none_power_defaults_to_zero(self):
        text = build_floorplan_file(footprint_mm=(11.0, 10.0), power_w=None)
        assert "power values 0.000000 ;" in text

    def test_dimension_matches_footprint_um(self):
        text = build_floorplan_file(footprint_mm=(11.0, 10.0), power_w=1.0)
        assert "dimension 11000.0000, 10000.0000 ;" in text


class TestBuildOutputBlock:
    def test_avg_and_max_per_die(self):
        text = build_output_block(["base_die", "top_die"])
        assert "base_die_avg.txt" in text
        assert "base_die_max.txt" in text
        assert "top_die_avg.txt" in text
        assert "top_die_max.txt" in text
        assert text.count("average") == 2
        assert text.count("maximum") == 2


class TestBuildSolverBlock:
    def test_steady_and_initial_temp(self):
        text = build_solver_block(ambient_c=40.0)
        assert "steady ;" in text
        assert "initial temperature 313.1500 ;" in text


class TestBuildStackDescription:
    def test_returns_stk_and_flp_files(self):
        files = build_stack_description()
        assert "stack.stk" in files
        geometry = build_geometry_spec()
        assert len(files) == 1 + len(geometry)

    def test_stk_contains_all_sections(self):
        files = build_stack_description()
        stk = files["stack.stk"]
        assert "material " in stk
        assert "top heat sink" in stk
        assert "dimensions" in stk
        assert "stack:" in stk
        assert "solver:" in stk
        assert "output:" in stk

    def test_default_matches_icepak_conditions(self):
        # Icepak 기준선(build_icepak_model.py 기본값)과 동일 조건인지 확인:
        # total 16W, base_die_fraction 0.55, ambient 40C, HTC 2500 W/m2K.
        files = build_stack_description()
        stk = files["stack.stk"]
        assert "313.1500" in stk  # 40C -> K
        assert "2.500000e-09" in stk  # 2500 W/m2K -> 3D-ICE 단위

    def test_flp_filenames_match_stack_refs(self):
        files = build_stack_description()
        stk = files["stack.stk"]
        for fname in files:
            if fname == "stack.stk":
                continue
            assert f'"./{fname}"' in stk


class TestBuildStackDescriptionPowerScenario:
    """P3 T3 — power_scenario 관통(base_die 다중 element/die 확장) 계약 테스트.

    docs/07-p3-power-map-design.md §2 T3. build_die_blocks_and_stack()는
    geometry 리스트 원소 개수에 무관하게 동작하므로(1 원소 = 1 die),
    별도 .flp 다중 element 문법 확장 없이 power_scenario가 3개 sub-die로
    자연 확장됨을 검증한다(리스크1 해소 근거).
    """

    def test_none_scenario_unchanged(self):
        # power_scenario=None(기본값)은 기존 파일 집합과 완전히 동일해야 한다.
        files_default = build_stack_description()
        files_explicit_none = build_stack_description(power_scenario=None)
        assert files_default == files_explicit_none
        assert "base_die.flp" in files_default
        assert set(files_default.keys()).isdisjoint(
            {f"{name}.flp" for name in BASE_DIE_BLOCK_NAMES}
        )

    def test_unknown_scenario_raises(self):
        with pytest.raises(ValueError):
            build_stack_description(power_scenario="no_such_scenario")

    @pytest.mark.parametrize("scenario", sorted(POWER_SCENARIOS))
    def test_scenario_replaces_base_die_with_three_blocks(self, scenario):
        files = build_stack_description(power_scenario=scenario)
        assert "base_die.flp" not in files
        for name in BASE_DIE_BLOCK_NAMES:
            assert f"{name}.flp" in files
        geometry = build_geometry_spec(power_scenario=scenario)
        # stack.stk + flp 파일 개수가 geometry 레이어 수와 정확히 일치해야 한다
        # (die 정의가 geometry 원소 개수에 1:1 대응 — 다중 .flp element 불필요).
        assert len(files) == 1 + len(geometry)

    @pytest.mark.parametrize("scenario", sorted(POWER_SCENARIOS))
    def test_scenario_preserves_total_power(self, scenario):
        # 전력 보존 불변식: 시나리오와 무관하게 총합은 total_power_w와 일치.
        files = build_stack_description(power_scenario=scenario, total_power_w=16.0)
        total = 0.0
        for fname, content in files.items():
            if fname == "stack.stk":
                continue
            for line in content.splitlines():
                if "power values" in line:
                    values_part = line.split("power values")[1].rstrip(" ;")
                    total += sum(float(v) for v in values_part.split(","))
        assert total == pytest.approx(16.0)

    @pytest.mark.parametrize("scenario", sorted(POWER_SCENARIOS))
    def test_scenario_die_blocks_each_have_one_source(self, scenario):
        # base_die가 3 die로 늘어나도 3D-ICE 문법 제약(die당 source 정확히
        # 1개)이 그대로 지켜져야 한다(export_3dice.build_die_blocks_and_stack
        # docstring 참고).
        files = build_stack_description(power_scenario=scenario)
        stk = files["stack.stk"]
        for name in BASE_DIE_BLOCK_NAMES:
            assert f"die die_{name} :\n   source" in stk

    def test_s0_uniform_stack_order_groups_base_die_blocks_at_bottom(self):
        # s0_uniform은 기존 단일 base_die 배분과 물리적으로 등가여야 하므로
        # 3 sub-die가 스택 최하단(stack: 블록에서 마지막 3개)에 그룹으로
        # 위치해야 한다 — 순서 반전 없이 다른 레이어와 동일한 규칙 적용.
        files = build_stack_description(power_scenario="s0_uniform")
        stk = files["stack.stk"]
        lines = [
            l.strip() for l in stk.splitlines() if l.strip().startswith("die ")
        ]
        # 최상단 die 목록(die_ 정의부 아닌 stack 참조부) 중 마지막 3개.
        stack_refs = [l for l in lines if " die_" in l and "floorplan" in l]
        last_three_names = {ref.split()[1] for ref in stack_refs[-3:]}
        assert last_three_names == set(BASE_DIE_BLOCK_NAMES)

    def test_s0_uniform_matches_area_fraction_power_split(self):
        # s0_uniform은 면적비(BASE_DIE_BLOCK_WIDTH_FRACTIONS) 배분과 물리적으로
        # 등가 — base_power_w * width_frac이어야 한다(회귀 게이트 근거).
        power_spec = build_power_spec(power_scenario="s0_uniform")
        files = build_stack_description(power_scenario="s0_uniform")
        base_power_w = 16.0 * 0.55
        for name in BASE_DIE_BLOCK_NAMES:
            content = files[f"{name}.flp"]
            line = next(l for l in content.splitlines() if "power values" in l)
            written_power = float(line.split("power values")[1].rstrip(" ;").strip())
            expected_power = base_power_w * BASE_DIE_BLOCK_WIDTH_FRACTIONS[name]
            assert written_power == pytest.approx(power_spec[name])
            assert written_power == pytest.approx(expected_power)
