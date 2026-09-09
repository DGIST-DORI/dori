from __future__ import annotations

from pathlib import Path

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, ExecuteProcess, GroupAction, IncludeLaunchDescription
from launch.conditions import IfCondition
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node, SetRemap


def generate_launch_description() -> LaunchDescription:
    root_dir = Path(__file__).resolve().parents[1]
    nav2_bringup_dir = Path(get_package_share_directory("nav2_bringup"))

    nav2_params_default = str(root_dir / "config" / "nav2_isaac.yaml")
    default_named_points = str(root_dir / "config" / "points.example.csv")
    rviz_default = str(root_dir / "config" / "isaac_nav2.rviz")
    odom_bridge_script = str(root_dir / "scripts" / "odom_to_tf.py")
    scan_restamp_script = str(root_dir / "scripts" / "restamp_scan.py")
    named_goal_bridge_script = str(root_dir / "scripts" / "named_goal_bridge.py")
    llm_named_goal_script = str(root_dir / "scripts" / "text_llm_named_goal.py")
    initial_pose_script = str(root_dir / "scripts" / "publish_initial_pose_from_odom.py")
    keyboard_viewer_script = str(root_dir / "keyboard_Drive" / "viewer.py")

    use_sim_time = LaunchConfiguration("use_sim_time")
    params_file = LaunchConfiguration("params_file")
    map_yaml = LaunchConfiguration("map")
    odom_topic = LaunchConfiguration("odom_topic")
    output_odom_topic = LaunchConfiguration("output_odom_topic")
    autostart = LaunchConfiguration("autostart")
    rviz = LaunchConfiguration("rviz")
    rviz_config = LaunchConfiguration("rviz_config")
    keyboard = LaunchConfiguration("keyboard")
    auto_initial_pose = LaunchConfiguration("auto_initial_pose")
    image_topic = LaunchConfiguration("image_topic")
    cmd_vel_topic = LaunchConfiguration("cmd_vel_topic")
    input_scan_topic = LaunchConfiguration("input_scan_topic")
    output_scan_topic = LaunchConfiguration("output_scan_topic")
    tf_topic = LaunchConfiguration("tf_topic")
    tf_static_topic = LaunchConfiguration("tf_static_topic")
    named_nav = LaunchConfiguration("named_nav")
    named_points_file = LaunchConfiguration("named_points_file")
    named_goal_topic = LaunchConfiguration("named_goal_topic")
    llm_nav = LaunchConfiguration("llm_nav")
    llm_prompt_file = LaunchConfiguration("llm_prompt_file")
    navigation_mode_topic = LaunchConfiguration("navigation_mode_topic")
    navigation_text_topic = LaunchConfiguration("navigation_text_topic")
    navigation_status_topic = LaunchConfiguration("navigation_status_topic")
    navigation_busy_topic = LaunchConfiguration("navigation_busy_topic")
    localization_launch = nav2_bringup_dir / "launch" / "localization_launch.py"
    navigation_launch = nav2_bringup_dir / "launch" / "navigation_launch.py"

    return LaunchDescription(
        [
            DeclareLaunchArgument("use_sim_time", default_value="true"),
            DeclareLaunchArgument("params_file", default_value=nav2_params_default),
            DeclareLaunchArgument("map"),
            DeclareLaunchArgument("odom_topic", default_value="/odom"),
            DeclareLaunchArgument("output_odom_topic", default_value="/nav2/odom_restamped"),
            DeclareLaunchArgument("autostart", default_value="true"),
            DeclareLaunchArgument("rviz", default_value="false"),
            DeclareLaunchArgument("rviz_config", default_value=rviz_default),
            DeclareLaunchArgument("keyboard", default_value="false"),
            DeclareLaunchArgument("auto_initial_pose", default_value="false"),
            DeclareLaunchArgument("image_topic", default_value="/rgb"),
            DeclareLaunchArgument("cmd_vel_topic", default_value="/cmd_vel"),
            DeclareLaunchArgument("input_scan_topic", default_value="/scan"),
            DeclareLaunchArgument("output_scan_topic", default_value="/nav2/scan_restamped"),
            DeclareLaunchArgument("tf_topic", default_value="/tf_nav"),
            DeclareLaunchArgument("tf_static_topic", default_value="/tf_static_nav"),
            DeclareLaunchArgument("named_nav", default_value="false"),
            DeclareLaunchArgument("named_points_file", default_value=default_named_points),
            DeclareLaunchArgument("named_goal_topic", default_value="/named_goal"),
            DeclareLaunchArgument("llm_nav", default_value="false"),
            DeclareLaunchArgument("llm_prompt_file", default_value=str(root_dir / "prompt.txt")),
            DeclareLaunchArgument("navigation_mode_topic", default_value="/NAVIGATION_MODE"),
            DeclareLaunchArgument("navigation_text_topic", default_value="/NAVIGATION_TEXT"),
            DeclareLaunchArgument("navigation_status_topic", default_value="/NAVIGATION_STATUS"),
            DeclareLaunchArgument("navigation_busy_topic", default_value="/NAVIGATION_BUSY"),
            Node(
                package="tf2_ros",
                executable="static_transform_publisher",
                name="base_link_to_base_scan_tf",
                arguments=[
                    "--x",
                    "0",
                    "--y",
                    "0",
                    "--z",
                    "0",
                    "--roll",
                    "0",
                    "--pitch",
                    "0",
                    "--yaw",
                    "0",
                    "--frame-id",
                    "base_link",
                    "--child-frame-id",
                    "base_scan",
                ],
                parameters=[{"use_sim_time": use_sim_time}],
                remappings=[("/tf_static", tf_static_topic)],
                output="screen",
            ),
            ExecuteProcess(
                cmd=[
                    "/usr/bin/python3",
                    odom_bridge_script,
                    "--ros-args",
                    "-r",
                    ["/tf:=", tf_topic],
                    "-p",
                    ["odom_topic:=", odom_topic],
                    "-p",
                    ["output_odom_topic:=", output_odom_topic],
                    "-p",
                    ["restamp_to_clock:=true"],
                    "-p",
                    ["use_sim_time:=", use_sim_time],
                ],
                output="screen",
            ),
            ExecuteProcess(
                cmd=[
                    "/usr/bin/python3",
                    scan_restamp_script,
                    "--ros-args",
                    "-p",
                    ["input_scan_topic:=", input_scan_topic],
                    "-p",
                    ["output_scan_topic:=", output_scan_topic],
                    "-p",
                    ["use_sim_time:=", use_sim_time],
                ],
                output="screen",
            ),
            ExecuteProcess(
                cmd=[
                    "/usr/bin/python3",
                    named_goal_bridge_script,
                    "--ros-args",
                    "-p",
                    ["points_file:=", named_points_file],
                    "-p",
                    ["goal_topic:=", named_goal_topic],
                    "-p",
                    ["use_sim_time:=", use_sim_time],
                ],
                output="screen",
                condition=IfCondition(named_nav),
            ),
            ExecuteProcess(
                cmd=[
                    "/usr/bin/python3",
                    llm_named_goal_script,
                    "--ros-args",
                    "-p",
                    ["points_file:=", named_points_file],
                    "-p",
                    ["prompt_file:=", llm_prompt_file],
                    "-p",
                    ["goal_topic:=", named_goal_topic],
                    "-p",
                    "input_mode:=topic",
                    "-p",
                    ["navigation_mode_topic:=", navigation_mode_topic],
                    "-p",
                    ["navigation_text_topic:=", navigation_text_topic],
                    "-p",
                    ["navigation_status_topic:=", navigation_status_topic],
                    "-p",
                    ["navigation_busy_topic:=", navigation_busy_topic],
                    "-p",
                    ["use_sim_time:=", use_sim_time],
                ],
                output="screen",
                condition=IfCondition(llm_nav),
            ),
            GroupAction(
                actions=[
                    SetRemap(src="tf", dst=tf_topic),
                    SetRemap(src="/tf", dst=tf_topic),
                    SetRemap(src="tf_static", dst=tf_static_topic),
                    SetRemap(src="/tf_static", dst=tf_static_topic),
                    IncludeLaunchDescription(
                        PythonLaunchDescriptionSource(str(localization_launch)),
                        launch_arguments={
                            "map": map_yaml,
                            "use_sim_time": use_sim_time,
                            "params_file": params_file,
                            "autostart": autostart,
                            "use_composition": "False",
                            "use_respawn": "False",
                        }.items(),
                    ),
                    IncludeLaunchDescription(
                        PythonLaunchDescriptionSource(str(navigation_launch)),
                        launch_arguments={
                            "use_sim_time": use_sim_time,
                            "params_file": params_file,
                            "autostart": autostart,
                            "use_composition": "False",
                            "use_respawn": "False",
                        }.items(),
                    ),
                ]
            ),
            ExecuteProcess(
                cmd=[
                    "/usr/bin/python3",
                    initial_pose_script,
                    "--ros-args",
                    "-p",
                    ["odom_topic:=", output_odom_topic],
                    "-p",
                    ["use_sim_time:=", use_sim_time],
                ],
                output="screen",
                condition=IfCondition(auto_initial_pose),
            ),
            Node(
                package="rviz2",
                executable="rviz2",
                name="rviz2",
                arguments=["-d", rviz_config],
                parameters=[{"use_sim_time": use_sim_time}],
                remappings=[
                    ("/tf", tf_topic),
                    ("/tf_static", tf_static_topic),
                ],
                output="screen",
                condition=IfCondition(rviz),
            ),
            ExecuteProcess(
                cmd=[
                    "/usr/bin/python3",
                    keyboard_viewer_script,
                    "--image_topic",
                    image_topic,
                ],
                output="screen",
                condition=IfCondition(keyboard),
            ),
        ]
    )
