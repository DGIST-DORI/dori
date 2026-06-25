#pragma once

#include <string>
#include <unordered_map>

#include <rclcpp/rclcpp.hpp>
#include <sensor_msgs/msg/joint_state.hpp>
#include <std_msgs/msg/float64_multi_array.hpp>
#include <std_msgs/msg/string.hpp>

#include "robot_msgs/msg/transform_step.hpp"
#include "robot_msgs/msg/transform_step_result.hpp"
#include "robot_msgs/msg/mit_command.hpp"
#include "robot_msgs/msg/system_error.hpp"

class TransformControllerNode : public rclcpp::Node
{
public:
  TransformControllerNode();

private:
  void stepCmdCallback(const robot_msgs::msg::TransformStep::SharedPtr msg);

  void bldcJointStateCallback(const sensor_msgs::msg::JointState::SharedPtr msg);
  void dxlJointStateCallback(const sensor_msgs::msg::JointState::SharedPtr msg);

  void controlTimerCallback();
  void transformProfileCallback(const std_msgs::msg::String::SharedPtr msg);

  void publishStepResult(bool success, bool timeout, const std::string & message);

  void publishBldcPositionCmd(int motor_id, double raw_target_deg);
  void publishBldcSpeedCmd(int motor_id, double v_des);
  void publishBldcStopCmd();

  double applyBldcSpeedRateLimit(int motor_id, double desired_v, double dt);
  void resetBldcSpeedLimiter();

  void publishDxlPositionCmd(int motor_id, double target_deg);

  double getMotorAngleDeg(int motor_id) const;
  double getMotorVelocityRad(int motor_id) const;

  double wrapToRangeDeg(double x, double range) const;
  double shortestWrappedErrorDeg(double current, double target, double range) const;
  double getWrapRangeDegForMotor(int motor_id) const;

  void applyTransformProfile(const std::string & profile_name);

  rclcpp::Subscription<robot_msgs::msg::TransformStep>::SharedPtr step_cmd_sub_;
  rclcpp::Subscription<sensor_msgs::msg::JointState>::SharedPtr bldc_joint_state_sub_;
  rclcpp::Subscription<sensor_msgs::msg::JointState>::SharedPtr dxl_joint_state_sub_;
  rclcpp::Subscription<std_msgs::msg::String>::SharedPtr transform_profile_sub_;

  rclcpp::Publisher<robot_msgs::msg::TransformStepResult>::SharedPtr step_result_pub_;
  rclcpp::Publisher<robot_msgs::msg::MitCommand>::SharedPtr mit_position_pub_;
  rclcpp::Publisher<robot_msgs::msg::MitCommand>::SharedPtr mit_speed_pub_;
  rclcpp::Publisher<std_msgs::msg::Float64MultiArray>::SharedPtr dxl_position_pub_;
  rclcpp::Publisher<robot_msgs::msg::SystemError>::SharedPtr error_pub_;

  rclcpp::TimerBase::SharedPtr control_timer_;

  bool step_active_;
  bool active_bldc_posvel_;

  int active_motor_id_;
  int active_motor_type_;
  double target_angle_deg_;
  double timeout_sec_;
  int retry_count_;

  rclcpp::Time step_start_time_;
  rclcpp::Time settle_start_time_;
  bool settle_started_;

  double position_tolerance_deg_;
  double velocity_tolerance_rad_s_;
  double settle_time_sec_;

  double mit_position_kp_;
  double mit_position_kd_;
  double mit_position_tau_ff_;

  double transform_precise_pos_kp_;
  double transform_precise_pos_kd_;
  double transform_precise_tau_ff_;

  double transform_fast_pos_kp_;
  double transform_fast_pos_kd_;
  double transform_fast_tau_ff_;

  double transform_soft_pos_kp_;
  double transform_soft_pos_kd_;
  double transform_soft_tau_ff_;

  std::string current_transform_profile_;

  bool test_auto_success_;
  double test_auto_success_delay_sec_;

  std::string motor1_joint_name_;
  std::string motor2_joint_name_;
  std::string motor3_joint_name_;
  std::string motor4_joint_name_;

  double bldc_wrap_turns_;
  double dxl_wrap_turns_;
  double bldc_wrap_range_deg_;
  double dxl_wrap_range_deg_;

  double bldc_posvel_kp_;
  double bldc_posvel_kd_;
  double bldc_posvel_max_vel_rad_s_;
  double bldc_posvel_min_vel_rad_s_;
  double bldc_posvel_position_tolerance_deg_;
  double bldc_posvel_velocity_tolerance_rad_s_;
  double bldc_posvel_accel_limit_rad_s2_;
  double bldc_posvel_jerk_limit_rad_s3_;
  double bldc_mit_speed_kd_;

  double last_bldc_speed_cmd_1_;
  double last_bldc_speed_cmd_2_;
  double last_bldc_accel_cmd_1_;
  double last_bldc_accel_cmd_2_;

  rclcpp::Time last_control_time_;
  bool has_last_control_time_;

  std::unordered_map<std::string, double> joint_position_deg_map_;
  std::unordered_map<std::string, double> joint_velocity_rad_map_;
};
