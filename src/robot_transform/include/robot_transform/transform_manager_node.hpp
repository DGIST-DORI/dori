#pragma once

#include <vector>
#include <string>
#include <unordered_map>

#include <rclcpp/rclcpp.hpp>
#include <std_msgs/msg/int32.hpp>
#include <std_msgs/msg/bool.hpp>
#include <sensor_msgs/msg/joint_state.hpp>

#include "robot_msgs/msg/transform_step.hpp"
#include "robot_msgs/msg/transform_step_result.hpp"
#include "robot_msgs/msg/command_feedback.hpp"
#include "robot_msgs/msg/system_error.hpp"

struct StepCommandData
{
  int motor_id;
  int motor_type;
  double target_angle_deg;
  double timeout_sec;
  int retry_count;
};

class TransformManagerNode : public rclcpp::Node
{
public:
  TransformManagerNode();

private:
  void transformRequestCallback(const std_msgs::msg::Int32::SharedPtr msg);
  void pauseCallback(const std_msgs::msg::Bool::SharedPtr msg);
  void resumeCallback(const std_msgs::msg::Bool::SharedPtr msg);
  void stepResultCallback(const robot_msgs::msg::TransformStepResult::SharedPtr msg);

  void bldcJointStateCallback(const sensor_msgs::msg::JointState::SharedPtr msg);
  void dxlJointStateCallback(const sensor_msgs::msg::JointState::SharedPtr msg);

  void delayedStartCallback();

  void publishStep(const StepCommandData & step);
  void publishTransformStatus(int status);
  void publishTransformFeedback(bool accepted, int code, const std::string & message);
  void publishSystemError(int code, const std::string & description);
  void publishCurrentPose(int pose);

  int detectPoseFromReferenceMotor() const;
  bool isAlreadyTargetPose(int request) const;

  void clearSequence();
  void buildReturnBldcToZeroSequence();
  void buildSequenceToA();
  void buildSequenceToB();
  void startNextStep();
  void completeTransform(int pose);
  void failTransform(const std::string & reason, int code);

  double wrapToRangeDeg(double x, double range) const;
  double shortestWrappedErrorDeg(double current, double target, double range) const;

  double snapToNearest90Deg(double angle_deg) const;

  double wrapBldcZeroPhaseTargetDeg(double target_deg) const;
  double getNearestBldcZeroPhaseTargetDeg(int motor_id) const;

  std::string getJointNameForMotor(int motor_id) const;
  int getMotorTypeForMotor(int motor_id) const;
  double getCurrentMotorAngleDeg(int motor_id) const;

  rclcpp::Subscription<std_msgs::msg::Int32>::SharedPtr tf_request_sub_;
  rclcpp::Subscription<std_msgs::msg::Bool>::SharedPtr pause_sub_;
  rclcpp::Subscription<std_msgs::msg::Bool>::SharedPtr resume_sub_;
  rclcpp::Subscription<robot_msgs::msg::TransformStepResult>::SharedPtr step_result_sub_;

  rclcpp::Subscription<sensor_msgs::msg::JointState>::SharedPtr bldc_joint_state_sub_;
  rclcpp::Subscription<sensor_msgs::msg::JointState>::SharedPtr dxl_joint_state_sub_;

  rclcpp::Publisher<robot_msgs::msg::TransformStep>::SharedPtr step_cmd_pub_;
  rclcpp::Publisher<std_msgs::msg::Int32>::SharedPtr tf_status_pub_;
  rclcpp::Publisher<robot_msgs::msg::CommandFeedback>::SharedPtr tf_feedback_pub_;
  rclcpp::Publisher<std_msgs::msg::Int32>::SharedPtr transform_pose_pub_;
  rclcpp::Publisher<robot_msgs::msg::SystemError>::SharedPtr error_pub_;

  rclcpp::TimerBase::SharedPtr delayed_start_timer_;

  int transform_status_;
  int current_pose_;
  int target_pose_;
  bool paused_;

  std::vector<StepCommandData> sequence_;
  std::size_t current_step_index_;

  std::unordered_map<std::string, double> joint_position_deg_map_;

  double pose_ref_angle_deg_;
  bool pose_ref_seen_;
  double pose_detect_tolerance_deg_;
  double default_step_timeout_sec_;
  double initial_step_delay_sec_;
  int force_initial_pose_;

  std::string motor1_joint_name_;
  std::string motor2_joint_name_;
  std::string motor3_joint_name_;
  std::string motor4_joint_name_;

  double dxl_wrap_turns_;
  double dxl_wrap_range_deg_;

  double bldc_wrap_turns_;
  double bldc_wrap_range_deg_;

  double bldc1_zero_phase_target_deg_;
  double bldc2_zero_phase_target_deg_;
};
