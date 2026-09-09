#include "robot_transform/target_plan.hpp"
#include <cassert>
#include <iostream>
#include <limits>

using robot_transform::makeTargetPlan;
using robot_transform::nearestEquivalent;
bool close(double a, double b) { return std::abs(a - b) < 1e-8; }

int main()
{
  const std::array<double, 4> reference{36.51, -43.1659, 18, 8.88};
  const std::array<double, 4> ratios{2, 2, 1, 1};
  auto current = reference;
  // Encoder error changes neither calibration nor the next planned target.
  current[2] = 16;
  auto a = makeTargetPlan(reference, current, ratios, false);
  assert(close(a.preparation[2], 18));
  assert(a.motion.size() == 15);
  assert(close(a.motion[0].angle_deg, -72));
  assert(close(a.motion[3].angle_deg, -162));
  auto previous = a.preparation;
  for (auto step : a.motion) {
    auto i = step.motor_id - 1;
    assert(close(std::abs(step.angle_deg - previous[i]) / ratios[i], 90));
    previous[i] = step.angle_deg;
  }
  assert(close(previous[3], 8.88 - 540));
  // Repeat full A/B cycles with nonzero endpoint errors. No drift is permitted.
  for (int cycle = 0; cycle < 100; ++cycle) {
    for (auto step : a.motion) { current[step.motor_id - 1] = step.angle_deg + 1.7; }
    auto b = makeTargetPlan(reference, current, ratios, true);
    for (int i = 0; i < 4; ++i) { assert(close(b.preparation[i], previous[i])); }
    for (auto step : b.motion) { current[step.motor_id - 1] = step.angle_deg - 1.2; }
    a = makeTargetPlan(reference, current, ratios, false);
    for (int i = 0; i < 4; ++i) { assert(close(a.preparation[i], reference[i])); }
  }
  // A B-start after reboot uses the same physical phase on the new encoder turn.
  current = {396.51, 316.8341, 288, 188.88};
  auto b = makeTargetPlan(reference, current, ratios, true);
  assert(close(b.preparation[0], 396.51));
  assert(close(b.preparation[1], 316.8341));
  assert(close(b.preparation[2], 288));
  assert(close(b.motion[0].angle_deg, 278.88));
  // Selecting the nearest calibrated phase accounts for the offset itself.
  assert(close(nearestEquivalent(370, 100, 720), 100));
  assert(close(nearestEquivalent(-719, 0, 720), -720));
  // Positive 90-degree progression: 106 measured still targets 108, then 198.
  current = {0, 0, 106, 0};
  const std::array<double, 4> positive_reference{0, 0, 198, 0};
  b = makeTargetPlan(positive_reference, current, ratios, true);
  assert(close(b.preparation[2], 108));
  for (auto step : b.motion) {
    if (step.motor_id == 3) { assert(close(step.angle_deg, 198)); break; }
  }
  bool rejected = false;
  try {
    auto bad = ratios;
    bad[0] = 0;
    makeTargetPlan(reference, current, bad, false);
  } catch (const std::invalid_argument &) { rejected = true; }
  assert(rejected);
  rejected = false;
  try { nearestEquivalent(std::numeric_limits<double>::quiet_NaN(), 0, 360); }
  catch (const std::invalid_argument &) { rejected = true; }
  assert(rejected);
  std::cout << "PASS: fixed references, 100 A/B cycles, 90-degree steps, signed zero crossing, "
    "reboot phase, positive progression, invalid inputs\n";
}
