#pragma once
#include <cmath>
#include <string>
#include "control_msgs/msg/dynamic_joint_state.hpp"

namespace dori_drive {
inline bool feedback_fresh(const control_msgs::msg::DynamicJointState & msg,
  const std::string & left, const std::string & right, double timeout, double transport_age = 0.0)
{
  if (!std::isfinite(transport_age) || transport_age < 0) return false;
  bool left_ok = false, right_ok = false;
  for (size_t i = 0; i < msg.joint_names.size() && i < msg.interface_values.size(); ++i) {
    const auto & values = msg.interface_values[i];
    for (size_t j = 0; j < values.interface_names.size() && j < values.values.size(); ++j) {
      if (values.interface_names[j] != "feedback_age") continue;
      const double age = values.values[j];
      const bool valid = std::isfinite(age) && age >= 0 && age + transport_age <= timeout;
      if (msg.joint_names[i] == left) left_ok = valid;
      if (msg.joint_names[i] == right) right_ok = valid;
    }
  }
  return left_ok && right_ok;
}
}
