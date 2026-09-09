#pragma once

#include <rclcpp/rclcpp.hpp>
#include <geometry_msgs/msg/twist.hpp>
#include <std_msgs/msg/int32.hpp>
#include <std_msgs/msg/bool.hpp>

class KeyboardInputNode : public rclcpp::Node
{
public:
  KeyboardInputNode();

private:
  void timerCallback();
  void processKey(char key);

  void publishManualTwist(double linear_x, double angular_z);
  void publishTransformCmd(int cmd);
  void publishControlMode(int mode);
  void publishEmergencyStop(bool value);
  void publishEmergencyGo(bool value);

  rclcpp::Publisher<geometry_msgs::msg::Twist>::SharedPtr manual_cmd_pub_;
  rclcpp::Publisher<std_msgs::msg::Int32>::SharedPtr manual_transform_pub_;
  rclcpp::Publisher<std_msgs::msg::Int32>::SharedPtr control_mode_pub_;
  rclcpp::Publisher<std_msgs::msg::Bool>::SharedPtr estop_pub_;
  rclcpp::Publisher<std_msgs::msg::Bool>::SharedPtr ego_pub_;

  rclcpp::TimerBase::SharedPtr timer_;

  double manual_linear_speed_;
  double manual_angular_speed_;
};
