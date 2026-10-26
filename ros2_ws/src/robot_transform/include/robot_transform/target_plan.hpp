#pragma once

#include <array>
#include <cmath>
#include <stdexcept>
#include <vector>

namespace robot_transform
{
struct MotionStep
{
  int motor_id;
  double angle_deg;
};

// Mechanical degrees. Preserve the original order; split the final -180
// into two -90 steps so every mechanical move has a settling checkpoint.
inline const std::vector<MotionStep> & forwardSteps()
{
  static const std::vector<MotionStep> steps = {
    {3, -90}, {4, -90}, {1, 90}, {3, -90}, {2, -90},
    {4, -90}, {3, -90}, {4, -90}, {1, 90}, {3, -90},
    {2, -90}, {4, -90}, {3, -90}, {4, -90}, {4, -90}};
  return steps;
}

inline double nearestEquivalent(double current, double reference, double period)
{
  if (!std::isfinite(current) || !std::isfinite(reference) ||
    !std::isfinite(period) || period <= 0)
  {
    throw std::invalid_argument("Invalid reference, feedback, or angle period");
  }
  return reference + std::round((current - reference) / period) * period;
}

struct TargetPlan
{
  std::array<double, 4> preparation;
  std::vector<MotionStep> motion;
};

inline TargetPlan makeTargetPlan(
  const std::array<double, 4> & a_reference,
  const std::array<double, 4> & feedback,
  const std::array<double, 4> & motor_per_mechanical,
  bool from_b)
{
  auto reference = a_reference;
  for (double ratio : motor_per_mechanical) {
    if (!std::isfinite(ratio) || ratio <= 0) {
      throw std::invalid_argument("Motor/mechanical ratios must be positive and finite");
    }
  }
  // B preparation is the planned A->B endpoint, never the measured endpoint.
  if (from_b) {
    for (const auto & step : forwardSteps()) {
      reference[step.motor_id - 1] +=
        step.angle_deg * motor_per_mechanical[step.motor_id - 1];
    }
  }
  TargetPlan plan;
  for (std::size_t i = 0; i < reference.size(); ++i) {
    // Only select an equivalent full mechanical revolution. The calibrated
    // phase is immutable; do not snap to whichever 90-degree cell is closest.
    plan.preparation[i] = nearestEquivalent(
      feedback[i], reference[i], 360.0 * motor_per_mechanical[i]);
  }
  auto target = plan.preparation;
  const auto append = [&](const MotionStep & step, double direction) {
      auto i = step.motor_id - 1;
      target[i] += direction * step.angle_deg * motor_per_mechanical[i];
      plan.motion.push_back({step.motor_id, target[i]});
    };
  if (from_b) {
    for (auto it = forwardSteps().rbegin(); it != forwardSteps().rend(); ++it) {
      append(*it, -1.0);
    }
  } else {
    for (const auto & step : forwardSteps()) {
      append(step, 1.0);
    }
  }
  return plan;
}
}  // namespace robot_transform
