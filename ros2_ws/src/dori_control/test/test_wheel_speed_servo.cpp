#include <gtest/gtest.h>
#include <limits>
#include "dori_control/wheel_speed_servo.hpp"
using dori_control::WheelSpeedServo;
using dori_control::WheelServoConfig;

TEST(WheelSpeedServo, TracksVelocityThroughFrictionAndMotorLag)
{
  WheelSpeedServo servo;
  double actual = 0, baseline = 0;
  auto plant = [](double velocity, double torque) {
    const double friction = 1.3;
    if (std::abs(velocity) < 0.001 && std::abs(torque) < friction) return 0.0;
    return velocity + 0.01 * (torque - std::copysign(friction, std::abs(velocity) > 0.001 ? velocity : torque) - .3 * velocity) / .4;
  };
  for (int i = 0; i < 600; ++i) {
    double target = .35;
    actual = plant(actual, 3 * (target - actual) + .35 + servo.update(target, actual, .01, true));
    baseline = plant(baseline, 3 * (target - baseline) + .35);
  }
  EXPECT_NEAR(actual, .35, .025);
  EXPECT_LT(baseline, .10);
}

TEST(WheelSpeedServo, SaturationDoesNotWindUp)
{
  WheelSpeedServo servo;
  for (int i = 0; i < 2000; ++i) EXPECT_LE(servo.update(5, 0, .01, true), 3);
  EXPECT_DOUBLE_EQ(servo.integral(), 0);
  EXPECT_LT(servo.update(.1, .2, .01, true), 1);
}

TEST(WheelSpeedServo, ResetsOnStopFaultAndReversal)
{
  WheelSpeedServo servo;
  for (int i = 0; i < 100; ++i) servo.update(.1, 0, .01, true);
  EXPECT_GT(servo.integral(), .2);
  EXPECT_LT(servo.update(-.1, 0, .01, true), 0);
  EXPECT_GT(servo.integral(), -.01);
  EXPECT_EQ(servo.update(0, .1, .01, true), 0);
  EXPECT_EQ(servo.integral(), 0);
  EXPECT_EQ(servo.update(1, 0, .01, false), 0);
  EXPECT_EQ(servo.update(1, std::numeric_limits<double>::quiet_NaN(), .01, true), 0);
  EXPECT_EQ(servo.update(1, 0, 1, true), 0);
}

TEST(WheelSpeedServo, ObeysAvailableMixerBudgetAndRejectsBadConfiguration)
{
  WheelSpeedServo servo;
  for (int i = 0; i < 200; ++i) EXPECT_LE(servo.update(1, 0, .01, true, -.2, .2), .2);
  EXPECT_DOUBLE_EQ(servo.integral(), 0);
  WheelServoConfig config; config.ki = -1;
  EXPECT_THROW(servo.configure(config), std::invalid_argument);
}
