"""Deterministic body-speed demand -> joystick input, with bounded online fitting.

Nav2 owns the collision-checked path and desired SI motion. This layer owns the
actuation needed to realize that motion. Encoder motion validates model updates;
LiDAR odometry supplies ground motion. Nothing here publishes odometry or TF.
"""
from dataclasses import dataclass
import math


def clamp(value, low, high):
    return max(low, min(value, high))


def rolling_arc(v, w, scale_v, scale_w, separation):
    """Keep wheel targets in the requested travel direction; prohibit pivots."""
    if v == 0.: return 0., 0.
    # Leave 10% of the center velocity on the inner wheel. Motor acceleration
    # limits still apply downstream, exactly as they do for manual control.
    limit=.9*2.*abs(v)*scale_v/(separation*scale_w)
    return v, clamp(w,-limit,limit)


@dataclass(frozen=True)
class AxisConfig:
    nominal_gain: float
    start_input: float
    max_input: float
    kp: float
    ki: float
    motion_threshold: float
    stopped_demand: float
    startup_rate: float = .12
    adapt_start: bool = True

    def __post_init__(self):
        if not all(math.isfinite(x) and x >= 0 for x in self.__dict__.values()):
            raise ValueError('Motion interpreter settings must be finite and nonnegative')
        if not self.nominal_gain > 0 or not 0 <= self.start_input < self.max_input <= 1:
            raise ValueError('Invalid response gain or normalized input limits')


class AxisInterpreter:
    def __init__(self, config):
        self.config = config
        self.gain = config.nominal_gain
        self.start_input = config.start_input
        self.samples = 0
        self.reset()

    def reset(self):
        self.integral = self.output = self.measured = self.last_target = 0.
        self.started = self.stable = 0.
        self.phase = 'stop'

    def update(self, target, measured, encoder, dt, feedback_dt=0., applied=None,
               learning_applied=None, integrate=True, correction_limit=.35):
        c = self.config
        applied = self.output if applied is None else applied
        learning_applied = applied if learning_applied is None else learning_applied
        if not all(math.isfinite(x) for x in (target, measured, encoder, dt, applied)) or not 0 < dt <= .25:
            self.reset(); return 0.
        if abs(target) <= c.stopped_demand:
            self.reset(); return 0.
        sign = math.copysign(1., target)
        if target*self.last_target < 0:
            self.reset()
        demand = abs(target)
        if self.phase == 'stop': self.measured = measured
        if feedback_dt > 0:
            self.measured += clamp(feedback_dt/(.15+feedback_dt), 0., 1.)*(measured-self.measured)
        speed = sign*self.measured
        if abs(target-self.last_target) < c.motion_threshold:
            self.stable += dt
        else:
            self.stable = 0.
        self.last_target = target
        error = demand-speed
        # Fit only fresh, sustained, same-direction GROUND movement. Raw encoder
        # velocity alone must never teach a spinning/slipping wheel as progress.
        wheel_speed = sign*encoder
        if (integrate and feedback_dt > 0 and self.stable > 1. and speed > c.motion_threshold
                and wheel_speed > c.motion_threshold*.25 and .05 < speed/wheel_speed < 4.
                and math.isfinite(learning_applied) and learning_applied*target > 0
                and abs(learning_applied) > self.start_input+.05
                and abs(applied-self.output) < .05
                and abs(error) < max(demand*.6, c.motion_threshold)):
            observed_gain = speed/(abs(learning_applied)-self.start_input)
            observed_gain = clamp(observed_gain, c.nominal_gain*.25, c.nominal_gain*2.)
            # At most 3% relative change per second; observations are not independent
            # at the 20Hz actuator timer, so only new LiDAR stamps update the model.
            delta = clamp(observed_gain-self.gain, -self.gain*.03*feedback_dt, self.gain*.03*feedback_dt)
            self.gain += delta
            self.samples += 1
        moving = speed > c.motion_threshold
        if c.adapt_start and moving and self.phase == 'start' and wheel_speed > c.motion_threshold*.25 and applied*target > 0:
            # Learn from the command AFTER the common acceleration limiter.
            # Requested joystick effort can still be far ahead of the motor.
            observed_start = abs(applied)-speed/self.gain
            change = clamp(.75*(observed_start-self.start_input), -.15, .10)
            self.start_input = clamp(self.start_input+change, .05, c.max_input*.85)
        self.started = 0. if moving else self.started+dt
        self.phase = 'track' if moving else 'start'
        # Smooth sign-specific starting offset plus adaptive inverse gain and PI.
        # An arbitrarily tiny planner velocity must not wait forever below
        # breakaway. Increase joystick effort while actual ground motion is zero.
        startup = min(c.max_input, c.startup_rate*max(0., self.started-.3)) if not moving else 0.
        feedforward = self.start_input + demand/self.gain + startup
        self.integral = clamp(self.integral, -correction_limit, correction_limit)
        candidate = clamp(self.integral + c.ki*error*dt, -correction_limit, correction_limit)
        requested = feedforward+c.kp*error+candidate
        limiter_catching_up = sign*applied < abs(self.output)-.03 and error > 0
        if integrate and not limiter_catching_up and (requested <= c.max_input or error < 0) and (requested >= 0 or error > 0):
            self.integral = candidate
        output = clamp(feedforward+c.kp*error+self.integral, 0., c.max_input)
        if speed > max(demand*1.5, demand+c.motion_threshold):
            self.phase = 'brake'
            output = min(output, abs(self.output)*clamp(demand/speed, 0., 1.)**2)
            self.integral = min(self.integral, 0.)
        self.output = sign*output
        return self.output

    def status(self):
        return dict(phase=self.phase, input=self.output, ground_speed=self.measured,
                    response_gain=self.gain, start_input=self.start_input, learned_samples=self.samples)


class MotionInterpreter:
    def __init__(self, scale_v=1.72, scale_w=7., linear_config=None, angular_config=None,
                 arc_only=False, wheel_separation=.184):
        self.linear = AxisInterpreter(linear_config or AxisConfig(scale_v, .18, .50, .5, .7, .025, .004))
        self.angular = AxisInterpreter(angular_config or AxisConfig(scale_w, .25, .65, .10, .15, .08, .015))
        self.last_stamp = None
        self.scale_v, self.scale_w = scale_v, scale_w
        self.arc_only, self.wheel_separation = arc_only, wheel_separation

    def reset(self):
        self.linear.reset(); self.angular.reset(); self.last_stamp = None

    def update(self, v, w, measured_v, measured_w, encoder_v, encoder_w, dt, stamp,
               applied_v=None, applied_w=None, learning_input=None):
        if self.arc_only and abs(v) <= self.linear.config.stopped_demand:
            self.reset(); return 0., 0.
        feedback_dt = 0. if self.last_stamp is None else clamp(stamp-self.last_stamp, 0., .5)
        if self.last_stamp is None or stamp > self.last_stamp: self.last_stamp = stamp
        learning_v, learning_w = learning_input if learning_input is not None else (None, None)
        output_v = self.linear.update(v, measured_v, encoder_v, dt, feedback_dt, applied_v, learning_v)
        small_turn = self.arc_only and abs(w) <= .15
        # A gentle path correction must not inherit a large turn integral. Keep
        # ordinary feedforward, and limit delayed-response correction to half
        # that input; never create extra forward motion for heading alignment.
        correction = .5*abs(w)/self.angular.gain if small_turn else .35
        can_integrate = not self.arc_only or abs(measured_v) > self.linear.config.motion_threshold
        if small_turn and abs(measured_w) < abs(w)*.5:
            can_integrate &= self.angular.stable >= .6
        output_w = self.angular.update(w, measured_w, encoder_w, dt, feedback_dt, applied_w, learning_w,
            integrate=can_integrate, correction_limit=correction)
        if self.arc_only:
            output_v, output_w = rolling_arc(output_v, output_w, self.scale_v, self.scale_w, self.wheel_separation)
            if abs(output_w) < abs(self.angular.output):
                self.angular.integral = min(self.angular.integral, 0.)
                self.angular.output = output_w
        return output_v, output_w

    def status(self):
        return dict(linear=self.linear.status(), angular=self.angular.status())
