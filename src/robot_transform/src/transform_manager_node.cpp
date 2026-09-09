#include "robot_transform/transform_manager_node.hpp"
#include "robot_transform/target_plan.hpp"
#include <limits>

#include <cmath>
#include <chrono>
#include <vector>

namespace
{
constexpr int UNKNOWN = 0;
constexpr int POSE_A = 1;
constexpr int POSE_B = 2;

constexpr int TF_TO_A = 1;
constexpr int TF_TO_B = 2;

constexpr int TF_IDLE = 0;
constexpr int TF_RUNNING = 1;
constexpr int TF_PAUSED = 2;
constexpr int TF_DONE = 3;
constexpr int TF_FAILED = 4;

constexpr int MOTOR_TYPE_BLDC = 1;
constexpr int MOTOR_TYPE_DXL = 2;

constexpr int TRANSFORM_ACCEPTED = 200;
constexpr int TRANSFORM_STARTED = 201;
constexpr int TRANSFORM_ALREADY_RUNNING = 202;
constexpr int TRANSFORM_ALREADY_IN_TARGET_POSE = 203;
constexpr int TRANSFORM_REJECTED_INVALID_POSE = 206;
constexpr int TRANSFORM_PAUSED_FB = 207;
constexpr int TRANSFORM_RESUMED_FB = 208;
constexpr int TRANSFORM_COMPLETED = 209;
constexpr int TRANSFORM_FAILED_TIMEOUT = 210;
constexpr int TRANSFORM_FAILED_STEP_ERROR = 211;

double radToDeg(double rad)
{
  return rad * 180.0 / M_PI;
}

}  // namespace

TransformManagerNode::TransformManagerNode()
: Node("transform_manager_node"),
  transform_status_(TF_IDLE),
  current_pose_(UNKNOWN),
  target_pose_(UNKNOWN),
  paused_(false),
  current_step_index_(0),
  pose_ref_angle_deg_(0.0),
  pose_ref_seen_(false),
  pose_detect_tolerance_deg_(5.0),
  default_step_timeout_sec_(5.0),
  initial_step_delay_sec_(0.5),
  motor1_joint_name_("left_wheel_joint"),
  motor2_joint_name_("right_wheel_joint"),
  motor3_joint_name_("motor_3_joint"),
  motor4_joint_name_("motor_4_joint")
{
  this->declare_parameter("pose_detect_tolerance_deg", pose_detect_tolerance_deg_);
  this->declare_parameter("default_step_timeout_sec", default_step_timeout_sec_);
  this->declare_parameter("initial_step_delay_sec", initial_step_delay_sec_);

  this->declare_parameter<double>("feedback_timeout_sec", 0.5);
  this->declare_parameter<double>("left_bldc_motor_per_mechanical", 2.0);
  this->declare_parameter<double>("right_bldc_motor_per_mechanical", 2.0);
  this->declare_parameter<double>("max_dxl_preparation_deg", 45.0);

  // Mechanical pose references for motor4.
  // These allow the real A/B posture to differ from encoder 0/180 deg.
  this->declare_parameter<double>("pose_a_reference_deg", 9.32);
  this->declare_parameter<double>("pose_b_reference_deg", 189.32);

  // Fixed A references in motor/feedback degrees. Keep the legacy motor3
  // parameter name so existing calibration files continue to work.
  this->declare_parameter<double>("motor3_grid_offset_deg", 0.0);
  this->declare_parameter<double>("motor4_a_reference_deg",
    this->get_parameter("pose_a_reference_deg").as_double());

  this->declare_parameter("motor1_joint_name", motor1_joint_name_);
  this->declare_parameter("motor2_joint_name", motor2_joint_name_);
  this->declare_parameter("motor3_joint_name", motor3_joint_name_);
  this->declare_parameter("motor4_joint_name", motor4_joint_name_);

  // Fixed BLDC A references; B references come from the planned endpoint.
  this->declare_parameter<double>("left_bldc_alignment_offset_deg", 0.0);
  this->declare_parameter<double>("right_bldc_alignment_offset_deg", 0.0);

  this->get_parameter("pose_detect_tolerance_deg", pose_detect_tolerance_deg_);
  this->get_parameter("default_step_timeout_sec", default_step_timeout_sec_);
  this->get_parameter("initial_step_delay_sec", initial_step_delay_sec_);

  this->get_parameter("motor1_joint_name", motor1_joint_name_);
  this->get_parameter("motor2_joint_name", motor2_joint_name_);
  this->get_parameter("motor3_joint_name", motor3_joint_name_);
  this->get_parameter("motor4_joint_name", motor4_joint_name_);

  for (const auto & name : {"feedback_timeout_sec", "pose_detect_tolerance_deg",
    "default_step_timeout_sec", "initial_step_delay_sec", "max_dxl_preparation_deg"})
  {
    const double value = get_parameter(name).as_double();
    if (!std::isfinite(value) || value <= 0) {
      throw std::invalid_argument(std::string(name) + " must be positive and finite");
    }
  }
  for (const auto & name : {"pose_a_reference_deg", "pose_b_reference_deg"}) {
    if (!std::isfinite(get_parameter(name).as_double())) {
      throw std::invalid_argument(std::string(name) + " must be finite");
    }
  }

  tf_request_sub_ = this->create_subscription<std_msgs::msg::Int32>(
    "/transform/request", 20,
    std::bind(&TransformManagerNode::transformRequestCallback, this, std::placeholders::_1));

  pause_sub_ = this->create_subscription<std_msgs::msg::Bool>(
    "/transform/pause", 20,
    std::bind(&TransformManagerNode::pauseCallback, this, std::placeholders::_1));

  resume_sub_ = this->create_subscription<std_msgs::msg::Bool>(
    "/transform/resume", 20,
    std::bind(&TransformManagerNode::resumeCallback, this, std::placeholders::_1));

  step_result_sub_ = this->create_subscription<robot_msgs::msg::TransformStepResult>(
    "/transform/step_result", 20,
    std::bind(&TransformManagerNode::stepResultCallback, this, std::placeholders::_1));

  bldc_joint_state_sub_ = this->create_subscription<sensor_msgs::msg::JointState>(
    "/joint_states", 20,
    std::bind(&TransformManagerNode::bldcJointStateCallback, this, std::placeholders::_1));

  dxl_joint_state_sub_ = this->create_subscription<sensor_msgs::msg::JointState>(
    "/dxl_joint_states", 20,
    std::bind(&TransformManagerNode::dxlJointStateCallback, this, std::placeholders::_1));

  step_cmd_pub_ =
    this->create_publisher<robot_msgs::msg::TransformStep>("/transform/step_cmd", 20);

  tf_status_pub_ =
    this->create_publisher<std_msgs::msg::Int32>("/transform/status", 20);

  tf_feedback_pub_ =
    this->create_publisher<robot_msgs::msg::CommandFeedback>("/transform/command_feedback", 20);

  transform_pose_pub_ =
    this->create_publisher<std_msgs::msg::Int32>("/system/transform_pose", 20);

  error_pub_ =
    this->create_publisher<robot_msgs::msg::SystemError>("/system/error", 20);

  publishTransformStatus(transform_status_);
  publishCurrentPose(current_pose_);

  RCLCPP_INFO(get_logger(),
    "Fixed-reference transform planner started; A/B reference joint: %s",
    motor4_joint_name_.c_str());
}

double TransformManagerNode::wrapToRangeDeg(double x, double range) const
{
  double y = std::fmod(x, range);
  if (y < 0.0) {
    y += range;
  }
  return y;
}

double TransformManagerNode::shortestWrappedErrorDeg(
  double current,
  double target,
  double range) const
{
  double err = std::fmod(target - current, range);

  if (err > range / 2.0) {
    err -= range;
  }

  if (err < -range / 2.0) {
    err += range;
  }

  return err;
}

std::string TransformManagerNode::getJointNameForMotor(int motor_id) const
{
  if (motor_id == 1) {
    return motor1_joint_name_;
  }

  if (motor_id == 2) {
    return motor2_joint_name_;
  }

  if (motor_id == 3) {
    return motor3_joint_name_;
  }

  if (motor_id == 4) {
    return motor4_joint_name_;
  }

  return "";
}

int TransformManagerNode::getMotorTypeForMotor(int motor_id) const
{
  if (motor_id == 1 || motor_id == 2) {
    return MOTOR_TYPE_BLDC;
  }

  if (motor_id == 3 || motor_id == 4) {
    return MOTOR_TYPE_DXL;
  }

  return 0;
}

double TransformManagerNode::getCurrentMotorAngleDeg(int motor_id) const
{
  const std::string joint_name = getJointNameForMotor(motor_id);

  if (joint_name.empty()) {
    return std::numeric_limits<double>::quiet_NaN();
  }

  const auto it = joint_position_deg_map_.find(joint_name);
  if (it != joint_position_deg_map_.end()) {
    return it->second;
  }

  return std::numeric_limits<double>::quiet_NaN();
}

void TransformManagerNode::bldcJointStateCallback(
  const sensor_msgs::msg::JointState::SharedPtr msg)
{
  for (std::size_t i = 0; i < msg->name.size(); ++i) {
    if (i >= msg->position.size()) {
      continue;
    }

    if (!std::isfinite(msg->position[i])) { continue; }
    joint_position_deg_map_[msg->name[i]] = radToDeg(msg->position[i]);
    joint_feedback_time_[msg->name[i]] = rclcpp::Time(msg->header.stamp);
  }
}

void TransformManagerNode::dxlJointStateCallback(
  const sensor_msgs::msg::JointState::SharedPtr msg)
{
  for (std::size_t i = 0; i < msg->name.size(); ++i) {
    if (i >= msg->position.size()) {
      continue;
    }

    if (!std::isfinite(msg->position[i])) { continue; }
    const double angle_deg = radToDeg(msg->position[i]);
    joint_feedback_time_[msg->name[i]] = rclcpp::Time(msg->header.stamp);
    joint_position_deg_map_[msg->name[i]] = angle_deg;

    if (msg->name[i] == motor4_joint_name_) {
      pose_ref_angle_deg_ = angle_deg;
      pose_ref_seen_ = true;
    }
  }
}

void TransformManagerNode::publishStep(const StepCommandData & step)
{
  robot_msgs::msg::TransformStep msg;
  msg.motor_id = step.motor_id;
  msg.motor_type = step.motor_type;
  msg.target_angle_deg = step.target_angle_deg;
  msg.timeout_sec = step.timeout_sec;
  msg.retry_count = step.retry_count;

  RCLCPP_INFO(
    this->get_logger(),
    "Publish transform step: index=%zu motor_id=%d motor_type=%d target=%.3f deg timeout=%.3f retry=%d",
    current_step_index_,
    msg.motor_id,
    msg.motor_type,
    msg.target_angle_deg,
    msg.timeout_sec,
    msg.retry_count);

  step_cmd_pub_->publish(msg);
}

void TransformManagerNode::publishTransformStatus(int status)
{
  std_msgs::msg::Int32 msg;
  msg.data = status;
  tf_status_pub_->publish(msg);
}

void TransformManagerNode::publishTransformFeedback(
  bool accepted,
  int code,
  const std::string & message)
{
  robot_msgs::msg::CommandFeedback fb;
  fb.source_node = "transform_manager_node";
  fb.command_type = "transform";
  fb.accepted = accepted;
  fb.code = code;
  fb.message = message;
  tf_feedback_pub_->publish(fb);
}

void TransformManagerNode::publishSystemError(int code, const std::string & description)
{
  robot_msgs::msg::SystemError msg;
  msg.source_node = "transform_manager_node";
  msg.error_code = code;
  msg.description = description;
  error_pub_->publish(msg);
}

void TransformManagerNode::publishCurrentPose(int pose)
{
  std_msgs::msg::Int32 msg;
  msg.data = pose;
  transform_pose_pub_->publish(msg);
}

int TransformManagerNode::detectPoseFromReferenceMotor() const
{
  if (!pose_ref_seen_ || !feedbackFresh(4)) {
    RCLCPP_WARN(
      this->get_logger(),
      "Pose unknown: motor4 joint state has not been received yet.");
    return UNKNOWN;
  }

  double pose_a_reference_deg = 9.32;
  double pose_b_reference_deg = 189.32;

  this->get_parameter(
    "pose_a_reference_deg",
    pose_a_reference_deg);

  this->get_parameter(
    "pose_b_reference_deg",
    pose_b_reference_deg);

  const double angle_360 =
    wrapToRangeDeg(pose_ref_angle_deg_, 360.0);

  const double pose_a_360 =
    wrapToRangeDeg(pose_a_reference_deg, 360.0);

  const double pose_b_360 =
    wrapToRangeDeg(pose_b_reference_deg, 360.0);

  const double err_to_a =
    std::abs(
      shortestWrappedErrorDeg(
        angle_360,
        pose_a_360,
        360.0));

  const double err_to_b =
    std::abs(
      shortestWrappedErrorDeg(
        angle_360,
        pose_b_360,
        360.0));

  if (err_to_a <= pose_detect_tolerance_deg_) {
    RCLCPP_INFO(
      this->get_logger(),
      "Detected POSE_A from motor4: raw=%.3f deg angle_360=%.3f deg "
      "A_ref=%.3f deg err_to_A=%.3f deg tolerance=%.3f deg",
      pose_ref_angle_deg_,
      angle_360,
      pose_a_360,
      err_to_a,
      pose_detect_tolerance_deg_);
    return POSE_A;
  }

  if (err_to_b <= pose_detect_tolerance_deg_) {
    RCLCPP_INFO(
      this->get_logger(),
      "Detected POSE_B from motor4: raw=%.3f deg angle_360=%.3f deg "
      "B_ref=%.3f deg err_to_B=%.3f deg tolerance=%.3f deg",
      pose_ref_angle_deg_,
      angle_360,
      pose_b_360,
      err_to_b,
      pose_detect_tolerance_deg_);
    return POSE_B;
  }

  RCLCPP_WARN(
    this->get_logger(),
    "Pose unknown: motor4_raw=%.3f deg angle_360=%.3f deg "
    "A_ref=%.3f deg err_to_A=%.3f deg "
    "B_ref=%.3f deg err_to_B=%.3f deg tolerance=%.3f deg",
    pose_ref_angle_deg_,
    angle_360,
    pose_a_360,
    err_to_a,
    pose_b_360,
    err_to_b,
    pose_detect_tolerance_deg_);

  return UNKNOWN;
}

bool TransformManagerNode::isAlreadyTargetPose(int request) const
{
  if (request == TF_TO_A && current_pose_ == POSE_A) {
    return true;
  }

  if (request == TF_TO_B && current_pose_ == POSE_B) {
    return true;
  }

  return false;
}

void TransformManagerNode::clearSequence()
{
  if (delayed_start_timer_) {
    delayed_start_timer_->cancel();
    delayed_start_timer_.reset();
  }
  step_in_flight_ = false;
  sequence_.clear();
  current_step_index_ = 0;
}

bool TransformManagerNode::feedbackFresh(int motor_id) const
{
  const auto it = joint_feedback_time_.find(getJointNameForMotor(motor_id));
  if (it == joint_feedback_time_.end()) { return false; }
  const double age = (this->now() - it->second).seconds();
  return age >= 0.0 && age <= this->get_parameter("feedback_timeout_sec").as_double() &&
    std::isfinite(getCurrentMotorAngleDeg(motor_id));
}

void TransformManagerNode::buildFixedReferenceSequence()
{
  const std::array<double, 4> reference = {
    this->get_parameter("left_bldc_alignment_offset_deg").as_double(),
    this->get_parameter("right_bldc_alignment_offset_deg").as_double(),
    this->get_parameter("motor3_grid_offset_deg").as_double(),
    this->get_parameter("motor4_a_reference_deg").as_double()};
  const std::array<double, 4> feedback = {
    getCurrentMotorAngleDeg(1), getCurrentMotorAngleDeg(2),
    getCurrentMotorAngleDeg(3), getCurrentMotorAngleDeg(4)};
  const std::array<double, 4> ratio = {
    this->get_parameter("left_bldc_motor_per_mechanical").as_double(),
    this->get_parameter("right_bldc_motor_per_mechanical").as_double(), 1.0, 1.0};
  const auto plan = robot_transform::makeTargetPlan(
    reference, feedback, ratio, current_pose_ == POSE_B);

  // Reject inconsistent calibration before issuing any preparation command.
  const double a_pose = this->get_parameter("pose_a_reference_deg").as_double();
  const double b_pose = this->get_parameter("pose_b_reference_deg").as_double();
  if (std::abs(shortestWrappedErrorDeg(reference[3], a_pose, 360.0)) >
      pose_detect_tolerance_deg_ ||
    std::abs(shortestWrappedErrorDeg(reference[3] - 540.0, b_pose, 360.0)) >
      pose_detect_tolerance_deg_)
  {
    throw std::invalid_argument("Motor4 A/B calibration disagrees with sequence endpoints");
  }
  for (int i = 2; i < 4; ++i) {
    if (std::abs(plan.preparation[i] - feedback[i]) >
      this->get_parameter("max_dxl_preparation_deg").as_double())
    {
      throw std::invalid_argument("DXL is too far from the preparation pose");
    }
  }
  for (int i = 0; i < 4; ++i) {
    if (i >= 2 && std::abs(plan.preparation[i] * 4096.0 / 360.0) > 1048575) {
      throw std::invalid_argument("DXL preparation exceeds extended position range");
    }
    sequence_.push_back({i + 1, getMotorTypeForMotor(i + 1),
      plan.preparation[i], default_step_timeout_sec_, 0});
  }
  for (const auto & step : plan.motion) {
    // Continuous signed targets preserve the requested direction through zero.
    if (step.motor_id >= 3 && std::abs(step.angle_deg * 4096.0 / 360.0) > 1048575) {
      throw std::invalid_argument("DXL target exceeds extended position range");
    }
    sequence_.push_back({step.motor_id, getMotorTypeForMotor(step.motor_id),
      step.angle_deg, default_step_timeout_sec_, 0});
  }
}

void TransformManagerNode::startNextStep()
{
  if (paused_) {
    return;
  }

  if (current_step_index_ >= sequence_.size()) {
    if (target_pose_ == POSE_A) {
      completeTransform(POSE_A);
    } else if (target_pose_ == POSE_B) {
      completeTransform(POSE_B);
    } else {
      failTransform("Unknown target pose at completion", TRANSFORM_FAILED_STEP_ERROR);
    }
    return;
  }

  step_in_flight_ = true;
  publishStep(sequence_[current_step_index_]);
}

void TransformManagerNode::delayedStartCallback()
{
  if (delayed_start_timer_) {
    delayed_start_timer_->cancel();
    delayed_start_timer_.reset();
  }

  if (transform_status_ != TF_RUNNING || paused_) {
    return;
  }

  startNextStep();
}

void TransformManagerNode::completeTransform(int pose)
{
  if (!feedbackFresh(4) || detectPoseFromReferenceMotor() != pose) {
    failTransform("Final motor4 feedback does not confirm the requested pose",
      TRANSFORM_FAILED_STEP_ERROR);
    return;
  }
  current_pose_ = pose;
  transform_status_ = TF_DONE;
  publishTransformStatus(transform_status_);
  publishCurrentPose(current_pose_);
  publishTransformFeedback(true, TRANSFORM_COMPLETED, "Transform completed");
  clearSequence();
}

void TransformManagerNode::failTransform(const std::string & reason, int code)
{
  transform_status_ = TF_FAILED;
  publishTransformStatus(transform_status_);
  publishTransformFeedback(false, code, reason);
  publishSystemError(code, reason);
  clearSequence();
}

void TransformManagerNode::transformRequestCallback(const std_msgs::msg::Int32::SharedPtr msg)
{
  if (transform_status_ == TF_RUNNING || transform_status_ == TF_PAUSED) {
    publishTransformFeedback(false, TRANSFORM_ALREADY_RUNNING, "Transform rejected: already transforming");
    return;
  }

  current_pose_ = detectPoseFromReferenceMotor();
  publishCurrentPose(current_pose_);

  if (current_pose_ == UNKNOWN) {
    publishTransformFeedback(false, TRANSFORM_REJECTED_INVALID_POSE, "Transform rejected: pose unknown");
    publishSystemError(
      TRANSFORM_REJECTED_INVALID_POSE,
      "Pose detection failed from reference motor (motor4 joint)");
    return;
  }

  if (isAlreadyTargetPose(msg->data)) {
    publishTransformFeedback(
      false,
      TRANSFORM_ALREADY_IN_TARGET_POSE,
      "Transform rejected: already in target pose");
    return;
  }

  if (msg->data != TF_TO_A && msg->data != TF_TO_B) {
    publishTransformFeedback(false, TRANSFORM_REJECTED_INVALID_POSE, "Invalid transform request");
    return;
  }
  for (int motor = 1; motor <= 4; ++motor) {
    if (!feedbackFresh(motor)) {
      publishTransformFeedback(false, TRANSFORM_REJECTED_INVALID_POSE,
        "Missing or stale feedback for motor " + std::to_string(motor));
      return;
    }
  }
  clearSequence();

  if (msg->data == TF_TO_A) {
    target_pose_ = POSE_A;

  } else if (msg->data == TF_TO_B) {
    target_pose_ = POSE_B;

  } else {
    publishTransformFeedback(false, TRANSFORM_REJECTED_INVALID_POSE, "Transform rejected: invalid request");
    return;
  }

  try {
    buildFixedReferenceSequence();
  } catch (const std::exception & e) {
    clearSequence();
    publishTransformFeedback(false, TRANSFORM_REJECTED_INVALID_POSE, e.what());
    return;
  }
  transform_status_ = TF_RUNNING;
  paused_ = false;
  publishTransformStatus(transform_status_);
  publishTransformFeedback(true, TRANSFORM_ACCEPTED, "Transform request accepted");
  publishTransformFeedback(true, TRANSFORM_STARTED, "Transform started");

  const auto delay_ms = std::chrono::duration_cast<std::chrono::milliseconds>(
    std::chrono::duration<double>(initial_step_delay_sec_));

  delayed_start_timer_ = this->create_wall_timer(
    delay_ms,
    std::bind(&TransformManagerNode::delayedStartCallback, this));
}

void TransformManagerNode::pauseCallback(const std_msgs::msg::Bool::SharedPtr msg)
{
  if (!msg->data) {
    return;
  }

  if (transform_status_ != TF_RUNNING) { return; }
  paused_ = true;
  transform_status_ = TF_PAUSED;
  publishTransformStatus(transform_status_);
  publishTransformFeedback(true, TRANSFORM_PAUSED_FB, "Transform paused");
}

void TransformManagerNode::resumeCallback(const std_msgs::msg::Bool::SharedPtr msg)
{
  if (!msg->data) {
    return;
  }

  if (transform_status_ != TF_PAUSED) { return; }
  paused_ = false;
  transform_status_ = TF_RUNNING;
  publishTransformStatus(transform_status_);
  publishTransformFeedback(true, TRANSFORM_RESUMED_FB, "Transform resumed");

  if (step_in_flight_ || delayed_start_timer_) { return; }

  if (!delayed_start_timer_ && current_step_index_ == 0) {
    const auto delay_ms = std::chrono::duration_cast<std::chrono::milliseconds>(
      std::chrono::duration<double>(initial_step_delay_sec_));

    delayed_start_timer_ = this->create_wall_timer(
      delay_ms,
      std::bind(&TransformManagerNode::delayedStartCallback, this));
    return;
  }

  startNextStep();
}

void TransformManagerNode::stepResultCallback(
  const robot_msgs::msg::TransformStepResult::SharedPtr msg)
{
  if (transform_status_ != TF_RUNNING && transform_status_ != TF_PAUSED) {
    return;
  }

  if (!step_in_flight_ || current_step_index_ >= sequence_.size() ||
    msg->motor_id != sequence_[current_step_index_].motor_id) { return; }

  step_in_flight_ = false;
  if (msg->success) {
    current_step_index_++;
    startNextStep();
    return;
  }

  if (msg->timeout) {
    failTransform("Transform failed: step timeout", TRANSFORM_FAILED_TIMEOUT);
    return;
  }

  failTransform("Transform failed: step error", TRANSFORM_FAILED_STEP_ERROR);
}

int main(int argc, char ** argv)
{
  rclcpp::init(argc, argv);
  rclcpp::spin(std::make_shared<TransformManagerNode>());
  rclcpp::shutdown();
  return 0;
}