#include "robot_drive/bldc_command_bridge_node.hpp"

#include <cmath>
#include <chrono>

namespace
{
constexpr int IDLE = 0;
constexpr int DRIVE = 1;
constexpr int TRANSFORM = 2;
constexpr int TRANSFORM_PAUSED = 3;

double degToRad(double deg)
{
  return deg * M_PI / 180.0;
}
}  // namespace

BldcCommandBridgeNode::BldcCommandBridgeNode()
: Node("bldc_command_bridge_node"),
  velocity_cmds_{0.0, 0.0},
  position_cmds_rad_{0.0, 0.0},
  velocity_controller_name_("bldc_velocity_controller"),
  position_controller_name_("bldc_position_controller"),
  current_active_controller_("bldc_velocity_controller"),
  left_joint_name_("left_wheel_joint"),
  right_joint_name_("right_wheel_joint"),
  bldc_wrap_turns_(12.0),
  bldc_wrap_range_rad_(12.0 * 2.0 * M_PI)
{
  this->declare_parameter("velocity_controller_name", velocity_controller_name_);
  this->declare_parameter("position_controller_name", position_controller_name_);
  this->declare_parameter("left_joint_name", left_joint_name_);
  this->declare_parameter("right_joint_name", right_joint_name_);
  this->declare_parameter("bldc_wrap_turns", bldc_wrap_turns_);

  this->get_parameter("velocity_controller_name", velocity_controller_name_);
  this->get_parameter("position_controller_name", position_controller_name_);
  this->get_parameter("left_joint_name", left_joint_name_);
  this->get_parameter("right_joint_name", right_joint_name_);
  this->get_parameter("bldc_wrap_turns", bldc_wrap_turns_);

  bldc_wrap_range_rad_ = bldc_wrap_turns_ * 2.0 * M_PI;

  current_active_controller_ = velocity_controller_name_;

  speed_cmd_sub_ = this->create_subscription<robot_msgs::msg::MitCommand>(
    "/bldc_mit_speed_cmd", 20,
    std::bind(&BldcCommandBridgeNode::speedCmdCallback, this, std::placeholders::_1));

  position_cmd_sub_ = this->create_subscription<robot_msgs::msg::MitCommand>(
    "/bldc_mit_position_cmd", 20,
    std::bind(&BldcCommandBridgeNode::positionCmdCallback, this, std::placeholders::_1));

  action_state_sub_ = this->create_subscription<std_msgs::msg::Int32>(
    "/system/action_state", 20,
    std::bind(&BldcCommandBridgeNode::actionStateCallback, this, std::placeholders::_1));

  joint_state_sub_ = this->create_subscription<sensor_msgs::msg::JointState>(
    "/joint_states", 50,
    std::bind(&BldcCommandBridgeNode::jointStateCallback, this, std::placeholders::_1));

  velocity_cmd_pub_ = this->create_publisher<std_msgs::msg::Float64MultiArray>(
    "/" + velocity_controller_name_ + "/commands", 20);

  position_cmd_pub_ = this->create_publisher<std_msgs::msg::Float64MultiArray>(
    "/" + position_controller_name_ + "/commands", 20);

  switch_client_ =
    this->create_client<controller_manager_msgs::srv::SwitchController>(
      "/controller_manager/switch_controller");

  RCLCPP_INFO(this->get_logger(), "bldc_command_bridge_node started");
  RCLCPP_INFO(
    this->get_logger(),
    "velocity_controller=%s position_controller=%s",
    velocity_controller_name_.c_str(),
    position_controller_name_.c_str());
  RCLCPP_INFO(
    this->get_logger(),
    "left_joint=%s right_joint=%s bldc_wrap_turns=%.1f range=%.3f rad",
    left_joint_name_.c_str(),
    right_joint_name_.c_str(),
    bldc_wrap_turns_,
    bldc_wrap_range_rad_);
  RCLCPP_INFO(
    this->get_logger(),
    "initial active controller assumption=%s",
    current_active_controller_.c_str());
}

double BldcCommandBridgeNode::wrapToRange(double x, double range) const
{
  double y = std::fmod(x, range);
  if (y < 0.0) {
    y += range;
  }
  return y;
}

double BldcCommandBridgeNode::shortestWrappedError(double current, double target, double range) const
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

double BldcCommandBridgeNode::nearestEquivalentTarget(
  double current,
  double target_base,
  double range) const
{
  const double wrapped_current = wrapToRange(current, range);
  const double wrapped_target = wrapToRange(target_base, range);
  const double err = shortestWrappedError(wrapped_current, wrapped_target, range);
  return current + err;
}

double BldcCommandBridgeNode::getJointPositionRad(
  const std::string & joint_name,
  bool & ok) const
{
  const auto it = joint_position_map_rad_.find(joint_name);
  if (it == joint_position_map_rad_.end()) {
    ok = false;
    return 0.0;
  }

  ok = true;
  return it->second;
}

void BldcCommandBridgeNode::jointStateCallback(
  const sensor_msgs::msg::JointState::SharedPtr msg)
{
  for (std::size_t i = 0; i < msg->name.size(); ++i) {
    if (i < msg->position.size()) {
      joint_position_map_rad_[msg->name[i]] = msg->position[i];
    }
  }
}

void BldcCommandBridgeNode::publishVelocityCommands()
{
  std_msgs::msg::Float64MultiArray msg;
  msg.data = {velocity_cmds_[0], velocity_cmds_[1]};
  velocity_cmd_pub_->publish(msg);
}

void BldcCommandBridgeNode::publishPositionCommands()
{
  std_msgs::msg::Float64MultiArray msg;
  msg.data = {position_cmds_rad_[0], position_cmds_rad_[1]};
  position_cmd_pub_->publish(msg);
}

void BldcCommandBridgeNode::requestControllerSwitch(
  const std::string & activate_controller,
  const std::string & deactivate_controller)
{
  if (!switch_client_->service_is_ready()) {
    if (!switch_client_->wait_for_service(std::chrono::seconds(2))) {
      RCLCPP_WARN(this->get_logger(), "controller_manager switch service not available");
      return;
    }
  }

  auto req = std::make_shared<controller_manager_msgs::srv::SwitchController::Request>();
  req->activate_controllers.push_back(activate_controller);
  req->deactivate_controllers.push_back(deactivate_controller);
  req->strictness = 2;
  req->activate_asap = true;
  req->timeout = rclcpp::Duration::from_seconds(3.0);

  switch_client_->async_send_request(
    req,
    [this, activate_controller, deactivate_controller](
      rclcpp::Client<controller_manager_msgs::srv::SwitchController>::SharedFuture future)
    {
      try {
        const auto resp = future.get();
        if (!resp->ok) {
          RCLCPP_WARN(
            this->get_logger(),
            "Controller switch rejected: activate=%s deactivate=%s",
            activate_controller.c_str(), deactivate_controller.c_str());
          return;
        }

        RCLCPP_INFO(
          this->get_logger(),
          "Controller switch success: activate=%s deactivate=%s",
          activate_controller.c_str(), deactivate_controller.c_str());
      } catch (const std::exception & e) {
        RCLCPP_ERROR(
          this->get_logger(),
          "Controller switch future exception: %s",
          e.what());
      }
    });
}

void BldcCommandBridgeNode::switchToVelocityController()
{
  if (current_active_controller_ == velocity_controller_name_) {
    return;
  }

  requestControllerSwitch(velocity_controller_name_, position_controller_name_);
  current_active_controller_ = velocity_controller_name_;
  RCLCPP_INFO(this->get_logger(), "Requested switch to velocity controller");
}

void BldcCommandBridgeNode::switchToPositionController()
{
  if (current_active_controller_ == position_controller_name_) {
    return;
  }

  bool ok_left = false;
  bool ok_right = false;
  const double current_left = getJointPositionRad(left_joint_name_, ok_left);
  const double current_right = getJointPositionRad(right_joint_name_, ok_right);

  if (ok_left) {
    position_cmds_rad_[0] = current_left;
  }
  if (ok_right) {
    position_cmds_rad_[1] = current_right;
  }

  requestControllerSwitch(position_controller_name_, velocity_controller_name_);
  current_active_controller_ = position_controller_name_;

  publishPositionCommands();

  RCLCPP_INFO(
    this->get_logger(),
    "Requested switch to position controller with seeded hold positions: left=%.3f right=%.3f",
    position_cmds_rad_[0], position_cmds_rad_[1]);
}

void BldcCommandBridgeNode::speedCmdCallback(
  const robot_msgs::msg::MitCommand::SharedPtr msg)
{
  if (msg->motor_id < 1 || msg->motor_id > 2) {
    return;
  }

  velocity_cmds_[msg->motor_id - 1] = msg->v_des;
  publishVelocityCommands();

  RCLCPP_INFO(
    this->get_logger(),
    "Published velocity cmd motor=%d v_des=%.3f active_controller=%s",
    msg->motor_id, msg->v_des, current_active_controller_.c_str());
}

void BldcCommandBridgeNode::positionCmdCallback(
  const robot_msgs::msg::MitCommand::SharedPtr msg)
{
  if (msg->motor_id < 1 || msg->motor_id > 2) {
    return;
  }

  // transform_controller가 이미 raw target(deg)을 계산해서 보내므로
  // bridge는 추가 해석 없이 그대로 rad로만 바꿔서 전달한다.
  const double target_rad = degToRad(msg->p_des);

  if (msg->motor_id == 1) {
    position_cmds_rad_[0] = target_rad;
    RCLCPP_INFO(
      this->get_logger(),
      "BLDC position bridge motor=1 raw_target_deg=%.2f target_rad=%.3f hold_motor2=%.3f",
      msg->p_des, target_rad, position_cmds_rad_[1]);
  } else {
    position_cmds_rad_[1] = target_rad;
    RCLCPP_INFO(
      this->get_logger(),
      "BLDC position bridge motor=2 raw_target_deg=%.2f target_rad=%.3f hold_motor1=%.3f",
      msg->p_des, target_rad, position_cmds_rad_[0]);
  }

  publishPositionCommands();
}

void BldcCommandBridgeNode::actionStateCallback(
  const std_msgs::msg::Int32::SharedPtr msg)
{
  if (msg->data == DRIVE) {
    switchToVelocityController();
    return;
  }

  if (msg->data == TRANSFORM || msg->data == TRANSFORM_PAUSED) {
    switchToPositionController();
    return;
  }
}

int main(int argc, char ** argv)
{
  rclcpp::init(argc, argv);
  rclcpp::spin(std::make_shared<BldcCommandBridgeNode>());
  rclcpp::shutdown();
  return 0;
}
