"""Start DORI's physical actuators, sensors and safety supervisor."""

import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription, OpaqueFunction
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from dori_hardware.startup_checks import CAN_INTERFACE, CAN_WAIT_TIMEOUT, DXL_PORT, DXL_BAUDRATE, IMU_PORT, validate_devices


def check_devices(context):
    value = lambda name: LaunchConfiguration(name).perform(context)
    resolved = validate_devices(value("can_interface"), {
        "Dynamixel": value("dxl_port"), "IMU": value("imu_port"),
    }, can_wait_timeout=value("can_wait_timeout"), dxl_baudrate=value("dxl_baudrate"))
    if resolved:
        context.launch_configurations["dxl_port"] = resolved["Dynamixel"]
    return []


def generate_launch_description():
    return LaunchDescription(
        [
            DeclareLaunchArgument("use_joystick", default_value="false"),
            DeclareLaunchArgument("can_interface", default_value=CAN_INTERFACE),
            DeclareLaunchArgument("can_wait_timeout", default_value=CAN_WAIT_TIMEOUT),
            DeclareLaunchArgument("dxl_port", default_value=DXL_PORT),
            DeclareLaunchArgument("dxl_baudrate", default_value=DXL_BAUDRATE),
            DeclareLaunchArgument("imu_port", default_value=IMU_PORT),
            OpaqueFunction(function=check_devices),
            IncludeLaunchDescription(
                PythonLaunchDescriptionSource(
                    os.path.join(
                        get_package_share_directory("dori_hardware"),
                        "launch",
                        "system_real_with_imu.launch.py",
                    )
                ),
                launch_arguments={
                    "use_joystick": LaunchConfiguration("use_joystick"),
                    **{k: LaunchConfiguration(k) for k in ("can_interface", "dxl_port", "dxl_baudrate", "imu_port")},
                    # The legacy virtual VLM keyboard publishes normalized AUTO
                    # inputs directly; it must never compete with the TTA bridge.
                    "use_input_nodes": "false",
                    "use_wheel_odometry": "false",
                    "odom_publish_tf": "false",
                }.items(),
            ),
        ]
    )
