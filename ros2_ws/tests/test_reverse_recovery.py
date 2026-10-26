"""Rear scan collision gating and signed motion through the normal interpreter."""
import math
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src/robot_navigation/scripts'))
from reverse_clearance import rear_clearance
from motion_interpreter import MotionInterpreter, AxisConfig, rolling_arc


def scan():
    return SimpleNamespace(ranges=[3.]*720,angle_min=-math.pi,angle_increment=math.pi/360,range_min=.1,range_max=12.)


class ReverseRecovery(unittest.TestCase):
    def test_clear_rear_and_front_obstacle_with_reversed_laser_mount(self):
        s=scan();s.ranges[0]=.4  # laser -pi + mounting pi = robot front
        self.assertEqual(rear_clearance(s,(0,0,math.pi),.12),'driving')

    def test_rear_obstacle_and_stopping_distance(self):
        s=scan();s.ranges[360]=.44
        self.assertEqual(rear_clearance(s,(0,0,math.pi),.12),'rear_obstacle')
        s.ranges[360]=.60
        self.assertEqual(rear_clearance(s,(0,0,math.pi),.12),'driving')
        self.assertEqual(rear_clearance(s,(0,0,math.pi),.4),'rear_obstacle')

    def test_missing_rear_beams_and_partial_fov_are_unknown(self):
        s=scan();s.ranges[350:380]=[math.nan]*30
        self.assertEqual(rear_clearance(s,(0,0,math.pi),.12),'rear_scan_unknown')
        s=scan();s.ranges=s.ranges[:180]
        self.assertEqual(rear_clearance(s,(0,0,math.pi),.12),'rear_scan_unknown')

    def test_footprint_width_and_laser_translation(self):
        s=scan();s.ranges[405]=.4
        self.assertEqual(rear_clearance(s,(0,0,math.pi),.12),'rear_obstacle')
        s=scan();s.ranges[360]=.65
        self.assertEqual(rear_clearance(s,(.25,0,math.pi),.12),'rear_obstacle')

    def test_reverse_command_survives_interpreter_but_pivot_does_not(self):
        m=MotionInterpreter(linear_config=AxisConfig(.62,.22,1.,.5,.7,.025,.004,0.,False),arc_only=True)
        v,w=m.update(-.12,0.,0.,0.,0.,0.,.05,1.,0.,0.)
        self.assertLess(v,-.4);self.assertEqual(w,0.)
        self.assertEqual(m.update(0.,.4,0.,0.,0.,0.,.05,1.1),(0.,0.))
        v,w=rolling_arc(-.3,1.,1.72,7.,.184)
        self.assertLess(v*1.72+w*7.*.184/2,0.)
        self.assertLess(v*1.72-w*7.*.184/2,0.)


if __name__=='__main__':unittest.main()
