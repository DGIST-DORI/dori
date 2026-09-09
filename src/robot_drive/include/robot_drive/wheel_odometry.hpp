#pragma once

#include <cmath>
#include <stdexcept>

namespace robot_drive
{
// Joint positions are wheel radians with direction_sign already applied by hardware.
class WheelOdometry
{
public:
  enum class Result { initialized, integrated, rebased, rejected };
  WheelOdometry(double radius, double separation, double wrap, double max_dt, double max_speed)
  : radius_(radius), separation_(separation), wrap_(wrap), max_dt_(max_dt), max_speed_(max_speed)
  {
    if (!std::isfinite(radius) || radius <= 0 || !std::isfinite(separation) || separation <= 0 ||
      !std::isfinite(wrap) || wrap < 0 || !std::isfinite(max_dt) || max_dt <= 0 ||
      !std::isfinite(max_speed) || max_speed <= 0 ||
      (wrap > 0 && max_dt * max_speed >= wrap / 2))
    {
      throw std::invalid_argument("Invalid wheel geometry, timing, speed or ambiguous wrap interval");
    }
  }

  void reset_history() { initialized_ = false; linear = angular = 0.0; }

  Result update(double stamp, double left, double right)
  {
    if (!std::isfinite(stamp) || !std::isfinite(left) || !std::isfinite(right)) {
      return Result::rejected;
    }
    if (!initialized_) {
      baseline(stamp, left, right);
      return Result::initialized;
    }
    const double dt = stamp - stamp_;
    if (dt <= 0) {return Result::rejected;}
    double dl = left - left_, dr = right - right_;
    if (wrap_ > 0) {dl = std::remainder(dl, wrap_); dr = std::remainder(dr, wrap_);}
    baseline(stamp, left, right);
    // Do not invent motion across long gaps or integrate encoder resets/spikes.
    if (dt > max_dt_ || std::abs(dl) > max_speed_ * dt || std::abs(dr) > max_speed_ * dt) {
      return Result::rebased;
    }
    const double ds = radius_ * (dl + dr) / 2.0;
    const double da = radius_ * (dr - dl) / separation_;
    const double half = da / 2.0;
    const double scale = std::abs(half) < 1e-9 ? 1.0 : std::sin(half) / half;
    x += ds * scale * std::cos(yaw + half);
    y += ds * scale * std::sin(yaw + half);
    yaw = std::atan2(std::sin(yaw + da), std::cos(yaw + da));
    linear = ds / dt;
    angular = da / dt;
    return Result::integrated;
  }

  double x{0}, y{0}, yaw{0}, linear{0}, angular{0};

private:
  void baseline(double stamp, double left, double right)
  {
    initialized_ = true; stamp_ = stamp; left_ = left; right_ = right;
    linear = angular = 0.0;
  }
  double radius_, separation_, wrap_, max_dt_, max_speed_;
  double stamp_{0}, left_{0}, right_{0};
  bool initialized_{false};
};
}  // namespace robot_drive
