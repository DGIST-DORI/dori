#pragma once

#include <vector>

#include <rclcpp/rclcpp.hpp>
#include <sensor_msgs/msg/joy.hpp>
#include <geometry_msgs/msg/twist.hpp>
#include <std_msgs/msg/int32.hpp>
#include <std_msgs/msg/bool.hpp>

class JoystickInputNode : public rclcpp::Node
{
public:
  JoystickInputNode();

private:
  void joyCallback(const sensor_msgs::msg::Joy::SharedPtr msg);
  bool isButtonPressed(const sensor_msgs::msg::Joy::SharedPtr & msg, int index) const;

  rclcpp::Subscription<sensor_msgs::msg::Joy>::SharedPtr joy_sub_;

  rclcpp::Publisher<geometry_msgs::msg::Twist>::SharedPtr manual_cmd_vel_pub_;
  rclcpp::Publisher<std_msgs::msg::Int32>::SharedPtr manual_transform_cmd_pub_;
  rclcpp::Publisher<std_msgs::msg::Int32>::SharedPtr control_mode_cmd_pub_;
  rclcpp::Publisher<std_msgs::msg::Bool>::SharedPtr emergency_stop_pub_;
  rclcpp::Publisher<std_msgs::msg::Bool>::SharedPtr emergency_go_pub_;

  int linear_axis_;
  int angular_axis_;
  double linear_scale_;
  double angular_scale_;
  double deadzone_;

  int transform_to_a_button_;
  int transform_to_b_button_;
  int manual_mode_button_;
  int auto_mode_button_;
  int emergency_stop_button_;
  int emergency_go_button_;

  bool publish_zero_on_idle_;

  std::vector<int> prev_buttons_;
};
