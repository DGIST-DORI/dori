"""Select the complete robot profile (default) or desktop development profile."""
from launch import LaunchDescription
from launch.actions import OpaqueFunction
from launch.substitutions import LaunchConfiguration
from dori_bringup.configuration import DEFAULTS, arguments
from dori_bringup.launch_support import include


def setup(context):
    value = lambda key: LaunchConfiguration(key).perform(context)
    mode = value("dori_mode")
    return [include("dori_bringup", mode + ".launch.py", {
        key: value(key) for key in ("dori_mode", "config_file", *DEFAULTS)
    })]


def generate_launch_description():
    return LaunchDescription(arguments() + [OpaqueFunction(function=setup)])
