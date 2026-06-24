#include "robot_transform/transform_controller_node.hpp"

#include <algorithm>
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
  if (y < 0.0) {
    y += range;
  }
  return y;
}

double shortestWrappedErrorDeg(double current, double target, double range)
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
}  // namespace

TransformControllerNode::TransformControllerNode()
: Node("transform_controller_node"),
  step_active_(false),
  active_bldc_posvel_(false),
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
  bldc_wrap_turns_(4.0),
  dxl_wrap_turns_(3.0),
  bldc_wrap_range_deg_(4.0 * 360.0),
  dxl_wrap_range_deg_(3.0 * 360.0),
  bldc_posvel_kp_(1.3),
  bldc_posvel_kd_(0.15),
  bldc_posvel_max_vel_rad_s_(6.0),
  bldc_posvel_min_vel_rad_s_(0.0),
  bldc_posvel_position_tolerance_deg_(3.0),
  bldc_posvel_velocity_tolerance_rad_s_(0.35),
  bldc_posvel_accel_limit_rad_s2_(3.0),
  bldc_posvel_jerk_limit_rad_s3_(20.0),
  bldc_mit_speed_kd_(0.0),
  last_bldc_speed_cmd_1_(0.0),
  last_bldc_speed_cmd_2_(0.0),
  last_bldc_accel_cmd_1_(0.0),
  last_bldc_accel_cmd_2_(0.0),
  last_control_time_(0, 0, RCL_ROS_TIME),
  has_last_control_time_(false)
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

  this->declare_parameter("bldc_posvel_kp", bldc_posvel_kp_);
  this->declare_parameter("bldc_posvel_kd", bldc_posvel_kd_);
  this->declare_parameter("bldc_posvel_max_vel_rad_s", bldc_posvel_max_vel_rad_s_);
  this->declare_parameter("bldc_posvel_min_vel_rad_s", bldc_posvel_min_vel_rad_s_);
  this->declare_parameter("bldc_posvel_position_tolerance_deg", bldc_posvel_position_tolerance_deg_);
  this->declare_parameter("bldc_posvel_velocity_tolerance_rad_s", bldc_posvel_velocity_tolerance_rad_s_);
  this->declare_parameter("bldc_posvel_accel_limit_rad_s2", bldc_posvel_accel_limit_rad_s2_);
  this->declare_parameter("bldc_posvel_jerk_limit_rad_s3", bldc_posvel_jerk_limit_rad_s3_);
  this->declare_parameter("bldc_mit_speed_kd", bldc_mit_speed_kd_);

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

  this->get_parameter("bldc_posvel_kp", bldc_posvel_kp_);
  this->get_parameter("bldc_posvel_kd", bldc_posvel_kd_);
  this->get_parameter("bldc_posvel_max_vel_rad_s", bldc_posvel_max_vel_rad_s_);
  this->get_parameter("bldc_posvel_min_vel_rad_s", bldc_posvel_min_vel_rad_s_);
  this->get_parameter("bldc_posvel_position_tolerance_deg", bldc_posvel_position_tolerance_deg_);
  this->get_parameter("bldc_posvel_velocity_tolerance_rad_s", bldc_posvel_velocity_tolerance_rad_s_);
  this->get_parameter("bldc_posvel_accel_limit_rad_s2", bldc_posvel_accel_limit_rad_s2_);
  this->get_parameter("bldc_posvel_jerk_limit_rad_s3", bldc_posvel_jerk_limit_rad_s3_);
  this->get_parameter("bldc_mit_speed_kd", bldc_mit_speed_kd_);

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

  step_result_pub_ =
    this->create_publisher<robot_msgs::msg::TransformStepResult>("/transform/step_result", 20);

  mit_position_pub_ =
    this->create_publisher<robot_msgs::msg::MitCommand>("/bldc_mit_position_cmd", 20);

  mit_speed_pub_ =
    this->create_publisher<robot_msgs::msg::MitCommand>("/bldc_mit_speed_cmd", 20);

  dxl_position_pub_ =
    this->create_publisher<std_msgs::msg::Float64MultiArray>("/dxl_position_cmd", 20);

  error_pub_ =
    this->create_publisher<robot_msgs::msg::SystemError>("/system/error", 20);

  control_timer_ = this->create_wall_timer(
    2ms,
    std::bind(&TransformControllerNode::controlTimerCallback, this));

  applyTransformProfile(current_transform_profile_);

  RCLCPP_INFO(this->get_logger(), "transform_controller_node started");
  RCLCPP_INFO(
    this->get_logger(),
    "BLDC transform mode: velocity-based PD position control enabled. "
    "timer=2ms target_rate=500Hz kp=%.3f kd=%.3f max_vel=%.3f min_vel=%.3f "
    "tol_deg=%.3f vel_tol=%.3f accel_limit=%.3f jerk_limit=%.3f mit_speed_kd=%.3f",
    bldc_posvel_kp_,
    bldc_posvel_kd_,
    bldc_posvel_max_vel_rad_s_,
    bldc_posvel_min_vel_rad_s_,
    bldc_posvel_position_tolerance_deg_,
    bldc_posvel_velocity_tolerance_rad_s_,
    bldc_posvel_accel_limit_rad_s2_,
    bldc_posvel_jerk_limit_rad_s3_,
    bldc_mit_speed_kd_);
}

double TransformControllerNode::wrapToRangeDeg(double x, double range) const
{
  return ::wrapToRangeDeg(x, range);
}

double TransformControllerNode::shortestWrappedErrorDeg(
  double current,
  double target,
  double range) const
{
  return ::shortestWrappedErrorDeg(current, target, range);
}

double TransformControllerNode::getWrapRangeDegForMotor(int motor_id) const
{
  if (motor_id == 1 || motor_id == 2) {
    return bldc_wrap_range_deg_;
  }
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
  } else {
    RCLCPP_WARN(this->get_logger(), "Unknown transform profile: %s", profile_name.c_str());
  }
}

void TransformControllerNode::transformProfileCallback(
  const std_msgs::msg::String::SharedPtr msg)
{
  applyTransformProfile(msg->data);
}

void TransformControllerNode::publishStepResult(
  bool success,
  bool timeout,
  const std::string & message)
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

void TransformControllerNode::publishBldcSpeedCmd(int motor_id, double v_des)
{
  robot_msgs::msg::MitCommand msg;
  msg.motor_id = motor_id;
  msg.p_des = 0.0;
  msg.v_des = v_des;
  msg.kp = 0.0;
  msg.kd = bldc_mit_speed_kd_;
  msg.tau_ff = 0.0;

  mit_speed_pub_->publish(msg);
}

void TransformControllerNode::publishBldcStopCmd()
{
  publishBldcSpeedCmd(1, 0.0);
  publishBldcSpeedCmd(2, 0.0);
  resetBldcSpeedLimiter();
}

double TransformControllerNode::applyBldcSpeedRateLimit(
  int motor_id,
  double desired_v,
  double dt)
{
  if (dt <= 0.0) {
    return desired_v;
  }

  double * last_v = nullptr;
  double * last_a = nullptr;

  if (motor_id == 1) {
    last_v = &last_bldc_speed_cmd_1_;
    last_a = &last_bldc_accel_cmd_1_;
  } else if (motor_id == 2) {
    last_v = &last_bldc_speed_cmd_2_;
    last_a = &last_bldc_accel_cmd_2_;
  } else {
    return 0.0;
  }

  double desired_a = (desired_v - *last_v) / dt;

  desired_a = std::clamp(
    desired_a,
    -bldc_posvel_accel_limit_rad_s2_,
    bldc_posvel_accel_limit_rad_s2_);

  const double max_delta_a = bldc_posvel_jerk_limit_rad_s3_ * dt;
  const double delta_a = desired_a - *last_a;

  double limited_a = desired_a;

  if (delta_a > max_delta_a) {
    limited_a = *last_a + max_delta_a;
  } else if (delta_a < -max_delta_a) {
    limited_a = *last_a - max_delta_a;
  }

  double limited_v = *last_v + limited_a * dt;

  if ((*last_v < desired_v && limited_v > desired_v) ||
      (*last_v > desired_v && limited_v < desired_v)) {
    limited_v = desired_v;
    limited_a = 0.0;
  }

  *last_v = limited_v;
  *last_a = limited_a;

  return limited_v;
}

void TransformControllerNode::resetBldcSpeedLimiter()
{
  last_bldc_speed_cmd_1_ = 0.0;
  last_bldc_speed_cmd_2_ = 0.0;

  last_bldc_accel_cmd_1_ = 0.0;
  last_bldc_accel_cmd_2_ = 0.0;

  has_last_control_time_ = false;
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

  if (motor_id == 1) {
    joint_name = motor1_joint_name_;
  } else if (motor_id == 2) {
    joint_name = motor2_joint_name_;
  } else if (motor_id == 3) {
    joint_name = motor3_joint_name_;
  } else if (motor_id == 4) {
    joint_name = motor4_joint_name_;
  } else {
    return 0.0;
  }

  const auto it = joint_position_deg_map_.find(joint_name);
  if (it != joint_position_deg_map_.end()) {
    return it->second;
  }

  return 0.0;
}

double TransformControllerNode::getMotorVelocityRad(int motor_id) const
{
  std::string joint_name;

  if (motor_id == 1) {
    joint_name = motor1_joint_name_;
  } else if (motor_id == 2) {
    joint_name = motor2_joint_name_;
  } else if (motor_id == 3) {
    joint_name = motor3_joint_name_;
  } else if (motor_id == 4) {
    joint_name = motor4_joint_name_;
  } else {
    return 0.0;
  }

  const auto it = joint_velocity_rad_map_.find(joint_name);
  if (it != joint_velocity_rad_map_.end()) {
    return it->second;
  }

  return 0.0;
}

void TransformControllerNode::stepCmdCallback(
  const robot_msgs::msg::TransformStep::SharedPtr msg)
{
  if (step_active_) {
    RCLCPP_WARN(
      this->get_logger(),
      "Rejected new step because previous step is still active. active_motor=%d new_motor=%d",
      active_motor_id_,
      msg->motor_id);
    return;
  }

  active_motor_id_ = msg->motor_id;
  active_motor_type_ = msg->motor_type;
  timeout_sec_ = msg->timeout_sec;
  retry_count_ = msg->retry_count;

  step_start_time_ = this->now();
  settle_start_time_ = this->now();
  settle_started_ = false;
  step_active_ = true;

  if (active_motor_type_ == MOTOR_TYPE_BLDC) {
    active_bldc_posvel_ = true;
    target_angle_deg_ = msg->target_angle_deg;

    // Step 시작 시 두 BLDC를 한 번 정지시킨 뒤 active motor만 제어한다.
    publishBldcStopCmd();

    last_control_time_ = this->now();
    has_last_control_time_ = true;

    RCLCPP_INFO(
      this->get_logger(),
      "BLDC velocity-position PD step start: motor=%d target_deg=%.3f timeout=%.2f",
      active_motor_id_,
      target_angle_deg_,
      timeout_sec_);

  } else if (active_motor_type_ == MOTOR_TYPE_DXL) {
    active_bldc_posvel_ = false;
    target_angle_deg_ = msg->target_angle_deg;

    publishDxlPositionCmd(active_motor_id_, target_angle_deg_);

    RCLCPP_INFO(
      this->get_logger(),
      "DXL step command: motor=%d target_deg=%.3f timeout=%.2f",
      active_motor_id_,
      target_angle_deg_,
      timeout_sec_);

  } else {
    active_bldc_posvel_ = false;

    RCLCPP_ERROR(
      this->get_logger(),
      "Invalid motor type: motor_id=%d motor_type=%d",
      active_motor_id_,
      active_motor_type_);

    publishStepResult(false, false, "Invalid motor type");
    step_active_ = false;
  }
}

void TransformControllerNode::bldcJointStateCallback(
  const sensor_msgs::msg::JointState::SharedPtr msg)
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

void TransformControllerNode::dxlJointStateCallback(
  const sensor_msgs::msg::JointState::SharedPtr msg)
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
  if (!step_active_) {
    return;
  }

  const rclcpp::Time now = this->now();
  const double elapsed = (now - step_start_time_).seconds();

  double dt = 0.002;
  if (has_last_control_time_) {
    dt = (now - last_control_time_).seconds();
  }

  // Protect against timer jitter or invalid clock jumps.
  if (dt <= 0.0 || dt > 0.05) {
    dt = 0.002;
  }

  last_control_time_ = now;
  has_last_control_time_ = true;

  if (test_auto_success_) {
    if (elapsed >= test_auto_success_delay_sec_) {
      if (active_motor_type_ == MOTOR_TYPE_BLDC) {
        publishBldcStopCmd();
      }

      publishStepResult(true, false, "Step completed by test_auto_success");
      step_active_ = false;
      active_bldc_posvel_ = false;
      return;
    }
    return;
  }

  const double current_angle_deg_raw = getMotorAngleDeg(active_motor_id_);
  const double current_vel_rad = getMotorVelocityRad(active_motor_id_);

  double error_deg = 0.0;
  bool pos_ok = false;
  bool vel_ok = false;

  if (active_motor_type_ == MOTOR_TYPE_BLDC && active_bldc_posvel_) {
    error_deg = target_angle_deg_ - current_angle_deg_raw;

    const double error_rad = error_deg * M_PI / 180.0;

    /*
      Outer PD loop:
        position error [rad] -> velocity command [rad/s]

      target velocity is treated as 0 rad/s.
      D term is velocity damping:
        v_cmd = Kp * position_error + Kd * (0 - current_velocity)
              = Kp * position_error - Kd * current_velocity
    */
    double desired_v_cmd =
      bldc_posvel_kp_ * error_rad
      - bldc_posvel_kd_ * current_vel_rad;

    desired_v_cmd = std::clamp(
      desired_v_cmd,
      -bldc_posvel_max_vel_rad_s_,
      bldc_posvel_max_vel_rad_s_);

    if (std::abs(error_deg) > bldc_posvel_position_tolerance_deg_ &&
        std::abs(desired_v_cmd) < bldc_posvel_min_vel_rad_s_) {
      desired_v_cmd = (error_rad >= 0.0)
        ? bldc_posvel_min_vel_rad_s_
        : -bldc_posvel_min_vel_rad_s_;
    }

    pos_ok = std::abs(error_deg) <= bldc_posvel_position_tolerance_deg_;
    vel_ok = std::abs(current_vel_rad) <= bldc_posvel_velocity_tolerance_rad_s_;

    if (pos_ok && vel_ok) {
      // settle 구간에 처음 들어왔을 때만 stop 명령을 보낸다.
      // 이전 코드처럼 settle 동안 매 2ms마다 0 명령을 반복 publish하지 않는다.
      if (!settle_started_) {
        publishBldcStopCmd();
        settle_started_ = true;
        settle_start_time_ = now;
      } else {
        const double settle_elapsed = (now - settle_start_time_).seconds();

        if (settle_elapsed >= settle_time_sec_) {
          publishStepResult(true, false, "Step completed");
          step_active_ = false;
          active_bldc_posvel_ = false;
          publishBldcStopCmd();
          return;
        }
      }
    } else {
      settle_started_ = false;

      if (active_motor_id_ == 1) {
        const double limited_v_cmd = applyBldcSpeedRateLimit(1, desired_v_cmd, dt);

        // active motor에만 명령을 보낸다.
        // motor 2에 매 루프마다 0 명령을 보내지 않는다.
        publishBldcSpeedCmd(1, limited_v_cmd);

        RCLCPP_INFO_THROTTLE(
          this->get_logger(),
          *this->get_clock(),
          500,
          "BLDC speed limit motor=1 desired=%.3f limited=%.3f dt=%.4f",
          desired_v_cmd,
          limited_v_cmd,
          dt);

      } else if (active_motor_id_ == 2) {
        const double limited_v_cmd = applyBldcSpeedRateLimit(2, desired_v_cmd, dt);

        // active motor에만 명령을 보낸다.
        // motor 1에 매 루프마다 0 명령을 보내지 않는다.
        publishBldcSpeedCmd(2, limited_v_cmd);

        RCLCPP_INFO_THROTTLE(
          this->get_logger(),
          *this->get_clock(),
          500,
          "BLDC speed limit motor=2 desired=%.3f limited=%.3f dt=%.4f",
          desired_v_cmd,
          limited_v_cmd,
          dt);
      }
    }

    RCLCPP_INFO_THROTTLE(
      this->get_logger(),
      *this->get_clock(),
      500,
      "BLDC pos-vel PD control motor=%d current=%.3f target=%.3f error=%.3f "
      "v_fb=%.3f kp=%.3f kd=%.3f pos_ok=%d vel_ok=%d",
      active_motor_id_,
      current_angle_deg_raw,
      target_angle_deg_,
      error_deg,
      current_vel_rad,
      bldc_posvel_kp_,
      bldc_posvel_kd_,
      pos_ok,
      vel_ok);

  } else if (active_motor_type_ == MOTOR_TYPE_DXL) {
    const double wrap_range_deg = getWrapRangeDegForMotor(active_motor_id_);
    const double current_angle_deg = wrapToRangeDeg(current_angle_deg_raw, wrap_range_deg);
    const double target_angle_deg = wrapToRangeDeg(target_angle_deg_, wrap_range_deg);

    error_deg = shortestWrappedErrorDeg(
      current_angle_deg,
      target_angle_deg,
      wrap_range_deg);

    pos_ok = std::abs(error_deg) <= position_tolerance_deg_;
    vel_ok = std::abs(current_vel_rad) <= velocity_tolerance_rad_s_;

    if (pos_ok && vel_ok) {
      if (!settle_started_) {
        settle_started_ = true;
        settle_start_time_ = now;
      } else {
        const double settle_elapsed = (now - settle_start_time_).seconds();

        if (settle_elapsed >= settle_time_sec_) {
          publishStepResult(true, false, "Step completed");
          step_active_ = false;
          return;
        }
      }
    } else {
      settle_started_ = false;
    }

  } else {
    publishStepResult(false, false, "Invalid active motor type");
    step_active_ = false;
    active_bldc_posvel_ = false;
    publishBldcStopCmd();
    return;
  }

  if (elapsed >= timeout_sec_) {
    if (active_motor_type_ == MOTOR_TYPE_BLDC) {
      publishBldcStopCmd();
    }

    RCLCPP_WARN(
      this->get_logger(),
      "Step timeout motor=%d type=%d current=%.3f target=%.3f error=%.3f vel=%.3f",
      active_motor_id_,
      active_motor_type_,
      current_angle_deg_raw,
      target_angle_deg_,
      error_deg,
      current_vel_rad);

    publishStepResult(false, true, "Step timeout");
    step_active_ = false;
    active_bldc_posvel_ = false;
    return;
  }
}

int main(int argc, char ** argv)
{
  rclcpp::init(argc, argv);
  rclcpp::spin(std::make_shared<TransformControllerNode>());
  rclcpp::shutdown();
  return 0;
}