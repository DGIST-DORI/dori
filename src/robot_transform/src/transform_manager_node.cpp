#include "robot_transform/transform_manager_node.hpp"

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

struct RelativeStep
{
  int motor_id;
  double delta_deg;
};

double radToDeg(double rad)
{
  return rad * 180.0 / M_PI;
}

double wrapTo360(double deg)
{
  double y = std::fmod(deg, 360.0);
  if (y < 0.0) y += 360.0;
  return y;
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
  force_initial_pose_(0),
  motor1_joint_name_("left_wheel_joint"),
  motor2_joint_name_("right_wheel_joint"),
  motor3_joint_name_("motor_3_joint"),
  motor4_joint_name_("motor_4_joint"),
  dxl_wrap_turns_(3.0),
  dxl_wrap_range_deg_(3.0 * 360.0)
{
  this->declare_parameter("pose_detect_tolerance_deg", pose_detect_tolerance_deg_);
  this->declare_parameter("default_step_timeout_sec", default_step_timeout_sec_);
  this->declare_parameter("initial_step_delay_sec", initial_step_delay_sec_);
  this->declare_parameter("force_initial_pose", force_initial_pose_);

  this->declare_parameter("motor1_joint_name", motor1_joint_name_);
  this->declare_parameter("motor2_joint_name", motor2_joint_name_);
  this->declare_parameter("motor3_joint_name", motor3_joint_name_);
  this->declare_parameter("motor4_joint_name", motor4_joint_name_);
  this->declare_parameter("dxl_wrap_turns", dxl_wrap_turns_);

  this->get_parameter("pose_detect_tolerance_deg", pose_detect_tolerance_deg_);
  this->get_parameter("default_step_timeout_sec", default_step_timeout_sec_);
  this->get_parameter("initial_step_delay_sec", initial_step_delay_sec_);
  this->get_parameter("force_initial_pose", force_initial_pose_);

  this->get_parameter("motor1_joint_name", motor1_joint_name_);
  this->get_parameter("motor2_joint_name", motor2_joint_name_);
  this->get_parameter("motor3_joint_name", motor3_joint_name_);
  this->get_parameter("motor4_joint_name", motor4_joint_name_);
  this->get_parameter("dxl_wrap_turns", dxl_wrap_turns_);

  dxl_wrap_range_deg_ = dxl_wrap_turns_ * 360.0;

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

  step_cmd_pub_ = this->create_publisher<robot_msgs::msg::TransformStep>("/transform/step_cmd", 20);
  tf_status_pub_ = this->create_publisher<std_msgs::msg::Int32>("/transform/status", 20);
  tf_feedback_pub_ = this->create_publisher<robot_msgs::msg::CommandFeedback>("/transform/command_feedback", 20);
  transform_pose_pub_ = this->create_publisher<std_msgs::msg::Int32>("/system/transform_pose", 20);
  error_pub_ = this->create_publisher<robot_msgs::msg::SystemError>("/system/error", 20);

  publishTransformStatus(transform_status_);
  publishCurrentPose(current_pose_);
}

double TransformManagerNode::wrapToRangeDeg(double x, double range) const
{
  double y = std::fmod(x, range);
  if (y < 0.0) y += range;
  return y;
}

double TransformManagerNode::shortestWrappedErrorDeg(double current, double target, double range) const
{
  double err = std::fmod(target - current, range);
  if (err > range / 2.0) err -= range;
  if (err < -range / 2.0) err += range;
  return err;
}

std::string TransformManagerNode::getJointNameForMotor(int motor_id) const
{
  if (motor_id == 1) return motor1_joint_name_;
  if (motor_id == 2) return motor2_joint_name_;
  if (motor_id == 3) return motor3_joint_name_;
  if (motor_id == 4) return motor4_joint_name_;
  return "";
}

int TransformManagerNode::getMotorTypeForMotor(int motor_id) const
{
  if (motor_id == 1 || motor_id == 2) return MOTOR_TYPE_BLDC;
  if (motor_id == 3 || motor_id == 4) return MOTOR_TYPE_DXL;
  return 0;
}

double TransformManagerNode::getCurrentMotorAngleDeg(int motor_id) const
{
  const std::string joint_name = getJointNameForMotor(motor_id);
  if (joint_name.empty()) return 0.0;

  const auto it = joint_position_deg_map_.find(joint_name);
  if (it != joint_position_deg_map_.end()) {
    return it->second;
  }
  return 0.0;
}

void TransformManagerNode::bldcJointStateCallback(const sensor_msgs::msg::JointState::SharedPtr msg)
{
  for (std::size_t i = 0; i < msg->name.size(); ++i) {
    if (i >= msg->position.size()) continue;
    joint_position_deg_map_[msg->name[i]] = radToDeg(msg->position[i]);
  }
}

void TransformManagerNode::dxlJointStateCallback(const sensor_msgs::msg::JointState::SharedPtr msg)
{
  for (std::size_t i = 0; i < msg->name.size(); ++i) {
    if (i >= msg->position.size()) continue;

    const double angle_deg = radToDeg(msg->position[i]);
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
  step_cmd_pub_->publish(msg);
}

void TransformManagerNode::publishTransformStatus(int status)
{
  std_msgs::msg::Int32 msg;
  msg.data = status;
  tf_status_pub_->publish(msg);
}

void TransformManagerNode::publishTransformFeedback(bool accepted, int code, const std::string & message)
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
  if (force_initial_pose_ == POSE_A) {
    return POSE_A;
  }

  if (force_initial_pose_ == POSE_B) {
    return POSE_B;
  }

  if (!pose_ref_seen_) {
    RCLCPP_WARN(
      this->get_logger(),
      "Pose unknown: motor4 joint state has not been received yet.");
    return UNKNOWN;
  }

  // 중요:
  // pose 판정은 dxl_wrap_turns 기준 1080도가 아니라 360도 기준으로 해야 한다.
  // 예를 들어 motor4가 359.8도 또는 6.28rad 근처면 실제로는 0도와 같은 A pose다.
  const double angle_360 = wrapToRangeDeg(pose_ref_angle_deg_, 360.0);

  const double err_to_a =
    std::abs(shortestWrappedErrorDeg(angle_360, 0.0, 360.0));

  const double err_to_b =
    std::abs(shortestWrappedErrorDeg(angle_360, 180.0, 360.0));

  if (err_to_a <= pose_detect_tolerance_deg_) {
    RCLCPP_INFO(
      this->get_logger(),
      "Detected POSE_A from motor4: raw=%.3f deg angle_360=%.3f deg err_to_A=%.3f deg tolerance=%.3f deg",
      pose_ref_angle_deg_,
      angle_360,
      err_to_a,
      pose_detect_tolerance_deg_);
    return POSE_A;
  }

  if (err_to_b <= pose_detect_tolerance_deg_) {
    RCLCPP_INFO(
      this->get_logger(),
      "Detected POSE_B from motor4: raw=%.3f deg angle_360=%.3f deg err_to_B=%.3f deg tolerance=%.3f deg",
      pose_ref_angle_deg_,
      angle_360,
      err_to_b,
      pose_detect_tolerance_deg_);
    return POSE_B;
  }

  RCLCPP_WARN(
    this->get_logger(),
    "Pose unknown: motor4_raw=%.3f deg angle_360=%.3f deg err_to_A=%.3f deg err_to_B=%.3f deg tolerance=%.3f deg",
    pose_ref_angle_deg_,
    angle_360,
    err_to_a,
    err_to_b,
    pose_detect_tolerance_deg_);

  return UNKNOWN;
}

bool TransformManagerNode::isAlreadyTargetPose(int request) const
{
  if (request == TF_TO_A && current_pose_ == POSE_A) return true;
  if (request == TF_TO_B && current_pose_ == POSE_B) return true;
  return false;
}

void TransformManagerNode::clearSequence()
{
  sequence_.clear();
  current_step_index_ = 0;
}

void TransformManagerNode::buildReturnBldcToZeroSequence()
{
  sequence_.push_back({1, MOTOR_TYPE_BLDC, 0.0, default_step_timeout_sec_, 0});
  sequence_.push_back({2, MOTOR_TYPE_BLDC, 0.0, default_step_timeout_sec_, 0});
}

void TransformManagerNode::buildSequenceToB()
{
  // BLDC 1,2는 직전에 0도로 복귀시키므로 indexing sequence는 0도부터 누적
  // DXL 3,4는 현재 각도부터 상대각 누적 후 0~360으로 wrap
  double target1 = 0.0;
  double target2 = 0.0;
  double target3 = getCurrentMotorAngleDeg(3);
  double target4 = getCurrentMotorAngleDeg(4);

  const std::vector<RelativeStep> rel_b = {
    {3, -90.0}, {4, -90.0}, {1,  180.0}, {3, -90.0}, {2, -180.0},
    {4, -90.0}, {3, -90.0}, {4,  -90.0}, {1,  180.0}, {3, -90.0},
    {2, -180.0}, {4, -90.0}, {3, -90.0}, {4, -180.0}
  };

  for (const auto & step : rel_b) {
    double target_deg = 0.0;

    if (step.motor_id == 1) {
      target1 += step.delta_deg;
      target_deg = target1;
    } else if (step.motor_id == 2) {
      target2 += step.delta_deg;
      target_deg = target2;
    } else if (step.motor_id == 3) {
      target3 += step.delta_deg;
      target_deg = wrapTo360(target3);
    } else if (step.motor_id == 4) {
      target4 += step.delta_deg;
      target_deg = wrapTo360(target4);
    } else {
      continue;
    }

    sequence_.push_back({
      step.motor_id,
      getMotorTypeForMotor(step.motor_id),
      target_deg,
      default_step_timeout_sec_,
      0
    });
  }
}

void TransformManagerNode::buildSequenceToA()
{
  // A로 복귀할 때는 B sequence의 역순 + 부호 반전
  // BLDC 1,2는 직전에 0도로 복귀시키므로 indexing sequence는 0도부터 누적
  // DXL 3,4는 현재 각도부터 상대각 누적 후 0~360으로 wrap
  double target1 = 0.0;
  double target2 = 0.0;
  double target3 = getCurrentMotorAngleDeg(3);
  double target4 = getCurrentMotorAngleDeg(4);

  const std::vector<RelativeStep> rel_b = {
    {3, -90.0}, {4, -90.0}, {1,  180.0}, {3, -90.0}, {2, -180.0},
    {4, -90.0}, {3, -90.0}, {4,  -90.0}, {1,  180.0}, {3, -90.0},
    {2, -180.0}, {4, -90.0}, {3, -90.0}, {4, -180.0}
  };

  for (auto it = rel_b.rbegin(); it != rel_b.rend(); ++it) {
    const int motor_id = it->motor_id;
    const double delta_deg = -(it->delta_deg);

    double target_deg = 0.0;

    if (motor_id == 1) {
      target1 += delta_deg;
      target_deg = target1;
    } else if (motor_id == 2) {
      target2 += delta_deg;
      target_deg = target2;
    } else if (motor_id == 3) {
      target3 += delta_deg;
      target_deg = wrapTo360(target3);
    } else if (motor_id == 4) {
      target4 += delta_deg;
      target_deg = wrapTo360(target4);
    } else {
      continue;
    }

    sequence_.push_back({
      motor_id,
      getMotorTypeForMotor(motor_id),
      target_deg,
      default_step_timeout_sec_,
      0
    });
  }
}

void TransformManagerNode::startNextStep()
{
  if (paused_) return;

  if (current_step_index_ >= sequence_.size()) {
    if (target_pose_ == POSE_A) completeTransform(POSE_A);
    else if (target_pose_ == POSE_B) completeTransform(POSE_B);
    else failTransform("Unknown target pose at completion", TRANSFORM_FAILED_STEP_ERROR);
    return;
  }

  publishStep(sequence_[current_step_index_]);
}

void TransformManagerNode::delayedStartCallback()
{
  if (delayed_start_timer_) {
    delayed_start_timer_->cancel();
    delayed_start_timer_.reset();
  }

  if (transform_status_ != TF_RUNNING || paused_) return;
  startNextStep();
}

void TransformManagerNode::completeTransform(int pose)
{
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
    publishTransformFeedback(false, TRANSFORM_ALREADY_IN_TARGET_POSE, "Transform rejected: already in target pose");
    return;
  }

  clearSequence();
  buildReturnBldcToZeroSequence();

  if (msg->data == TF_TO_A) {
    target_pose_ = POSE_A;
    buildSequenceToA();
  } else if (msg->data == TF_TO_B) {
    target_pose_ = POSE_B;
    buildSequenceToB();
  } else {
    publishTransformFeedback(false, TRANSFORM_REJECTED_INVALID_POSE, "Transform rejected: invalid request");
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
  if (!msg->data) return;

  paused_ = true;
  transform_status_ = TF_PAUSED;
  publishTransformStatus(transform_status_);
  publishTransformFeedback(true, TRANSFORM_PAUSED_FB, "Transform paused");
}

void TransformManagerNode::resumeCallback(const std_msgs::msg::Bool::SharedPtr msg)
{
  if (!msg->data) return;

  paused_ = false;
  transform_status_ = TF_RUNNING;
  publishTransformStatus(transform_status_);
  publishTransformFeedback(true, TRANSFORM_RESUMED_FB, "Transform resumed");

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

void TransformManagerNode::stepResultCallback(const robot_msgs::msg::TransformStepResult::SharedPtr msg)
{
  if (paused_) return;
  if (transform_status_ != TF_RUNNING) return;

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
