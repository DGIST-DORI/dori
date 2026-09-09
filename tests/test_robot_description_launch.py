#!/usr/bin/env python3
"""Evaluate installed launch robot_description without launching hardware processes."""
import ast
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from ament_index_python.packages import get_package_share_directory
from launch import LaunchContext
from launch_ros.utilities import evaluate_parameters, normalize_parameters


class RobotDescriptionLaunchTest(unittest.TestCase):
    def test_installed_descriptions_are_explicit_strings(self):
        root=Path(get_package_share_directory('robot_bringup'))/'launch'
        for name in ['system_real.launch.py','breakaway_hardware.launch.py','friction_torque_test.launch.py']:
            with self.subTest(launch=name):
                tree=ast.parse((root/name).read_text())
                fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='generate_launch_description')
                # Stop before Node actions; retain the real imports/substitutions/parameter declaration.
                index=next(i for i,n in enumerate(fn.body) if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='robot_description' for t in n.targets))
                fn.body=fn.body[:index+1]+[ast.Return(value=ast.Name(id='robot_description',ctx=ast.Load()))]
                ast.fix_missing_locations(tree)
                namespace={};exec(compile(tree,str(root/name),'exec'),namespace)
                value=evaluate_parameters(LaunchContext(),normalize_parameters([namespace['generate_launch_description']()]))[0]['robot_description']
                self.assertIsInstance(value,str)
                xml=ET.fromstring(value)
                signs={j.attrib['name']:j.find("param[@name='direction_sign']").text for j in xml.findall('ros2_control/joint')}
                ids={j.attrib['name']:j.find("param[@name='can_id']").text for j in xml.findall('ros2_control/joint')}
                self.assertEqual(ids,{'left_wheel_joint':'2','right_wheel_joint':'1'})
                self.assertEqual(signs,{'left_wheel_joint':'1','right_wheel_joint':'-1'})


if __name__=='__main__':unittest.main()
