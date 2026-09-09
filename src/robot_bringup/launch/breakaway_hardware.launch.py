from launch_ros.parameter_descriptions import ParameterValue
from launch import LaunchDescription
from launch.substitutions import (
    PathJoinSubstitution,
    Command,
    FindExecutable,
)

from launch_ros.actions import Node
from launch_ros.substitutions import FindPackageShare


def generate_launch_description():

    # ============================================================
    # Robot description
    # ============================================================

    urdf_file = PathJoinSubstitution([
        FindPackageShare("robot_bringup"),
        "config",
        "cubemars_mit.urdf.xacro",
    ])

    controllers_file = PathJoinSubstitution([
        FindPackageShare("robot_bringup"),
        "config",
        "bldc_controllers.yaml",
    ])

    robot_description = {
        "robot_description": ParameterValue(Command([
            FindExecutable(name="xacro"),
            " ",
            urdf_file,
        ]), value_type=str)
    }

    # ============================================================
    # Launch
    #
    # Breakaway torque 측정용 최소 구성
    #
    # 실행:
    #   ros2_control
    #   joint_state_broadcaster
    #   left/right wheel controller
    #   bldc command bridge
    #
    # 실행하지 않음:
    #   drive_controller_node
    #   transform_controller_node
    #   transform_manager_node
    #   supervisor
    #   joystick
    #   IMU stabilization
    # ============================================================

    return LaunchDescription([

        # ========================================================
        # ros2_control
        # ========================================================

        Node(
            package="controller_manager",
            executable="ros2_control_node",
            parameters=[
                robot_description,
                controllers_file,
            ],
            output="screen",
        ),

        # ========================================================
        # Robot state publisher
        # ========================================================

        Node(
            package="robot_state_publisher",
            executable="robot_state_publisher",
            parameters=[robot_description],
            output="screen",
        ),

        # ========================================================
        # Joint state broadcaster
        #
        # /joint_states 생성
        # ========================================================

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
        # Left wheel controller
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

        # ========================================================
        # Right wheel controller
        # ========================================================

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
        # BLDC command bridge
        #
        # /bldc_mit_speed_cmd
        #       ↓
        # left/right drive controller
        # ========================================================

        Node(
            package="robot_drive",
            executable="bldc_command_bridge_node",
            output="screen",
        ),
    ])

