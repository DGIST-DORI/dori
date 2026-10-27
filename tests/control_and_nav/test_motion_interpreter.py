import math,sys,unittest
import yaml
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'ros2_ws/src/robot_navigation/scripts'))
from motion_interpreter import MotionInterpreter,AxisConfig,AxisInterpreter,rolling_arc

class MotionInterpreterTests(unittest.TestCase):
    def calibrated(self):
        path=Path(__file__).resolve().parents[2]/'ros2_ws/src/robot_navigation/config/motion_interpreter.yaml'
        p=yaml.safe_load(path.read_text())['nav_drive_bridge']['ros__parameters']
        def axis(name,threshold,stop):
            return AxisConfig(p['motion.'+name+'.response_gain'],
                *[p['motion.'+name+'.'+key] for key in ('start_input','max_input','kp','ki')],
                threshold,stop,p.get('motion.'+name+'.startup_rate',.12),p['motion.'+name+'.adapt_start'])
        return MotionInterpreter(linear_config=axis('linear',.025,.004),
            angular_config=axis('angular',.08,.015),arc_only=True)

    def test_calibrated_rolling_response_with_real_drive_limits_and_measurement_delay(self):
        controller=self.calibrated();applied=[0.,0.];ground=[0.,0.];history=[];samples=[]
        for i in range(500):
            t=i*.05;desired=(.3,.4 if t<12 else -.4)
            observed=history[-3] if len(history)>=3 else (0.,0.)
            output=controller.update(*desired,*observed,observed[0]*1.94,observed[1]*2.17,
                                     .05,t,*applied)
            for axis in (0,1):
                # Unchanged hardware limits: v +0.5/-0.3 m/s^2, w +/-1 rad/s^2.
                rate=(.5 if abs(output[0])>abs(applied[0]) else .3)/1.72 if axis==0 else 1/7
                applied[axis]+=max(-rate*.05,min(rate*.05,output[axis]-applied[axis]))
            target=[.62*max(0,applied[0]-.22),1.67*applied[1] if ground[0]>.025 else 0.]
            for axis in (0,1):ground[axis]+=(target[axis]-ground[axis])*.05/.15
            history.append(tuple(ground));samples.append(tuple(ground))
            self.assertGreaterEqual(output[0]*1.72-abs(output[1])*7*.184/2,-1e-9)
        self.assertLess(max(s[0] for s in samples),.38)
        self.assertLess(max(abs(s[1]) for s in samples),.55)
        self.assertAlmostEqual(samples[200][0],.3,delta=.03)
        self.assertAlmostEqual(samples[200][1],.4,delta=.05)
        self.assertAlmostEqual(samples[-1][1],-.4,delta=.05)
        self.assertEqual(controller.update(0,1.2,*ground,1.,1.,.05,26.,*applied),(0.,0.))
        self.assertEqual(controller.angular.start_input,0.)

    def test_rolling_steering_does_not_learn_pivot_resistance_while_stopped(self):
        c=self.calibrated()
        for i in range(100):c.update(.2,.3,0.,0.,0.,0.,.05,i*.05,0.,0.)
        self.assertEqual(c.angular.integral,0.)
        self.assertEqual(c.angular.start_input,0.)
        self.assertEqual(c.angular.samples,0)

    def test_small_turn_correction_does_not_grow_into_large_turn(self):
        c=self.calibrated()
        for i in range(200):
            _,w=c.update(.2,.03,.2,0.,.4,0.,.05,i*.05,.55,.03)
            self.assertLessEqual(abs(w),.03/1.67*1.5+.0031)
        self.assertGreater(w,.03/1.67)  # Some bounded correction remains.
        c.angular.integral=.3
        _,w=c.update(.2,.02,.2,0.,.4,0.,.05,11.,.55,.03)
        self.assertLess(w,.021)

    def test_rolling_arc_cannot_pivot_or_reverse_inner_wheel(self):
        self.assertEqual(rolling_arc(0.,.9,1.72,7.,.184),(0.,0.))
        for steering in (-.9,.9):
            v,w=rolling_arc(.2,steering,1.72,7.,.184)
            self.assertEqual(v,.2)
            self.assertGreater(v*1.72-abs(w)*7.*.184/2.,0.)
            self.assertGreater(w*steering,0.)
    def test_overcomes_deadzone_and_tracks_delayed_ground_speed(self):
        c=MotionInterpreter();actual=0.;outputs=[]
        for i in range(300):
            u,_=c.update(.2,0,actual,0,actual,0,.05,i*.05)
            physical=1.2*max(0,u-.22)
            actual+=(physical-actual)*.05/.25
            outputs.append(u)
        self.assertAlmostEqual(actual,.2,delta=.035)
        self.assertGreater(max(outputs),.22)
        self.assertTrue(all(0<=x<=.5 for x in outputs))
    def test_tiny_demand_increases_effort_until_ground_motion(self):
        c=MotionInterpreter();outputs=[]
        for i in range(100):
            _,u=c.update(0,.04,0,0,0,0,.05,i*.05);outputs.append(u)
        self.assertGreater(outputs[-1],outputs[0]+.2)
        self.assertLessEqual(outputs[-1],.65)
        self.assertEqual(c.angular.samples,0)

    def test_tracks_rotation_through_unchanged_acceleration_limiter(self):
        c=AxisInterpreter(AxisConfig(7.,.25,.9,.1,.15,.08,.015))
        wheel=applied=0.;speeds=[]
        for _ in range(600):
            speed=2*.234*wheel/.184
            u=c.update(1.2,speed,speed,.02,.02,applied/7.)
            # Existing drive limit: 1 rad/s^2. Firmware velocity feedback and
            # static friction reproduce the requested/applied command delay.
            applied+=max(-.02,min(.02,u*7-applied))
            target=applied*.184/(2*.234)
            torque=3*(target-wheel)+(.35 if target>.05 else 0.)
            if abs(wheel)<.001 and abs(torque)<1.3:wheel=0.
            else:
                next_wheel=wheel+.02*(torque-math.copysign(1.3,wheel if abs(wheel)>.001 else torque)-.3*wheel)/.4
                wheel=0. if next_wheel*wheel<0 and abs(torque)<1.3 else next_wheel
            speeds.append(speed)
        self.assertLess(max(speeds),1.5)
        self.assertAlmostEqual(sum(speeds[-100:])/100,1.2,delta=.08)
        self.assertLess(c.start_input,.2)

    def test_no_learning_from_spinning_wheels_or_repeated_lidar_stamp(self):
        c=MotionInterpreter()
        for i in range(100):c.update(.2,0,0,0,1.,0,.05,i*.05)
        self.assertEqual(c.linear.samples,0)
        self.assertEqual(c.linear.gain,1.72)
        for i in range(100):c.update(.2,0,.2,0,.2,0,.05,5.)
        self.assertLessEqual(c.linear.samples,1)
    def test_stop_reversal_and_invalid_input(self):
        c=MotionInterpreter()
        for i in range(30):c.update(.2,.5,0,0,0,0,.05,i*.05)
        self.assertEqual(c.update(0,0,.2,.5,.2,.5,.05,2.),(0.,0.))
        u,w=c.update(-.2,-.5,0,0,0,0,.05,2.1)
        self.assertLess(u,0);self.assertLess(w,0)
        self.assertEqual(c.update(math.nan,0,0,0,0,0,.05,2.2),(0.,0.))
    def test_overspeed_brakes_instead_of_adding_start_input(self):
        c=MotionInterpreter();c.update(.1,0,0,0,0,0,.05,0)
        first=c.linear.output
        for i in range(1,15):u,_=c.update(.1,0,.5,0,.5,0,.05,i*.05)
        self.assertLess(u,first*.1)
        self.assertEqual(c.linear.phase,'brake')
    def test_online_fit_is_bounded_and_uses_ground_and_encoder(self):
        c=AxisInterpreter(AxisConfig(1.72,.18,.5,.5,.7,.025,.004))
        for _ in range(300):c.update(.2,.2,.2,.05,.05)
        self.assertGreater(c.samples,0)
        self.assertTrue(.43<=c.gain<=3.44)
        self.assertTrue(.05<=c.start_input<=.35)
if __name__=='__main__':unittest.main()
