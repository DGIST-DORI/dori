#pragma once

#include <array>
#include <string>

#include <rclcpp/rclcpp.hpp>
#include <sensor_msgs/msg/joint_state.hpp>
#include <std_msgs/msg/float64_multi_array.hpp>

#include "robot_msgs/msg/mit_command.hpp"

class FakeJointStatesNode : public rclcpp::Node
{
public:
  FakeJointStatesNode();

private:
  void publishTimerCallback();
  void inputTimerCallback();
  void processKey(char key);
  void publishJointStates();
  void setPoseA();
  void setPoseB();
  double degToRad(double deg) const;

  void bldcPositionCmdCallback(const robot_msgs::msg::MitCommand::SharedPtr msg);
  void dxlPositionCmdCallback(const std_msgs::msg::Float64MultiArray::SharedPtr msg);

  rclcpp::Publisher<sensor_msgs::msg::JointState>::SharedPtr joint_state_pub_;
  rclcpp::Subscription<robot_msgs::msg::MitCommand>::SharedPtr bldc_position_sub_;
  rclcpp::Subscription<std_msgs::msg::Float64MultiArray>::SharedPtr dxl_position_sub_;

  rclcpp::TimerBase::SharedPtr publish_timer_;
  rclcpp::TimerBase::SharedPtr input_timer_;

  std::string motor1_joint_name_;
  std::string motor2_joint_name_;
  std::string motor3_joint_name_;
  std::string motor4_joint_name_;

  std::array<double, 4> joint_pos_deg_;
  std::array<double, 4> joint_vel_rad_;
};
