from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.conditions import IfCondition
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
from launch_ros.actions import Node
from launch_ros.substitutions import FindPackageShare


def generate_launch_description():
    use_fake_joint_states = LaunchConfiguration("use_fake_joint_states")
    use_input_nodes = LaunchConfiguration("use_input_nodes")

    supervisor_params = PathJoinSubstitution([
        FindPackageShare("robot_supervisor"),
        "config",
        "supervisor_params.yaml",
    ])

    drive_params = PathJoinSubstitution([
        FindPackageShare("robot_drive"),
        "config",
        "drive_params.yaml",
    ])

    transform_params = PathJoinSubstitution([
        FindPackageShare("robot_transform"),
        "config",
        "transform_params.yaml",
    ])

    return LaunchDescription([
        DeclareLaunchArgument(
            "use_fake_joint_states",
            default_value="true",
            description="Use fake joint states node for transform testing"
        ),
        DeclareLaunchArgument(
            "use_input_nodes",
            default_value="true",
            description="Launch keyboard_input_node and virtual_vlm_input_node"
        ),

        Node(
            package="robot_supervisor",
            executable="mode_manager_node",
            name="mode_manager_node",
            parameters=[supervisor_params],
            output="screen",
        ),

        Node(
            package="robot_drive",
            executable="drive_controller_node",
            name="drive_controller_node",
            parameters=[drive_params],
            output="screen",
        ),

        Node(
            package="robot_transform",
            executable="transform_manager_node",
            name="transform_manager_node",
            parameters=[transform_params],
            output="screen",
        ),

        Node(
            package="robot_transform",
            executable="transform_controller_node",
            name="transform_controller_node",
            parameters=[transform_params],
            output="screen",
        ),

        Node(
            package="robot_error",
            executable="error_manager_node",
            name="error_manager_node",
            output="screen",
        ),

        Node(
            package="robot_input",
            executable="keyboard_input_node",
            name="keyboard_input_node",
            condition=IfCondition(use_input_nodes),
            output="screen",
        ),

        Node(
            package="robot_input",
            executable="virtual_vlm_input_node",
            name="virtual_vlm_input_node",
            condition=IfCondition(use_input_nodes),
            output="screen",
        ),

        Node(
            package="robot_transform",
            executable="fake_joint_states_node",
            name="fake_joint_states_node",
            parameters=[transform_params],
            condition=IfCondition(use_fake_joint_states),
            output="screen",
        ),
    ])
