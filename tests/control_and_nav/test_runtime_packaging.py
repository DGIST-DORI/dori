"""Portable source paths and launch contracts; never starts hardware nodes."""
import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from launch import LaunchContext, LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription, SetLaunchConfiguration
from launch_ros.actions import Node
from launch.utilities import normalize_to_list_of_substitutions, perform_substitutions
from ament_index_python.packages import get_package_share_directory

ROOT = Path(__file__).resolve().parents[2]


class RuntimePackaging(unittest.TestCase):
    def test_integrated_hardware_blocks_inherited_virtual_auto_input(self):
        """Expand include arguments/conditions without executing any ROS node."""
        path = Path(get_package_share_directory('dori_hardware'))/'launch/real_hardware.launch.py'
        spec = importlib.util.spec_from_file_location('integrated_hardware_launch', path)
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        context = LaunchContext()
        # A parent's stale CLI setting must not introduce an AUTO publisher.
        context.launch_configurations['use_input_nodes'] = 'true'
        active = []
        def expand(actions):
            for action in actions:
                condition = getattr(action, 'condition', None)
                if condition is not None and not condition.evaluate(context): continue
                if isinstance(action, Node):
                    active.append(perform_substitutions(context, normalize_to_list_of_substitutions(action.node_executable)))
                elif isinstance(action, LaunchDescription):
                    expand(action.entities)
                elif isinstance(action, (DeclareLaunchArgument, SetLaunchConfiguration)):
                    action.execute(context)
                elif isinstance(action, IncludeLaunchDescription):
                    expand(action.execute(context))
        expand(module.generate_launch_description().entities)
        self.assertNotIn('virtual_vlm_input_node', active)
        self.assertNotIn('keyboard_input_node', active)
        self.assertNotIn('joystick_input_node', active)
        self.assertEqual(active.count('drive_controller_node'), 1)

    def test_full_hardware_launch_constructs_without_removed_dependencies(self):
        context = LaunchContext()
        for filename in ('system_real.launch.py', 'system_real_with_imu.launch.py'):
            with self.subTest(launch=filename):
                path = Path(get_package_share_directory('dori_hardware'))/'launch'/filename
                spec = importlib.util.spec_from_file_location('hardware_launch', path)
                module = importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
                description = module.generate_launch_description()
                nodes = [action for action in description.entities if isinstance(action, Node)]
                self.assertTrue(nodes)
                for action in description.entities:
                    if isinstance(action, DeclareLaunchArgument):action.execute(context)
                executables = [perform_substitutions(context, normalize_to_list_of_substitutions(node.node_executable)) for node in nodes]
                if filename == 'system_real.launch.py':
                    self.assertEqual(executables.count('transform_controller_node'), 1)
                    self.assertEqual(executables.count('drive_controller_node'), 1)
                else:
                    self.assertIn('servo3_pitch_follower_node', executables)

    def test_installed_packages_belong_to_this_workspace(self):
        for package in ['dori_hardware', 'dori_mapping', 'dori_navigation', 'imu_serial']:
            share = Path(get_package_share_directory(package))
            self.assertTrue(share.is_relative_to(ROOT/'ros2_ws/install'), share)

    def test_mapping_uses_external_lidar_odom_without_imu(self):
        path = ROOT/'ros2_ws/src/dori_mapping/launch/lidar_only_cartographer.launch.py'
        spec = importlib.util.spec_from_file_location('mapping_launch', path)
        module = importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        context = LaunchContext()
        for action in module.generate_launch_description().entities:
            if isinstance(action, DeclareLaunchArgument):
                action.execute(context)
        with tempfile.TemporaryDirectory() as directory, patch('tempfile.gettempdir', return_value=directory):
            nodes = module._render_cartographer_config(context)
            files = list((Path(directory)/'lidar_only_slam').glob('*.lua'))
            self.assertEqual(len(files), 1)
            text = files[0].read_text()
            for expected in ['use_odometry = true', 'provide_odom_frame = false',
                             'published_frame = "odom"', 'tracking_frame = "base_link"',
                             'TRAJECTORY_BUILDER_2D.use_imu_data = false']:
                self.assertIn(expected, text)
            self.assertNotIn('__', text)
            self.assertEqual(len(nodes), 5)

    def test_no_old_workspace_path_in_runtime(self):
        for folder in ['scripts', 'ros2_ws/src/dori_navigation', 'ros2_ws/src/dori_mapping']:
            for path in (ROOT/folder).rglob('*'):
                if path.suffix in ('.py', '.sh', '.yaml', '.xml', '.cpp'):
                    for old_folder in ('robot_ws', 'dori_ws'):
                        self.assertNotIn('/home/dori/'+old_folder, path.read_text(), str(path))


if __name__ == '__main__':
    unittest.main()
