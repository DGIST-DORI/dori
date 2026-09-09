from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, OpaqueFunction
from launch.conditions import IfCondition
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def _render_cartographer_config(context, *args, **kwargs):
    root_dir = Path(__file__).resolve().parents[1]
    template_path = root_dir / "config" / "cartographer_2d_lidar.lua.in"
    template_text = template_path.read_text(encoding="utf-8")

    use_odom = LaunchConfiguration("use_wheel_odometry").perform(context).lower() == "true"

    external_odom = use_odom or LaunchConfiguration("external_odom_tf").perform(context).lower() == "true"
    calibration_path=LaunchConfiguration("imu_calibration_file").perform(context)
    use_imu=bool(calibration_path)
    imu_nodes=[]
    if use_imu:
        sys.path.insert(0,str(root_dir / "scripts"))
        from imu_calibration import load_calibration
        c=load_calibration(calibration_path)
        imu_nodes=[
            Node(package="robot_mapping",executable="mapping_imu.py",parameters=[{"calibration_file":calibration_path}],output="screen"),
            Node(package="tf2_ros",executable="static_transform_publisher",name="base_to_mapping_imu_tf",
                 arguments=["--x",str(c['xyz_m'][0]),"--y",str(c['xyz_m'][1]),"--z",str(c['xyz_m'][2]),
                            "--roll",str(c['rpy_rad'][0]),"--pitch",str(c['rpy_rad'][1]),"--yaw",str(c['rpy_rad'][2]),
                            "--frame-id",LaunchConfiguration("base_frame"),"--child-frame-id",c['frame_id']],output="screen")]
    if use_imu and c.get('mapping_frame_id'):
        imu_nodes.append(Node(package='tf2_ros',executable='static_transform_publisher',name='base_to_aligned_imu_tf',
            arguments=['--x',str(c['xyz_m'][0]),'--y',str(c['xyz_m'][1]),'--z',str(c['xyz_m'][2]),
                       '--roll','0','--pitch','0','--yaw','0','--frame-id',LaunchConfiguration('base_frame'),
                       '--child-frame-id',c['mapping_frame_id']],output='screen'))
    replacements = {
        "__TRACKING_FRAME__": c.get("mapping_frame_id", "imu_link") if use_imu else LaunchConfiguration("base_frame").perform(context),
        "__USE_IMU__": "true" if use_imu else "false",
        "__PUBLISHED_FRAME__": LaunchConfiguration("odom_frame" if external_odom else "base_frame").perform(context),
        "__PROVIDE_ODOM_FRAME__": "false" if external_odom else "true",
        "__USE_ODOMETRY__": "true" if use_odom else "false",
        "__MAP_FRAME__": LaunchConfiguration("map_frame").perform(context),
        "__BASE_FRAME__": LaunchConfiguration("base_frame").perform(context),
        "__ODOM_FRAME__": LaunchConfiguration("odom_frame").perform(context),
        "__MIN_RANGE__": LaunchConfiguration("min_range").perform(context),
        "__MAX_RANGE__": LaunchConfiguration("max_range").perform(context),
        "__MISSING_DATA_RAY_LENGTH__": LaunchConfiguration("missing_data_ray_length").perform(context),
        "__SUBMAP_RANGE_DATA__": LaunchConfiguration("submap_range_data").perform(context),
        "__NUM_SUBDIVISIONS__": LaunchConfiguration("num_subdivisions_per_laser_scan").perform(context),
    }

    rendered_text = template_text
    for key, value in replacements.items():
        rendered_text = rendered_text.replace(key, value)

    rendered_dir = Path(tempfile.gettempdir()) / "lidar_only_slam"
    rendered_dir.mkdir(parents=True, exist_ok=True)
    rendered_path = rendered_dir / f"cartographer_2d_lidar_{os.getpid()}_{int(time.time() * 1000)}.lua"
    rendered_path.write_text(rendered_text, encoding="utf-8")

    use_sim_time = LaunchConfiguration("use_sim_time")
    scan_topic = LaunchConfiguration("scan_topic")
    start_lidar_driver = LaunchConfiguration("start_lidar_driver")
    serial_port = LaunchConfiguration("serial_port")
    serial_baudrate = LaunchConfiguration("serial_baudrate")
    scan_mode = LaunchConfiguration("scan_mode")
    lidar_inverted = LaunchConfiguration("lidar_inverted")
    angle_compensate = LaunchConfiguration("angle_compensate")
    rviz = LaunchConfiguration("rviz")
    rviz_config = LaunchConfiguration("rviz_config")
    publish_laser_tf = LaunchConfiguration("publish_laser_tf")
    base_frame = LaunchConfiguration("base_frame")
    laser_frame = LaunchConfiguration("laser_frame")
    laser_x = LaunchConfiguration("laser_x")
    laser_y = LaunchConfiguration("laser_y")
    laser_z = LaunchConfiguration("laser_z")
    laser_roll = LaunchConfiguration("laser_roll")
    laser_pitch = LaunchConfiguration("laser_pitch")
    laser_yaw = LaunchConfiguration("laser_yaw")
    map_resolution = LaunchConfiguration("map_resolution")

    return imu_nodes + [
        Node(
            package="sllidar_ros2",
            executable="sllidar_node",
            name="sllidar_node",
            parameters=[
                {
                    "channel_type": "serial",
                    "serial_port": serial_port,
                    "serial_baudrate": serial_baudrate,
                    "frame_id": laser_frame,
                    "inverted": lidar_inverted,
                    "angle_compensate": angle_compensate,
                    "scan_mode": scan_mode,
                }
            ],
            remappings=[("scan", scan_topic)],
            output="screen",
            condition=IfCondition(start_lidar_driver),
            respawn=True,
            respawn_delay=2.0,
        ),
        Node(
            package="tf2_ros",
            executable="static_transform_publisher",
            name="base_to_laser_tf",
            arguments=[
                "--x",
                laser_x,
                "--y",
                laser_y,
                "--z",
                laser_z,
                "--roll",
                laser_roll,
                "--pitch",
                laser_pitch,
                "--yaw",
                laser_yaw,
                "--frame-id",
                base_frame,
                "--child-frame-id",
                laser_frame,
            ],
            parameters=[{"use_sim_time": use_sim_time}],
            output="screen",
            condition=IfCondition(publish_laser_tf),
        ),
        Node(
            package="cartographer_ros",
            executable="cartographer_node",
            name="cartographer_node",
            arguments=[
                "-configuration_directory",
                str(rendered_dir),
                "-configuration_basename",
                rendered_path.name,
            ],
            parameters=[{"use_sim_time": use_sim_time}],
            remappings=[("scan", scan_topic), ("odom", LaunchConfiguration("odom_topic")), ("imu", "/imu/mapping")],
            output="screen",
        ),
        Node(
            package="cartographer_ros",
            executable="cartographer_occupancy_grid_node",
            name="cartographer_occupancy_grid_node",
            parameters=[
                {"use_sim_time": use_sim_time},
                {"resolution": map_resolution},
            ],
            output="screen",
        ),
        Node(
            package="rviz2",
            executable="rviz2",
            name="rviz2",
            arguments=["-d", rviz_config],
            parameters=[{"use_sim_time": use_sim_time}],
            output="screen",
            condition=IfCondition(rviz),
        ),
    ]


def generate_launch_description() -> LaunchDescription:
    root_dir = Path(__file__).resolve().parents[1]
    rviz_default = str(root_dir / "config" / "lidar_only_mapping.rviz")

    return LaunchDescription(
        [
            DeclareLaunchArgument("use_sim_time", default_value="false"),
            DeclareLaunchArgument("use_wheel_odometry", default_value="false"),
            DeclareLaunchArgument("external_odom_tf", default_value="false"),
            DeclareLaunchArgument("imu_calibration_file", default_value=""),
            DeclareLaunchArgument("odom_topic", default_value="/odom"),
            DeclareLaunchArgument("scan_topic", default_value="/scan"),
            DeclareLaunchArgument("start_lidar_driver", default_value="true"),
            DeclareLaunchArgument("serial_port", default_value="/dev/slamtec_c1"),
            DeclareLaunchArgument("serial_baudrate", default_value="460800"),
            DeclareLaunchArgument("scan_mode", default_value="Standard"),
            DeclareLaunchArgument("lidar_inverted", default_value="false"),
            DeclareLaunchArgument("angle_compensate", default_value="true"),
            DeclareLaunchArgument("map_frame", default_value="map"),
            DeclareLaunchArgument("odom_frame", default_value="odom"),
            DeclareLaunchArgument("base_frame", default_value="base_link"),
            DeclareLaunchArgument("laser_frame", default_value="laser"),
            DeclareLaunchArgument("publish_laser_tf", default_value="true"),
            DeclareLaunchArgument("laser_x", default_value="0.0"),
            DeclareLaunchArgument("laser_y", default_value="0.0"),
            DeclareLaunchArgument("laser_z", default_value="0.0"),
            DeclareLaunchArgument("laser_roll", default_value="0.0"),
            DeclareLaunchArgument("laser_pitch", default_value="0.0"),
            DeclareLaunchArgument("laser_yaw", default_value="0.0"),
            DeclareLaunchArgument("rviz", default_value="false"),
            DeclareLaunchArgument("rviz_config", default_value=rviz_default),
            DeclareLaunchArgument("map_resolution", default_value="0.05"),
            DeclareLaunchArgument("min_range", default_value="0.10"),
            DeclareLaunchArgument("max_range", default_value="16.0"),
            DeclareLaunchArgument("missing_data_ray_length", default_value="16.5"),
            DeclareLaunchArgument("submap_range_data", default_value="35"),
            DeclareLaunchArgument("num_subdivisions_per_laser_scan", default_value="1"),
            OpaqueFunction(function=_render_cartographer_config),
        ]
    )
