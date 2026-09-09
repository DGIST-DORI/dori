import sys,math,unittest,os
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src/robot_mapping/scripts'))
from imu_rotation import rotation,vector,covariance
class ImuRotation(unittest.TestCase):
    def setUp(self):self.r=rotation([math.pi,0.,math.pi/2])
    def test_observed_gravity_and_nose_up_and_left_turn(self):
        for source,expected in [([0,0,-9.81],[0,0,9.81]),([-1,0,0],[0,-1,0]),([0,0,-1],[0,0,1]),([0,1,0],[1,0,0])]:
            for x,y in zip(vector(self.r,source),expected):self.assertAlmostEqual(x,y)
    def test_covariance_changes_axes_and_cross_terms(self):
        actual=covariance(self.r,[1,.1,.2,.1,2,.3,.2,.3,3])
        for x,y in zip(actual,[2,.1,-.3,.1,1,-.2,-.3,-.2,3]):self.assertAlmostEqual(x,y)
    def test_ros_executable_permission(self):
        path=Path(__file__).resolve().parents[1]/'src/robot_mapping/scripts/mapping_imu.py'
        self.assertTrue(os.access(path,os.X_OK))
    def test_unknown_covariance_preserved(self):
        c=[-1,0,0,0,0,0,0,0,0];self.assertEqual(covariance(self.r,c),c)
if __name__=='__main__':unittest.main()
