#!/usr/bin/env python3

import argparse
import os

from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt


# ==============================================================
# Arguments
# ==============================================================

parser = argparse.ArgumentParser()

parser.add_argument(
    '--raw',
    required=True
)

parser.add_argument(
    '--summary',
    required=True
)

parser.add_argument(
    '--output-dir',
    default=None
)

args = parser.parse_args()


raw_path = os.path.expanduser(
    args.raw
)

summary_path = os.path.expanduser(
    args.summary
)


if args.output_dir is None:

    output_dir = os.path.dirname(
        summary_path
    )

else:

    output_dir = os.path.expanduser(
        args.output_dir
    )


Path(
    output_dir
).mkdir(
    parents=True,
    exist_ok=True
)


raw = pd.read_csv(
    raw_path
)

summary = pd.read_csv(
    summary_path
)


# ==============================================================
# Save helper
# ==============================================================

def save_figure(
    fig,
    name
):

    fig.savefig(
        os.path.join(
            output_dir,
            name + '.png'
        ),
        dpi=600,
        bbox_inches='tight'
    )

    fig.savefig(
        os.path.join(
            output_dir,
            name + '.pdf'
        ),
        bbox_inches='tight'
    )

    fig.savefig(
        os.path.join(
            output_dir,
            name + '.svg'
        ),
        bbox_inches='tight'
    )

    plt.close(
        fig
    )


# ==============================================================
# Figure 1
# Velocity time history
# ==============================================================

fig, ax = plt.subplots(
    figsize=(7.2, 4.3)
)

ax.plot(
    raw['elapsed_sec'],
    raw['reference_speed_rad_s'],
    linestyle='--',
    label='Velocity reference'
)

ax.plot(
    raw['elapsed_sec'],
    raw['left_velocity_rad_s'],
    alpha=0.5,
    label='Left wheel'
)

ax.plot(
    raw['elapsed_sec'],
    raw['right_velocity_rad_s'],
    alpha=0.5,
    label='Right wheel'
)

ax.plot(
    raw['elapsed_sec'],
    raw['left_velocity_mean_rad_s'],
    linewidth=1.8,
    label='Left filtered'
)

ax.plot(
    raw['elapsed_sec'],
    raw['right_velocity_mean_rad_s'],
    linewidth=1.8,
    label='Right filtered'
)

ax.set_xlabel(
    'Time (s)'
)

ax.set_ylabel(
    'Angular velocity (rad/s)'
)

ax.set_title(
    'MIT velocity-mode response'
)

ax.grid(
    True,
    alpha=0.25
)

ax.legend(
    frameon=False,
    ncol=2
)

fig.tight_layout()

save_figure(
    fig,
    'mit_velocity_response'
)


# ==============================================================
# Figure 2
# Effort time history
# ==============================================================

fig, ax = plt.subplots(
    figsize=(7.2, 4.3)
)

ax.plot(
    raw['elapsed_sec'],
    raw['left_effort_nm'],
    label='Left wheel'
)

ax.plot(
    raw['elapsed_sec'],
    raw['right_effort_nm'],
    label='Right wheel'
)

ax.set_xlabel(
    'Time (s)'
)

ax.set_ylabel(
    'Measured effort (N·m)'
)

ax.set_title(
    'Motor effort during velocity control'
)

ax.grid(
    True,
    alpha=0.25
)

ax.legend(
    frameon=False
)

fig.tight_layout()

save_figure(
    fig,
    'mit_effort_response'
)


# ==============================================================
# Only successful steady-state measurements
# ==============================================================

if summary.empty:

    print(
        'Summary CSV is empty. '
        'No steady-state measurements available.'
    )

    raise SystemExit(0)


# ==============================================================
# Aggregate repeats
#
# IMPORTANT:
#
# x = measured velocity
# NOT target velocity
# ==============================================================

grouped = (
    summary
    .groupby(
        'target_speed_rad_s',
        as_index=False
    )
    .agg({

        'left_mean_velocity_rad_s':
            ['mean', 'std'],

        'right_mean_velocity_rad_s':
            ['mean', 'std'],

        'left_mean_effort_nm':
            ['mean', 'std'],

        'right_mean_effort_nm':
            ['mean', 'std'],
    })
)


grouped.columns = [

    'target_speed',

    'left_velocity_mean',
    'left_velocity_repeat_std',

    'right_velocity_mean',
    'right_velocity_repeat_std',

    'left_effort_mean',
    'left_effort_repeat_std',

    'right_effort_mean',
    'right_effort_repeat_std',
]


grouped = grouped.sort_values(
    'target_speed'
)


aggregate_path = os.path.join(
    output_dir,
    'mit_dynamic_friction_aggregated.csv'
)

grouped.to_csv(
    aggregate_path,
    index=False
)


# ==============================================================
# Friction model
#
# tau =
# tau_bias
# + tau_c * sign(omega)
# + b * omega
# ==============================================================

def fit_friction_model(
    omega,
    torque
):

    omega = np.asarray(
        omega,
        dtype=float
    )

    torque = np.asarray(
        torque,
        dtype=float
    )

    valid = (
        np.isfinite(
            omega
        )
        &
        np.isfinite(
            torque
        )
        &
        (
            np.abs(
                omega
            )
            >
            1e-6
        )
    )

    omega = omega[
        valid
    ]

    torque = torque[
        valid
    ]

    if len(
        omega
    ) < 3:

        return (
            np.nan,
            np.nan,
            np.nan,
            np.nan
        )

    X = np.column_stack([

        np.ones_like(
            omega
        ),

        np.sign(
            omega
        ),

        omega,
    ])

    beta, _, _, _ = (
        np.linalg.lstsq(
            X,
            torque,
            rcond=None
        )
    )

    prediction = (
        X @ beta
    )

    ss_res = np.sum(
        (
            torque
            -
            prediction
        ) ** 2
    )

    ss_tot = np.sum(
        (
            torque
            -
            np.mean(
                torque
            )
        ) ** 2
    )

    if ss_tot > 0.0:

        r_squared = (
            1.0
            -
            ss_res
            /
            ss_tot
        )

    else:

        r_squared = (
            np.nan
        )

    return (
        beta[0],
        beta[1],
        beta[2],
        r_squared
    )


left_model = fit_friction_model(

    grouped[
        'left_velocity_mean'
    ],

    grouped[
        'left_effort_mean'
    ]
)


right_model = fit_friction_model(

    grouped[
        'right_velocity_mean'
    ],

    grouped[
        'right_effort_mean'
    ]
)


# ==============================================================
# Model CSV
# ==============================================================

model_df = pd.DataFrame([

    {
        'wheel':
            'left',

        'tau_bias_nm':
            left_model[0],

        'coulomb_tau_nm':
            left_model[1],

        'viscous_b_nm_per_rad_s':
            left_model[2],

        'r_squared':
            left_model[3],
    },

    {
        'wheel':
            'right',

        'tau_bias_nm':
            right_model[0],

        'coulomb_tau_nm':
            right_model[1],

        'viscous_b_nm_per_rad_s':
            right_model[2],

        'r_squared':
            right_model[3],
    },
])


model_df.to_csv(

    os.path.join(
        output_dir,
        'mit_dynamic_friction_model.csv'
    ),

    index=False
)


# ==============================================================
# Figure 3
# Publication-ready friction curve
# ==============================================================

fig, ax = plt.subplots(
    figsize=(6.3, 4.6)
)


ax.errorbar(

    grouped[
        'left_velocity_mean'
    ],

    grouped[
        'left_effort_mean'
    ],

    xerr=grouped[
        'left_velocity_repeat_std'
    ],

    yerr=grouped[
        'left_effort_repeat_std'
    ],

    fmt='o',
    capsize=3,

    label='Left wheel'
)


ax.errorbar(

    grouped[
        'right_velocity_mean'
    ],

    grouped[
        'right_effort_mean'
    ],

    xerr=grouped[
        'right_velocity_repeat_std'
    ],

    yerr=grouped[
        'right_effort_repeat_std'
    ],

    fmt='s',
    capsize=3,

    label='Right wheel'
)


# ==============================================================
# Fit curves
# ==============================================================

velocity_values = np.concatenate([

    grouped[
        'left_velocity_mean'
    ].values,

    grouped[
        'right_velocity_mean'
    ].values,
])


velocity_values = velocity_values[
    np.isfinite(
        velocity_values
    )
]


if len(
    velocity_values
) > 0:

    omega_min = np.min(
        velocity_values
    )

    omega_max = np.max(
        velocity_values
    )

    # negative and positive branches separately
    omega_negative = np.linspace(
        omega_min,
        -0.01,
        200
    )

    omega_positive = np.linspace(
        0.01,
        omega_max,
        200
    )

    for omega_fit in [
        omega_negative,
        omega_positive
    ]:

        left_fit = (

            left_model[0]

            +

            left_model[1]
            *
            np.sign(
                omega_fit
            )

            +

            left_model[2]
            *
            omega_fit
        )

        right_fit = (

            right_model[0]

            +

            right_model[1]
            *
            np.sign(
                omega_fit
            )

            +

            right_model[2]
            *
            omega_fit
        )


        ax.plot(
            omega_fit,
            left_fit,
            linestyle='--',
            linewidth=1.2
        )

        ax.plot(
            omega_fit,
            right_fit,
            linestyle=':',
            linewidth=1.2
        )


ax.axhline(
    0.0,
    linewidth=0.8
)

ax.axvline(
    0.0,
    linewidth=0.8
)


ax.set_xlabel(
    'Measured angular velocity (rad/s)'
)

ax.set_ylabel(
    'Steady-state effort (N·m)'
)

ax.set_title(
    'Dynamic drivetrain friction'
)

ax.grid(
    True,
    alpha=0.25
)

ax.legend(
    frameon=False
)

fig.tight_layout()

save_figure(
    fig,
    'mit_dynamic_friction_curve'
)


# ==============================================================
# Figure 4
# Directional friction magnitude
#
# 논문에서 전/후진 비대칭을 보기 편함
# ==============================================================

fig, ax = plt.subplots(
    figsize=(6.3, 4.6)
)


ax.scatter(
    np.abs(
        grouped[
            'left_velocity_mean'
        ]
    ),

    np.abs(
        grouped[
            'left_effort_mean'
        ]
    ),

    label='Left wheel'
)


ax.scatter(
    np.abs(
        grouped[
            'right_velocity_mean'
        ]
    ),

    np.abs(
        grouped[
            'right_effort_mean'
        ]
    ),

    label='Right wheel'
)


ax.set_xlabel(
    'Angular speed magnitude (rad/s)'
)

ax.set_ylabel(
    'Effort magnitude (N·m)'
)

ax.set_title(
    'Dynamic friction magnitude'
)

ax.grid(
    True,
    alpha=0.25
)

ax.legend(
    frameon=False
)

fig.tight_layout()

save_figure(
    fig,
    'mit_dynamic_friction_magnitude'
)


print()
print(
    '=========================================='
)

print(
    'FITTED FRICTION MODEL'
)

print(
    'tau = tau_bias + tau_c sign(omega) + b omega'
)

print()

print(
    model_df.to_string(
        index=False
    )
)

print()
print(
    f'Output directory: {output_dir}'
)

print(
    'PNG: 600 dpi'
)

print(
    'PDF/SVG: vector'
)

print(
    '=========================================='
)
