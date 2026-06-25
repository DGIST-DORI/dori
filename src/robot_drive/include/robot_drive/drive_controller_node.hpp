#pragma once

#include <string>

#include <rclcpp/rclcpp.hpp>
#include <geometry_msgs/msg/twist.hpp>
#include <std_msgs/msg/string.hpp>
#include <std_msgs/msg/int32.hpp>

#include "robot_msgs/msg/mit_command.hpp"
#include "robot_msgs/msg/command_feedback.hpp"

class DriveControllerNode : public rclcpp::Node
{
public:
  DriveControllerNode();

private:
  void driveCmdCallback(const geometry_msgs::msg::Twist::SharedPtr msg);
  void driveProfileCallback(const std_msgs::msg::String::SharedPtr msg);
  void transformStatusCallback(const std_msgs::msg::Int32::SharedPtr msg);

  double clamp(double value, double min_value, double max_value) const;
  double applyRateLimit(double target, double current, double rate_limit, double dt) const;

  void publishMitSpeedCommand(int motor_id, double v_des);
  void publishDriveFeedback(bool accepted, int code, const std::string & message);
  void applyDriveProfile(const std::string & profile_name);

  rclcpp::Subscription<geometry_msgs::msg::Twist>::SharedPtr drive_cmd_sub_;
  rclcpp::Subscription<std_msgs::msg::String>::SharedPtr drive_profile_sub_;
  rclcpp::Subscription<std_msgs::msg::Int32>::SharedPtr transform_status_sub_;

  rclcpp::Publisher<robot_msgs::msg::MitCommand>::SharedPtr mit_speed_pub_;
  rclcpp::Publisher<robot_msgs::msg::CommandFeedback>::SharedPtr drive_feedback_pub_;

  double wheel_radius_;
  double wheel_separation_;

  double max_linear_velocity_;
  double max_angular_velocity_;
  double linear_accel_limit_;
  double angular_accel_limit_;

  double current_linear_cmd_;
  double current_angular_cmd_;

  double speed_mode_kd_;
  double speed_mode_tau_ff_;

  double drive_normal_vel_kd_;
  double drive_normal_tau_ff_;

  double drive_slope_vel_kd_;
  double drive_slope_tau_ff_;

  double drive_obstacle_vel_kd_;
  double drive_obstacle_tau_ff_;

  std::string current_drive_profile_;

  rclcpp::Time last_cmd_time_;

  bool transform_active_;
};
