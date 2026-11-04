"""Verify aggregation units and missing-data handling without motor access."""
import importlib.util
from pathlib import Path

import pytest


SOURCE = Path(__file__).resolve().parents[2] / "tools/drive/analyze_bldc_speed_comparison.py"
SPEC = importlib.util.spec_from_file_location("bldc_speed_analysis", SOURCE)
analysis = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(analysis)


def measured_leg(motor, direction, elapsed, count, *, source="trial", number=1):
    leg = dict(source=source, motor=motor, phase=f"round{number}_{direction}",
               speed_deg_s=20, elapsed_s=elapsed, first_pass=False,
               ramp_end_error_deg=-2, correction_and_confirmation_s=2,
               overshoot_deg=0, start_temperature_c=50, end_temperature_c=51)
    if count is not None:
        leg["correction_count"] = count
    return leg


def test_round_totals_keep_motors_directions_and_sources_separate():
    legs = [measured_leg(1, "zero", 10, 2), measured_leg(2, "zero", 11, 1),
            measured_leg(1, "return", 12, 3), measured_leg(2, "return", 13, 0),
            measured_leg(1, "zero", 14, 1, source="second")]
    first, second = analysis.round_rows(legs)
    assert first["completed_legs"] == 4
    assert first["motor1_round_trip_s"] == 22
    assert first["motor2_round_trip_s"] == 24
    assert first["motor1_corrections"] == 5
    assert first["motor2_corrections"] == 1
    assert first["motor2_return_corrections"] == 0
    assert second["repetition_at_speed"] == 2
    assert second["completed_legs"] == 1
    assert second["motor1_round_trip_s"] is None
    assert second["motor1_corrections"] is None


def test_summary_uses_sample_deviation_and_does_not_treat_missing_counts_as_zero():
    legs = [measured_leg(1, "zero", 10, None), measured_leg(1, "return", 14, 0),
            measured_leg(2, "zero", 12, 2)]
    summary = analysis.summarize(legs)[20]
    assert summary["moves"] == 3
    assert summary["mean_total_s"] == 12
    assert summary["stdev_total_s"] == pytest.approx(2)
    assert summary["correction_counted_moves"] == 2
    assert summary["mean_correction_count"] == 1
    assert summary["total_correction_count"] == 2
    assert analysis.summarize(legs[:1])[20]["mean_correction_count"] is None
