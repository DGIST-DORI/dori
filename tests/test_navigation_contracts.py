import math
from pathlib import Path
import sys
import tempfile
import unittest
from PIL import Image
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src/robot_navigation/scripts'))
from navigation_contract import load_points_csv,validate_map,normalized_twist

class Contracts(unittest.TestCase):
    def test_units_and_curvature(self):
        self.assertEqual(normalized_twist(0.172,0.7,1.72,7,0.3,0.8),(0.09999999999999999,0.09999999999999999))
        v,w=normalized_twist(1,2,1.72,7,0.3,0.8)
        self.assertAlmostEqual(v*1.72,0.3);self.assertAlmostEqual(w*7,0.6)
        v,w=normalized_twist(-0.1,-0.5,1.72,7,0.3,0.8)
        self.assertLess(v,0);self.assertLess(w,0)
        for values in [(math.nan,0,1,1,1,1),(0,0,0,1,1,1),(0,math.inf,1,1,1,1)]:
            with self.assertRaises(ValueError):normalized_twist(*values)
    def test_points_and_map(self):
        with tempfile.TemporaryDirectory() as td:
            r=Path(td);csv=r/'points.csv';mp=r/'map.yaml'
            Image.new('L',(100,100),254).save(r/'map.pgm')
            mp.write_text('image: map.pgm\nresolution: 0.1\norigin: [-5, -5, 0]\nnegate: 0\nfree_thresh: 0.25\noccupied_thresh: 0.65\n')
            header='name,x,y,yaw_deg,frame_id\n'
            csv.write_text(header+'water,0,0,90,map\n')
            self.assertEqual(validate_map(mp,csv)['points'],1)
            for row in ['water,nan,0,0,map\n','water,0,0,0,odom\n','water,0,0,0,map\nwater,1,1,0,map\n','cancel,0,0,0,map\n']:
                csv.write_text(header+row)
                with self.assertRaises(ValueError):load_points_csv(csv)
            csv.write_text(header+'water,999,0,0,map\n')
            with self.assertRaises(ValueError):validate_map(mp,csv)
            csv.write_text(header+'water,0,0,0,map\n');Image.new('L',(100,100),0).save(r/'map.pgm')
            with self.assertRaises(ValueError):validate_map(mp,csv)

if __name__=='__main__':unittest.main()
