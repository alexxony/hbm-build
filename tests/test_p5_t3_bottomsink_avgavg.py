"""P5 T3 B계열 avg-vs-avg 진폭비율 재구성 회귀 테스트.

scripts/p5_t3_bottomsink_avgavg.py의 순수 계산 함수(read_icepak_avg,
read_icepak_b_s0_anchor, read_3dice_avg, compute_amplitude_ratio_avg_avg,
judge_amplitude_gate, classify_verdict, append_crossval_row)를 입력 CSV
픽스처로 검증한다. 실제 결과 CSV(results/p4_icepak_scenarios/*,
results/p4_3dice_t4/*, results/p4_t4_crossval.csv)는 건드리지 않고
tmp_path에 최소 픽스처만 생성한다.
"""
import csv
import importlib.util
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SCRIPT_PATH = REPO / "scripts" / "p5_t3_bottomsink_avgavg.py"

_spec = importlib.util.spec_from_file_location("p5_t3_bottomsink_avgavg", SCRIPT_PATH)
p5_t3 = importlib.util.module_from_spec(_spec)
sys.modules["p5_t3_bottomsink_avgavg"] = p5_t3
_spec.loader.exec_module(p5_t3)


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
        _write_icepak_csv(path, [("base_die_phy", 100.169, 111.947), ("dram_die1", 84.6, 112.6)])
        assert p5_t3.read_icepak_avg(path, "base_die_phy") == pytest.approx(100.169)

    def test_missing_die_raises(self, tmp_path):
        path = tmp_path / "icepak.csv"
        _write_icepak_csv(path, [("dram_die1", 84.6, 112.6)])
        with pytest.raises(KeyError):
            p5_t3.read_icepak_avg(path, "base_die_phy")


class TestReadIcepakBS0Anchor:
    def test_falls_back_to_base_die_when_phy_missing(self, tmp_path):
        """B-S0 실제 구조: base_die_phy 없음, base_die만 존재(균일 시나리오)."""
        path = tmp_path / "icepak_b_s0.csv"
        _write_icepak_csv(path, [("base_die", 67.871, 80.973), ("dram_die1", 68.05, 82.09)])
        avg, die_used = p5_t3.read_icepak_b_s0_anchor(path)
        assert avg == pytest.approx(67.871)
        assert die_used == "base_die"

    def test_prefers_base_die_phy_when_present(self, tmp_path):
        path = tmp_path / "icepak_hypothetical.csv"
        _write_icepak_csv(path, [("base_die_phy", 90.0, 100.0), ("base_die", 67.871, 80.973)])
        avg, die_used = p5_t3.read_icepak_b_s0_anchor(path)
        assert avg == pytest.approx(90.0)
        assert die_used == "base_die_phy"

    def test_raises_when_neither_present(self, tmp_path):
        path = tmp_path / "icepak_broken.csv"
        _write_icepak_csv(path, [("dram_die1", 68.05, 82.09)])
        with pytest.raises(KeyError):
            p5_t3.read_icepak_b_s0_anchor(path)


class TestRead3diceAvg:
    def test_reads_matching_row(self, tmp_path):
        path = tmp_path / "3dice.csv"
        _write_3dice_csv(
            path,
            [
                ("B", "s0_uniform", "base_die_phy", 101.004, 101.004),
                ("B", "s2_phy_heavy", "base_die_phy", 125.601, 125.601),
            ],
        )
        assert p5_t3.read_3dice_avg(path, "B", "s0_uniform", "base_die_phy") == pytest.approx(101.004)
        assert p5_t3.read_3dice_avg(path, "B", "s2_phy_heavy", "base_die_phy") == pytest.approx(125.601)

    def test_missing_combo_raises(self, tmp_path):
        path = tmp_path / "3dice.csv"
        _write_3dice_csv(path, [("B", "s0_uniform", "base_die_phy", 101.004, 101.004)])
        with pytest.raises(KeyError):
            p5_t3.read_3dice_avg(path, "B", "s2_phy_heavy", "base_die_phy")


class TestComputeAmplitudeRatioAvgAvg:
    def test_real_p4_values_lands_fail(self):
        # 실측값(CSV 확인): Icepak avg S0(base_die 폴백)=67.871, S2(base_die_phy)=100.169
        # 3D-ICE avg S0=101.004, S2=125.601
        icepak_amp, threedice_amp, ratio = p5_t3.compute_amplitude_ratio_avg_avg(
            67.871, 100.169, 101.004, 125.601
        )
        assert icepak_amp == pytest.approx(32.298, abs=1e-3)
        assert threedice_amp == pytest.approx(24.597, abs=1e-3)
        assert ratio == pytest.approx(0.7616, abs=1e-3)

    def test_equal_amplitudes_ratio_one(self):
        icepak_amp, threedice_amp, ratio = p5_t3.compute_amplitude_ratio_avg_avg(50.0, 80.0, 60.0, 90.0)
        assert icepak_amp == pytest.approx(30.0)
        assert threedice_amp == pytest.approx(30.0)
        assert ratio == pytest.approx(1.0)


class TestJudgeAmplitudeGate:
    def test_ratio_below_gate_fails(self):
        assert p5_t3.judge_amplitude_gate(0.7616) is False

    def test_ratio_in_gate_passes(self):
        assert p5_t3.judge_amplitude_gate(1.0) is True

    def test_gate_boundaries_pass(self):
        assert p5_t3.judge_amplitude_gate(0.9) is True
        assert p5_t3.judge_amplitude_gate(1.1) is True

    def test_ratio_above_gate_fails(self):
        assert p5_t3.judge_amplitude_gate(1.15) is False


class TestClassifyVerdict:
    def test_mean_error_fail_forces_root_redesign(self):
        # 평균오차가 여전히 FAIL이면 진폭비율 결과와 무관하게 "근본 재설계 필요"
        verdict = p5_t3.classify_verdict(mean_errors_still_fail=True, amp_gate_pass=True)
        assert "근본 재설계" in verdict

    def test_mean_error_fail_and_amp_fail_also_root_redesign(self):
        verdict = p5_t3.classify_verdict(mean_errors_still_fail=True, amp_gate_pass=False)
        assert "근본 재설계" in verdict

    def test_mean_error_pass_gives_correction_possible(self):
        verdict = p5_t3.classify_verdict(mean_errors_still_fail=False, amp_gate_pass=True)
        assert verdict == "보정 가능성 있음"


class TestAppendCrossvalRow:
    def test_appends_without_touching_existing_rows(self, tmp_path, monkeypatch):
        csv_path = tmp_path / "p4_t4_crossval.csv"
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["항목", "판정/값", "근거수치"])
            writer.writerow(["G4_B계열_참고_평균오차%", "28.2851", "판정제외(R1완화)"])
        monkeypatch.setattr(p5_t3, "CROSSVAL_CSV", csv_path)

        appended = p5_t3.append_crossval_row(32.298, 24.597, 0.7616, False, dry_run=False)

        assert appended is True
        with open(csv_path, newline="", encoding="utf-8") as f:
            rows = list(csv.reader(f))
        assert len(rows) == 3
        assert rows[1] == ["G4_B계열_참고_평균오차%", "28.2851", "판정제외(R1완화)"]
        assert rows[2][0] == p5_t3.ROW_LABEL
        assert rows[2][1] == "0.7616"

    def test_idempotent_skip_when_row_already_exists(self, tmp_path, monkeypatch):
        """음성 케이스: 이미 ROW_LABEL 행이 있으면 재실행해도 append하지 않는다."""
        csv_path = tmp_path / "p4_t4_crossval.csv"
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["항목", "판정/값", "근거수치"])
            writer.writerow([p5_t3.ROW_LABEL, "0.7616", "기존 실행 결과"])
        monkeypatch.setattr(p5_t3, "CROSSVAL_CSV", csv_path)

        appended = p5_t3.append_crossval_row(32.298, 24.597, 0.7616, False, dry_run=False)

        assert appended is False
        with open(csv_path, newline="", encoding="utf-8") as f:
            rows = list(csv.reader(f))
        assert len(rows) == 2  # 헤더 + 기존 행만, 중복 append 없음

    def test_dry_run_does_not_write(self, tmp_path, monkeypatch):
        """음성 케이스: --dry-run이면 파일 내용이 전혀 바뀌지 않는다."""
        csv_path = tmp_path / "p4_t4_crossval.csv"
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["항목", "판정/값", "근거수치"])
        monkeypatch.setattr(p5_t3, "CROSSVAL_CSV", csv_path)
        before = csv_path.read_text(encoding="utf-8")

        appended = p5_t3.append_crossval_row(32.298, 24.597, 0.7616, False, dry_run=True)

        assert appended is False
        after = csv_path.read_text(encoding="utf-8")
        assert before == after

    def test_appends_when_csv_does_not_exist_yet(self, tmp_path, monkeypatch):
        """음성 케이스: CROSSVAL_CSV 자체가 없을 때도 existing_labels 조회가 죽지 않아야 한다."""
        csv_path = tmp_path / "does_not_exist_yet.csv"
        monkeypatch.setattr(p5_t3, "CROSSVAL_CSV", csv_path)

        appended = p5_t3.append_crossval_row(32.298, 24.597, 0.7616, False, dry_run=False)

        assert appended is True
        assert csv_path.exists()
