#pragma once

#include <array>
#include <string>
#include <unordered_map>

#include <rclcpp/rclcpp.hpp>
#include <std_msgs/msg/float64_multi_array.hpp>
#include <std_msgs/msg/int32.hpp>
#include <sensor_msgs/msg/joint_state.hpp>
#include <controller_manager_msgs/srv/switch_controller.hpp>

#include "robot_msgs/msg/mit_command.hpp"

class BldcCommandBridgeNode : public rclcpp::Node
{
public:
  BldcCommandBridgeNode();

private:
  void speedCmdCallback(const robot_msgs::msg::MitCommand::SharedPtr msg);
  void positionCmdCallback(const robot_msgs::msg::MitCommand::SharedPtr msg);
  void actionStateCallback(const std_msgs::msg::Int32::SharedPtr msg);
  void jointStateCallback(const sensor_msgs::msg::JointState::SharedPtr msg);

  void publishVelocityCommands();
  void publishPositionCommands();
  void switchToVelocityController();
  void switchToPositionController();
  void requestControllerSwitch(
    const std::string & activate_controller,
    const std::string & deactivate_controller);

  double wrapToRange(double x, double range) const;
  double shortestWrappedError(double current, double target, double range) const;
  double nearestEquivalentTarget(double current, double target_base, double range) const;
  double getJointPositionRad(const std::string & joint_name, bool & ok) const;

  rclcpp::Subscription<robot_msgs::msg::MitCommand>::SharedPtr speed_cmd_sub_;
  rclcpp::Subscription<robot_msgs::msg::MitCommand>::SharedPtr position_cmd_sub_;
  rclcpp::Subscription<std_msgs::msg::Int32>::SharedPtr action_state_sub_;
  rclcpp::Subscription<sensor_msgs::msg::JointState>::SharedPtr joint_state_sub_;

  rclcpp::Publisher<std_msgs::msg::Float64MultiArray>::SharedPtr velocity_cmd_pub_;
  rclcpp::Publisher<std_msgs::msg::Float64MultiArray>::SharedPtr position_cmd_pub_;

  rclcpp::Client<controller_manager_msgs::srv::SwitchController>::SharedPtr switch_client_;

  std::array<double, 2> velocity_cmds_;
  std::array<double, 2> position_cmds_rad_;

  std::string velocity_controller_name_;
  std::string position_controller_name_;
  std::string current_active_controller_;

  std::string left_joint_name_;
  std::string right_joint_name_;
  double bldc_wrap_turns_;
  double bldc_wrap_range_rad_;

  std::unordered_map<std::string, double> joint_position_map_rad_;
  bool switch_in_progress_;
	std::string pending_target_controller_;
};
