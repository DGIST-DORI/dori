"""App, voice and HRI development with optional perception."""
from launch import LaunchDescription
from launch.actions import OpaqueFunction
from dori_bringup.configuration import arguments
from dori_bringup.launch_support import prepare, services


def setup(context):
    return prepare(context) + services(context)


def generate_launch_description():
    return LaunchDescription(arguments("desktop", fixed=True) + [OpaqueFunction(function=setup)])
