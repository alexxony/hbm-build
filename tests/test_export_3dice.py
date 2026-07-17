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
    """P3 T5 — power_scenario 관통(base_die 단일 die + 다중 floorplan element) 계약 테스트.

    docs/07-p3-power-map-design.md §2 T5. **T3의 원래 계약은 오매핑이었다**:
    base_die_phy/tsva/da 3개 geometry sub-box를 3D-ICE die 3개로 그대로
    매핑했는데, 이 함수는 각 die에 build_floorplan_file()(항상 position 0,0 /
    전체 footprint)을 발급해 xy 분할이 z축(수직) 적층으로 둔갑했다(base_die
    60um 1층이 60um die 3개 적층 180um가 됨 — 실측 확인, T3 커밋의
    build_stack_description(power_scenario=...) 반환 dict가 base_die_phy.flp
    등 3개 파일 모두 전체 footprint였음).

    정정본 계약: base_die는 항상 **단일 die**(None 경로와 동일 60um 1층)로
    유지되고, 그 die의 base_die.flp 하나에 블록별 named element 3개
    (phy/tsva/da)가 올바른 x-offset/폭으로 기입된다(3D-ICE .flp 문법이 파일
    하나에 다중 element를 허용함을 공식 예제 bin/core.flp로 실측 확인,
    bison/floorplan_parser.y IDENTIFIER 목록 문법과 일치). 온도 출력은 die
    단위 Tflp 대신 element 단위 Tflpel(die.element_id, ...)을 쓴다
    (bison/stack_description_parser.y "TFLPEL '(' IDENTIFIER '.' IDENTIFIER
    ..." 문법 실측 확인).
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
    def test_scenario_keeps_base_die_as_single_merged_die(self, scenario):
        # base_die_phy/tsva/da는 개별 .flp로 늘어나지 않는다 — base_die.flp
        # 하나로 병합된다(None 경로와 동일 die/파일 수 유지, 회귀 방지).
        files = build_stack_description(power_scenario=scenario)
        assert "base_die.flp" in files
        for name in BASE_DIE_BLOCK_NAMES:
            assert f"{name}.flp" not in files
        geometry_none = build_geometry_spec(power_scenario=None)
        # stack.stk + flp 파일 개수는 None 경로(17레이어)와 정확히 일치해야
        # 한다 — power_scenario는 base_die 내부 전력 분포에만 영향을 준다.
        assert len(files) == 1 + len(geometry_none)

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
    def test_scenario_base_die_is_single_die_with_one_source(self, scenario):
        # base_die는 항상 단일 die(60um 1층)를 유지한다 — 3D-ICE 문법 제약
        # (die당 source 정확히 1개)과 None 경로 스택 두께가 그대로 보존된다.
        files = build_stack_description(power_scenario=scenario)
        stk = files["stack.stk"]
        assert "die die_base_die :\n   source" in stk
        for name in BASE_DIE_BLOCK_NAMES:
            assert f"die die_{name} :\n   source" not in stk

    @pytest.mark.parametrize("scenario", sorted(POWER_SCENARIOS))
    def test_scenario_stack_die_count_matches_none_path(self, scenario):
        # stack: 블록의 die 참조 개수가 None 경로(17개)와 동일해야 한다 —
        # power_scenario가 스택 층수를 바꾸지 않는다(T3 오매핑 정정 핵심).
        files_none = build_stack_description(power_scenario=None)
        files_scenario = build_stack_description(power_scenario=scenario)
        stk_none = files_none["stack.stk"]
        stk_scenario = files_scenario["stack.stk"]

        def _die_ref_count(stk_text: str) -> int:
            return sum(
                1
                for line in stk_text.splitlines()
                if line.strip().startswith("die ") and "floorplan" in line
            )

        assert _die_ref_count(stk_scenario) == _die_ref_count(stk_none)

    @pytest.mark.parametrize("scenario", sorted(POWER_SCENARIOS))
    def test_scenario_base_die_flp_has_three_named_elements(self, scenario):
        # base_die.flp 하나에 phy/tsva/da 3개 named element가 있어야 한다
        # (3D-ICE 공식 예제 bin/core.flp 다중 element 문법과 동일 패턴).
        files = build_stack_description(power_scenario=scenario)
        content = files["base_die.flp"]
        for element_id in ("phy", "tsva", "da"):
            assert f"{element_id} :" in content

    @pytest.mark.parametrize("scenario", sorted(POWER_SCENARIOS))
    def test_scenario_base_die_elements_do_not_overlap_and_span_full_width(self, scenario):
        # 각 element의 position(x)/dimension(x)이 실제 블록 위치를 반영해야
        # 하며(오매핑 방지 — 전부 position 0,0에 전체 footprint를 쓰던 T3
        # 버그의 회귀 게이트), 폭 합이 footprint 전폭과 일치해야 한다.
        files = build_stack_description(power_scenario=scenario, footprint_mm=(11.0, 10.0))
        content = files["base_die.flp"]

        positions = {}
        widths = {}
        current_id = None
        for line in content.splitlines():
            stripped = line.strip()
            if stripped.endswith(":"):
                current_id = stripped.rstrip(" :")
            elif stripped.startswith("position") and current_id:
                x_str = stripped.split("position")[1].rstrip(" ;").split(",")[0]
                positions[current_id] = float(x_str)
            elif stripped.startswith("dimension") and current_id:
                x_str = stripped.split("dimension")[1].rstrip(" ;").split(",")[0]
                widths[current_id] = float(x_str)

        assert set(positions) == {"phy", "tsva", "da"}
        # 최소 하나는 x=0에서 시작해야 하고(가장 왼쪽 블록), 전 구간이
        # 겹치지 않고 전체 11000um을 채워야 한다(정렬 후 연속성 확인).
        ordered = sorted(positions, key=lambda k: positions[k])
        cursor = 0.0
        for element_id in ordered:
            assert positions[element_id] == pytest.approx(cursor)
            cursor += widths[element_id]
        assert cursor == pytest.approx(11000.0)

    @pytest.mark.parametrize("scenario", sorted(POWER_SCENARIOS))
    def test_scenario_output_block_uses_tflpel_for_base_die_blocks(self, scenario):
        # base_die는 die 단위 Tflp 대신 블록별 Tflpel을 써야 한다(문법:
        # Tflpel ( base_die.<element_id>, "path", average|maximum, final ) ;).
        files = build_stack_description(power_scenario=scenario)
        stk = files["stack.stk"]
        assert "Tflp ( base_die," not in stk
        for element_id in ("phy", "tsva", "da"):
            assert f"Tflpel ( base_die.{element_id}," in stk

    def test_s0_uniform_matches_area_fraction_power_split(self):
        # s0_uniform은 면적비(BASE_DIE_BLOCK_WIDTH_FRACTIONS) 배분과 물리적으로
        # 등가 — base_power_w * width_frac이어야 한다(회귀 게이트 근거).
        power_spec = build_power_spec(power_scenario="s0_uniform")
        files = build_stack_description(power_scenario="s0_uniform")
        base_power_w = 16.0 * 0.55
        content = files["base_die.flp"]
        element_ids = {
            "base_die_phy": "phy",
            "base_die_tsva": "tsva",
            "base_die_da": "da",
        }
        for name in BASE_DIE_BLOCK_NAMES:
            element_id = element_ids[name]
            lines = content.splitlines()
            start = next(i for i, l in enumerate(lines) if l.strip() == f"{element_id} :")
            power_line = next(l for l in lines[start:] if "power values" in l)
            written_power = float(power_line.split("power values")[1].rstrip(" ;").strip())
            expected_power = base_power_w * BASE_DIE_BLOCK_WIDTH_FRACTIONS[name]
            assert written_power == pytest.approx(power_spec[name])
            assert written_power == pytest.approx(expected_power)
