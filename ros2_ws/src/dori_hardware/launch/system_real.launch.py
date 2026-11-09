from launch_ros.parameter_descriptions import ParameterValue
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, OpaqueFunction
from launch.conditions import IfCondition
from launch.substitutions import (
    LaunchConfiguration,
    PathJoinSubstitution,
    Command,
    FindExecutable,
)
from launch_ros.actions import Node
from launch_ros.substitutions import FindPackageShare
from dori_hardware.startup_checks import CAN_INTERFACE, DXL_PORT, DXL_BAUDRATE, IMU_PORT, LIDAR_PORT
from dori_hardware.serial_identity import resolve_dxl_port


def identify_dynamixel(context):
    context.launch_configurations["dxl_port"] = resolve_dxl_port(
        LaunchConfiguration("dxl_port").perform(context),
        baudrate=LaunchConfiguration("dxl_baudrate").perform(context),
        excluded_ports=[LaunchConfiguration("imu_port", default=IMU_PORT).perform(context),
                        LaunchConfiguration("lidar_port", default=LIDAR_PORT).perform(context)],
    )
    return []


def generate_launch_description():

    # ============================================================
    # Launch arguments
    # ============================================================

    use_input_nodes = LaunchConfiguration("use_input_nodes")
    use_joystick = LaunchConfiguration("use_joystick")

    # ============================================================
    # Parameter / config files
    # ============================================================

    supervisor_params = PathJoinSubstitution(
        [FindPackageShare("dori_supervisor"), "config", "supervisor_params.yaml"]
    )

    drive_params = PathJoinSubstitution(
        [FindPackageShare("dori_control"), "config", "drive_params.yaml"]
    )

    transform_params = PathJoinSubstitution(
        [FindPackageShare("dori_control"), "config", "transform_params.yaml"]
    )

    dxl_bridge_params = PathJoinSubstitution(
        [FindPackageShare("dori_hardware"), "config", "dxl_bridge_params.yaml"]
    )

    urdf_file = PathJoinSubstitution(
        [FindPackageShare("dori_hardware"), "config", "cubemars_mit.urdf.xacro"]
    )

    kinematics_file = PathJoinSubstitution(
        [FindPackageShare("dori_control"), "config", "kinematics.yaml"]
    )

    controllers_file = PathJoinSubstitution(
        [FindPackageShare("dori_hardware"), "config", "bldc_controllers.yaml"]
    )

    # ============================================================
    # Robot description
    # ============================================================

    robot_description = {
        "robot_description": ParameterValue(
            Command([FindExecutable(name="xacro"), " ", urdf_file,
                     " can_interface:=", LaunchConfiguration("can_interface", default=CAN_INTERFACE)]),
            value_type=str
        )
    }

    # ============================================================
    # Nodes
    # ============================================================

    return LaunchDescription(
        [
            # --------------------------------------------------------
            # Launch arguments
            # --------------------------------------------------------
            DeclareLaunchArgument("use_input_nodes", default_value="false"),
            DeclareLaunchArgument("can_interface", default_value=CAN_INTERFACE),
            DeclareLaunchArgument("dxl_port", default_value=DXL_PORT),
            DeclareLaunchArgument("dxl_baudrate", default_value=DXL_BAUDRATE),
            DeclareLaunchArgument("use_joystick", default_value="false"),
            DeclareLaunchArgument("use_wheel_odometry", default_value="false"),
            DeclareLaunchArgument("odom_publish_tf", default_value="false"),
            DeclareLaunchArgument("odom_scale", default_value="1.0"),
            OpaqueFunction(function=identify_dynamixel),
            Node(
                package="dori_control",
                executable="wheel_odometry_node",
                condition=IfCondition(LaunchConfiguration("use_wheel_odometry")),
                parameters=[
                    PathJoinSubstitution(
                        [FindPackageShare("dori_control"), "config", "odometry.yaml"]
                    ),
                    kinematics_file,
                    {
                        "publish_tf": LaunchConfiguration("odom_publish_tf"),
                        "odom_scale": ParameterValue(
                            LaunchConfiguration("odom_scale"), value_type=float
                        ),
                    },
                ],
                output="screen",
            ),
            # ========================================================
            # ros2_control
            # ========================================================
            Node(
                package="controller_manager",
                executable="ros2_control_node",
                parameters=[robot_description, controllers_file],
                output="screen",
            ),
            Node(
                package="robot_state_publisher",
                executable="robot_state_publisher",
                parameters=[robot_description],
                output="screen",
            ),
            Node(
                package="controller_manager",
                executable="spawner",
                arguments=[
                    "joint_state_broadcaster",
                    "--controller-manager",
                    "/controller_manager",
                ],
                output="screen",
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
                    "/controller_manager",
                ],
                output="screen",
            ),
            Node(
                package="controller_manager",
                executable="spawner",
                arguments=[
                    "right_bldc_drive_controller",
                    "--controller-manager",
                    "/controller_manager",
                ],
                output="screen",
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
                    "--inactive",
                ],
                output="screen",
            ),
            Node(
                package="controller_manager",
                executable="spawner",
                arguments=[
                    "right_bldc_effort_controller",
                    "--controller-manager",
                    "/controller_manager",
                    "--inactive",
                ],
                output="screen",
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
                    "--inactive",
                ],
                output="screen",
            ),
            # ========================================================
            # BLDC command bridge
            # ========================================================
            Node(
                package="dori_control",
                executable="bldc_command_bridge_node",
                output="screen",
            ),
            # ========================================================
            # Dynamixel
            # ========================================================
            Node(
                package="dori_hardware",
                executable="dxl_driver_node",
                parameters=[{"device_name": LaunchConfiguration("dxl_port"),
                             "baudrate": ParameterValue(LaunchConfiguration("dxl_baudrate"), value_type=int)}],
                output="screen",
            ),
            Node(
                package="dori_hardware",
                executable="dxl_bridge_node",
                parameters=[dxl_bridge_params],
                output="screen",
            ),
            Node(
                package="dori_hardware",
                executable="dxl_state_publisher_node",
                parameters=[dxl_bridge_params],
                output="screen",
            ),
            # ========================================================
            # Supervisor
            # ========================================================
            Node(
                package="dori_hardware",
                executable="motor4_servo_node",
                parameters=[PathJoinSubstitution(
                    [FindPackageShare("dori_hardware"), "config", "motor4_servo.yaml"]
                ), {"can_interface": LaunchConfiguration("can_interface")}],
                output="screen",
            ),
            Node(
                package="dori_supervisor",
                executable="mode_manager_node",
                parameters=[supervisor_params],
                output="screen",
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
                package="dori_control",
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
                    kinematics_file,
                ],
                output="screen",
            ),
            # ========================================================
            # Transform
            # ========================================================
            Node(
                package="dori_control",
                executable="transform_manager_node",
                parameters=[transform_params],
                output="screen",
            ),
            Node(
                package="dori_control",
                executable="transform_controller_node",
                parameters=[transform_params],
                output="screen",
            ),
            # ========================================================
            # Error manager
            # ========================================================
            Node(
                package="dori_diagnostics",
                executable="error_manager_node",
                output="screen",
            ),
            # ========================================================
            # Keyboard / virtual input
            # ========================================================
            Node(
                package="dori_control",
                executable="keyboard_input_node",
                condition=IfCondition(use_input_nodes),
                output="screen",
            ),
            Node(
                package="dori_control",
                executable="virtual_vlm_input_node",
                condition=IfCondition(use_input_nodes),
                output="screen",
            ),
            # ========================================================
            # Joystick
            # ========================================================
            Node(
                package="joy",
                executable="joy_node",
                condition=IfCondition(use_joystick),
                output="screen",
            ),
            Node(
                package="dori_control",
                executable="joystick_input_node",
                condition=IfCondition(use_joystick),
                parameters=[
                    {
                        "linear_axis": 1,
                        "angular_axis": 0,
                        "linear_scale": 1.0,
                        "angular_scale": 1.0,
                        "deadzone": 0.1,
                        "transform_to_a_button": 0,
                        "transform_to_b_button": 1,
                        "emergency_stop_button": 3,
                        "emergency_go_button": 4,
                        "manual_mode_button": 6,
                        "auto_mode_button": 7,
                        "publish_zero_on_idle": True,
                    }
                ],
                output="screen",
            ),
        ]
    )
