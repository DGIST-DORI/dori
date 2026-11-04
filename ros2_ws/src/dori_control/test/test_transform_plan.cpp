#include "dori_control/target_plan.hpp"

#include <gtest/gtest.h>
#include <limits>

namespace
{
const std::array<double, 4> reference{42.133, -1.395, 172.441, 12.3};
const std::array<double, 4> ratios{2, 2, 1, 1};

std::array<double, 4> endpoint(const dori_control::TargetPlan & plan)
{
  auto result = plan.preparation;
  for (const auto & step : plan.motion) {result.at(step.motor_id - 1) = step.angle_deg;}
  return result;
}
}  // namespace

TEST(TransformPlan, LegacyTravelRemainsUnchanged)
{
  const auto plan = dori_control::makeTargetPlan(reference, reference, ratios, false);
  ASSERT_EQ(plan.motion.size(), 15u);
  const auto end = endpoint(plan);
  EXPECT_NEAR(end[0], reference[0] + 360, 1e-9);
  EXPECT_NEAR(end[1], reference[1] - 360, 1e-9);
  EXPECT_NEAR(end[2], reference[2] - 450, 1e-9);
  EXPECT_NEAR(end[3], reference[3] - 540, 1e-9);
}

TEST(TransformPlan, Motor4HalfTurnPreservesOtherMotorsAndCheckpoints)
{
  const auto legacy = dori_control::makeTargetPlan(reference, reference, ratios, false);
  for (double travel : {-180.0, 180.0}) {
    const auto plan = dori_control::makeTargetPlan(reference, reference, ratios, false, travel);
    ASSERT_EQ(plan.motion.size(), legacy.motion.size());
    double previous = plan.preparation[3];
    unsigned count = 0;
    for (size_t i = 0; i < plan.motion.size(); ++i) {
      const auto step = plan.motion[i];
      EXPECT_EQ(step.motor_id, legacy.motion[i].motor_id);
      if (step.motor_id == 4) {
        EXPECT_NEAR(step.angle_deg - previous, travel / 6, 1e-9);
        previous = step.angle_deg;
        ++count;
      } else {
        EXPECT_DOUBLE_EQ(step.angle_deg, legacy.motion[i].angle_deg);
      }
    }
    EXPECT_EQ(count, 6u);
    EXPECT_NEAR(previous, reference[3] + travel, 1e-9);
  }
}

TEST(TransformPlan, HalfTurnReversesExactlyWithoutEndpointErrorDrift)
{
  for (double travel : {-180.0, 180.0}) {
    auto measured = reference;
    for (int cycle = 0; cycle < 100; ++cycle) {
      const auto forward = dori_control::makeTargetPlan(reference, measured, ratios, false, travel);
      const auto expected_end = endpoint(forward);
      measured = expected_end;
      for (double & value : measured) {value += 1.2;}
      const auto reverse = dori_control::makeTargetPlan(reference, measured, ratios, true, travel);
      for (size_t i = 0; i < 4; ++i) {
        EXPECT_NEAR(forward.preparation[i], reference[i], 1e-9);
        EXPECT_NEAR(reverse.preparation[i], expected_end[i], 1e-9);
      }
      for (size_t i = 0; i < forward.motion.size(); ++i) {
        EXPECT_EQ(reverse.motion[i].motor_id, forward.motion[forward.motion.size() - 1 - i].motor_id);
      }
      measured = endpoint(reverse);
      for (size_t i = 0; i < 4; ++i) {
        EXPECT_NEAR(measured[i], reference[i], 1e-9);
        measured[i] -= 0.7;
      }
    }
  }
}

TEST(TransformPlan, InvalidTravelIsRejected)
{
  for (double travel : {0.0, std::numeric_limits<double>::quiet_NaN(),
      std::numeric_limits<double>::infinity()}) {
    EXPECT_THROW(dori_control::makeTargetPlan(reference, reference, ratios, false, travel),
      std::invalid_argument);
  }
}
