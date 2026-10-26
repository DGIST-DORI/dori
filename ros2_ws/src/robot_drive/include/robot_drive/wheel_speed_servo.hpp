#pragma once

#include <algorithm>
#include <cmath>
#include <stdexcept>

namespace robot_drive
{
// Supplement the motor's existing MIT velocity loop with load/friction torque.
// Units: wheel rad/s, Nm, seconds. No change to commanded velocity or geometry.
struct WheelServoConfig
{
  double kp{1.5}, ki{3.0}, friction{0.8}, friction_speed{0.03};
  double torque_limit{3.0}, integral_limit{2.0}, filter_time{0.06};
  double zero_speed{0.005};

  void validate() const
  {
    for (double v : {kp, ki, friction, integral_limit, filter_time, zero_speed}) {
      if (!std::isfinite(v) || v < 0) throw std::invalid_argument("Invalid wheel servo parameter");
    }
    if (!std::isfinite(torque_limit) || torque_limit <= 0 ||
      !std::isfinite(friction_speed) || friction_speed <= 0) {
      throw std::invalid_argument("Wheel servo limits must be positive");
    }
  }
};

class WheelSpeedServo
{
public:
  void configure(const WheelServoConfig & config) {config.validate(); config_ = config; reset();}
  void reset() {integral_ = torque_ = filtered_ = previous_target_ = 0; initialized_ = false;}
  double measured() const {return filtered_;}
  double integral() const {return integral_;}
  double torque() const {return torque_;}

  double update(double target, double measured, double dt, bool valid,
    double lower = -1e9, double upper = 1e9)
  {
    if (!valid || !std::isfinite(target) || !std::isfinite(measured) ||
      !std::isfinite(dt) || dt <= 0 || dt > 0.1 ||
      std::abs(target) <= config_.zero_speed) {
      reset(); return 0;
    }
    if (target * previous_target_ < 0) integral_ = 0;
    previous_target_ = target;
    if (!initialized_) {filtered_ = measured; initialized_ = true;}
    filtered_ += dt / (config_.filter_time + dt) * (measured - filtered_);
    const double error = target - filtered_;
    const double feedforward = config_.friction * std::tanh(target / config_.friction_speed);
    const double proportional = config_.kp * error;
    lower = std::max(lower, -config_.torque_limit);
    upper = std::min(upper, config_.torque_limit);
    if (lower > upper) {reset(); return 0;}
    const double candidate = clamp(integral_ + config_.ki * error * dt,
      -config_.integral_limit, config_.integral_limit);
    const double requested = proportional + feedforward + candidate;
    // Conditional integration: unwind freely, never accumulate beyond available torque.
    if ((requested <= upper || error < 0) && (requested >= lower || error > 0)) {
      integral_ = candidate;
    }
    torque_ = clamp(proportional + feedforward + integral_, lower, upper);
    return torque_;
  }

private:
  static double clamp(double v, double lo, double hi) {return std::max(lo, std::min(v, hi));}
  WheelServoConfig config_;
  double integral_{0}, torque_{0}, filtered_{0}, previous_target_{0};
  bool initialized_{false};
};
}  // namespace robot_drive
