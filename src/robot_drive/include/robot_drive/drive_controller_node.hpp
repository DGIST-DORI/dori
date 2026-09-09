#pragma once

#include <string>

#include <rclcpp/rclcpp.hpp>

#include <geometry_msgs/msg/twist.hpp>

#include <std_msgs/msg/string.hpp>
#include <std_msgs/msg/int32.hpp>
#include <std_msgs/msg/float64.hpp>

#include <sensor_msgs/msg/joint_state.hpp>

#include "robot_msgs/msg/mit_command.hpp"
#include "robot_msgs/msg/command_feedback.hpp"


class DriveControllerNode : public rclcpp::Node
{
public:
  DriveControllerNode();

private:

  // ==========================================================
  // Callbacks
  // ==========================================================

  void driveCmdCallback(
    const geometry_msgs::msg::Twist::SharedPtr msg);

  void driveProfileCallback(
    const std_msgs::msg::String::SharedPtr msg);

  void transformStatusCallback(
    const std_msgs::msg::Int32::SharedPtr msg);

  void stabilizationTorqueCallback(
    const std_msgs::msg::Float64::SharedPtr msg);

  void jointStateCallback(
    const sensor_msgs::msg::JointState::SharedPtr msg);

  void controlLoopCallback();


  // ==========================================================
  // Helpers
  // ==========================================================

  double clamp(
    double value,
    double min_value,
    double max_value) const;

  double applyRateLimit(
    double target,
    double current,
    double rate_limit,
    double dt) const;

  double applyAccelDecelLimit(
    double target,
    double current,
    double accel_limit,
    double decel_limit,
    double dt) const;

  double updateObstacleBoost(
    double v_des,
    double v_actual,
    bool joint_state_valid,
    bool & blocked_condition,
    bool & obstacle_active,
    bool & stall_lockout,
    rclcpp::Time & blocked_start_time,
    rclcpp::Time & obstacle_start_time,
    double current_boost,
    double dt,
    const rclcpp::Time & now,
    const std::string & wheel_name);


  // ==========================================================
  // Output
  // ==========================================================

  void publishMitSpeedCommand(
    int motor_id,
    double v_des,
    double feedforward_tau,
    double stabilization_tau,
    double obstacle_tau);

  void publishDriveFeedback(
    bool accepted,
    int code,
    const std::string & message);

  void applyDriveProfile(
    const std::string & profile_name);


  // ==========================================================
  // Subscribers
  // ==========================================================

  rclcpp::Subscription<
    geometry_msgs::msg::Twist>::SharedPtr
    drive_cmd_sub_;

  rclcpp::Subscription<
    std_msgs::msg::String>::SharedPtr
    drive_profile_sub_;

  rclcpp::Subscription<
    std_msgs::msg::Int32>::SharedPtr
    transform_status_sub_;

  rclcpp::Subscription<
    std_msgs::msg::Float64>::SharedPtr
    stabilization_torque_sub_;

  rclcpp::Subscription<
    sensor_msgs::msg::JointState>::SharedPtr
    joint_state_sub_;
    
  rclcpp::Publisher<std_msgs::msg::Float64>::SharedPtr
    target_linear_debug_pub_;

  rclcpp::Publisher<std_msgs::msg::Float64>::SharedPtr
    current_linear_debug_pub_;

  rclcpp::Publisher<std_msgs::msg::Float64>::SharedPtr
    actual_linear_debug_pub_;

  rclcpp::Publisher<std_msgs::msg::Float64>::SharedPtr
    left_v_des_debug_pub_;

  rclcpp::Publisher<std_msgs::msg::Float64>::SharedPtr
    right_v_des_debug_pub_;

  rclcpp::Publisher<std_msgs::msg::Float64>::SharedPtr
    active_pd_debug_pub_;

  rclcpp::Publisher<std_msgs::msg::Float64>::SharedPtr
    left_final_torque_debug_pub_;

  rclcpp::Publisher<std_msgs::msg::Float64>::SharedPtr
    right_final_torque_debug_pub_;


  // ==========================================================
  // Publishers
  // ==========================================================

  
  rclcpp::Publisher<
    robot_msgs::msg::MitCommand>::SharedPtr
    mit_speed_pub_;

  rclcpp::Publisher<
    robot_msgs::msg::CommandFeedback>::SharedPtr
    drive_feedback_pub_;


  // ==========================================================
  // Feedforward debug publishers
  // ==========================================================

  // 가감속 limiter를 통과한 명령 선가속도 [m/s^2]
rclcpp::Publisher<
  std_msgs::msg::Float64>::SharedPtr
  command_linear_accel_pub_;

// 가속도 Feedforward가 만들어낸 torque command
rclcpp::Publisher<
  std_msgs::msg::Float64>::SharedPtr
  feedforward_torque_pub_;


  // ==========================================================
  // Timer
  // ==========================================================

  rclcpp::TimerBase::SharedPtr
    control_timer_;


  // ==========================================================
  // Geometry
  // ==========================================================

  double wheel_radius_;
  double wheel_separation_;


  // ==========================================================
  // Drive limits
  // ==========================================================

  double max_linear_velocity_;
  double max_angular_velocity_;

  double linear_accel_limit_;
  double linear_decel_limit_;

  double angular_accel_limit_;
  double angular_decel_limit_;


  // ==========================================================
  // Target command
  // ==========================================================

  double target_linear_cmd_;
  double target_angular_cmd_;


  // ==========================================================
  // Rate-limited current command
  // ==========================================================

  double current_linear_cmd_;
  double current_angular_cmd_;

  rclcpp::Time last_control_time_;


  // ==========================================================
  // Feedforward stabilization
  //
  // tau_FF = Kff * commanded_linear_acceleration
  // ==========================================================

  bool feedforward_enabled_;

  double feedforward_gain_;

  double feedforward_torque_limit_;

  double feedforward_accel_deadband_;

  double previous_linear_cmd_;

  double command_linear_accel_;

  double feedforward_torque_;
  
  double final_torque_limit_;


  // ==========================================================
  // MIT speed mode
  // ==========================================================

  double speed_mode_kd_;
  double speed_mode_tau_ff_;


  // ==========================================================
  // Drive profiles
  // ==========================================================

  double drive_normal_vel_kd_;
  double drive_normal_tau_ff_;

  double drive_slope_vel_kd_;
  double drive_slope_tau_ff_;

  double drive_obstacle_vel_kd_;
  double drive_obstacle_tau_ff_;

  std::string current_drive_profile_;


  // ==========================================================
  // Transform
  // ==========================================================

  bool transform_active_;


  // ==========================================================
  // IMU stabilization
  // ==========================================================

  double stabilization_torque_;
  double stabilization_torque_limit_;
  double stabilization_timeout_sec_;

  rclcpp::Time last_stabilization_time_;

  bool stabilization_received_;


  // ==========================================================
  // Joint-state feedback
  // ==========================================================

  double left_actual_velocity_;
  double right_actual_velocity_;

  bool left_velocity_received_;
  bool right_velocity_received_;

  rclcpp::Time last_joint_state_time_;

  double joint_state_timeout_sec_;

  std::string left_joint_name_;
  std::string right_joint_name_;


  // ==========================================================
  // Obstacle detection parameters
  // ==========================================================

  bool obstacle_detection_enabled_;

  double obstacle_min_command_velocity_;

  double obstacle_velocity_ratio_threshold_;

  double obstacle_detect_time_sec_;

  double obstacle_torque_limit_;

  double obstacle_torque_ramp_up_;
  double obstacle_torque_ramp_down_;

  double obstacle_stall_timeout_sec_;

  double obstacle_recovery_ratio_;


  // ==========================================================
  // Left obstacle state
  // ==========================================================

  bool left_blocked_condition_;
  bool left_obstacle_active_;
  bool left_stall_lockout_;

  rclcpp::Time left_blocked_start_time_;
  rclcpp::Time left_obstacle_start_time_;

  double left_obstacle_boost_;


  // ==========================================================
  // Right obstacle state
  // ==========================================================

  bool right_blocked_condition_;
  bool right_obstacle_active_;
  bool right_stall_lockout_;

  rclcpp::Time right_blocked_start_time_;
  rclcpp::Time right_obstacle_start_time_;

  double right_obstacle_boost_;


  // ==========================================================
  // Control loop
  // ==========================================================

  double control_frequency_hz_;
};
