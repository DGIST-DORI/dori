#include <algorithm>
#include <chrono>
#include <cmath>
#include <memory>
#include <string>

#include "rclcpp/rclcpp.hpp"
#include "geometry_msgs/msg/twist.hpp"
#include "sensor_msgs/msg/joint_state.hpp"
#include "std_msgs/msg/float64.hpp"
#include "std_msgs/msg/int32.hpp"
#include "std_msgs/msg/string.hpp"
#include "robot_msgs/msg/command_feedback.hpp"
#include "robot_msgs/msg/mit_command.hpp"

namespace {
constexpr double kEps = 1e-6;
constexpr double kCmdMin = -1.0;
constexpr double kCmdMax = 1.0;
constexpr int TF_RUNNING = 1;
constexpr int TF_PAUSED = 2;
}

class DriveControllerNode : public rclcpp::Node
{
public:
  DriveControllerNode() : Node("drive_controller_node")
  {
    wheel_radius_ = declare_parameter<double>("wheel_radius", 0.234);
    wheel_separation_ = declare_parameter<double>("wheel_separation", 0.184);
    max_linear_velocity_ = declare_parameter<double>("max_linear_velocity", 1.72);
    max_angular_velocity_ = declare_parameter<double>("max_angular_velocity", 7.0);

    linear_accel_limit_ = declare_parameter<double>("linear_accel_limit", 0.5);
    linear_decel_limit_ = declare_parameter<double>("linear_decel_limit", 0.3);
    angular_accel_limit_ = declare_parameter<double>("angular_accel_limit", 1.0);
    angular_decel_limit_ = declare_parameter<double>("angular_decel_limit", 1.0);

    feedforward_enabled_ = declare_parameter<bool>("feedforward_enabled", true);
    feedforward_gain_ = declare_parameter<double>("feedforward_gain", 4.0);
    feedforward_torque_limit_ = declare_parameter<double>("feedforward_torque_limit", 6.0);
    feedforward_accel_deadband_ = declare_parameter<double>("feedforward_accel_deadband", 0.02);
    final_torque_limit_ = declare_parameter<double>("final_torque_limit", 15.0);

    drive_normal_vel_kd_ = declare_parameter<double>("drive_normal_vel_kd", 1.5);
    drive_normal_tau_ff_ = declare_parameter<double>("drive_normal_tau_ff", 0.0);
    drive_slope_vel_kd_ = declare_parameter<double>("drive_slope_vel_kd", 2.0);
    drive_slope_tau_ff_ = declare_parameter<double>("drive_slope_tau_ff", 0.2);
    drive_obstacle_vel_kd_ = declare_parameter<double>("drive_obstacle_vel_kd", 2.5);
    drive_obstacle_tau_ff_ = declare_parameter<double>("drive_obstacle_tau_ff", 0.3);
    current_drive_profile_ = declare_parameter<std::string>("default_drive_profile", "normal");

    stabilization_torque_limit_ = declare_parameter<double>("stabilization_torque_limit", 13.0);
    stabilization_timeout_sec_ = declare_parameter<double>("stabilization_timeout_sec", 0.10);
    left_joint_name_ = declare_parameter<std::string>("left_joint_name", "left_wheel_joint");
    right_joint_name_ = declare_parameter<std::string>("right_joint_name", "right_wheel_joint");
    joint_state_timeout_sec_ = declare_parameter<double>("joint_state_timeout_sec", 0.20);
    control_frequency_hz_ = declare_parameter<double>("control_frequency_hz", 100.0);

    if (wheel_radius_ <= kEps) wheel_radius_ = 0.234;
    if (wheel_separation_ <= kEps) wheel_separation_ = 0.184;
    if (control_frequency_hz_ <= kEps) control_frequency_hz_ = 100.0;
    feedforward_torque_limit_ = std::abs(feedforward_torque_limit_);
    final_torque_limit_ = std::abs(final_torque_limit_);
    stabilization_torque_limit_ = std::abs(stabilization_torque_limit_);

    applyDriveProfile(current_drive_profile_);

    drive_cmd_sub_ = create_subscription<geometry_msgs::msg::Twist>(
      "/drive/cmd_vel", 20,
      std::bind(&DriveControllerNode::driveCmdCallback, this, std::placeholders::_1));
    drive_profile_sub_ = create_subscription<std_msgs::msg::String>(
      "/drive/profile_cmd", 20,
      std::bind(&DriveControllerNode::driveProfileCallback, this, std::placeholders::_1));
    transform_status_sub_ = create_subscription<std_msgs::msg::Int32>(
      "/transform/status", 20,
      std::bind(&DriveControllerNode::transformStatusCallback, this, std::placeholders::_1));
    stabilization_torque_sub_ = create_subscription<std_msgs::msg::Float64>(
      "/body/stabilization_torque", 50,
      std::bind(&DriveControllerNode::stabilizationTorqueCallback, this, std::placeholders::_1));
    joint_state_sub_ = create_subscription<sensor_msgs::msg::JointState>(
      "/joint_states", 50,
      std::bind(&DriveControllerNode::jointStateCallback, this, std::placeholders::_1));

    mit_speed_pub_ = create_publisher<robot_msgs::msg::MitCommand>("/bldc_mit_speed_cmd", 20);
    drive_feedback_pub_ = create_publisher<robot_msgs::msg::CommandFeedback>("/drive/command_feedback", 20);
    command_linear_accel_pub_ = create_publisher<std_msgs::msg::Float64>("/drive/command_linear_accel", 20);
    feedforward_torque_pub_ = create_publisher<std_msgs::msg::Float64>("/body/feedforward_torque", 20);
    target_linear_debug_pub_ = create_publisher<std_msgs::msg::Float64>("/drive/debug/target_linear", 20);
    current_linear_debug_pub_ = create_publisher<std_msgs::msg::Float64>("/drive/debug/current_linear", 20);
    current_angular_debug_pub_ = create_publisher<std_msgs::msg::Float64>("/drive/debug/current_angular", 20);
    actual_linear_debug_pub_ = create_publisher<std_msgs::msg::Float64>("/drive/debug/actual_linear", 20);
    left_v_des_debug_pub_ = create_publisher<std_msgs::msg::Float64>("/drive/debug/left_v_des", 20);
    right_v_des_debug_pub_ = create_publisher<std_msgs::msg::Float64>("/drive/debug/right_v_des", 20);
    active_pd_debug_pub_ = create_publisher<std_msgs::msg::Float64>("/drive/debug/active_pd_torque", 20);
    left_final_torque_debug_pub_ = create_publisher<std_msgs::msg::Float64>("/drive/debug/left_final_torque", 20);
    right_final_torque_debug_pub_ = create_publisher<std_msgs::msg::Float64>("/drive/debug/right_final_torque", 20);

    auto now = this->now();
    last_control_time_ = now;
    last_stabilization_time_ = now;
    last_joint_state_time_ = now;

    auto period = std::chrono::duration<double>(1.0 / control_frequency_hz_);
    control_timer_ = create_wall_timer(
      std::chrono::duration_cast<std::chrono::nanoseconds>(period),
      std::bind(&DriveControllerNode::controlLoopCallback, this));

    RCLCPP_INFO(get_logger(), "MIT SPEED ROLLBACK CONTROLLER STARTED");
    RCLCPP_INFO(get_logger(), "R=%.3f L=%.3f vmax=%.2f wmax=%.2f Kd=%.2f",
      wheel_radius_, wheel_separation_, max_linear_velocity_, max_angular_velocity_, speed_mode_kd_);
  }

private:
  double clamp(double x, double lo, double hi) const { return std::max(lo, std::min(x, hi)); }

  double applyAccelDecelLimit(double target, double current, double accel, double decel, double dt) const
  {
    double limit = accel;
    if (target * current < 0.0 || std::abs(target) < std::abs(current)) limit = decel;
    const double max_delta = std::max(limit, 0.01) * dt;
    return current + clamp(target - current, -max_delta, max_delta);
  }

  void applyDriveProfile(const std::string & p)
  {
    if (p == "slope") { speed_mode_kd_ = drive_slope_vel_kd_; speed_mode_tau_ff_ = drive_slope_tau_ff_; current_drive_profile_ = p; }
    else if (p == "obstacle") { speed_mode_kd_ = drive_obstacle_vel_kd_; speed_mode_tau_ff_ = drive_obstacle_tau_ff_; current_drive_profile_ = p; }
    else { speed_mode_kd_ = drive_normal_vel_kd_; speed_mode_tau_ff_ = drive_normal_tau_ff_; current_drive_profile_ = "normal"; }
  }

  void driveProfileCallback(const std_msgs::msg::String::SharedPtr msg) { applyDriveProfile(msg->data); }

  void driveCmdCallback(const geometry_msgs::msg::Twist::SharedPtr msg)
  {
    if (transform_active_) { target_linear_cmd_ = 0.0; target_angular_cmd_ = 0.0; publishFeedback(false, 210, "Drive ignored during transform"); return; }
    target_linear_cmd_ = clamp(msg->linear.x, kCmdMin, kCmdMax) * max_linear_velocity_;
    target_angular_cmd_ = clamp(msg->angular.z, kCmdMin, kCmdMax) * max_angular_velocity_;
    if (std::abs(msg->linear.x) < kEps) target_linear_cmd_ = 0.0;
    if (std::abs(msg->angular.z) < kEps) target_angular_cmd_ = 0.0;
    publishFeedback(true, 100, "Drive target accepted");
  }

  void transformStatusCallback(const std_msgs::msg::Int32::SharedPtr msg)
  {
    transform_active_ = (msg->data == TF_RUNNING || msg->data == TF_PAUSED);
    if (transform_active_) {
      target_linear_cmd_ = target_angular_cmd_ = 0.0;
      current_linear_cmd_ = current_angular_cmd_ = 0.0;
      publishMit(1, 0.0, 0.0, 0.0);
      publishMit(2, 0.0, 0.0, 0.0);
    }
  }

  void stabilizationTorqueCallback(const std_msgs::msg::Float64::SharedPtr msg)
  {
    stabilization_torque_ = clamp(msg->data, -stabilization_torque_limit_, stabilization_torque_limit_);
    stabilization_received_ = true;
    last_stabilization_time_ = this->now();
  }

  void jointStateCallback(const sensor_msgs::msg::JointState::SharedPtr msg)
  {
    const std::size_t n = std::min(msg->name.size(), msg->velocity.size());
    bool got = false;
    for (std::size_t i = 0; i < n; ++i) {
      if (msg->name[i] == left_joint_name_) { left_actual_velocity_ = msg->velocity[i]; left_velocity_received_ = true; got = true; }
      if (msg->name[i] == right_joint_name_) { right_actual_velocity_ = msg->velocity[i]; right_velocity_received_ = true; got = true; }
    }
    if (got) last_joint_state_time_ = this->now();
  }

  void publishFeedback(bool accepted, int code, const std::string & message)
  {
    robot_msgs::msg::CommandFeedback fb;
    fb.source_node = "drive_controller_node";
    fb.command_type = "drive";
    fb.accepted = accepted;
    fb.code = code;
    fb.message = message;
    drive_feedback_pub_->publish(fb);
  }

  void pubScalar(const rclcpp::Publisher<std_msgs::msg::Float64>::SharedPtr & pub, double x)
  {
    std_msgs::msg::Float64 m; m.data = x; pub->publish(m);
  }

  void publishMit(int motor_id, double v_des, double ff_tau, double pd_tau)
  {
    robot_msgs::msg::MitCommand msg;
    msg.motor_id = motor_id;
    msg.p_des = 0.0;
    msg.v_des = v_des;
    msg.kp = 0.0;
    msg.kd = speed_mode_kd_;

    double profile_tau = 0.0;
    if (std::abs(v_des) > 0.05) profile_tau = (v_des > 0.0) ? speed_mode_tau_ff_ : -speed_mode_tau_ff_;
    const double final_tau = clamp(profile_tau + ff_tau + pd_tau, -final_torque_limit_, final_torque_limit_);
    msg.tau_ff = final_tau;
    mit_speed_pub_->publish(msg);

    if (motor_id == 1) pubScalar(left_final_torque_debug_pub_, final_tau);
    else if (motor_id == 2) pubScalar(right_final_torque_debug_pub_, final_tau);
  }

  void controlLoopCallback()
  {
    if (transform_active_) return;
    const auto now = this->now();
    double dt = (now - last_control_time_).seconds();
    last_control_time_ = now;
    const double nominal = 1.0 / control_frequency_hz_;
    if (dt <= 0.0 || dt > nominal * 5.0) dt = nominal;

    const double old_linear = current_linear_cmd_;
    current_linear_cmd_ = applyAccelDecelLimit(target_linear_cmd_, current_linear_cmd_, linear_accel_limit_, linear_decel_limit_, dt);
    current_angular_cmd_ = applyAccelDecelLimit(target_angular_cmd_, current_angular_cmd_, angular_accel_limit_, angular_decel_limit_, dt);

    command_linear_accel_ = (current_linear_cmd_ - old_linear) / std::max(dt, 1e-4);
    double ff_tau = 0.0;
    if (feedforward_enabled_ && std::abs(command_linear_accel_) >= feedforward_accel_deadband_) {
      ff_tau = clamp(feedforward_gain_ * command_linear_accel_, -feedforward_torque_limit_, feedforward_torque_limit_);
    }

    double pd_tau = 0.0;
    if (stabilization_received_ && (now - last_stabilization_time_).seconds() <= stabilization_timeout_sec_) pd_tau = stabilization_torque_;

    const double left_v_des = (current_linear_cmd_ - current_angular_cmd_ * wheel_separation_ / 2.0) / wheel_radius_;
    const double right_v_des = (current_linear_cmd_ + current_angular_cmd_ * wheel_separation_ / 2.0) / wheel_radius_;

    double actual_linear = 0.0;
    if ((now - last_joint_state_time_).seconds() <= joint_state_timeout_sec_ && left_velocity_received_ && right_velocity_received_) {
      actual_linear = wheel_radius_ * (left_actual_velocity_ + right_actual_velocity_) / 2.0;
    }

    publishMit(1, left_v_des, ff_tau, pd_tau);
    publishMit(2, right_v_des, ff_tau, pd_tau);

    pubScalar(command_linear_accel_pub_, command_linear_accel_);
    pubScalar(feedforward_torque_pub_, ff_tau);
    pubScalar(target_linear_debug_pub_, target_linear_cmd_);
    pubScalar(current_linear_debug_pub_, current_linear_cmd_);
    pubScalar(current_angular_debug_pub_, current_angular_cmd_);
    pubScalar(actual_linear_debug_pub_, actual_linear);
    pubScalar(left_v_des_debug_pub_, left_v_des);
    pubScalar(right_v_des_debug_pub_, right_v_des);
    pubScalar(active_pd_debug_pub_, pd_tau);
  }

  double wheel_radius_{0.234}, wheel_separation_{0.184};
  double max_linear_velocity_{1.72}, max_angular_velocity_{7.0};
  double linear_accel_limit_{0.5}, linear_decel_limit_{0.3};
  double angular_accel_limit_{1.0}, angular_decel_limit_{1.0};
  bool feedforward_enabled_{true};
  double feedforward_gain_{4.0}, feedforward_torque_limit_{6.0}, feedforward_accel_deadband_{0.02};
  double final_torque_limit_{15.0};
  double speed_mode_kd_{1.5}, speed_mode_tau_ff_{0.0};
  double drive_normal_vel_kd_{1.5}, drive_normal_tau_ff_{0.0};
  double drive_slope_vel_kd_{2.0}, drive_slope_tau_ff_{0.2};
  double drive_obstacle_vel_kd_{2.5}, drive_obstacle_tau_ff_{0.3};
  std::string current_drive_profile_{"normal"};
  double stabilization_torque_{0.0}, stabilization_torque_limit_{13.0}, stabilization_timeout_sec_{0.10};
  bool stabilization_received_{false};
  std::string left_joint_name_{"left_wheel_joint"}, right_joint_name_{"right_wheel_joint"};
  double left_actual_velocity_{0.0}, right_actual_velocity_{0.0};
  bool left_velocity_received_{false}, right_velocity_received_{false};
  double joint_state_timeout_sec_{0.20};
  double target_linear_cmd_{0.0}, target_angular_cmd_{0.0};
  double current_linear_cmd_{0.0}, current_angular_cmd_{0.0};
  double command_linear_accel_{0.0};
  bool transform_active_{false};
  double control_frequency_hz_{100.0};
  rclcpp::Time last_control_time_, last_stabilization_time_, last_joint_state_time_;

  rclcpp::Subscription<geometry_msgs::msg::Twist>::SharedPtr drive_cmd_sub_;
  rclcpp::Subscription<std_msgs::msg::String>::SharedPtr drive_profile_sub_;
  rclcpp::Subscription<std_msgs::msg::Int32>::SharedPtr transform_status_sub_;
  rclcpp::Subscription<std_msgs::msg::Float64>::SharedPtr stabilization_torque_sub_;
  rclcpp::Subscription<sensor_msgs::msg::JointState>::SharedPtr joint_state_sub_;
  rclcpp::Publisher<robot_msgs::msg::MitCommand>::SharedPtr mit_speed_pub_;
  rclcpp::Publisher<robot_msgs::msg::CommandFeedback>::SharedPtr drive_feedback_pub_;
  rclcpp::Publisher<std_msgs::msg::Float64>::SharedPtr command_linear_accel_pub_, feedforward_torque_pub_;
  rclcpp::Publisher<std_msgs::msg::Float64>::SharedPtr target_linear_debug_pub_, current_linear_debug_pub_, current_angular_debug_pub_;
  rclcpp::Publisher<std_msgs::msg::Float64>::SharedPtr actual_linear_debug_pub_, left_v_des_debug_pub_, right_v_des_debug_pub_;
  rclcpp::Publisher<std_msgs::msg::Float64>::SharedPtr active_pd_debug_pub_, left_final_torque_debug_pub_, right_final_torque_debug_pub_;
  rclcpp::TimerBase::SharedPtr control_timer_;
};

int main(int argc, char ** argv)
{
  rclcpp::init(argc, argv);
  rclcpp::spin(std::make_shared<DriveControllerNode>());
  rclcpp::shutdown();
  return 0;
}
