import math,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from measure_odometry import metrics

class DistanceMeasurement(unittest.TestCase):
    def test_origin_heading_and_scale(self):
        m=metrics((12.,-8.,math.pi/2),(12.,-7.5,math.pi/2),.5,0.,1.,.1)
        self.assertAlmostEqual(m['odom_forward_m'],.5)
        self.assertAlmostEqual(m['odom_lateral_m'],0.)
        self.assertAlmostEqual(m['distance_error_percent'],-50)
        self.assertAlmostEqual(m['suggested_odom_scale'],.2)
    def test_correct_one_metre(self):
        m=metrics((3.,4.,0.),(4.,4.,0.),1.,0.,1.,1.)
        self.assertEqual(m['distance_error_m'],0.)
        self.assertEqual(m['suggested_odom_scale'],1.)
    def test_no_scale_guess_for_invalid_run(self):
        for end,path,yaw in [((0.,0.,0.),0.,0.),((-1.,0.,0.),1.,0.),((1.,.4,0.),1.1,0.),((1.,0.,.3),1.,.3),((1.,0.,0.),2.,0.)]:
            self.assertIsNone(metrics((0.,0.,0.),end,path,yaw,1.,1.)['suggested_odom_scale'])
if __name__=='__main__':unittest.main()
