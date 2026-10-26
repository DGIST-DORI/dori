import math
from pathlib import Path
import sys
import unittest
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src/robot_mapping'))
from lidar_odometry.core import Odometry, Reference, Settings, RegistrationError, scan_points, transform
from lidar_scene import ranges


def cloud(pose, mounting=(0.,0.,0.), seed=1, noise=0.):
    r = ranges(pose, mounting, noise=noise, seed=seed)
    p = scan_points(r,-math.pi,2*math.pi/len(r),.1,16.)
    return transform(p,np.array(mounting))


class ScanOdometry(unittest.TestCase):
    def test_translation_not_scaled_by_prior(self):
        estimator = Odometry()
        for i in range(51):
            estimator.update(cloud((i*.02,0,0),seed=i,noise=.005),1+i*.1)
        self.assertLess(np.linalg.norm(estimator.pose[:2]-[1,0]),.025)
        self.assertLess(abs(estimator.pose[2]),.008)
        self.assertAlmostEqual(estimator.velocity[0],.2,delta=.05)

    def test_rotation_and_lever_arm_with_backward_lidar(self):
        estimator = Odometry()
        mounting=(.23,.07,math.pi)
        for i in range(81):
            pose=(.5*math.sin(i*.015),.5*(1-math.cos(i*.015)),i*.015)
            estimator.update(cloud(pose,mounting,seed=i,noise=.004),1+i*.1)
        self.assertLess(np.linalg.norm(estimator.pose[:2]-pose[:2]),.03)
        self.assertAlmostEqual(estimator.pose[2],pose[2],delta=.015)

    def test_sudden_rotation_and_braking_recover_yaw_without_reanchoring(self):
        estimator=Odometry()
        for i,a in enumerate([0., .02, .30, .30, .10, -.15]):
            estimator.update(cloud((0,0,a),noise=.003,seed=i),1+i*.1)
            self.assertAlmostEqual(estimator.pose[2],a,delta=.012)
            self.assertLess(np.linalg.norm(estimator.pose[:2]),.02)

    def test_rejected_scan_keeps_reference_and_pose(self):
        estimator = Odometry()
        estimator.update(cloud((0,0,0)),1.)
        reference=estimator.reference
        with self.assertRaises(RegistrationError): estimator.update(np.zeros((2,2)),1.1)
        self.assertIs(reference,estimator.reference)
        np.testing.assert_array_equal(estimator.pose,[0,0,0])
        estimator.update(cloud((.03,0,0)),1.2)
        self.assertAlmostEqual(estimator.pose[0],.03,delta=.005)

    def test_changed_surfaces_refresh_only_after_accepted_registration(self):
        estimator=Odometry();points=cloud((0,0,0))
        estimator.update(points,1.);old=estimator.reference
        # Newly visible surfaces lower overlap without invalidating the old ones.
        added=points[::2]+np.array([20.,20.])
        estimator.update(np.vstack((points,added)),2.2)
        self.assertIsNot(estimator.reference,old)
        self.assertLess(np.linalg.norm(estimator.pose),.01)

    def test_long_gap_is_not_silently_reanchored(self):
        estimator=Odometry();estimator.update(cloud((0,0,0)),1.)
        with self.assertRaises(RegistrationError): estimator.update(cloud((2,0,0)),4.)
        with self.assertRaises(RegistrationError): estimator.update(cloud((2,0,0)),4.1)
        np.testing.assert_array_equal(estimator.pose,[0,0,0])

    def test_gap_recovers_against_original_reference(self):
        estimator=Odometry();estimator.update(cloud((0,0,0)),1.)
        estimator.update(cloud((.05,0,0)),4.)
        self.assertAlmostEqual(estimator.pose[0],.05,delta=.005)

    def test_parallel_walls_are_degenerate(self):
        x=np.linspace(-4,4,200);points=np.vstack((np.column_stack((x,np.ones(200))),np.column_stack((x,-np.ones(200)))))
        with self.assertRaisesRegex(RegistrationError,'degenerate'): Reference(points,Settings()).match(points,np.zeros(3))

    def test_invalid_ranges_and_time(self):
        r=ranges((0,0,0));r[:100]=np.nan;r[100:150]=np.inf;r[150:200]=0
        p=scan_points(r,-math.pi,2*math.pi/len(r),.1,16)
        self.assertTrue(np.isfinite(p).all());self.assertEqual(len(p),520)
        estimator=Odometry();estimator.update(cloud((0,0,0)),1.)
        with self.assertRaisesRegex(RegistrationError,'out_of_order'): estimator.update(cloud((0,0,0)),.9)

    def test_stationary_noise_does_not_random_walk(self):
        estimator=Odometry()
        for i in range(80): estimator.update(cloud((0,0,0),noise=.01,seed=i),1+i*.1)
        self.assertLess(np.linalg.norm(estimator.pose[:2]),.008)
        self.assertLess(abs(estimator.pose[2]),.003)

if __name__=='__main__':unittest.main()
