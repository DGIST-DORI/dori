#pragma once

#include <rclcpp/rclcpp.hpp>
#include <geometry_msgs/msg/twist.hpp>
#include <std_msgs/msg/int32.hpp>

class VirtualVlmInputNode : public rclcpp::Node
{
public:
  VirtualVlmInputNode();

private:
  void timerCallback();
  void processKey(char key);

  void publishAutoTwist(double linear_x, double angular_z);
  void publishTransformCmd(int cmd);

  rclcpp::Publisher<geometry_msgs::msg::Twist>::SharedPtr auto_cmd_pub_;
  rclcpp::Publisher<std_msgs::msg::Int32>::SharedPtr auto_transform_pub_;

  rclcpp::TimerBase::SharedPtr timer_;

  double auto_linear_speed_;
  double auto_angular_speed_;
};
