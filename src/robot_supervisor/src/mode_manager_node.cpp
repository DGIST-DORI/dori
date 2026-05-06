#include "robot_supervisor/mode_manager_node.hpp"

#include <chrono>

using namespace std::chrono_literals;

namespace
{
constexpr int MANUAL = 0;
constexpr int AUTO = 1;

constexpr int IDLE = 0;
constexpr int DRIVE = 1;
constexpr int TRANSFORM = 2;
constexpr int TRANSFORM_PAUSED = 3;
constexpr int ESTOP = 4;
constexpr int ERROR = 5;

constexpr int TF_IDLE = 0;
constexpr int TF_RUNNING = 1;
constexpr int TF_PAUSED = 2;
constexpr int TF_DONE = 3;
constexpr int TF_FAILED = 4;

constexpr int DRIVE_ACCEPTED = 100;
constexpr int REJECTED_TRANSFORM_ACTIVE = 101;
constexpr int REJECTED_ESTOP = 102;
constexpr int REJECTED_ERROR = 103;
constexpr int REJECTED_WRONG_CONTROL_SOURCE = 104;
constexpr int STOPPED_AUTO_TIMEOUT = 106;
constexpr int STOPPED_BY_CLEAR = 107;
}

ModeManagerNode::ModeManagerNode()
: Node("mode_manager_node"),
  control_mode_(MANUAL),
  action_state_(IDLE),
  transform_status_(TF_IDLE),
  current_pose_(0),
  estop_active_(false),
  error_active_(false),
  auto_timeout_sec_(1.0),
  transform_profile_before_transform_("precise"),
  transform_profile_for_transform_("precise"),
  default_transform_profile_("precise")
{
  this->declare_parameter("auto_timeout_sec", auto_timeout_sec_);
  this->declare_parameter("default_transform_profile", default_transform_profile_);
  this->declare_parameter("transform_profile_for_transform", transform_profile_for_transform_);

  this->get_parameter("auto_timeout_sec", auto_timeout_sec_);
  this->get_parameter("default_transform_profile", default_transform_profile_);
  this->get_parameter("transform_profile_for_transform", transform_profile_for_transform_);

  transform_profile_before_transform_ = default_transform_profile_;

  manual_cmd_sub_ = this->create_subscription<geometry_msgs::msg::Twist>(
    "/manual/cmd_vel", 20,
    std::bind(&ModeManagerNode::manualCmdCallback, this, std::placeholders::_1));

  auto_cmd_sub_ = this->create_subscription<geometry_msgs::msg::Twist>(
    "/auto/cmd_vel", 20,
    std::bind(&ModeManagerNode::autoCmdCallback, this, std::placeholders::_1));

  manual_tf_sub_ = this->create_subscription<std_msgs::msg::Int32>(
    "/manual/transform_cmd", 20,
    std::bind(&ModeManagerNode::manualTransformCallback, this, std::placeholders::_1));

  auto_tf_sub_ = this->create_subscription<std_msgs::msg::Int32>(
    "/auto/transform_cmd", 20,
    std::bind(&ModeManagerNode::autoTransformCallback, this, std::placeholders::_1));

  control_mode_sub_ = this->create_subscription<std_msgs::msg::Int32>(
    "/control_mode_cmd", 20,
    std::bind(&ModeManagerNode::controlModeCallback, this, std::placeholders::_1));

  estop_sub_ = this->create_subscription<std_msgs::msg::Bool>(
    "/emergency_stop", 20,
    std::bind(&ModeManagerNode::estopCallback, this, std::placeholders::_1));

  ego_sub_ = this->create_subscription<std_msgs::msg::Bool>(
    "/emergency_go", 20,
    std::bind(&ModeManagerNode::egoCallback, this, std::placeholders::_1));

  tf_status_sub_ = this->create_subscription<std_msgs::msg::Int32>(
    "/transform/status", 20,
    std::bind(&ModeManagerNode::transformStatusCallback, this, std::placeholders::_1));

  tf_feedback_sub_ = this->create_subscription<robot_msgs::msg::CommandFeedback>(
    "/transform/command_feedback", 20,
    std::bind(&ModeManagerNode::transformFeedbackCallback, this, std::placeholders::_1));

  error_sub_ = this->create_subscription<robot_msgs::msg::SystemError>(
    "/system/error", 20,
    std::bind(&ModeManagerNode::systemErrorCallback, this, std::placeholders::_1));

  drive_cmd_pub_ = this->create_publisher<geometry_msgs::msg::Twist>("/drive/cmd_vel", 20);
  transform_request_pub_ = this->create_publisher<std_msgs::msg::Int32>("/transform/request", 20);
  transform_pause_pub_ = this->create_publisher<std_msgs::msg::Bool>("/transform/pause", 20);
  transform_resume_pub_ = this->create_publisher<std_msgs::msg::Bool>("/transform/resume", 20);
  control_mode_pub_ = this->create_publisher<std_msgs::msg::Int32>("/system/control_mode", 20);
  action_state_pub_ = this->create_publisher<std_msgs::msg::Int32>("/system/action_state", 20);
  transform_pose_pub_ = this->create_publisher<std_msgs::msg::Int32>("/system/transform_pose", 20);
  drive_feedback_pub_ = this->create_publisher<robot_msgs::msg::CommandFeedback>("/drive/command_feedback", 20);
  transform_profile_pub_ = this->create_publisher<std_msgs::msg::String>("/transform/profile_cmd", 20);

  auto_timeout_timer_ = this->create_wall_timer(
    100ms, std::bind(&ModeManagerNode::autoTimeoutTimerCallback, this));

  last_auto_cmd_time_ = this->now();

  publishSystemControlMode(control_mode_);
  publishSystemActionState(action_state_);
  publishSystemTransformPose(current_pose_);
  publishTransformProfile(default_transform_profile_);

  RCLCPP_INFO(this->get_logger(), "mode_manager_node started");
}

bool ModeManagerNode::isTransformBusy() const
{
  return transform_status_ == TF_RUNNING || transform_status_ == TF_PAUSED ||
         action_state_ == TRANSFORM || action_state_ == TRANSFORM_PAUSED;
}

void ModeManagerNode::publishDriveCmd(const geometry_msgs::msg::Twist & cmd)
{
  drive_cmd_pub_->publish(cmd);
}

void ModeManagerNode::publishZeroDrive()
{
  geometry_msgs::msg::Twist zero;
  drive_cmd_pub_->publish(zero);
}

void ModeManagerNode::publishTransformRequest(int req)
{
  std_msgs::msg::Int32 msg;
  msg.data = req;
  transform_request_pub_->publish(msg);
}

void ModeManagerNode::publishTransformPause(bool value)
{
  std_msgs::msg::Bool msg;
  msg.data = value;
  transform_pause_pub_->publish(msg);
}

void ModeManagerNode::publishTransformResume(bool value)
{
  std_msgs::msg::Bool msg;
  msg.data = value;
  transform_resume_pub_->publish(msg);
}

void ModeManagerNode::publishTransformProfile(const std::string & profile_name)
{
  std_msgs::msg::String msg;
  msg.data = profile_name;
  transform_profile_pub_->publish(msg);
}

void ModeManagerNode::publishDriveFeedback(bool accepted, int code, const std::string & message)
{
  robot_msgs::msg::CommandFeedback fb;
  fb.source_node = "mode_manager_node";
  fb.command_type = "drive";
  fb.accepted = accepted;
  fb.code = code;
  fb.message = message;
  drive_feedback_pub_->publish(fb);
}

void ModeManagerNode::publishSystemControlMode(int mode)
{
  std_msgs::msg::Int32 msg;
  msg.data = mode;
  control_mode_pub_->publish(msg);
}

void ModeManagerNode::publishSystemActionState(int state)
{
  std_msgs::msg::Int32 msg;
  msg.data = state;
  action_state_pub_->publish(msg);
}

void ModeManagerNode::publishSystemTransformPose(int pose)
{
  std_msgs::msg::Int32 msg;
  msg.data = pose;
  transform_pose_pub_->publish(msg);
}

void ModeManagerNode::setControlMode(int mode)
{
  control_mode_ = mode;
  publishSystemControlMode(control_mode_);
  RCLCPP_INFO(this->get_logger(), "Control mode changed to %d", control_mode_);
}

void ModeManagerNode::setActionState(int state)
{
  action_state_ = state;
  publishSystemActionState(action_state_);
  RCLCPP_INFO(this->get_logger(), "Action state changed to %d", action_state_);
}

void ModeManagerNode::clearBuffers()
{
  last_manual_cmd_ = geometry_msgs::msg::Twist();
  last_auto_cmd_ = geometry_msgs::msg::Twist();
  publishDriveFeedback(true, STOPPED_BY_CLEAR, "Drive buffers cleared");
}

void ModeManagerNode::manualCmdCallback(const geometry_msgs::msg::Twist::SharedPtr msg)
{
  last_manual_cmd_ = *msg;

  if (control_mode_ != MANUAL) {
    publishZeroDrive();
    publishDriveFeedback(false, REJECTED_WRONG_CONTROL_SOURCE, "Manual drive rejected: control mode is AUTO");
    return;
  }
  if (estop_active_) {
    publishZeroDrive();
    publishDriveFeedback(false, REJECTED_ESTOP, "Manual drive rejected: estop active");
    return;
  }
  if (error_active_) {
    publishZeroDrive();
    publishDriveFeedback(false, REJECTED_ERROR, "Manual drive rejected: error active");
    return;
  }
  if (isTransformBusy()) {
    publishZeroDrive();
    publishDriveFeedback(false, REJECTED_TRANSFORM_ACTIVE, "Manual drive rejected: transform active");
    return;
  }

  publishDriveCmd(*msg);
  setActionState(DRIVE);
  publishDriveFeedback(true, DRIVE_ACCEPTED, "Manual drive accepted");
}

void ModeManagerNode::autoCmdCallback(const geometry_msgs::msg::Twist::SharedPtr msg)
{
  last_auto_cmd_ = *msg;
  last_auto_cmd_time_ = this->now();

  if (control_mode_ != AUTO) {
    publishZeroDrive();
    publishDriveFeedback(false, REJECTED_WRONG_CONTROL_SOURCE, "Auto drive rejected: control mode is MANUAL");
    return;
  }
  if (estop_active_) {
    publishZeroDrive();
    publishDriveFeedback(false, REJECTED_ESTOP, "Auto drive rejected: estop active");
    return;
  }
  if (error_active_) {
    publishZeroDrive();
    publishDriveFeedback(false, REJECTED_ERROR, "Auto drive rejected: error active");
    return;
  }
  if (isTransformBusy()) {
    publishZeroDrive();
    publishDriveFeedback(false, REJECTED_TRANSFORM_ACTIVE, "Auto drive rejected: transform active");
    return;
  }

  publishDriveCmd(*msg);
  setActionState(DRIVE);
  publishDriveFeedback(true, DRIVE_ACCEPTED, "Auto drive accepted");
}

void ModeManagerNode::manualTransformCallback(const std_msgs::msg::Int32::SharedPtr msg)
{
  if (control_mode_ != MANUAL) {
    RCLCPP_WARN(this->get_logger(), "Manual transform rejected: control mode is AUTO");
    return;
  }
  if (estop_active_) {
    RCLCPP_WARN(this->get_logger(), "Manual transform rejected: estop active");
    return;
  }
  if (error_active_) {
    RCLCPP_WARN(this->get_logger(), "Manual transform rejected: error active");
    return;
  }

  transform_profile_before_transform_ = default_transform_profile_;
  publishTransformProfile(transform_profile_for_transform_);

  publishZeroDrive();
  publishTransformRequest(msg->data);
  setActionState(TRANSFORM);
}

void ModeManagerNode::autoTransformCallback(const std_msgs::msg::Int32::SharedPtr msg)
{
  if (control_mode_ != AUTO) {
    RCLCPP_WARN(this->get_logger(), "Auto transform rejected: control mode is MANUAL");
    return;
  }
  if (estop_active_) {
    RCLCPP_WARN(this->get_logger(), "Auto transform rejected: estop active");
    return;
  }
  if (error_active_) {
    RCLCPP_WARN(this->get_logger(), "Auto transform rejected: error active");
    return;
  }

  transform_profile_before_transform_ = default_transform_profile_;
  publishTransformProfile(transform_profile_for_transform_);

  publishZeroDrive();
  publishTransformRequest(msg->data);
  setActionState(TRANSFORM);
}

void ModeManagerNode::controlModeCallback(const std_msgs::msg::Int32::SharedPtr msg)
{
  if (msg->data != MANUAL && msg->data != AUTO) {
    RCLCPP_WARN(this->get_logger(), "Invalid control mode request: %d", msg->data);
    return;
  }

  clearBuffers();
  publishZeroDrive();
  setControlMode(msg->data);

  if (!isTransformBusy() && !estop_active_ && !error_active_) {
    setActionState(IDLE);
  }
}

void ModeManagerNode::estopCallback(const std_msgs::msg::Bool::SharedPtr msg)
{
  if (!msg->data) {
    return;
  }

  estop_active_ = true;
  clearBuffers();
  publishZeroDrive();

  if (transform_status_ == TF_RUNNING) {
    publishTransformPause(true);
    setActionState(TRANSFORM_PAUSED);
  } else {
    setActionState(ESTOP);
  }

  RCLCPP_WARN(this->get_logger(), "ESTOP activated");
}

void ModeManagerNode::egoCallback(const std_msgs::msg::Bool::SharedPtr msg)
{
  if (!msg->data) {
    return;
  }

  estop_active_ = false;
  error_active_ = false;
  publishZeroDrive();
  clearBuffers();
  setControlMode(MANUAL);

  if (transform_status_ == TF_PAUSED) {
    publishTransformResume(true);
    setActionState(TRANSFORM);
  } else {
    setActionState(IDLE);
  }

  RCLCPP_INFO(this->get_logger(), "EGO processed, switched to MANUAL");
}

void ModeManagerNode::transformStatusCallback(const std_msgs::msg::Int32::SharedPtr msg)
{
  transform_status_ = msg->data;

  if (transform_status_ == TF_RUNNING) {
    setActionState(TRANSFORM);
    return;
  }

  if (transform_status_ == TF_PAUSED) {
    setActionState(TRANSFORM_PAUSED);
    return;
  }

  if (transform_status_ == TF_DONE) {
    publishTransformProfile(transform_profile_before_transform_);
    if (!estop_active_ && !error_active_) {
      setActionState(IDLE);
    }
    return;
  }

  if (transform_status_ == TF_FAILED) {
    publishTransformProfile(transform_profile_before_transform_);
    RCLCPP_WARN(this->get_logger(), "Transform status is FAILED, waiting for error callback");
    return;
  }
}

void ModeManagerNode::transformFeedbackCallback(const robot_msgs::msg::CommandFeedback::SharedPtr msg)
{
  RCLCPP_INFO(
    this->get_logger(),
    "Transform feedback: accepted=%d code=%d message=%s",
    msg->accepted, msg->code, msg->message.c_str());
}

void ModeManagerNode::systemErrorCallback(const robot_msgs::msg::SystemError::SharedPtr msg)
{
  publishZeroDrive();

  if (msg->error_code == 210 || msg->error_code == 211) {
    error_active_ = false;
    publishTransformProfile(transform_profile_before_transform_);

    if (!estop_active_) {
      setActionState(IDLE);
    }

    RCLCPP_WARN(
      this->get_logger(),
      "Non-latching transform error: code=%d desc=%s",
      msg->error_code,
      msg->description.c_str());
    return;
  }

  error_active_ = true;
  setActionState(ERROR);

  RCLCPP_WARN(
    this->get_logger(),
    "Latched system error: code=%d desc=%s",
    msg->error_code,
    msg->description.c_str());
}

void ModeManagerNode::autoTimeoutTimerCallback()
{
  if (control_mode_ != AUTO) {
    return;
  }
  if (action_state_ != DRIVE) {
    return;
  }

  const double dt = (this->now() - last_auto_cmd_time_).seconds();
  if (dt > auto_timeout_sec_) {
    publishZeroDrive();
    setActionState(IDLE);
    publishDriveFeedback(true, STOPPED_AUTO_TIMEOUT, "Auto drive stopped: timeout");
  }
}

int main(int argc, char ** argv)
{
  rclcpp::init(argc, argv);
  rclcpp::spin(std::make_shared<ModeManagerNode>());
  rclcpp::shutdown();
  return 0;
}
