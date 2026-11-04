#!/usr/bin/env python3
"""Summarize measured BLDC speed comparisons without accessing hardware."""
import argparse
from collections import Counter
import csv
import json
from pathlib import Path
import statistics


def summarize(legs):
    result = {}
    for speed in sorted({x["speed_deg_s"] for x in legs}):
        group = [x for x in legs if x["speed_deg_s"] == speed]
        counts = [x["correction_count"] for x in group if "correction_count" in x]
        result[speed] = dict(
            moves=len(group), first_pass=sum(x["first_pass"] for x in group),
            mean_abs_ramp_end_error_deg=statistics.mean(abs(x["ramp_end_error_deg"]) for x in group),
            median_abs_ramp_end_error_deg=statistics.median(abs(x["ramp_end_error_deg"]) for x in group),
            mean_correction_and_confirmation_s=statistics.mean(x["correction_and_confirmation_s"] for x in group),
            mean_total_s=statistics.mean(x["elapsed_s"] for x in group),
            stdev_total_s=statistics.stdev(x["elapsed_s"] for x in group) if len(group) > 1 else 0,
            min_total_s=min(x["elapsed_s"] for x in group),
            max_total_s=max(x["elapsed_s"] for x in group),
            correction_counted_moves=len(counts),
            mean_correction_count=statistics.mean(counts) if counts else None,
            total_correction_count=sum(counts) if counts else None,
            min_correction_count=min(counts) if counts else None,
            max_correction_count=max(counts) if counts else None,
            max_overshoot_deg=max(x["overshoot_deg"] for x in group),
            mean_start_temperature_c=statistics.mean(x["start_temperature_c"] for x in group),
            max_end_temperature_c=max(x["end_temperature_c"] for x in group))
    return result


def round_rows(legs):
    grouped = {}
    for leg in legs:
        number = int(leg["phase"].split("_")[0][5:])
        grouped.setdefault((leg["source"], number), []).append(leg)
    repetitions, rows = Counter(), []
    for (source, number), group in grouped.items():
        speed = group[0]["speed_deg_s"]
        repetitions[speed] += 1
        row = dict(source=source, round=number, speed_deg_s=speed,
                   repetition_at_speed=repetitions[speed], completed_legs=len(group))
        for motor in (1, 2):
            motor_legs = [x for x in group if x["motor"] == motor]
            for direction in ("zero", "return"):
                leg = next((x for x in motor_legs if x["phase"].endswith(direction)), None)
                row[f"motor{motor}_{direction}_s"] = leg["elapsed_s"] if leg else None
                row[f"motor{motor}_{direction}_corrections"] = leg.get("correction_count") if leg else None
            row[f"motor{motor}_round_trip_s"] = sum(x["elapsed_s"] for x in motor_legs) if len(motor_legs) == 2 else None
            row[f"motor{motor}_corrections"] = (sum(x["correction_count"] for x in motor_legs)
                if len(motor_legs) == 2 and all("correction_count" in x for x in motor_legs) else None)
        rows.append(row)
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    parser.add_argument("--baseline-report", type=Path,
                        help="Include the completed measured moves of an earlier comparison")
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    report = json.loads(args.report.read_text())
    sources = [(args.report, report)]
    if args.baseline_report:
        sources.insert(0, (args.baseline_report, json.loads(args.baseline_report.read_text())))
    legs = [dict(x, source=str(path)) for path, data in sources
            for x in data["legs"] if x["phase"].startswith("round")]
    if not legs:
        raise SystemExit("No completed measured legs")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    summary = dict(sources=[str(path) for path, _ in sources], result=report["result"],
                   completed_moves=len(legs), expected_moves=sum(4*len(d["comparison_speeds"]) for _, d in sources),
                   speed_orders=[d["comparison_speeds"] for _, d in sources], overall=summarize(legs),
                   rounds=round_rows(legs),
                   by_motor={m: summarize([x for x in legs if x["motor"] == m]) for m in (1, 2)},
                   by_motor_and_direction={f"motor{m}_{direction}": summarize([
                       x for x in legs if x["motor"] == m and x["phase"].endswith(direction)])
                       for m in (1, 2) for direction in ("zero", "return")},
                   definitions={
                       "ramp_end_error_deg": "Measured position minus target at first feedback after commanded deceleration ends",
                       "first_pass": "Every feedback sample from deceleration end through arrival confirmation is within +/-1 degree",
                       "correction_and_confirmation_s": "Elapsed time after planned deceleration, including the 0.5-second settling confirmation",
                       "overshoot_deg": "Maximum distance past target along the direction of travel, until arrival confirmation",
                       "correction_count": "Post-ramp physical movements >=0.2 deg outside the +/-1 deg window; continuous movement counts once; restart after 0.5 s with <=0.03 deg span or >=0.2 deg reversal counts again. Not PI command count."})
    (args.output_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    flat = [{k: v for k, v in x.items() if k not in ("trace", "trace_columns", "correction_events")} for x in legs]
    with (args.output_dir / "moves.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(dict.fromkeys(k for row in flat for k in row)))
        writer.writeheader()
        writer.writerows(flat)
    with (args.output_dir / "rounds.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(summary["rounds"][0]))
        writer.writeheader()
        writer.writerows(summary["rounds"])

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.ticker import MaxNLocator
    speeds = sorted({x["speed_deg_s"] for x in legs})
    fig, axes = plt.subplots(2, 2, figsize=(10, 7), constrained_layout=True)
    panels = [
        ("Error at deceleration end", "Absolute error (deg)", lambda x: abs(x["ramp_end_error_deg"])),
        ("Time after deceleration", "Correction + confirmation (s)", lambda x: x["correction_and_confirmation_s"]),
        ("Total arrival time", "Seconds per move", lambda x: x["elapsed_s"]),
        ("Overshoot", "Degrees past target", lambda x: x["overshoot_deg"])]
    if all("correction_count" in x for x in legs):
        panels[-1] = ("Correction movements", "Count per one-way move", lambda x: x["correction_count"])
    for ax, (title, label, metric) in zip(axes.flat, panels):
        values = [[metric(x) for x in legs if x["speed_deg_s"] == speed] for speed in speeds]
        ax.boxplot(values, positions=range(len(speeds)), widths=0.4, showfliers=False)
        for i, speed in enumerate(speeds):
            group = [x for x in legs if x["speed_deg_s"] == speed]
            for j, leg in enumerate(group):
                ax.scatter(i + (j - (len(group)-1)/2)*0.035, metric(leg),
                           marker="o" if leg["motor"] == 1 else "^",
                           color={10: "#2864b4", 15: "#d7771d", 20: "#27864c", 25: "#8451b2"}[speed], s=35, zorder=3)
        ax.set(title=title, ylabel=label, xticks=range(len(speeds)),
               xticklabels=[f"{s:g} deg/s" for s in speeds])
        ax.set_ylim(bottom=0)
        ax.grid(axis="y", alpha=0.2)
    axes[0, 0].axhline(1, color="crimson", linestyle="--", linewidth=1, label="1 deg tolerance")
    axes[0, 0].legend(loc="lower left", fontsize=8)
    orders = "; then ".join(" / ".join(f"{s:g}" for s in d["comparison_speeds"]) for _, d in sources)
    all_speeds = [s for _, d in sources for s in d["comparison_speeds"]]
    if len(all_speeds) > 8:
        orders = ", ".join(f"{s:g} deg/s x {n} rounds" for s, n in sorted(Counter(all_speeds).items()))
    fig.suptitle("BLDC speed comparison: same gains, acceleration and endpoint correction\n"
                 f"Order: {orders}; circle: motor 1, triangle: motor 2", fontsize=10)
    fig.savefig(args.output_dir / "comparison.png", dpi=160)
    plt.close(fig)
    if all("correction_count" in x for x in legs):
        fig, axes = plt.subplots(2, 2, figsize=(10, 7), constrained_layout=True)
        for motor, row in zip((1, 2), axes):
            for ax, metric, label in zip(row, ("elapsed_s", "correction_count"),
                                         ("Arrival time (s)", "Correction movements")):
                for i, speed in enumerate(speeds):
                    group = [x for x in legs if x["motor"] == motor and x["speed_deg_s"] == speed]
                    values = [x[metric] for x in group]
                    if not values:
                        continue
                    ax.boxplot([values], positions=[i], widths=0.4, showfliers=False)
                    for direction, marker, offset in (("zero", "v", -0.09), ("return", "^", 0.09)):
                        directed = [x[metric] for x in group if x["phase"].endswith(direction)]
                        ax.scatter([i+offset+(j-(len(directed)-1)/2)*0.025 for j in range(len(directed))],
                                   directed, marker=marker, color="#2864b4" if direction == "zero" else "#d7771d",
                                   s=35, zorder=3, label=direction if i == 0 else None)
                ax.set(title=f"Motor {motor}: {label}", ylabel=label, xticks=range(len(speeds)),
                       xticklabels=[f"{s:g} deg/s" for s in speeds])
                ax.set_ylim(bottom=0)
                if metric == "correction_count":
                    ax.yaxis.set_major_locator(MaxNLocator(integer=True))
                ax.grid(axis="y", alpha=0.2)
                ax.legend(fontsize=8)
        fig.suptitle(f"Arrival time and correction movements by motor ({len(legs)} measured moves)\n"
                     "Each point is one move; arrival includes 0.5 s stable confirmation", fontsize=11)
        fig.savefig(args.output_dir / "arrival_corrections.png", dpi=160)
        plt.close(fig)
    print(json.dumps({k: v for k, v in summary.items() if k not in ("definitions", "rounds")}, indent=2))


if __name__ == "__main__":
    main()
