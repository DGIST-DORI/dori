import sys
import unittest
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'scripts'))
from autonomy import component_plan,GROUPS


class AutonomyPlan(unittest.TestCase):
    def test_cold_start_and_full_existing_stack(self):
        self.assertTrue(all(value=='start' for value in component_plan([]).values()))
        names=set().union(*GROUPS.values())
        self.assertTrue(all(value=='reuse' for value in component_plan(names).values()))

    def test_partial_group_does_not_spawn_duplicate_hardware(self):
        with self.assertRaisesRegex(RuntimeError,'일부 노드'):component_plan(['controller_manager'])
        names=list(set().union(*GROUPS.values()))+['lidar_odometry']
        with self.assertRaisesRegex(RuntimeError,'중복'):component_plan(names)

    def test_other_odometry_or_orphan_extrinsic_is_not_adopted(self):
        for name in ['cartographer_node','lidar_imu_odometry','wheel_odometry_node','base_to_laser_tf']:
            with self.assertRaises(RuntimeError):component_plan([name])

    def test_missing_independent_components_are_started(self):
        plan=component_plan(GROUPS['control'] | GROUPS['lidar'])
        self.assertEqual(plan,dict(control='reuse',lidar='reuse',odometry='start',navigation='start'))


if __name__=='__main__':unittest.main()
