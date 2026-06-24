#include "robot_drive/drive_controller_node.hpp"

#include <algorithm>
#include <cmath>

namespace
{
constexpr double kZeroCmdEps = 1e-6;
constexpr double kZeroSnapEps = 1e-4;
constexpr double kNormalizedCmdMin = -1.0;
constexpr double kNormalizedCmdMax = 1.0;
}  // namespace

DriveControllerNode::DriveControllerNode()
: Node("drive_controller_node"),
  wheel_radius_(0.25),
  wheel_separation_(0.60),
  max_linear_velocity_(1.72),
  max_angular_velocity_(1.2),
  linear_accel_limit_(1.0),
  angular_accel_limit_(2.0),
  current_linear_cmd_(0.0),
  current_angular_cmd_(0.0),
  speed_mode_kd_(1.5),
  speed_mode_tau_ff_(0.0),
  drive_normal_vel_kd_(1.5),
  drive_normal_tau_ff_(0.0),
  drive_slope_vel_kd_(2.0),
  drive_slope_tau_ff_(0.2),
  drive_obstacle_vel_kd_(2.5),
  drive_obstacle_tau_ff_(0.3),
  current_drive_profile_("normal"),
  transform_active_(false),
  transform_action_state_value_(2)
{
  this->declare_parameter("wheel_radius", wheel_radius_);
  this->declare_parameter("wheel_separation", wheel_separation_);
  this->declare_parameter("max_linear_velocity", max_linear_velocity_);
  this->declare_parameter("max_angular_velocity", max_angular_velocity_);
  this->declare_parameter("linear_accel_limit", linear_accel_limit_);
  this->declare_parameter("angular_accel_limit", angular_accel_limit_);

  this->declare_parameter("drive_normal_vel_kd", drive_normal_vel_kd_);
  this->declare_parameter("drive_normal_tau_ff", drive_normal_tau_ff_);
  this->declare_parameter("drive_slope_vel_kd", drive_slope_vel_kd_);
  this->declare_parameter("drive_slope_tau_ff", drive_slope_tau_ff_);
  this->declare_parameter("drive_obstacle_vel_kd", drive_obstacle_vel_kd_);
  this->declare_parameter("drive_obstacle_tau_ff", drive_obstacle_tau_ff_);
  this->declare_parameter("default_drive_profile", current_drive_profile_);

  // /system/action_state에서 변신 상태로 쓰는 값.
  // 네 로그 기준 transform 중 data: 2였으므로 기본값 2.
  this->declare_parameter("transform_action_state_value", transform_action_state_value_);

  this->get_parameter("wheel_radius", wheel_radius_);
  this->get_parameter("wheel_separation", wheel_separation_);
  this->get_parameter("max_linear_velocity", max_linear_velocity_);
  this->get_parameter("max_angular_velocity", max_angular_velocity_);
  this->get_parameter("linear_accel_limit", linear_accel_limit_);
  this->get_parameter("angular_accel_limit", angular_accel_limit_);

  this->get_parameter("drive_normal_vel_kd", drive_normal_vel_kd_);
  this->get_parameter("drive_normal_tau_ff", drive_normal_tau_ff_);
  this->get_parameter("drive_slope_vel_kd", drive_slope_vel_kd_);
  this->get_parameter("drive_slope_tau_ff", drive_slope_tau_ff_);
  this->get_parameter("drive_obstacle_vel_kd", drive_obstacle_vel_kd_);
  this->get_parameter("drive_obstacle_tau_ff", drive_obstacle_tau_ff_);
  this->get_parameter("default_drive_profile", current_drive_profile_);
  this->get_parameter("transform_action_state_value", transform_action_state_value_);

  drive_cmd_sub_ = this->create_subscription<geometry_msgs::msg::Twist>(
    "/drive/cmd_vel", 20,
    std::bind(&DriveControllerNode::driveCmdCallback, this, std::placeholders::_1));

  drive_profile_sub_ = this->create_subscription<std_msgs::msg::String>(
    "/drive/profile_cmd", 20,
    std::bind(&DriveControllerNode::driveProfileCallback, this, std::placeholders::_1));

  action_state_sub_ = this->create_subscription<std_msgs::msg::Int32>(
    "/system/action_state", 20,
    std::bind(&DriveControllerNode::actionStateCallback, this, std::placeholders::_1));

  mit_speed_pub_ =
    this->create_publisher<robot_msgs::msg::MitCommand>("/bldc_mit_speed_cmd", 20);

  drive_feedback_pub_ =
    this->create_publisher<robot_msgs::msg::CommandFeedback>("/drive/command_feedback", 20);

  last_cmd_time_ = this->now();

  applyDriveProfile(current_drive_profile_);

  RCLCPP_INFO(this->get_logger(), "drive_controller_node started");
  RCLCPP_INFO(
    this->get_logger(),
    "current_drive_profile=%s max_linear_velocity=%.3f max_angular_velocity=%.3f",
    current_drive_profile_.c_str(),
    max_linear_velocity_,
    max_angular_velocity_);

  RCLCPP_INFO(
    this->get_logger(),
    "Drive input mode: normalized cmd_vel enabled. "
    "linear.x [-1, 1] -> [%.3f m/s], angular.z [-1, 1] -> [%.3f rad/s]",
    max_linear_velocity_,
    max_angular_velocity_);

  RCLCPP_INFO(
    this->get_logger(),
    "Drive output gate enabled. During /system/action_state == %d, "
    "drive_controller_node will NOT publish /bldc_mit_speed_cmd.",
    transform_action_state_value_);
}

double DriveControllerNode::clamp(double value, double min_value, double max_value) const
{
  return std::max(min_value, std::min(value, max_value));
}

double DriveControllerNode::applyRateLimit(
  double target, double current, double rate_limit, double dt) const
{
  const double max_delta = rate_limit * dt;
  const double delta = target - current;

  if (delta > max_delta) {
    return current + max_delta;
  }
  if (delta < -max_delta) {
    return current - max_delta;
  }
  return target;
}

void DriveControllerNode::actionStateCallback(const std_msgs::msg::Int32::SharedPtr msg)
{
  const bool new_transform_active = (msg->data == transform_action_state_value_);

  if (new_transform_active != transform_active_) {
    transform_active_ = new_transform_active;

    if (transform_active_) {
      current_linear_cmd_ = 0.0;
      current_angular_cmd_ = 0.0;

      RCLCPP_WARN(
        this->get_logger(),
        "Transform action detected. Drive output is now blocked. "
        "No zero speed command will be continuously published by drive_controller_node.");
    } else {
      last_cmd_time_ = this->now();

      RCLCPP_INFO(
        this->get_logger(),
        "Transform action ended. Drive output is now enabled.");
    }
  }
}

void DriveControllerNode::publishMitSpeedCommand(int motor_id, double v_des)
{
  robot_msgs::msg::MitCommand msg;
  msg.motor_id = motor_id;
  msg.p_des = 0.0;
  msg.v_des = v_des;
  msg.kp = 0.0;
  msg.kd = speed_mode_kd_;
  msg.tau_ff = 0.0;

  if (std::abs(v_des) > 0.05) {
    msg.tau_ff = (v_des > 0.0) ? speed_mode_tau_ff_ : -speed_mode_tau_ff_;
  }

  mit_speed_pub_->publish(msg);
}

void DriveControllerNode::publishDriveFeedback(
  bool accepted,
  int code,
  const std::string & message)
{
  robot_msgs::msg::CommandFeedback fb;
  fb.source_node = "drive_controller_node";
  fb.command_type = "drive";
  fb.accepted = accepted;
  fb.code = code;
  fb.message = message;
  drive_feedback_pub_->publish(fb);
}

void DriveControllerNode::applyDriveProfile(const std::string & profile_name)
{
  if (profile_name == "normal") {
    speed_mode_kd_ = drive_normal_vel_kd_;
    speed_mode_tau_ff_ = drive_normal_tau_ff_;
    current_drive_profile_ = "normal";
  } else if (profile_name == "slope") {
    speed_mode_kd_ = drive_slope_vel_kd_;
    speed_mode_tau_ff_ = drive_slope_tau_ff_;
    current_drive_profile_ = "slope";
  } else if (profile_name == "obstacle") {
    speed_mode_kd_ = drive_obstacle_vel_kd_;
    speed_mode_tau_ff_ = drive_obstacle_tau_ff_;
    current_drive_profile_ = "obstacle";
  } else {
    RCLCPP_WARN(this->get_logger(), "Unknown drive profile: %s", profile_name.c_str());
    return;
  }

  RCLCPP_INFO(
    this->get_logger(),
    "Applied drive profile=%s vel_kd=%.3f tau_ff=%.3f",
    current_drive_profile_.c_str(),
    speed_mode_kd_,
    speed_mode_tau_ff_);
}

void DriveControllerNode::driveProfileCallback(const std_msgs::msg::String::SharedPtr msg)
{
  applyDriveProfile(msg->data);
}

void DriveControllerNode::driveCmdCallback(const geometry_msgs::msg::Twist::SharedPtr msg)
{
  /*
   * 핵심 수정:
   * 변신 중에는 drive_controller_node가 /bldc_mit_speed_cmd에 아무것도 publish하지 않는다.
   *
   * 여기서 0 명령을 보내면 transform_controller_node의 속도 명령 사이에
   * drive_controller_node의 v_des=0.0이 섞여 들어간다.
   */
  if (transform_active_) {
    current_linear_cmd_ = 0.0;
    current_angular_cmd_ = 0.0;
    last_cmd_time_ = this->now();

    RCLCPP_INFO_THROTTLE(
      this->get_logger(),
      *this->get_clock(),
      1000,
      "Drive command ignored because transform is active. "
      "No /bldc_mit_speed_cmd was published by drive_controller_node.");

    publishDriveFeedback(false, 210, "Drive command ignored during transform");
    return;
  }

  const rclcpp::Time now = this->now();
  double dt = (now - last_cmd_time_).seconds();

  if (dt <= 0.0) {
    dt = 0.01;
  }

  last_cmd_time_ = now;

  /*
   * /drive/cmd_vel is treated as a normalized manual command here.
   *
   * msg->linear.x:
   *   -1.0 -> full reverse
   *    0.0 -> stop
   *   +1.0 -> full forward
   *
   * msg->angular.z:
   *   -1.0 -> full right/clockwise turn command
   *    0.0 -> no turn
   *   +1.0 -> full left/counterclockwise turn command
   *
   * The actual physical velocity is generated by multiplying this normalized
   * command by max_linear_velocity_ and max_angular_velocity_.
   */
  const double normalized_linear =
    clamp(msg->linear.x, kNormalizedCmdMin, kNormalizedCmdMax);

  const double normalized_angular =
    clamp(msg->angular.z, kNormalizedCmdMin, kNormalizedCmdMax);

  const double target_linear = normalized_linear * max_linear_velocity_;
  const double target_angular = normalized_angular * max_angular_velocity_;

  const bool zero_target =
    (std::abs(normalized_linear) < kZeroCmdEps) &&
    (std::abs(normalized_angular) < kZeroCmdEps);

  if (zero_target) {
    current_linear_cmd_ = 0.0;
    current_angular_cmd_ = 0.0;
  } else {
    current_linear_cmd_ =
      applyRateLimit(target_linear, current_linear_cmd_, linear_accel_limit_, dt);

    current_angular_cmd_ =
      applyRateLimit(target_angular, current_angular_cmd_, angular_accel_limit_, dt);

    if (std::abs(current_linear_cmd_) < kZeroSnapEps) {
      current_linear_cmd_ = 0.0;
    }

    if (std::abs(current_angular_cmd_) < kZeroSnapEps) {
      current_angular_cmd_ = 0.0;
    }
  }

  const double left_wheel_vel =
    (current_linear_cmd_ - current_angular_cmd_ * wheel_separation_ / 2.0) / wheel_radius_;

  const double right_wheel_vel =
    (current_linear_cmd_ + current_angular_cmd_ * wheel_separation_ / 2.0) / wheel_radius_;

  publishMitSpeedCommand(1, left_wheel_vel);
  publishMitSpeedCommand(2, right_wheel_vel);

  RCLCPP_INFO(
    this->get_logger(),
    "drive profile=%s normalized_linear=%.3f normalized_angular=%.3f "
    "target_linear=%.3f target_angular=%.3f "
    "limited_linear=%.3f limited_angular=%.3f -> left=%.3f right=%.3f "
    "kd=%.3f tau_ff=%.3f",
    current_drive_profile_.c_str(),
    normalized_linear,
    normalized_angular,
    target_linear,
    target_angular,
    current_linear_cmd_,
    current_angular_cmd_,
    left_wheel_vel,
    right_wheel_vel,
    speed_mode_kd_,
    speed_mode_tau_ff_);

  publishDriveFeedback(true, 100, "Drive command accepted and published");
}

int main(int argc, char ** argv)
{
  rclcpp::init(argc, argv);
  rclcpp::spin(std::make_shared<DriveControllerNode>());
  rclcpp::shutdown();
  return 0;
}