#pragma once

#include <rclcpp/rclcpp.hpp>
#include <std_msgs/msg/string.hpp>
#include "dori_msgs/msg/system_error.hpp"

class ErrorManagerNode : public rclcpp::Node
{
public:
  ErrorManagerNode();

private:
  void errorCallback(const dori_msgs::msg::SystemError::SharedPtr msg);

  rclcpp::Subscription<dori_msgs::msg::SystemError>::SharedPtr error_sub_;
  rclcpp::Publisher<std_msgs::msg::String>::SharedPtr error_log_pub_;
};
