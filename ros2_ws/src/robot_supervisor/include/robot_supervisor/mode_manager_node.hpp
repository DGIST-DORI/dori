#pragma once

#include <string>

#include <rclcpp/rclcpp.hpp>
#include <geometry_msgs/msg/twist.hpp>
#include <std_msgs/msg/int32.hpp>
#include <std_msgs/msg/bool.hpp>
#include <std_msgs/msg/string.hpp>

#include "robot_msgs/msg/command_feedback.hpp"
#include "robot_msgs/msg/system_error.hpp"

class ModeManagerNode : public rclcpp::Node
{
public:
  ModeManagerNode();

private:
  void manualCmdCallback(const geometry_msgs::msg::Twist::SharedPtr msg);
  void autoCmdCallback(const geometry_msgs::msg::Twist::SharedPtr msg);
  void manualTransformCallback(const std_msgs::msg::Int32::SharedPtr msg);
  void autoTransformCallback(const std_msgs::msg::Int32::SharedPtr msg);
  void controlModeCallback(const std_msgs::msg::Int32::SharedPtr msg);
  void estopCallback(const std_msgs::msg::Bool::SharedPtr msg);
  void egoCallback(const std_msgs::msg::Bool::SharedPtr msg);
  void transformStatusCallback(const std_msgs::msg::Int32::SharedPtr msg);
  void transformFeedbackCallback(const robot_msgs::msg::CommandFeedback::SharedPtr msg);
  void systemErrorCallback(const robot_msgs::msg::SystemError::SharedPtr msg);
  void autoTimeoutTimerCallback();

  void publishDriveCmd(const geometry_msgs::msg::Twist & cmd);
  void publishZeroDrive();
  void publishTransformRequest(int req);
  void publishTransformPause(bool value);
  void publishTransformResume(bool value);
  void publishTransformProfile(const std::string & profile_name);

  void publishDriveFeedback(bool accepted, int code, const std::string & message);
  void publishSystemControlMode(int mode);
  void publishSystemActionState(int state);
  void publishSystemTransformPose(int pose);

  void setControlMode(int mode);
  void setActionState(int state);
  void clearBuffers();

  bool isTransformBusy() const;

  rclcpp::Subscription<geometry_msgs::msg::Twist>::SharedPtr manual_cmd_sub_;
  rclcpp::Subscription<geometry_msgs::msg::Twist>::SharedPtr auto_cmd_sub_;
  rclcpp::Subscription<std_msgs::msg::Int32>::SharedPtr manual_tf_sub_;
  rclcpp::Subscription<std_msgs::msg::Int32>::SharedPtr auto_tf_sub_;
  rclcpp::Subscription<std_msgs::msg::Int32>::SharedPtr control_mode_sub_;
  rclcpp::Subscription<std_msgs::msg::Bool>::SharedPtr estop_sub_;
  rclcpp::Subscription<std_msgs::msg::Bool>::SharedPtr ego_sub_;
  rclcpp::Subscription<std_msgs::msg::Int32>::SharedPtr tf_status_sub_;
  rclcpp::Subscription<robot_msgs::msg::CommandFeedback>::SharedPtr tf_feedback_sub_;
  rclcpp::Subscription<robot_msgs::msg::SystemError>::SharedPtr error_sub_;

  rclcpp::Publisher<geometry_msgs::msg::Twist>::SharedPtr drive_cmd_pub_;
  rclcpp::Publisher<std_msgs::msg::Int32>::SharedPtr transform_request_pub_;
  rclcpp::Publisher<std_msgs::msg::Bool>::SharedPtr transform_pause_pub_;
  rclcpp::Publisher<std_msgs::msg::Bool>::SharedPtr transform_resume_pub_;
  rclcpp::Publisher<std_msgs::msg::Int32>::SharedPtr control_mode_pub_;
  rclcpp::Publisher<std_msgs::msg::Int32>::SharedPtr action_state_pub_;
  rclcpp::Publisher<std_msgs::msg::Int32>::SharedPtr transform_pose_pub_;
  rclcpp::Publisher<robot_msgs::msg::CommandFeedback>::SharedPtr drive_feedback_pub_;
  rclcpp::Publisher<std_msgs::msg::String>::SharedPtr transform_profile_pub_;

  rclcpp::TimerBase::SharedPtr auto_timeout_timer_;

  int control_mode_;
  int action_state_;
  int transform_status_;
  int current_pose_;

  bool estop_active_;
  bool error_active_;

  geometry_msgs::msg::Twist last_manual_cmd_;
  geometry_msgs::msg::Twist last_auto_cmd_;
  rclcpp::Time last_auto_cmd_time_;
  double auto_timeout_sec_;

  std::string transform_profile_before_transform_;
  std::string transform_profile_for_transform_;
  std::string default_transform_profile_;
};
