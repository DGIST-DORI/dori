import sys
import os

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt


def main():

    # ==========================================================
    # Input
    # ==========================================================

    if len(sys.argv) < 2:

        print(
            "Usage:"
        )

        print(
            "python3 plot_breakaway_map.py "
            "<summary.csv>"
        )

        return

    csv_path = os.path.expanduser(
        sys.argv[1]
    )

    if not os.path.exists(
        csv_path
    ):

        print(
            f"File not found: {csv_path}"
        )

        return

    # ==========================================================
    # Load
    # ==========================================================

    df = pd.read_csv(
        csv_path
    )

    print(
        "\n===== DATA SUMMARY ====="
    )

    print(
        f"File: {csv_path}"
    )

    print(
        f"Rows: {len(df)}"
    )

    print()

    print(
        df[
            [
                'target_phase_deg',
                'wheel',
                'initial_test_wheel_phase_deg',
                'breakaway_detected',
                'breakaway_detection_method',
                'breakaway_command_torque_nm',
                'breakaway_feedback_effort_nm',
                'max_torque_reached',
                'fault_type',
            ]
        ].to_string(
            index=False
        )
    )

    # ==========================================================
    # Numeric cleanup
    # ==========================================================

    df[
        'initial_test_wheel_phase_deg'
    ] = pd.to_numeric(
        df[
            'initial_test_wheel_phase_deg'
        ],
        errors='coerce'
    )

    df[
        'breakaway_command_torque_nm'
    ] = pd.to_numeric(
        df[
            'breakaway_command_torque_nm'
        ],
        errors='coerce'
    )

    df[
        'breakaway_feedback_effort_nm'
    ] = pd.to_numeric(
        df[
            'breakaway_feedback_effort_nm'
        ],
        errors='coerce'
    )

    # ==========================================================
    # Only valid breakaway measurements
    # ==========================================================

    valid = df[
        (
            df[
                'breakaway_detected'
            ] == 1
        )
        &
        (
            df[
                'breakaway_command_torque_nm'
            ].notna()
        )
        &
        (
            df[
                'initial_test_wheel_phase_deg'
            ].notna()
        )
    ].copy()

    left = valid[
        valid[
            'wheel'
        ] == 'left'
    ].copy()

    right = valid[
        valid[
            'wheel'
        ] == 'right'
    ].copy()

    left = left.sort_values(
        'initial_test_wheel_phase_deg'
    )

    right = right.sort_values(
        'initial_test_wheel_phase_deg'
    )

    # ==========================================================
    # Figure 1
    #
    # Actual angle vs breakaway torque
    # ==========================================================

    plt.figure(
        figsize=(10, 6)
    )

    if len(left) > 0:

        plt.plot(
            left[
                'initial_test_wheel_phase_deg'
            ],
            left[
                'breakaway_command_torque_nm'
            ],
            marker='o',
            label='Left wheel'
        )

    if len(right) > 0:

        plt.plot(
            right[
                'initial_test_wheel_phase_deg'
            ],
            right[
                'breakaway_command_torque_nm'
            ],
            marker='o',
            label='Right wheel'
        )

    plt.xlabel(
        'Actual Initial Motor Phase [deg]'
    )

    plt.ylabel(
        'Breakaway Torque [Nm]'
    )

    plt.title(
        'Angle-dependent Breakaway Torque'
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

    output_dir = os.path.dirname(
        csv_path
    )

    output_base = os.path.splitext(
        os.path.basename(
            csv_path
        )
    )[0]

    graph1_path = os.path.join(
        output_dir,
        output_base
        +
        '_breakaway_vs_angle.png'
    )

    plt.savefig(
        graph1_path,
        dpi=300
    )

    print(
        f"\nSaved: {graph1_path}"
    )

    plt.show()

    # ==========================================================
    # Figure 2
    #
    # Command torque vs feedback effort
    # ==========================================================

    feedback_valid = valid[
        valid[
            'breakaway_feedback_effort_nm'
        ].notna()
    ]

    if len(feedback_valid) > 0:

        plt.figure(
            figsize=(7, 7)
        )

        plt.scatter(
            feedback_valid[
                'breakaway_command_torque_nm'
            ],
            feedback_valid[
                'breakaway_feedback_effort_nm'
            ]
        )

        min_value = min(
            feedback_valid[
                'breakaway_command_torque_nm'
            ].min(),
            feedback_valid[
                'breakaway_feedback_effort_nm'
            ].min()
        )

        max_value = max(
            feedback_valid[
                'breakaway_command_torque_nm'
            ].max(),
            feedback_valid[
                'breakaway_feedback_effort_nm'
            ].max()
        )

        plt.plot(
            [
                min_value,
                max_value
            ],
            [
                min_value,
                max_value
            ],
            linestyle='--',
            label='Ideal: feedback = command'
        )

        plt.xlabel(
            'Command Torque at Breakaway [Nm]'
        )

        plt.ylabel(
            'Feedback Effort at Breakaway [Nm]'
        )

        plt.title(
            'Torque Command vs Motor Feedback'
        )

        plt.grid(
            True,
            alpha=0.3
        )

        plt.legend()

        plt.tight_layout()

        graph2_path = os.path.join(
            output_dir,
            output_base
            +
            '_command_vs_feedback.png'
        )

        plt.savefig(
            graph2_path,
            dpi=300
        )

        print(
            f"Saved: {graph2_path}"
        )

        plt.show()

    # ==========================================================
    # Statistics
    # ==========================================================

    print(
        "\n===== BREAKAWAY STATISTICS ====="
    )

    for wheel_name in [
        'left',
        'right'
    ]:

        wheel_df = valid[
            valid[
                'wheel'
            ] == wheel_name
        ]

        if len(wheel_df) == 0:

            print(
                f"\n{wheel_name.upper()}: "
                f"No valid breakaway data"
            )

            continue

        torque = wheel_df[
            'breakaway_command_torque_nm'
        ]

        print(
            f"\n{wheel_name.upper()}"
        )

        print(
            f"valid points = {len(torque)}"
        )

        print(
            f"mean = {torque.mean():.3f} Nm"
        )

        print(
            f"std  = {torque.std():.3f} Nm"
        )

        print(
            f"min  = {torque.min():.3f} Nm"
        )

        print(
            f"max  = {torque.max():.3f} Nm"
        )

        min_index = torque.idxmin()

        max_index = torque.idxmax()

        print(
            "minimum angle = "
            f"{wheel_df.loc[min_index, 'initial_test_wheel_phase_deg']:.2f} deg"
        )

        print(
            "maximum angle = "
            f"{wheel_df.loc[max_index, 'initial_test_wheel_phase_deg']:.2f} deg"
        )

    # ==========================================================
    # Failed / censored tests
    # ==========================================================

    print(
        "\n===== NO BREAKAWAY / FAULT ====="
    )

    failed = df[
        df[
            'breakaway_detected'
        ] != 1
    ]

    if len(failed) == 0:

        print(
            "None"
        )

    else:

        print(
            failed[
                [
                    'target_phase_deg',
                    'wheel',
                    'initial_test_wheel_phase_deg',
                    'max_torque_reached',
                    'safety_triggered',
                    'fault_type',
                ]
            ].to_string(
                index=False
            )
        )


if __name__ == '__main__':

    main()
