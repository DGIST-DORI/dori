#pragma once

#include <rclcpp/rclcpp.hpp>
#include <std_msgs/msg/string.hpp>
#include "robot_msgs/msg/system_error.hpp"

class ErrorManagerNode : public rclcpp::Node
{
public:
  ErrorManagerNode();

private:
  void errorCallback(const robot_msgs::msg::SystemError::SharedPtr msg);

  rclcpp::Subscription<robot_msgs::msg::SystemError>::SharedPtr error_sub_;
  rclcpp::Publisher<std_msgs::msg::String>::SharedPtr error_log_pub_;
};
