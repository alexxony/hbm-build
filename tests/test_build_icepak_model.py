"""build_icepak_model.py 구조 검증 테스트 (P3 T2).

이 모듈은 pyaedt import 없이 AEDT 없는 환경(WSL)에서도 전부 실행 가능해야
한다 — build_icepak_model.py 자체는 함수 내부에서만 pyaedt를 import하므로
모듈 레벨 import와 순수 로직(스펙 조립, die 이름 필터, CSV 합성)은
직접 테스트할 수 있다. 실제 AEDT 호출(create_box/assign_source/analyze 등)은
Windows+AEDT 환경에서만 검증 가능(design doc T2 게이트 (a)(b)(c) 참고).
"""
import argparse
import csv
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import build_icepak_model as bim  # noqa: E402
from hbm_thermal.model_config import (  # noqa: E402
    BASE_DIE_BLOCK_NAMES,
    BASE_DIE_BLOCK_WIDTH_FRACTIONS,
    POWER_SCENARIOS,
    build_geometry_spec,
    build_power_spec,
)


class TestCliPowerScenarioArg:
    def test_power_scenario_defaults_to_none(self):
        argv_backup = sys.argv
        try:
            sys.argv = ["build_icepak_model.py"]
            args = bim._parse_args()
        finally:
            sys.argv = argv_backup
        assert args.power_scenario is None

    @pytest.mark.parametrize("scenario", sorted(POWER_SCENARIOS))
    def test_power_scenario_accepts_each_known_key(self, scenario):
        argv_backup = sys.argv
        try:
            sys.argv = ["build_icepak_model.py", "--power-scenario", scenario]
            args = bim._parse_args()
        finally:
            sys.argv = argv_backup
        assert args.power_scenario == scenario

    def test_power_scenario_rejects_unknown_key(self):
        argv_backup = sys.argv
        try:
            sys.argv = ["build_icepak_model.py", "--power-scenario", "bogus"]
            with pytest.raises(SystemExit):
                bim._parse_args()
        finally:
            sys.argv = argv_backup


class TestCliBottomHtcArg:
    """P4 T1: --bottom-htc CLI 플래그 (기본 None=top-only, 지정 시 top+bottom)."""

    def test_bottom_htc_defaults_to_none(self):
        argv_backup = sys.argv
        try:
            sys.argv = ["build_icepak_model.py"]
            args = bim._parse_args()
        finally:
            sys.argv = argv_backup
        assert args.bottom_htc is None

    def test_bottom_htc_accepts_float_value(self):
        argv_backup = sys.argv
        try:
            sys.argv = ["build_icepak_model.py", "--bottom-htc", "2500.0"]
            args = bim._parse_args()
        finally:
            sys.argv = argv_backup
        assert args.bottom_htc == pytest.approx(2500.0)


class TestSpecAssemblyNoneModeUnchanged:
    """power_scenario=None일 때 기존 스펙(17 레이어, 9 전력키)과 완전히 동일해야 한다."""

    def test_geometry_layer_count_none(self):
        geometry = build_geometry_spec(footprint_mm=(11.0, 10.0), power_scenario=None)
        assert len(geometry) == 17
        assert not any(layer["name"] in BASE_DIE_BLOCK_NAMES for layer in geometry)
        assert any(layer["name"] == "base_die" for layer in geometry)

    def test_power_spec_key_count_none(self):
        power_spec = build_power_spec(total_w=16.0, base_die_fraction=0.55, power_scenario=None)
        assert len(power_spec) == 9
        assert "base_die" in power_spec
        assert not any(name in BASE_DIE_BLOCK_NAMES for name in power_spec)


class TestSpecAssemblyScenarioMode:
    """power_scenario 지정 시 base_die가 3 sub-box + 3 전력키로 확장된다."""

    @pytest.mark.parametrize("scenario", sorted(POWER_SCENARIOS))
    def test_geometry_layer_count_scenario(self, scenario):
        geometry = build_geometry_spec(footprint_mm=(11.0, 10.0), power_scenario=scenario)
        # 17(None) - 1(base_die 단일) + 3(sub-box) = 19.
        assert len(geometry) == 19
        names = [layer["name"] for layer in geometry]
        assert "base_die" not in names
        for block_name in BASE_DIE_BLOCK_NAMES:
            assert block_name in names

    @pytest.mark.parametrize("scenario", sorted(POWER_SCENARIOS))
    def test_power_spec_key_count_scenario(self, scenario):
        power_spec = build_power_spec(
            total_w=16.0, base_die_fraction=0.55, power_scenario=scenario
        )
        # 9(None) - 1(base_die) + 3(블록) = 11.
        assert len(power_spec) == 11
        assert "base_die" not in power_spec
        for block_name in BASE_DIE_BLOCK_NAMES:
            assert block_name in power_spec


class TestDieLayerNameFilter:
    """build_icepak_model()의 die_layer_names 필터가 None/scenario 양쪽에서
    올바른 오브젝트 이름 집합을 골라내는지 검증 (base_die/base_die_phy 등
    'base_die'로 시작하는 이름 전부 + dram_die/top_die)."""

    def _filter(self, stack_geometry):
        return [
            layer["name"]
            for layer in stack_geometry
            if layer["name"].startswith(("base_die", "dram_die", "top_die"))
        ]

    def test_none_mode_includes_single_base_die(self):
        geometry = build_geometry_spec(power_scenario=None)
        names = self._filter(geometry)
        assert "base_die" in names
        assert not any(n in BASE_DIE_BLOCK_NAMES for n in names)
        # bump_layer/EMC 등은 die가 아니므로 제외되어야 한다.
        assert not any(n.startswith("bump_layer") for n in names)
        assert "EMC" not in names

    @pytest.mark.parametrize("scenario", sorted(POWER_SCENARIOS))
    def test_scenario_mode_includes_all_three_blocks(self, scenario):
        geometry = build_geometry_spec(power_scenario=scenario)
        names = self._filter(geometry)
        assert "base_die" not in names
        for block_name in BASE_DIE_BLOCK_NAMES:
            assert block_name in names


class _FakePost:
    """ipk.post.get_scalar_field_value()를 흉내내는 스텁 — 미리 지정한
    (die 이름, avg/max) 값을 그대로 돌려준다. 실제 pyaedt 없이 CSV 합성
    로직만 검증하기 위함."""

    def __init__(self, temps_by_name: dict[str, dict[str, float]]):
        self._temps = temps_by_name

    def get_scalar_field_value(self, quantity, scalar_function, object_name):
        assert quantity == "Temp"
        key = "avg_temp_c" if scalar_function == "Mean" else "max_temp_c"
        return self._temps[object_name][key]


class _FakeIpk:
    def __init__(self, temps_by_name):
        self.post = _FakePost(temps_by_name)


class TestExportDieTemperaturesCompositeRow:
    def test_none_mode_no_composite_row(self, tmp_path):
        temps = {
            "base_die": {"avg_temp_c": 90.0, "max_temp_c": 95.0},
            "dram_die_1": {"avg_temp_c": 80.0, "max_temp_c": 85.0},
        }
        ipk = _FakeIpk(temps)
        out_csv = tmp_path / "out.csv"
        bim._export_die_temperatures(
            ipk, list(temps.keys()), str(out_csv), base_die_block_width_fractions=None
        )
        rows = list(csv.DictReader(open(out_csv)))
        assert len(rows) == 2
        assert {r["die"] for r in rows} == {"base_die", "dram_die_1"}

    def test_scenario_mode_adds_area_weighted_composite_row(self, tmp_path):
        # PHY:TSVA:DA = 0.20:0.65:0.15 폭 비율. avg는 폭 가중평균, max는 3블록 중 최댓값.
        temps = {
            "base_die_phy": {"avg_temp_c": 100.0, "max_temp_c": 110.0},
            "base_die_tsva": {"avg_temp_c": 90.0, "max_temp_c": 95.0},
            "base_die_da": {"avg_temp_c": 80.0, "max_temp_c": 85.0},
            "dram_die_1": {"avg_temp_c": 70.0, "max_temp_c": 75.0},
        }
        ipk = _FakeIpk(temps)
        out_csv = tmp_path / "out.csv"
        bim._export_die_temperatures(
            ipk,
            list(temps.keys()),
            str(out_csv),
            base_die_block_width_fractions=BASE_DIE_BLOCK_WIDTH_FRACTIONS,
        )
        rows = {r["die"]: r for r in csv.DictReader(open(out_csv))}
        assert set(rows) == {
            "base_die_phy",
            "base_die_tsva",
            "base_die_da",
            "dram_die_1",
            "base_die",
        }
        expected_avg = 100.0 * 0.20 + 90.0 * 0.65 + 80.0 * 0.15
        assert float(rows["base_die"]["avg_temp_c"]) == pytest.approx(expected_avg)
        assert float(rows["base_die"]["max_temp_c"]) == pytest.approx(110.0)
