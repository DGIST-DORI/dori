#include "robot_transform/transform_controller_node.hpp"

#include <chrono>
#include <cmath>

using namespace std::chrono_literals;

namespace
{
constexpr int MOTOR_TYPE_BLDC = 1;
constexpr int MOTOR_TYPE_DXL = 2;

double radToDeg(double rad)
{
  return rad * 180.0 / M_PI;
}

double wrapToRangeDeg(double x, double range)
{
  double y = std::fmod(x, range);
  if (y < 0.0) y += range;
  return y;
}

double shortestWrappedErrorDeg(double current, double target, double range)
{
  double err = std::fmod(target - current, range);
  if (err > range / 2.0) err -= range;
  if (err < -range / 2.0) err += range;
  return err;
}

double rawDegToPhase720(double raw_deg, double zero_offset_deg = 0.0)
{
  return wrapToRangeDeg(raw_deg - zero_offset_deg, 720.0);
}

double computeRawTargetDeg(
  double current_raw_deg,
  double target_phase_deg,
  double raw_range_deg,
  double zero_offset_deg = 0.0)
{
  const double current_phase = rawDegToPhase720(current_raw_deg, zero_offset_deg);
  const double error_deg = shortestWrappedErrorDeg(current_phase, target_phase_deg, 720.0);

  const double target_raw_nominal = current_raw_deg + error_deg;

  const double raw_min = -raw_range_deg * 0.5;
  const double raw_max =  raw_range_deg * 0.5;

  double best = target_raw_nominal;
  double best_dist = 1e18;

  for (int k = -4; k <= 4; ++k) {
    const double cand = target_raw_nominal + 720.0 * static_cast<double>(k);

    if (cand < raw_min || cand > raw_max) {
      continue;
    }

    const double dist = std::abs(cand - current_raw_deg);
    if (dist < best_dist) {
      best_dist = dist;
      best = cand;
    }
  }

  if (best_dist > 1e17) {
    if (target_raw_nominal < raw_min) return raw_min;
    if (target_raw_nominal > raw_max) return raw_max;
    return target_raw_nominal;
  }

  return best;
}
}  // namespace

TransformControllerNode::TransformControllerNode()
: Node("transform_controller_node"),
  step_active_(false),
  active_motor_id_(0),
  active_motor_type_(0),
  target_angle_deg_(0.0),
  timeout_sec_(2.0),
  retry_count_(0),
  settle_started_(false),
  position_tolerance_deg_(1.0),
  velocity_tolerance_rad_s_(0.02),
  settle_time_sec_(0.5),
  mit_position_kp_(45.0),
  mit_position_kd_(2.2),
  mit_position_tau_ff_(0.0),
  transform_precise_pos_kp_(45.0),
  transform_precise_pos_kd_(2.2),
  transform_precise_tau_ff_(0.0),
  transform_fast_pos_kp_(30.0),
  transform_fast_pos_kd_(1.2),
  transform_fast_tau_ff_(0.0),
  transform_soft_pos_kp_(20.0),
  transform_soft_pos_kd_(0.8),
  transform_soft_tau_ff_(0.0),
  current_transform_profile_("precise"),
  test_auto_success_(false),
  test_auto_success_delay_sec_(0.6),
  motor1_joint_name_("left_wheel_joint"),
  motor2_joint_name_("right_wheel_joint"),
  motor3_joint_name_("motor_3_joint"),
  motor4_joint_name_("motor_4_joint"),
  bldc_wrap_turns_(12.0),
  dxl_wrap_turns_(3.0),
  bldc_wrap_range_deg_(12.0 * 360.0),
  dxl_wrap_range_deg_(3.0 * 360.0)
{
  this->declare_parameter("position_tolerance_deg", position_tolerance_deg_);
  this->declare_parameter("velocity_tolerance_rad_s", velocity_tolerance_rad_s_);
  this->declare_parameter("settle_time_sec", settle_time_sec_);

  this->declare_parameter("transform_precise_pos_kp", transform_precise_pos_kp_);
  this->declare_parameter("transform_precise_pos_kd", transform_precise_pos_kd_);
  this->declare_parameter("transform_precise_tau_ff", transform_precise_tau_ff_);

  this->declare_parameter("transform_fast_pos_kp", transform_fast_pos_kp_);
  this->declare_parameter("transform_fast_pos_kd", transform_fast_pos_kd_);
  this->declare_parameter("transform_fast_tau_ff", transform_fast_tau_ff_);

  this->declare_parameter("transform_soft_pos_kp", transform_soft_pos_kp_);
  this->declare_parameter("transform_soft_pos_kd", transform_soft_pos_kd_);
  this->declare_parameter("transform_soft_tau_ff", transform_soft_tau_ff_);

  this->declare_parameter("default_transform_profile", current_transform_profile_);

  this->declare_parameter("test_auto_success", test_auto_success_);
  this->declare_parameter("test_auto_success_delay_sec", test_auto_success_delay_sec_);

  this->declare_parameter("motor1_joint_name", motor1_joint_name_);
  this->declare_parameter("motor2_joint_name", motor2_joint_name_);
  this->declare_parameter("motor3_joint_name", motor3_joint_name_);
  this->declare_parameter("motor4_joint_name", motor4_joint_name_);

  this->declare_parameter("bldc_wrap_turns", bldc_wrap_turns_);
  this->declare_parameter("dxl_wrap_turns", dxl_wrap_turns_);

  this->get_parameter("position_tolerance_deg", position_tolerance_deg_);
  this->get_parameter("velocity_tolerance_rad_s", velocity_tolerance_rad_s_);
  this->get_parameter("settle_time_sec", settle_time_sec_);

  this->get_parameter("transform_precise_pos_kp", transform_precise_pos_kp_);
  this->get_parameter("transform_precise_pos_kd", transform_precise_pos_kd_);
  this->get_parameter("transform_precise_tau_ff", transform_precise_tau_ff_);

  this->get_parameter("transform_fast_pos_kp", transform_fast_pos_kp_);
  this->get_parameter("transform_fast_pos_kd", transform_fast_pos_kd_);
  this->get_parameter("transform_fast_tau_ff", transform_fast_tau_ff_);

  this->get_parameter("transform_soft_pos_kp", transform_soft_pos_kp_);
  this->get_parameter("transform_soft_pos_kd", transform_soft_pos_kd_);
  this->get_parameter("transform_soft_tau_ff", transform_soft_tau_ff_);

  this->get_parameter("default_transform_profile", current_transform_profile_);

  this->get_parameter("test_auto_success", test_auto_success_);
  this->get_parameter("test_auto_success_delay_sec", test_auto_success_delay_sec_);

  this->get_parameter("motor1_joint_name", motor1_joint_name_);
  this->get_parameter("motor2_joint_name", motor2_joint_name_);
  this->get_parameter("motor3_joint_name", motor3_joint_name_);
  this->get_parameter("motor4_joint_name", motor4_joint_name_);

  this->get_parameter("bldc_wrap_turns", bldc_wrap_turns_);
  this->get_parameter("dxl_wrap_turns", dxl_wrap_turns_);

  // 하드코딩 제거: yaml의 bldc_wrap_turns를 그대로 사용
  bldc_wrap_range_deg_ = bldc_wrap_turns_ * 360.0;
  dxl_wrap_range_deg_ = dxl_wrap_turns_ * 360.0;

  step_cmd_sub_ = this->create_subscription<robot_msgs::msg::TransformStep>(
    "/transform/step_cmd", 20,
    std::bind(&TransformControllerNode::stepCmdCallback, this, std::placeholders::_1));

  bldc_joint_state_sub_ = this->create_subscription<sensor_msgs::msg::JointState>(
    "/joint_states", 50,
    std::bind(&TransformControllerNode::bldcJointStateCallback, this, std::placeholders::_1));

  dxl_joint_state_sub_ = this->create_subscription<sensor_msgs::msg::JointState>(
    "/dxl_joint_states", 50,
    std::bind(&TransformControllerNode::dxlJointStateCallback, this, std::placeholders::_1));

  transform_profile_sub_ = this->create_subscription<std_msgs::msg::String>(
    "/transform/profile_cmd", 20,
    std::bind(&TransformControllerNode::transformProfileCallback, this, std::placeholders::_1));

  step_result_pub_ = this->create_publisher<robot_msgs::msg::TransformStepResult>("/transform/step_result", 20);
  mit_position_pub_ = this->create_publisher<robot_msgs::msg::MitCommand>("/bldc_mit_position_cmd", 20);
  dxl_position_pub_ = this->create_publisher<std_msgs::msg::Float64MultiArray>("/dxl_position_cmd", 20);
  error_pub_ = this->create_publisher<robot_msgs::msg::SystemError>("/system/error", 20);

  control_timer_ = this->create_wall_timer(
    50ms, std::bind(&TransformControllerNode::controlTimerCallback, this));

  applyTransformProfile(current_transform_profile_);
}

double TransformControllerNode::wrapToRangeDeg(double x, double range) const
{
  return ::wrapToRangeDeg(x, range);
}

double TransformControllerNode::shortestWrappedErrorDeg(double current, double target, double range) const
{
  return ::shortestWrappedErrorDeg(current, target, range);
}

double TransformControllerNode::getWrapRangeDegForMotor(int motor_id) const
{
  if (motor_id == 1 || motor_id == 2) return bldc_wrap_range_deg_;
  return dxl_wrap_range_deg_;
}

void TransformControllerNode::applyTransformProfile(const std::string & profile_name)
{
  if (profile_name == "precise") {
    mit_position_kp_ = transform_precise_pos_kp_;
    mit_position_kd_ = transform_precise_pos_kd_;
    mit_position_tau_ff_ = transform_precise_tau_ff_;
    current_transform_profile_ = "precise";
  } else if (profile_name == "fast") {
    mit_position_kp_ = transform_fast_pos_kp_;
    mit_position_kd_ = transform_fast_pos_kd_;
    mit_position_tau_ff_ = transform_fast_tau_ff_;
    current_transform_profile_ = "fast";
  } else if (profile_name == "soft") {
    mit_position_kp_ = transform_soft_pos_kp_;
    mit_position_kd_ = transform_soft_pos_kd_;
    mit_position_tau_ff_ = transform_soft_tau_ff_;
    current_transform_profile_ = "soft";
  }
}

void TransformControllerNode::transformProfileCallback(const std_msgs::msg::String::SharedPtr msg)
{
  applyTransformProfile(msg->data);
}

void TransformControllerNode::publishStepResult(bool success, bool timeout, const std::string & message)
{
  robot_msgs::msg::TransformStepResult msg;
  msg.motor_id = active_motor_id_;
  msg.success = success;
  msg.timeout = timeout;
  msg.position_reached = success;
  msg.velocity_reached = success;
  msg.settled = success;
  msg.actual_angle_deg = getMotorAngleDeg(active_motor_id_);
  msg.message = message;
  step_result_pub_->publish(msg);
}

void TransformControllerNode::publishBldcPositionCmd(int motor_id, double raw_target_deg)
{
  robot_msgs::msg::MitCommand msg;
  msg.motor_id = motor_id;
  msg.p_des = raw_target_deg;
  msg.v_des = 0.0;
  msg.kp = mit_position_kp_;
  msg.kd = mit_position_kd_;
  msg.tau_ff = mit_position_tau_ff_;
  mit_position_pub_->publish(msg);
}

void TransformControllerNode::publishDxlPositionCmd(int motor_id, double target_deg)
{
  std_msgs::msg::Float64MultiArray msg;
  msg.data.push_back(static_cast<double>(motor_id));
  msg.data.push_back(target_deg);
  dxl_position_pub_->publish(msg);
}

double TransformControllerNode::getMotorAngleDeg(int motor_id) const
{
  std::string joint_name;
  if (motor_id == 1) joint_name = motor1_joint_name_;
  else if (motor_id == 2) joint_name = motor2_joint_name_;
  else if (motor_id == 3) joint_name = motor3_joint_name_;
  else if (motor_id == 4) joint_name = motor4_joint_name_;
  else return 0.0;

  const auto it = joint_position_deg_map_.find(joint_name);
  if (it != joint_position_deg_map_.end()) return it->second;
  return 0.0;
}

double TransformControllerNode::getMotorVelocityRad(int motor_id) const
{
  std::string joint_name;
  if (motor_id == 1) joint_name = motor1_joint_name_;
  else if (motor_id == 2) joint_name = motor2_joint_name_;
  else if (motor_id == 3) joint_name = motor3_joint_name_;
  else if (motor_id == 4) joint_name = motor4_joint_name_;
  else return 0.0;

  const auto it = joint_velocity_rad_map_.find(joint_name);
  if (it != joint_velocity_rad_map_.end()) return it->second;
  return 0.0;
}

void TransformControllerNode::stepCmdCallback(const robot_msgs::msg::TransformStep::SharedPtr msg)
{
  active_motor_id_ = msg->motor_id;
  active_motor_type_ = msg->motor_type;
  timeout_sec_ = msg->timeout_sec;
  retry_count_ = msg->retry_count;

  step_start_time_ = this->now();
  settle_start_time_ = this->now();
  settle_started_ = false;
  step_active_ = true;

  if (active_motor_type_ == MOTOR_TYPE_BLDC) {
    const double current_raw_deg = getMotorAngleDeg(active_motor_id_);
    const double requested_target_deg = msg->target_angle_deg;

    // BLDC 0도 정렬은 진짜 raw absolute 0도로 보낸다.
    // target 0.0을 720.0 또는 -720.0으로 바꾸면 안 된다.
    if (std::abs(requested_target_deg) < 1e-6) {
      target_angle_deg_ = 0.0;
    } else {
      target_angle_deg_ =
        computeRawTargetDeg(
          current_raw_deg,
          requested_target_deg,
          bldc_wrap_range_deg_,
          0.0);
    }

    publishBldcPositionCmd(active_motor_id_, target_angle_deg_);

    RCLCPP_INFO(
      this->get_logger(),
      "BLDC step latched: motor=%d current_raw_deg=%.3f requested_target_deg=%.3f latched_raw_target_deg=%.3f",
      active_motor_id_,
      current_raw_deg,
      requested_target_deg,
      target_angle_deg_);

  } else if (active_motor_type_ == MOTOR_TYPE_DXL) {
    target_angle_deg_ = msg->target_angle_deg;

    publishDxlPositionCmd(active_motor_id_, target_angle_deg_);

    RCLCPP_INFO(
      this->get_logger(),
      "DXL step command: motor=%d target_deg=%.3f timeout=%.2f",
      active_motor_id_,
      target_angle_deg_,
      timeout_sec_);

  } else {
    RCLCPP_ERROR(
      this->get_logger(),
      "Invalid motor type: motor_id=%d motor_type=%d",
      active_motor_id_,
      active_motor_type_);

    publishStepResult(false, false, "Invalid motor type");
    step_active_ = false;
  }
}

void TransformControllerNode::bldcJointStateCallback(const sensor_msgs::msg::JointState::SharedPtr msg)
{
  for (std::size_t i = 0; i < msg->name.size(); ++i) {
    if (i < msg->position.size()) {
      joint_position_deg_map_[msg->name[i]] = radToDeg(msg->position[i]);
    }
    if (i < msg->velocity.size()) {
      joint_velocity_rad_map_[msg->name[i]] = msg->velocity[i];
    }
  }
}

void TransformControllerNode::dxlJointStateCallback(const sensor_msgs::msg::JointState::SharedPtr msg)
{
  for (std::size_t i = 0; i < msg->name.size(); ++i) {
    if (i < msg->position.size()) {
      joint_position_deg_map_[msg->name[i]] = radToDeg(msg->position[i]);
    }
    if (i < msg->velocity.size()) {
      joint_velocity_rad_map_[msg->name[i]] = msg->velocity[i];
    }
  }
}

void TransformControllerNode::controlTimerCallback()
{
  if (!step_active_) return;

  const double elapsed = (this->now() - step_start_time_).seconds();

  if (test_auto_success_) {
    if (elapsed >= test_auto_success_delay_sec_) {
      publishStepResult(true, false, "Step completed by test_auto_success");
      step_active_ = false;
      return;
    }
    return;
  }

  const double current_angle_deg_raw = getMotorAngleDeg(active_motor_id_);
  const double current_vel_rad = getMotorVelocityRad(active_motor_id_);

  double error_deg = 0.0;

  if (active_motor_type_ == MOTOR_TYPE_BLDC) {
    // stepCmdCallback에서 latch된 raw target만 사용
    error_deg = target_angle_deg_ - current_angle_deg_raw;
    publishBldcPositionCmd(active_motor_id_, target_angle_deg_);
  } else {
    const double wrap_range_deg = getWrapRangeDegForMotor(active_motor_id_);
    const double current_angle_deg = wrapToRangeDeg(current_angle_deg_raw, wrap_range_deg);
    const double target_angle_deg = wrapToRangeDeg(target_angle_deg_, wrap_range_deg);
    error_deg = shortestWrappedErrorDeg(current_angle_deg, target_angle_deg, wrap_range_deg);
  }

  const bool pos_ok = std::abs(error_deg) <= position_tolerance_deg_;
  const bool vel_ok = std::abs(current_vel_rad) <= velocity_tolerance_rad_s_;

  if (pos_ok && vel_ok) {
    if (!settle_started_) {
      settle_started_ = true;
      settle_start_time_ = this->now();
    } else {
      const double settle_elapsed = (this->now() - settle_start_time_).seconds();
      if (settle_elapsed >= settle_time_sec_) {
        publishStepResult(true, false, "Step completed");
        step_active_ = false;
        return;
      }
    }
  } else {
    settle_started_ = false;
  }

  if (elapsed >= timeout_sec_) {
    publishStepResult(false, true, "Step timeout");
    step_active_ = false;
  }
}

int main(int argc, char ** argv)
{
  rclcpp::init(argc, argv);
  rclcpp::spin(std::make_shared<TransformControllerNode>());
  rclcpp::shutdown();
  return 0;
}
