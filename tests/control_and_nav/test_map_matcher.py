"""Coarse initial poses recover against an asymmetric occupancy map."""
import math
import json
import sys
import unittest
from pathlib import Path
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'ros2_ws/src/robot_navigation'))
from dori_web.map_matcher import MapMatcher


class MapSearch(unittest.TestCase):
    def scene(self,angle=0.):
        grid=np.zeros((140,180),dtype=int)
        grid[10,10:160]=100;grid[125,10:160]=100
        grid[10:126,10]=100;grid[10:126,159]=100
        grid[70:126,115]=100;grid[70,115:160]=100
        iy,ix=np.where(grid==100);world=np.column_stack(((ix+.5)*.05,(iy+.5)*.05))
        true=np.array([3.5,2.5,.6]);c=math.cos(true[2]);s=math.sin(true[2]);delta=world-true[:2]
        points=np.column_stack((c*delta[:,0]+s*delta[:,1],-s*delta[:,0]+c*delta[:,1]))
        origin=np.array([1.,-2.,angle]);c=math.cos(angle);s=math.sin(angle)
        true[:2]=origin[:2]+np.array([c*true[0]-s*true[1],s*true[0]+c*true[1]])
        true[2]+=angle
        return MapMatcher(grid,.05,origin),points,true

    def test_recovers_xy_and_heading_from_approximate_click(self):
        matcher,points,true=self.scene()
        result=matcher.search(points,true+np.array([.8,-.65,1.4]))
        self.assertLess(np.linalg.norm(np.array(result['pose'])[:2]-true[:2]),.10)
        self.assertLess(abs(math.remainder(result['pose'][2]-true[2],2*math.pi)),math.radians(3))
        self.assertGreater(result['matched_fraction'],.9)
        json.dumps(result,allow_nan=False)

    def test_map_origin_rotation_is_applied(self):
        matcher,points,true=self.scene(.45)
        result=matcher.search(points,true+np.array([-.6,.7,-.8]))
        self.assertLess(np.linalg.norm(np.array(result['pose'])[:2]-true[:2]),.10)

    def test_wrong_area_and_insufficient_returns_are_rejected(self):
        matcher,points,_=self.scene()
        with self.assertRaises(ValueError):matcher.search(points,[30.,30.,0.])
        with self.assertRaises(ValueError):matcher.search(points[:10],[3.,2.,0.])


if __name__=='__main__':unittest.main()
