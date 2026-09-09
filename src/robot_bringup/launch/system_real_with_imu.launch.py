from launch import LaunchDescription
from launch.actions import IncludeLaunchDescription, DeclareLaunchArgument
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from ament_index_python.packages import get_package_share_directory
import os


def generate_launch_description():

    use_joystick = LaunchConfiguration("use_joystick")

    share = get_package_share_directory("robot_bringup")

    # ============================================================
    # Base robot system
    #
    # 주의:
    # drive_controller_node는 system_real.launch.py 안에서 실행됨.
    # 따라서 drive controller 관련 파라미터는
    # system_real.launch.py 쪽 Node 정의에 넣어야 함.
    # ============================================================

    robot_system = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(
                share,
                "launch",
                "system_real.launch.py"
            )
        ),
        launch_arguments={
            "use_joystick": use_joystick,
            "use_wheel_odometry": LaunchConfiguration("use_wheel_odometry"),
            "odom_publish_tf": LaunchConfiguration("odom_publish_tf"),
            "odom_scale": LaunchConfiguration("odom_scale"),
        }.items()
    )

    # ============================================================
    # IMU raw data
    # ============================================================

    imu_node = Node(
        package="imu_serial",
        executable="imu_node",
        name="imu_node",
        output="screen"
    )

    # ============================================================
    # Body pitch estimator
    #
    # 수정된 IMU 부호 기준:
    # gyro_rate = -gx
    #
    # /body/pitch와 /body/pitch_rate가
    # 동일한 +pitch 방향을 사용해야 함.
    # ============================================================

    body_pitch_node = Node(
        package="imu_serial",
        executable="body_pitch_node",
        name="body_pitch_node",
        output="screen",
        parameters=[{
            "alpha": 0.98,
            "gyro_deadband": 0.002,
        }]
    )

    # ============================================================
    # Body stabilization PD
    #
    # tau =
    #    * (target - pitch)
    #   - Kd * pitch_rate
    #
    # IMU 부호를 수정했으므로 기존 gain을 그대로 쓰지 않고
    # 낮은 값에서 다시 튜닝.
    # ============================================================

    body_stabilizer_node = Node(
        package="imu_serial",
        executable="body_stabilizer_node",
        name="body_stabilizer_node",
        output="screen",
        parameters=[{
            "target_pitch_deg": 0.0,

            # ----------------------------------------------------
            # PD gains
            # ----------------------------------------------------

            "kp": 0.0,
            "kd": 0.0,

            # ----------------------------------------------------
            # Torque limit
            # ----------------------------------------------------

            "max_torque": 0.0,

            # ----------------------------------------------------
            # P deadband
            #
            # 기존 5 deg는 너무 커서
            # 작은 기울기에서 P가 꺼지는 문제가 있었음.
            # ----------------------------------------------------

            "angle_deadband_deg": 1.0,

            # ----------------------------------------------------
            # Controller frequency
            # ----------------------------------------------------

            "control_frequency_hz": 100.0,

            # ----------------------------------------------------
            # IMU timeout
            # ----------------------------------------------------

            "sensor_timeout_sec": 0.10,
        }]
    )

    # ============================================================
    # Servo 3 pitch follower
    #
    # servo =
    #   center
    #   + direction * pitch
    #   + direction * Kff * pitch_rate_deg_s
    #
    # Safety:
    # 135 ~ 225 deg
    #
    # logical motor 5
    #   -> Dynamixel ID 3
    # ============================================================

    servo3_pitch_follower_node = Node(
        package="imu_serial",
        executable="servo3_pitch_follower_node",
        name="servo3_pitch_follower_node",
        output="screen",
        parameters=[{

            # ----------------------------------------------------
            # Dynamixel
            # ----------------------------------------------------

            "logical_motor_id": 5,

            # ----------------------------------------------------
            # Servo center / safety range
            # ----------------------------------------------------

            "center_deg": 180.0,

            "min_deg": 135.0,
            "max_deg": 225.0,

            # ----------------------------------------------------
            # Direction
            # ----------------------------------------------------

            "direction": 1.0,

            # ----------------------------------------------------
            # Pitch deadband
            # ----------------------------------------------------

            "pitch_deadband_deg": 0.5,

            # ----------------------------------------------------
            # Minimum command change
            # ----------------------------------------------------

            "command_threshold_deg": 0.2,

            # ----------------------------------------------------
            # DXL command frequency
            # ----------------------------------------------------

            "command_rate_hz": 30.0,

            # ----------------------------------------------------
            # Pitch-rate feedforward
            #
            # 현재 네가 튜닝해서 안정적으로 쓴 값 유지
            # 0.08 이상에서 진동이 있었다면
            # 실제 최종값은 안정된 값으로 조정하면 됨.
            # ----------------------------------------------------

            "pitch_rate_ff_gain": 0.05,

            # ----------------------------------------------------
            # Pitch-rate safety clamp
            # ----------------------------------------------------

            "pitch_rate_limit_deg_s": 180.0,
        }]
    )

    # ============================================================
    # Launch
    # ============================================================

    return LaunchDescription([

        DeclareLaunchArgument("use_wheel_odometry", default_value="true"),
        DeclareLaunchArgument("odom_publish_tf", default_value="true"),
        DeclareLaunchArgument("odom_scale", default_value="1.0"),

        DeclareLaunchArgument(
            "use_joystick",
            default_value="true",
            description="Enable joystick control"
        ),

        robot_system,

        imu_node,
        body_pitch_node,
        body_stabilizer_node,

        servo3_pitch_follower_node,
    ])
