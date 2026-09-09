#!/usr/bin/env python3

import argparse
import math
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt


# ============================================================
# Utility
# ============================================================

def circular_diff_deg(a, b):
    """
    두 각도의 차이를 -180 ~ +180 deg 범위로 반환
    """
    return ((a - b + 180.0) % 360.0) - 180.0


def load_summary(path):
    """
    summary CSV 로드 및 numeric column 정리
    """

    df = pd.read_csv(path)

    numeric_cols = [
        "target_phase_deg",
        "initial_test_wheel_phase_deg",
        "breakaway_command_torque_nm",
        "breakaway_feedback_effort_nm",
        "position_left_error_deg",
        "position_right_error_deg",
        "breakaway_detected",
        "max_torque_reached",
        "safety_triggered",
    ]

    for col in numeric_cols:

        if col in df.columns:

            df[col] = pd.to_numeric(
                df[col],
                errors="coerce"
            )

    return df


# ============================================================
# Basic statistics
# ============================================================

def print_basic_stats(df, name):

    print(
        f"\n===== {name.upper()} ====="
    )

    print(
        f"Total trials: {len(df)}"
    )

    print(
        "Breakaway detected: "
        f"{(df['breakaway_detected'] == 1).sum()}"
    )

    print(
        "No breakaway / invalid: "
        f"{(df['breakaway_detected'] != 1).sum()}"
    )

    print(
        "Max torque reached: "
        f"{(df['max_torque_reached'] == 1).sum()}"
    )

    print(
        "Safety fault: "
        f"{(df['safety_triggered'] == 1).sum()}"
    )

    # --------------------------------------------------------
    # Position status
    # --------------------------------------------------------

    print(
        "\nPosition status:"
    )

    print(
        df[
            "position_status"
        ].value_counts(
            dropna=False
        )
    )

    # --------------------------------------------------------
    # Detection method
    # --------------------------------------------------------

    print(
        "\nDetection method:"
    )

    print(
        df[
            "breakaway_detection_method"
        ].value_counts(
            dropna=False
        )
    )

    # --------------------------------------------------------
    # Wheel statistics
    # --------------------------------------------------------

    for wheel in [
        "left",
        "right"
    ]:

        d = df[
            (
                df["wheel"] == wheel
            )
            &
            (
                df["breakaway_detected"] == 1
            )
        ].copy()

        t = (
            d[
                "breakaway_command_torque_nm"
            ]
            .abs()
            .dropna()
        )

        print(
            f"\n{wheel.upper()} "
            f"valid breakaway points: {len(t)}"
        )

        if len(t) == 0:

            continue

        print(
            f"  Mean   : "
            f"{t.mean():.3f} Nm"
        )

        print(
            f"  Median : "
            f"{t.median():.3f} Nm"
        )

        print(
            f"  Std    : "
            f"{t.std():.3f} Nm"
        )

        print(
            f"  Min    : "
            f"{t.min():.3f} Nm"
        )

        print(
            f"  Max    : "
            f"{t.max():.3f} Nm"
        )


# ============================================================
# Figure 1
#
# Forward / Reverse breakaway torque
# ============================================================

def make_direction_plot(
    forward,
    reverse,
    output_dir
):

    plt.figure(
        figsize=(11, 6)
    )

    for wheel in [
        "left",
        "right"
    ]:

        # ----------------------------------------------------
        # Forward
        # ----------------------------------------------------

        f = forward[
            (
                forward["wheel"] == wheel
            )
            &
            (
                forward[
                    "breakaway_detected"
                ] == 1
            )
        ].copy()

        f = f.sort_values(
            "initial_test_wheel_phase_deg"
        )

        # ----------------------------------------------------
        # Reverse
        # ----------------------------------------------------

        r = reverse[
            (
                reverse["wheel"] == wheel
            )
            &
            (
                reverse[
                    "breakaway_detected"
                ] == 1
            )
        ].copy()

        r = r.sort_values(
            "initial_test_wheel_phase_deg"
        )

        # ----------------------------------------------------
        # IMPORTANT:
        # pandas Series -> NumPy array
        #
        # matplotlib / pandas version compatibility fix
        # ----------------------------------------------------

        f_angle = (
            f[
                "initial_test_wheel_phase_deg"
            ].to_numpy()
        )

        f_torque = (
            f[
                "breakaway_command_torque_nm"
            ].abs().to_numpy()
        )

        r_angle = (
            r[
                "initial_test_wheel_phase_deg"
            ].to_numpy()
        )

        r_torque = (
            r[
                "breakaway_command_torque_nm"
            ].abs().to_numpy()
        )

        if len(f_angle) > 0:

            plt.plot(
                f_angle,
                f_torque,
                marker="o",
                label=(
                    f"{wheel.capitalize()} "
                    f"forward"
                )
            )

        if len(r_angle) > 0:

            plt.plot(
                r_angle,
                r_torque,
                marker="o",
                linestyle="--",
                label=(
                    f"{wheel.capitalize()} "
                    f"reverse"
                )
            )

    plt.xlabel(
        "Actual initial motor phase [deg]"
    )

    plt.ylabel(
        "Breakaway command torque magnitude [Nm]"
    )

    plt.title(
        "Forward and reverse angle-dependent "
        "breakaway torque"
    )

    plt.xlim(
        0,
        360
    )

    plt.xticks(
        np.arange(
            0,
            361,
            30
        )
    )

    plt.grid(
        True,
        alpha=0.3
    )

    plt.legend()

    plt.tight_layout()

    path = (
        output_dir
        /
        "01_forward_reverse_breakaway.png"
    )

    plt.savefig(
        path,
        dpi=300
    )

    plt.close()

    return path


# ============================================================
# Figure 2
#
# Torque command vs feedback
# ============================================================

def make_feedback_plot(
    forward,
    reverse,
    output_dir
):

    all_df = pd.concat(
        [
            forward.assign(
                experiment="forward"
            ),
            reverse.assign(
                experiment="reverse"
            ),
        ],
        ignore_index=True
    )

    valid = all_df[
        (
            all_df[
                "breakaway_detected"
            ] == 1
        )
        &
        (
            all_df[
                "breakaway_command_torque_nm"
            ].notna()
        )
        &
        (
            all_df[
                "breakaway_feedback_effort_nm"
            ].notna()
        )
    ].copy()

    x = (
        valid[
            "breakaway_command_torque_nm"
        ].to_numpy()
    )

    y = (
        valid[
            "breakaway_feedback_effort_nm"
        ].to_numpy()
    )

    if len(x) == 0:

        print(
            "\nNo valid command/feedback data."
        )

        return None

    plt.figure(
        figsize=(7, 7)
    )

    plt.scatter(
        x,
        y
    )

    lo = min(
        np.min(x),
        np.min(y)
    )

    hi = max(
        np.max(x),
        np.max(y)
    )

    plt.plot(
        [
            lo,
            hi
        ],
        [
            lo,
            hi
        ],
        linestyle="--",
        label=(
            "Ideal: feedback = command"
        )
    )

    plt.xlabel(
        "Breakaway command torque [Nm]"
    )

    plt.ylabel(
        "Breakaway feedback effort [Nm]"
    )

    plt.title(
        "Breakaway command vs motor feedback"
    )

    plt.grid(
        True,
        alpha=0.3
    )

    plt.legend()

    plt.tight_layout()

    path = (
        output_dir
        /
        "02_command_vs_feedback.png"
    )

    plt.savefig(
        path,
        dpi=300
    )

    plt.close()

    # --------------------------------------------------------
    # Feedback error statistics
    # --------------------------------------------------------

    err = (
        y - x
    )

    print(
        "\n===== COMMAND / FEEDBACK AGREEMENT ====="
    )

    print(
        "Mean error       : "
        f"{np.mean(err):.4f} Nm"
    )

    print(
        "Mean abs. error  : "
        f"{np.mean(np.abs(err)):.4f} Nm"
    )

    print(
        "Max abs. error   : "
        f"{np.max(np.abs(err)):.4f} Nm"
    )

    return path


# ============================================================
# Forward / Reverse pairing
#
# Model:
#
# +T_plus + bias = +Fs
# -T_minus + bias = -Fs
#
# Fs =
#   (T_plus + T_minus) / 2
#
# bias =
#   (T_minus - T_plus) / 2
#
# ============================================================

def build_paired_estimates(
    forward,
    reverse,
    max_phase_gap_deg
):

    rows = []

    for wheel in [
        "left",
        "right"
    ]:

        # ----------------------------------------------------
        # Valid forward points
        # ----------------------------------------------------

        f = forward[
            (
                forward["wheel"] == wheel
            )
            &
            (
                forward[
                    "breakaway_detected"
                ] == 1
            )
        ].copy()

        # ----------------------------------------------------
        # Valid reverse points
        # ----------------------------------------------------

        r = reverse[
            (
                reverse["wheel"] == wheel
            )
            &
            (
                reverse[
                    "breakaway_detected"
                ] == 1
            )
        ].copy()

        # ----------------------------------------------------
        # Match using commanded target phase
        #
        # 실제 encoder phase 차이는 아래에서 추가 검사
        # ----------------------------------------------------

        merged = f.merge(
            r,
            on=[
                "target_phase_deg",
                "wheel"
            ],
            suffixes=(
                "_forward",
                "_reverse"
            )
        )

        for _, row in merged.iterrows():

            phi_f = row[
                "initial_test_wheel_phase_deg_forward"
            ]

            phi_r = row[
                "initial_test_wheel_phase_deg_reverse"
            ]

            if (
                pd.isna(phi_f)
                or
                pd.isna(phi_r)
            ):

                continue

            # ------------------------------------------------
            # Circular phase difference
            # ------------------------------------------------

            gap = circular_diff_deg(
                phi_r,
                phi_f
            )

            if (
                abs(gap)
                >
                max_phase_gap_deg
            ):

                continue

            # ------------------------------------------------
            # Torque magnitude
            # ------------------------------------------------

            t_plus = abs(
                row[
                    "breakaway_command_torque_nm_forward"
                ]
            )

            t_minus = abs(
                row[
                    "breakaway_command_torque_nm_reverse"
                ]
            )

            if (
                pd.isna(t_plus)
                or
                pd.isna(t_minus)
            ):

                continue

            # ------------------------------------------------
            # Static friction estimate
            # ------------------------------------------------

            friction = (
                0.5
                *
                (
                    t_plus
                    +
                    t_minus
                )
            )

            # ------------------------------------------------
            # Internal mechanical bias estimate
            # ------------------------------------------------

            bias = (
                0.5
                *
                (
                    t_minus
                    -
                    t_plus
                )
            )

            # ------------------------------------------------
            # Circular mean of two measured phases
            # ------------------------------------------------

            x1 = math.radians(
                phi_f
            )

            x2 = math.radians(
                phi_r
            )

            mean_phase = math.degrees(
                math.atan2(
                    math.sin(x1)
                    +
                    math.sin(x2),

                    math.cos(x1)
                    +
                    math.cos(x2)
                )
            ) % 360.0

            rows.append(
                {
                    "wheel":
                        wheel,

                    "target_phase_deg":
                        row[
                            "target_phase_deg"
                        ],

                    "forward_actual_phase_deg":
                        phi_f,

                    "reverse_actual_phase_deg":
                        phi_r,

                    "phase_gap_deg":
                        gap,

                    "mean_actual_phase_deg":
                        mean_phase,

                    "forward_breakaway_nm":
                        t_plus,

                    "reverse_breakaway_nm":
                        t_minus,

                    "estimated_static_friction_nm":
                        friction,

                    "estimated_internal_bias_nm":
                        bias,
                }
            )

    return pd.DataFrame(
        rows
    )


# ============================================================
# Paired statistics
# ============================================================

def print_paired_stats(
    paired
):

    print(
        "\n===== PAIRED FORWARD / REVERSE ESTIMATES ====="
    )

    if len(paired) == 0:

        print(
            "No matched forward/reverse points."
        )

        return

    for wheel in [
        "left",
        "right"
    ]:

        d = paired[
            paired[
                "wheel"
            ] == wheel
        ]

        print(
            f"\n{wheel.upper()}"
        )

        print(
            f"Matched points: {len(d)}"
        )

        if len(d) == 0:

            continue

        fs = (
            d[
                "estimated_static_friction_nm"
            ]
        )

        bias = (
            d[
                "estimated_internal_bias_nm"
            ]
        )

        print(
            "Estimated static friction [Nm]"
        )

        print(
            f"  Mean   : "
            f"{fs.mean():.3f}"
        )

        print(
            f"  Median : "
            f"{fs.median():.3f}"
        )

        print(
            f"  Std    : "
            f"{fs.std():.3f}"
        )

        print(
            f"  Min    : "
            f"{fs.min():.3f}"
        )

        print(
            f"  Max    : "
            f"{fs.max():.3f}"
        )

        print(
            "Estimated internal bias torque [Nm]"
        )

        print(
            f"  Mean   : "
            f"{bias.mean():+.3f}"
        )

        print(
            f"  Median : "
            f"{bias.median():+.3f}"
        )

        print(
            f"  Std    : "
            f"{bias.std():.3f}"
        )

        print(
            f"  Min    : "
            f"{bias.min():+.3f}"
        )

        print(
            f"  Max    : "
            f"{bias.max():+.3f}"
        )


# ============================================================
# Figure 3
#
# Estimated static friction
# ============================================================

def make_friction_plot(
    paired,
    output_dir
):

    if len(paired) == 0:

        print(
            "\nNo paired data for friction plot."
        )

        return None

    plt.figure(
        figsize=(11, 6)
    )

    for wheel in [
        "left",
        "right"
    ]:

        d = paired[
            paired[
                "wheel"
            ] == wheel
        ].copy()

        d = d.sort_values(
            "mean_actual_phase_deg"
        )

        x = (
            d[
                "mean_actual_phase_deg"
            ].to_numpy()
        )

        y = (
            d[
                "estimated_static_friction_nm"
            ].to_numpy()
        )

        if len(x) == 0:

            continue

        plt.plot(
            x,
            y,
            marker="o",
            label=wheel.capitalize()
        )

    plt.xlabel(
        "Matched actual motor phase [deg]"
    )

    plt.ylabel(
        "Estimated static friction magnitude [Nm]"
    )

    plt.title(
        "Estimated angle-dependent static friction"
    )

    plt.xlim(
        0,
        360
    )

    plt.xticks(
        np.arange(
            0,
            361,
            30
        )
    )

    plt.grid(
        True,
        alpha=0.3
    )

    plt.legend()

    plt.tight_layout()

    path = (
        output_dir
        /
        "03_estimated_static_friction.png"
    )

    plt.savefig(
        path,
        dpi=300
    )

    plt.close()

    return path


# ============================================================
# Figure 4
#
# Estimated internal bias torque
# ============================================================

def make_bias_plot(
    paired,
    output_dir
):

    if len(paired) == 0:

        print(
            "\nNo paired data for bias plot."
        )

        return None

    plt.figure(
        figsize=(11, 6)
    )

    for wheel in [
        "left",
        "right"
    ]:

        d = paired[
            paired[
                "wheel"
            ] == wheel
        ].copy()

        d = d.sort_values(
            "mean_actual_phase_deg"
        )

        x = (
            d[
                "mean_actual_phase_deg"
            ].to_numpy()
        )

        y = (
            d[
                "estimated_internal_bias_nm"
            ].to_numpy()
        )

        if len(x) == 0:

            continue

        plt.plot(
            x,
            y,
            marker="o",
            label=wheel.capitalize()
        )

    plt.axhline(
        0.0,
        linestyle="--"
    )

    plt.xlabel(
        "Matched actual motor phase [deg]"
    )

    plt.ylabel(
        "Estimated internal bias torque [Nm]"
    )

    plt.title(
        "Estimated angle-dependent internal bias torque"
    )

    plt.xlim(
        0,
        360
    )

    plt.xticks(
        np.arange(
            0,
            361,
            30
        )
    )

    plt.grid(
        True,
        alpha=0.3
    )

    plt.legend()

    plt.tight_layout()

    path = (
        output_dir
        /
        "04_estimated_internal_bias.png"
    )

    plt.savefig(
        path,
        dpi=300
    )

    plt.close()

    return path


# ============================================================
# Main
# ============================================================

def main():

    parser = argparse.ArgumentParser(
        description=(
            "Analyze forward/reverse "
            "angle-dependent breakaway tests"
        )
    )

    parser.add_argument(
        "forward_csv",
        help=(
            "Forward summary CSV path"
        )
    )

    parser.add_argument(
        "reverse_csv",
        help=(
            "Reverse summary CSV path"
        )
    )

    parser.add_argument(
        "--max-phase-gap-deg",
        type=float,
        default=5.0,
        help=(
            "Maximum allowed difference between "
            "forward/reverse actual start phase "
            "for friction/bias estimation. "
            "Default = 5 deg"
        )
    )

    parser.add_argument(
        "--output-dir",
        default=None,
        help=(
            "Output directory. "
            "Default = breakaway_analysis "
            "inside forward CSV directory"
        )
    )

    args = parser.parse_args()

    # ========================================================
    # Paths
    # ========================================================

    forward_path = Path(
        args.forward_csv
    ).expanduser()

    reverse_path = Path(
        args.reverse_csv
    ).expanduser()

    if (
        not
        forward_path.exists()
    ):

        raise FileNotFoundError(
            f"Forward CSV not found: "
            f"{forward_path}"
        )

    if (
        not
        reverse_path.exists()
    ):

        raise FileNotFoundError(
            f"Reverse CSV not found: "
            f"{reverse_path}"
        )

    if (
        args.output_dir
        is None
    ):

        output_dir = (
            forward_path.parent
            /
            "breakaway_analysis"
        )

    else:

        output_dir = Path(
            args.output_dir
        ).expanduser()

    output_dir.mkdir(
        parents=True,
        exist_ok=True
    )

    # ========================================================
    # Load data
    # ========================================================

    forward = load_summary(
        forward_path
    )

    reverse = load_summary(
        reverse_path
    )

    # ========================================================
    # Basic numerical analysis
    # ========================================================

    print_basic_stats(
        forward,
        "forward"
    )

    print_basic_stats(
        reverse,
        "reverse"
    )

    # ========================================================
    # Figure 1
    # ========================================================

    graph1 = make_direction_plot(
        forward,
        reverse,
        output_dir
    )

    # ========================================================
    # Figure 2
    # ========================================================

    graph2 = make_feedback_plot(
        forward,
        reverse,
        output_dir
    )

    # ========================================================
    # Pair forward / reverse
    # ========================================================

    paired = build_paired_estimates(
        forward,
        reverse,
        args.max_phase_gap_deg
    )

    # ========================================================
    # Save paired values
    # ========================================================

    paired_csv = (
        output_dir
        /
        "paired_friction_bias_estimates.csv"
    )

    paired.to_csv(
        paired_csv,
        index=False
    )

    # ========================================================
    # Numerical friction/bias analysis
    # ========================================================

    print_paired_stats(
        paired
    )

    # ========================================================
    # Figure 3
    # ========================================================

    graph3 = make_friction_plot(
        paired,
        output_dir
    )

    # ========================================================
    # Figure 4
    # ========================================================

    graph4 = make_bias_plot(
        paired,
        output_dir
    )

    # ========================================================
    # Output summary
    # ========================================================

    print(
        "\n===== SAVED FILES ====="
    )

    saved_files = [
        graph1,
        graph2,
        graph3,
        graph4,
        paired_csv,
    ]

    for path in saved_files:

        if path is not None:

            print(
                path
            )

    print(
        "\nIMPORTANT:"
    )

    print(
        "estimated_static_friction_nm and "
        "estimated_internal_bias_nm are "
        "model-based estimates."
    )

    print(
        "Only forward/reverse measurements "
        "whose actual start-phase difference "
        f"is <= {args.max_phase_gap_deg:.1f} deg "
        "are paired."
    )


if __name__ == "__main__":

    main()
