import importlib.util
import tempfile
import unittest
from pathlib import Path
import sys
import yaml
from launch import LaunchContext
from launch.actions import DeclareLaunchArgument
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src/robot_mapping/scripts'))
from imu_calibration import load_calibration

class MappingModes(unittest.TestCase):
    def test_tf_ownership_and_imu_gate(self):
        spec=importlib.util.spec_from_file_location('mapping_launch',ROOT/'src/robot_mapping/launch/lidar_only_cartographer.launch.py')
        m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'imu.yaml';c={'verified':True,'frame_id':'imu_link','mapping_frame_id':'imu_mapping','xyz_m':[0,0,0.1],'rpy_rad':[3.14159,0,0],'gyro_bias_rad_s':[.1,0,0]};path.write_text(yaml.safe_dump(c))
            for wheel,external,imu in [(True,False,False),(False,False,False),(False,True,False),(False,True,True),(True,True,True)]:
                ctx=LaunchContext()
                for action in m.generate_launch_description().entities:
                    if isinstance(action,DeclareLaunchArgument):action.execute(ctx)
                ctx.launch_configurations.update(use_wheel_odometry=str(wheel).lower(),external_odom_tf=str(external).lower(),imu_calibration_file=str(path) if imu else '')
                nodes=m._render_cartographer_config(ctx)
                # Rendering writes the configuration, but no ROS processes are executed.
                files=list((Path(tempfile.gettempdir())/'lidar_only_slam').glob('cartographer_2d_lidar_*.lua'))
                text=max(files,key=lambda p:p.stat().st_mtime_ns).read_text()
                self.assertNotIn('__',text)
                self.assertIn('use_odometry = '+str(wheel).lower(),text)
                self.assertIn('provide_odom_frame = '+str(not(wheel or external)).lower(),text)
                self.assertIn('tracking_frame = "'+('imu_mapping' if imu else 'base_link')+'"',text)
                self.assertIn('TRAJECTORY_BUILDER_2D.use_imu_data = '+str(imu).lower(),text)
            c['verified']=False;path.write_text(yaml.safe_dump(c))
            with self.assertRaises(ValueError):load_calibration(path)
            c['verified']=True;c['rpy_rad'][0]=float('nan');path.write_text(yaml.safe_dump(c))
            with self.assertRaises(ValueError):load_calibration(path)
if __name__=='__main__':unittest.main()
