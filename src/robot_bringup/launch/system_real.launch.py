from launch_ros.parameter_descriptions import ParameterValue
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.conditions import IfCondition
from launch.substitutions import (
    LaunchConfiguration,
    PathJoinSubstitution,
    Command,
    FindExecutable,
)
from launch_ros.actions import Node
from launch_ros.substitutions import FindPackageShare


def generate_launch_description():

    # ============================================================
    # Launch arguments
    # ============================================================

    use_input_nodes = LaunchConfiguration("use_input_nodes")
    use_joystick = LaunchConfiguration("use_joystick")

    # ============================================================
    # Parameter / config files
    # ============================================================

    supervisor_params = PathJoinSubstitution([
        FindPackageShare("robot_supervisor"),
        "config",
        "supervisor_params.yaml"
    ])

    drive_params = PathJoinSubstitution([
        FindPackageShare("robot_drive"),
        "config",
        "drive_params.yaml"
    ])

    transform_params = PathJoinSubstitution([
        FindPackageShare("robot_transform"),
        "config",
        "transform_params.yaml"
    ])

    dxl_bridge_params = PathJoinSubstitution([
        FindPackageShare("robot_transform"),
        "config",
        "dxl_bridge_params.yaml"
    ])

    urdf_file = PathJoinSubstitution([
        FindPackageShare("robot_bringup"),
        "config",
        "cubemars_mit.urdf.xacro"
    ])

    kinematics_file = PathJoinSubstitution([FindPackageShare("robot_drive"), "config", "kinematics.yaml"])

    controllers_file = PathJoinSubstitution([
        FindPackageShare("robot_bringup"),
        "config",
        "bldc_controllers.yaml"
    ])

    # ============================================================
    # Robot description
    # ============================================================

    robot_description = {
        "robot_description": ParameterValue(Command([
            FindExecutable(name="xacro"),
            " ",
            urdf_file
        ]), value_type=str)
    }

    # ============================================================
    # Nodes
    # ============================================================

    return LaunchDescription([

        # --------------------------------------------------------
        # Launch arguments
        # --------------------------------------------------------

        DeclareLaunchArgument(
            "use_input_nodes",
            default_value="false"
        ),

        DeclareLaunchArgument(
            "use_joystick",
            default_value="false"
        ),

        DeclareLaunchArgument("use_wheel_odometry", default_value="true"),
        DeclareLaunchArgument("odom_publish_tf", default_value="true"),
        DeclareLaunchArgument("odom_scale", default_value="1.0"),
        Node(
            package="robot_drive", executable="wheel_odometry_node",
            condition=IfCondition(LaunchConfiguration("use_wheel_odometry")),
            parameters=[PathJoinSubstitution([
                FindPackageShare("robot_drive"), "config", "odometry.yaml"
            ]), kinematics_file, {"publish_tf": LaunchConfiguration("odom_publish_tf"), "odom_scale": ParameterValue(LaunchConfiguration("odom_scale"), value_type=float)}],
            output="screen"
        ),

        # ========================================================
        # ros2_control
        # ========================================================

        Node(
            package="controller_manager",
            executable="ros2_control_node",
            parameters=[
                robot_description,
                controllers_file
            ],
            output="screen"
        ),

        Node(
            package="robot_state_publisher",
            executable="robot_state_publisher",
            parameters=[
                robot_description
            ],
            output="screen"
        ),

        Node(
            package="controller_manager",
            executable="spawner",
            arguments=[
                "joint_state_broadcaster",
                "--controller-manager",
                "/controller_manager"
            ],
            output="screen"
        ),

        # ========================================================
        # MIT SPEED MODE controllers
        # ========================================================

        Node(
            package="controller_manager",
            executable="spawner",
            arguments=[
                "left_bldc_drive_controller",
                "--controller-manager",
                "/controller_manager"
            ],
            output="screen"
        ),

        Node(
            package="controller_manager",
            executable="spawner",
            arguments=[
                "right_bldc_drive_controller",
                "--controller-manager",
                "/controller_manager"
            ],
            output="screen"
        ),

        # ========================================================
        # Effort-only controllers
        #
        # 필요할 때만 switch해서 사용
        # 현재는 inactive
        # ========================================================

        Node(
            package="controller_manager",
            executable="spawner",
            arguments=[
                "left_bldc_effort_controller",
                "--controller-manager",
                "/controller_manager",
                "--inactive"
            ],
            output="screen"
        ),

        Node(
            package="controller_manager",
            executable="spawner",
            arguments=[
                "right_bldc_effort_controller",
                "--controller-manager",
                "/controller_manager",
                "--inactive"
            ],
            output="screen"
        ),

        # ========================================================
        # Position controller
        # ========================================================

        Node(
            package="controller_manager",
            executable="spawner",
            arguments=[
                "bldc_position_controller",
                "--controller-manager",
                "/controller_manager",
                "--inactive"
            ],
            output="screen"
        ),

        # ========================================================
        # BLDC command bridge
        # ========================================================

        Node(
            package="robot_drive",
            executable="bldc_command_bridge_node",
            output="screen"
        ),

        # ========================================================
        # Dynamixel
        # ========================================================

        Node(
            package="dynamixel_sdk_examples",
            executable="read_write_node",
            output="screen"
        ),

        Node(
            package="robot_transform",
            executable="dxl_bridge_node",
            parameters=[
                dxl_bridge_params
            ],
            output="screen"
        ),

        Node(
            package="robot_transform",
            executable="dxl_state_publisher_node",
            parameters=[
                dxl_bridge_params
            ],
            output="screen"
        ),

        # ========================================================
        # Supervisor
        # ========================================================

        Node(
            package="robot_supervisor",
            executable="mode_manager_node",
            parameters=[
                supervisor_params
            ],
            output="screen"
        ),

        # ========================================================
        # Drive controller
        #
        # drive_params.yaml의 기존 설정을 유지하면서
        # 아래 dictionary 값이 같은 parameter를 override함.
        #
        # 우리가 새로 추가한 stabilization priority 관련 값도
        # 여기서 명확하게 지정.
        # ========================================================

        Node(
            package="robot_drive",
            executable="drive_controller_node",
            name="drive_controller_node",
            parameters=[
                drive_params,

                {
                    # ------------------------------------------------
                    # Robot geometry
                    # ------------------------------------------------

                    "wheel_radius": 0.234,
                    "wheel_separation": 0.184,

                    # ------------------------------------------------
                    # Max velocity
                    # ------------------------------------------------

                    "max_linear_velocity": 1.72,
                    "max_angular_velocity": 7.0,

                    # ------------------------------------------------
                    # Acceleration / deceleration
                    # ------------------------------------------------

                    "linear_accel_limit": 0.5,
                    "linear_decel_limit": 0.3,

                    "angular_accel_limit": 1.0,
                    "angular_decel_limit": 1.0,

                    # ------------------------------------------------
                    # Drive acceleration feedforward
                    #
                    # 이번 단계에서는 기존 구조 유지
                    #
                    # tau_ff =
                    #     feedforward_gain
                    #     * command_linear_accel
                    # ------------------------------------------------

                    "feedforward_enabled": False,
                    "feedforward_gain": 4.0,
                    "feedforward_torque_limit": 6.0,
                    "feedforward_accel_deadband": 0.02,

                    # ------------------------------------------------
                    # Final actuator torque limit
                    # ------------------------------------------------

                    "final_torque_limit": 15.0,

                    # ------------------------------------------------
                    # Drive profiles
                    # ------------------------------------------------

                    "drive_normal_vel_kd": 1.5,
                    "drive_normal_tau_ff": 0.0,

                    "drive_slope_vel_kd": 1.5,
                    "drive_slope_tau_ff": 0.0,

                    "drive_obstacle_vel_kd": 1.5,
                    "drive_obstacle_tau_ff": 0.0,

                    "default_drive_profile": "normal",

                    # ------------------------------------------------
                    # Body stabilization
                    # ------------------------------------------------

                    "stabilization_torque_limit": 13.0,
                    "stabilization_timeout_sec": 0.10,

                    # ------------------------------------------------
                    # NEW:
                    # stabilization priority mixer
                    #
                    # true:
                    # body stabilization torque와 반대 방향의
                    # drive torque가 balance torque를 깎지 못하게 함.
                    # ------------------------------------------------

                    "stabilization_priority_enabled": True,

                    # stabilization torque가 이 값 이상일 때
                    # priority logic 활성화
                    "stabilization_priority_threshold": 0.5,

                    # ------------------------------------------------
                    # Joint state
                    # ------------------------------------------------

                    "left_joint_name": "left_wheel_joint",
                    "right_joint_name": "right_wheel_joint",

                    "joint_state_timeout_sec": 0.20,

                    # ------------------------------------------------
                    # Controller frequency
                    # ------------------------------------------------

                    "control_frequency_hz": 100.0,
                },
                kinematics_file
            ],
            output="screen"
        ),

        # ========================================================
        # Transform
        # ========================================================

        Node(
            package="robot_transform",
            executable="transform_manager_node",
            parameters=[
                transform_params
            ],
            output="screen"
        ),

        Node(
            package="robot_transform",
            executable="transform_controller_node",
            parameters=[
                transform_params
            ],
            output="screen"
        ),

        # ========================================================
        # Error manager
        # ========================================================

        Node(
            package="robot_error",
            executable="error_manager_node",
            output="screen"
        ),

        # ========================================================
        # Keyboard / virtual input
        # ========================================================

        Node(
            package="robot_input",
            executable="keyboard_input_node",
            condition=IfCondition(use_input_nodes),
            output="screen"
        ),

        Node(
            package="robot_input",
            executable="virtual_vlm_input_node",
            condition=IfCondition(use_input_nodes),
            output="screen"
        ),

        # ========================================================
        # Joystick
        # ========================================================

        Node(
            package="joy",
            executable="joy_node",
            condition=IfCondition(use_joystick),
            output="screen"
        ),

        Node(
            package="robot_input",
            executable="joystick_input_node",
            condition=IfCondition(use_joystick),
            parameters=[{
                "linear_axis": 1,
                "angular_axis": 0,

                "linear_scale": 1.0,
                "angular_scale": 1.0,

                "deadzone": 0.1,

                "transform_to_a_button": 0,
                "transform_to_b_button": 1,

                "emergency_stop_button": 3,
                "emergency_go_button": 2,

                "manual_mode_button": 6,
                "auto_mode_button": 7,

                "publish_zero_on_idle": True,
            }],
            output="screen"
        ),
    ])
