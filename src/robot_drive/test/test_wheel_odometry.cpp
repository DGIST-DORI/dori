#include <gtest/gtest.h>
#include <limits>
#include "robot_drive/wheel_odometry.hpp"
#include "robot_drive/feedback_freshness.hpp"

using robot_drive::WheelOdometry;
using Result = WheelOdometry::Result;

TEST(WheelFeedback, RejectsMissingStaleAndNonfiniteFeedback)
{
  control_msgs::msg::DynamicJointState msg;
  EXPECT_FALSE(robot_drive::feedback_fresh(msg, "left", "right", 0.2));
  msg.joint_names = {"right", "left"};
  msg.interface_values.resize(2);
  for (auto & values : msg.interface_values) {
    values.interface_names = {"position", "feedback_age"};
    values.values = {1.0, 0.01};
  }
  EXPECT_TRUE(robot_drive::feedback_fresh(msg, "left", "right", 0.2));
  msg.interface_values[0].values[1] = 0.3;
  EXPECT_FALSE(robot_drive::feedback_fresh(msg, "left", "right", 0.2));
  msg.interface_values[0].values[1] = std::numeric_limits<double>::infinity();
  EXPECT_FALSE(robot_drive::feedback_fresh(msg, "left", "right", 0.2));
}

TEST(WheelOdometry, StraightAndReverse)
{
  WheelOdometry o(0.234, 0.184, 0, 0.2, 30);
  EXPECT_EQ(o.update(1, 7, -2), Result::initialized);
  o.update(1.1, 8, -1);
  EXPECT_NEAR(o.x, 0.234, 1e-10);
  EXPECT_NEAR(o.linear, 2.34, 1e-10);
  EXPECT_NEAR(o.y, 0, 1e-10);
  o.update(1.2, 7, -2);
  EXPECT_NEAR(o.x, 0, 1e-10);
  EXPECT_LT(o.linear, 0);
}

TEST(WheelOdometry, PureRotationAndExactArc)
{
  WheelOdometry rotate(1, 2, 0, 1, 30);
  rotate.update(1, 0, 0); rotate.update(1.5, -0.5, 0.5);
  EXPECT_NEAR(rotate.yaw, 0.5, 1e-10);
  EXPECT_NEAR(rotate.x, 0, 1e-10);
  EXPECT_NEAR(rotate.y, 0, 1e-10);
  WheelOdometry arc(1, 2, 0, 1, 30);
  arc.update(1, 0, 0); arc.update(1.5, 0, 2);
  EXPECT_NEAR(arc.x, std::sin(1.0), 1e-10);
  EXPECT_NEAR(arc.y, 1-std::cos(1.0), 1e-10);
  EXPECT_NEAR(arc.yaw, 1, 1e-10);
}

TEST(WheelOdometry, ActualMitWrapInBothDirections)
{
  const double pi = std::acos(-1.0);
  WheelOdometry o(1, 2, 8*pi, 0.2, 30);
  o.update(1, 4*pi-0.1, 4*pi-0.1);
  o.update(1.1, -4*pi+0.1, -4*pi+0.1);
  EXPECT_NEAR(o.x, 0.2, 1e-10);
  o.update(1.2, 4*pi-0.1, 4*pi-0.1);
  EXPECT_NEAR(o.x, 0, 1e-10);
}

TEST(WheelOdometry, InvalidSamplesGapsAndEncoderResets)
{
  WheelOdometry o(1, 2, 0, 0.2, 30);
  o.update(1, 0, 0);
  EXPECT_EQ(o.update(1, 1, 1), Result::rejected);
  EXPECT_EQ(o.update(0.9, 1, 1), Result::rejected);
  EXPECT_EQ(o.update(1.1, std::numeric_limits<double>::quiet_NaN(), 1), Result::rejected);
  EXPECT_EQ(o.update(1.1, 1, 1), Result::integrated);
  EXPECT_NEAR(o.x, 1, 1e-10);
  EXPECT_EQ(o.update(2, 5, 5), Result::rebased);
  EXPECT_NEAR(o.x, 1, 1e-10);
  EXPECT_EQ(o.update(2.1, 20, 20), Result::rebased);
  EXPECT_DOUBLE_EQ(o.linear, 0);
  o.update(2.2, 21, 21);
  EXPECT_NEAR(o.x, 2, 1e-10);
  o.reset_history(); o.update(0.1, 0, 0);
  EXPECT_NEAR(o.x, 2, 1e-10);
  o.update(0.2, 1, 1);
  EXPECT_NEAR(o.x, 3, 1e-10);
}

TEST(WheelOdometry, InvalidConfiguration)
{
  EXPECT_THROW(WheelOdometry(0, 1, 0, 0.2, 30), std::invalid_argument);
  EXPECT_THROW(WheelOdometry(1, -1, 0, 0.2, 30), std::invalid_argument);
  EXPECT_THROW(WheelOdometry(1, 1, 6.28, 0.2, 30), std::invalid_argument);
}
