"""P5 T1 avg-vs-avg 진폭비율 재구성 회귀 테스트.

scripts/p5_t1_amplitude_recheck.py의 순수 계산 함수(read_icepak_avg,
read_3dice_avg, compute_amplitude_ratio_avg_avg, judge_h_t1)를 입력 CSV
픽스처로 검증한다. 실제 결과 CSV(results/p4_icepak_scenarios/*,
results/p4_3dice_t4/*)는 건드리지 않고 tmp_path에 최소 픽스처만 생성한다.
"""
import csv
import importlib.util
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SCRIPT_PATH = REPO / "scripts" / "p5_t1_amplitude_recheck.py"

_spec = importlib.util.spec_from_file_location("p5_t1_amplitude_recheck", SCRIPT_PATH)
p5_t1 = importlib.util.module_from_spec(_spec)
sys.modules["p5_t1_amplitude_recheck"] = p5_t1
_spec.loader.exec_module(p5_t1)


def _write_icepak_csv(path: Path, die_rows: list[tuple[str, float, float]]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["die", "avg_temp_c", "max_temp_c"])
        for die, avg, mx in die_rows:
            writer.writerow([die, avg, mx])


def _write_3dice_csv(path: Path, rows: list[tuple[str, str, str, float, float]]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["series", "scenario", "die", "avg_c", "max_c"])
        for series, scenario, die, avg_c, max_c in rows:
            writer.writerow([series, scenario, die, avg_c, max_c])


class TestReadIcepakAvg:
    def test_reads_matching_die(self, tmp_path):
        path = tmp_path / "icepak.csv"
        _write_icepak_csv(path, [("base_die_phy", 183.659, 193.679), ("dram_die1", 150.0, 155.0)])
        assert p5_t1.read_icepak_avg(path) == pytest.approx(183.659)

    def test_missing_die_raises(self, tmp_path):
        path = tmp_path / "icepak.csv"
        _write_icepak_csv(path, [("dram_die1", 150.0, 155.0)])
        with pytest.raises(KeyError):
            p5_t1.read_icepak_avg(path)


class TestRead3diceAvg:
    def test_reads_matching_row(self, tmp_path):
        path = tmp_path / "3dice.csv"
        _write_3dice_csv(
            path,
            [
                ("A", "s0_uniform", "base_die_phy", 180.147, 180.147),
                ("A", "s2_phy_heavy", "base_die_phy", 212.24, 212.24),
            ],
        )
        assert p5_t1.read_3dice_avg(path, "A", "s0_uniform") == pytest.approx(180.147)
        assert p5_t1.read_3dice_avg(path, "A", "s2_phy_heavy") == pytest.approx(212.24)

    def test_missing_combo_raises(self, tmp_path):
        path = tmp_path / "3dice.csv"
        _write_3dice_csv(path, [("A", "s0_uniform", "base_die_phy", 180.147, 180.147)])
        with pytest.raises(KeyError):
            p5_t1.read_3dice_avg(path, "A", "s2_phy_heavy")


class TestComputeAmplitudeRatioAvgAvg:
    def test_real_p4_values_lands_in_gate(self):
        # 실측값(설계 문서·CSV 확인): Icepak avg S0=183.65861242320244,
        # S2=215.3178073448489 / 3D-ICE avg S0=180.147, S2=212.24
        icepak_amp, threedice_amp, ratio = p5_t1.compute_amplitude_ratio_avg_avg(
            183.65861242320244, 215.3178073448489, 180.147, 212.24
        )
        assert icepak_amp == pytest.approx(31.65920, abs=1e-3)
        assert threedice_amp == pytest.approx(32.093, abs=1e-3)
        assert ratio == pytest.approx(1.0137, abs=1e-3)

    def test_equal_amplitudes_ratio_one(self):
        icepak_amp, threedice_amp, ratio = p5_t1.compute_amplitude_ratio_avg_avg(100.0, 130.0, 50.0, 80.0)
        assert icepak_amp == pytest.approx(30.0)
        assert threedice_amp == pytest.approx(30.0)
        assert ratio == pytest.approx(1.0)


class TestJudgeHT1:
    def test_ratio_in_gate_confirms(self):
        gate_pass, verdict = p5_t1.judge_h_t1(1.0137)
        assert gate_pass is True
        assert "확증" in verdict

    def test_ratio_below_gate_refutes(self):
        gate_pass, verdict = p5_t1.judge_h_t1(0.8905)
        assert gate_pass is False
        assert "반증" in verdict

    def test_ratio_above_gate_refutes(self):
        gate_pass, verdict = p5_t1.judge_h_t1(1.15)
        assert gate_pass is False
        assert "반증" in verdict

    def test_gate_boundaries_pass(self):
        assert p5_t1.judge_h_t1(0.9)[0] is True
        assert p5_t1.judge_h_t1(1.1)[0] is True


class TestAppendCrossvalRow:
    def test_appends_without_touching_existing_rows(self, tmp_path, monkeypatch):
        csv_path = tmp_path / "p4_t4_crossval.csv"
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["항목", "판정/값", "근거수치"])
            writer.writerow(["G4_A계열_진폭비율", "0.8905", "합격선[0.9,1.1] -> FAIL"])
        monkeypatch.setattr(p5_t1, "CROSSVAL_CSV", csv_path)

        p5_t1.append_crossval_row(31.659, 32.093, 1.0137, True)

        with open(csv_path, newline="", encoding="utf-8") as f:
            rows = list(csv.reader(f))
        assert len(rows) == 3
        assert rows[1] == ["G4_A계열_진폭비율", "0.8905", "합격선[0.9,1.1] -> FAIL"]
        assert rows[2][0] == "G4_A계열_진폭비율_avg대avg_T1"
        assert rows[2][1] == "1.0137"
