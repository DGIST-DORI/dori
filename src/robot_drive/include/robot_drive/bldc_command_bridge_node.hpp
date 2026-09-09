#pragma once

#include <array>
#include <string>
#include <unordered_map>
#include <vector>

#include <rclcpp/rclcpp.hpp>
#include <std_msgs/msg/float64_multi_array.hpp>
#include <std_msgs/msg/int32.hpp>
#include <sensor_msgs/msg/joint_state.hpp>
#include <controller_manager_msgs/srv/switch_controller.hpp>
#include <std_msgs/msg/float64.hpp>

#include "robot_msgs/msg/mit_command.hpp"


class BldcCommandBridgeNode : public rclcpp::Node
{
public:
  BldcCommandBridgeNode();

private:
  // ==========================================================
  // ROS callbacks
  // ==========================================================

  void speedCmdCallback(
    const robot_msgs::msg::MitCommand::SharedPtr msg);

  void positionCmdCallback(
    const robot_msgs::msg::MitCommand::SharedPtr msg);

  void actionStateCallback(
    const std_msgs::msg::Int32::SharedPtr msg);

  void jointStateCallback(
    const sensor_msgs::msg::JointState::SharedPtr msg);
    
  void stabilizationTorqueCallback(
    const std_msgs::msg::Float64::SharedPtr msg);


  // ==========================================================
  // Command publish
  // ==========================================================

  void publishDriveCommands();

  void publishPositionCommands();


  // ==========================================================
  // Controller switching
  // ==========================================================

  void switchToDriveControllers();

  void switchToPositionController();

  void requestControllerSwitch(
    const std::vector<std::string> & activate_controllers,
    const std::vector<std::string> & deactivate_controllers);


  // ==========================================================
  // Position helper functions
  // ==========================================================

  double wrapToRange(
    double x,
    double range) const;

  double shortestWrappedError(
    double current,
    double target,
    double range) const;

  double nearestEquivalentTarget(
    double current,
    double target_base,
    double range) const;

  double getJointPositionRad(
    const std::string & joint_name,
    bool & ok) const;


  // ==========================================================
  // Subscribers
  // ==========================================================

  rclcpp::Subscription<
    robot_msgs::msg::MitCommand>::SharedPtr speed_cmd_sub_;

  rclcpp::Subscription<
    robot_msgs::msg::MitCommand>::SharedPtr position_cmd_sub_;

  rclcpp::Subscription<
    std_msgs::msg::Int32>::SharedPtr action_state_sub_;

  rclcpp::Subscription<
    sensor_msgs::msg::JointState>::SharedPtr joint_state_sub_;
    
  rclcpp::Subscription<std_msgs::msg::Float64>::SharedPtr
    stabilization_torque_sub_;


  // ==========================================================
  // Publishers
  //
  // 각 drive controller는 한 joint의
  // velocity + effort interface를 동시에 제어
  // ==========================================================

  rclcpp::Publisher<
    std_msgs::msg::Float64MultiArray>::SharedPtr
    left_drive_cmd_pub_;

  rclcpp::Publisher<
    std_msgs::msg::Float64MultiArray>::SharedPtr
    right_drive_cmd_pub_;

  rclcpp::Publisher<
    std_msgs::msg::Float64MultiArray>::SharedPtr
    position_cmd_pub_;


  // ==========================================================
  // Controller manager client
  // ==========================================================

  rclcpp::Client<
    controller_manager_msgs::srv::SwitchController>::SharedPtr
    switch_client_;


  // ==========================================================
  // Commands
  // ==========================================================

  // wheel target velocity [rad/s]
  std::array<double, 2> velocity_cmds_;

  // MIT external tau_ff [Nm]
  std::array<double, 2> effort_cmds_;

  // transform position [rad]
  std::array<double, 2> position_cmds_rad_;


  // ==========================================================
  // Controller names
  // ==========================================================

  std::string left_drive_controller_name_;
  std::string right_drive_controller_name_;
  std::string position_controller_name_;

  // "drive" / "position"
  std::string current_control_mode_;


  // ==========================================================
  // Joint configuration
  // ==========================================================

  std::string left_joint_name_;
  std::string right_joint_name_;

  double bldc_wrap_turns_;
  double bldc_wrap_range_rad_;
  double stabilization_torque_;
  double stabilization_torque_limit_;


  // ==========================================================
  // Joint state cache
  // ==========================================================

  std::unordered_map<std::string, double>
    joint_position_map_rad_;


  // ==========================================================
  // Switch state
  // ==========================================================

  bool switch_in_progress_;
};
