#include "robot_drive/bldc_command_bridge_node.hpp"

#include <cmath>
#include <chrono>
#include <vector>


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


// ============================================================
// Constructor
// ============================================================

BldcCommandBridgeNode::BldcCommandBridgeNode()
: Node("bldc_command_bridge_node"),

  velocity_cmds_{0.0, 0.0},
  effort_cmds_{0.0, 0.0},
  position_cmds_rad_{0.0, 0.0},

  left_drive_controller_name_(
    "left_bldc_drive_controller"),

  right_drive_controller_name_(
    "right_bldc_drive_controller"),

  position_controller_name_(
    "bldc_position_controller"),

  current_control_mode_("drive"),

  left_joint_name_("left_wheel_joint"),
  right_joint_name_("right_wheel_joint"),

  bldc_wrap_turns_(12.0),

  bldc_wrap_range_rad_(
    12.0 * 2.0 * M_PI),

  switch_in_progress_(false)
{
  // ==========================================================
  // Parameters
  // ==========================================================

  this->declare_parameter(
    "left_drive_controller_name",
    left_drive_controller_name_);

  this->declare_parameter(
    "right_drive_controller_name",
    right_drive_controller_name_);

  this->declare_parameter(
    "position_controller_name",
    position_controller_name_);

  this->declare_parameter(
    "left_joint_name",
    left_joint_name_);

  this->declare_parameter(
    "right_joint_name",
    right_joint_name_);

  this->declare_parameter(
    "bldc_wrap_turns",
    bldc_wrap_turns_);


  this->get_parameter(
    "left_drive_controller_name",
    left_drive_controller_name_);

  this->get_parameter(
    "right_drive_controller_name",
    right_drive_controller_name_);

  this->get_parameter(
    "position_controller_name",
    position_controller_name_);

  this->get_parameter(
    "left_joint_name",
    left_joint_name_);

  this->get_parameter(
    "right_joint_name",
    right_joint_name_);

  this->get_parameter(
    "bldc_wrap_turns",
    bldc_wrap_turns_);


  bldc_wrap_range_rad_ =
    bldc_wrap_turns_ *
    2.0 *
    M_PI;


  // ==========================================================
  // Subscribers
  // ==========================================================

  speed_cmd_sub_ =
    this->create_subscription<
      robot_msgs::msg::MitCommand>(
      "/bldc_mit_speed_cmd",
      20,
      std::bind(
        &BldcCommandBridgeNode::speedCmdCallback,
        this,
        std::placeholders::_1));


  position_cmd_sub_ =
    this->create_subscription<
      robot_msgs::msg::MitCommand>(
      "/bldc_mit_position_cmd",
      20,
      std::bind(
        &BldcCommandBridgeNode::positionCmdCallback,
        this,
        std::placeholders::_1));


  action_state_sub_ =
    this->create_subscription<
      std_msgs::msg::Int32>(
      "/system/action_state",
      20,
      std::bind(
        &BldcCommandBridgeNode::actionStateCallback,
        this,
        std::placeholders::_1));


  joint_state_sub_ =
    this->create_subscription<
      sensor_msgs::msg::JointState>(
      "/joint_states",
      50,
      std::bind(
        &BldcCommandBridgeNode::jointStateCallback,
        this,
        std::placeholders::_1));


  // ==========================================================
  // Publishers
  //
  // 각 controller의 command:
  //
  // data[0] = velocity
  // data[1] = effort (= MIT tau_ff)
  //
  // YAML의 interface_names 순서를 반드시
  // [velocity, effort]로 설정할 것.
  // ==========================================================

  left_drive_cmd_pub_ =
    this->create_publisher<
      std_msgs::msg::Float64MultiArray>(
      "/" +
      left_drive_controller_name_ +
      "/commands",
      20);


  right_drive_cmd_pub_ =
    this->create_publisher<
      std_msgs::msg::Float64MultiArray>(
      "/" +
      right_drive_controller_name_ +
      "/commands",
      20);


  position_cmd_pub_ =
    this->create_publisher<
      std_msgs::msg::Float64MultiArray>(
      "/" +
      position_controller_name_ +
      "/commands",
      20);


  // ==========================================================
  // Controller manager
  // ==========================================================

  switch_client_ =
    this->create_client<
      controller_manager_msgs::srv::SwitchController>(
      "/controller_manager/switch_controller");


  // ==========================================================
  // Logs
  // ==========================================================

  RCLCPP_INFO(
    this->get_logger(),
    "bldc_command_bridge_node started");


  RCLCPP_INFO(
    this->get_logger(),
    "Drive controllers: left=%s right=%s",
    left_drive_controller_name_.c_str(),
    right_drive_controller_name_.c_str());


  RCLCPP_INFO(
    this->get_logger(),
    "Position controller=%s",
    position_controller_name_.c_str());


  RCLCPP_INFO(
    this->get_logger(),
    "left_joint=%s right_joint=%s "
    "bldc_wrap_turns=%.1f range=%.3f rad",
    left_joint_name_.c_str(),
    right_joint_name_.c_str(),
    bldc_wrap_turns_,
    bldc_wrap_range_rad_);
}


// ============================================================
// Position helpers
// ============================================================

double BldcCommandBridgeNode::wrapToRange(
  double x,
  double range) const
{
  double y =
    std::fmod(
      x,
      range);


  if (y < 0.0) {
    y += range;
  }


  return y;
}


double BldcCommandBridgeNode::shortestWrappedError(
  double current,
  double target,
  double range) const
{
  double err =
    std::fmod(
      target - current,
      range);


  if (
    err >
    range / 2.0)
  {
    err -= range;
  }


  if (
    err <
    -range / 2.0)
  {
    err += range;
  }


  return err;
}


double BldcCommandBridgeNode::nearestEquivalentTarget(
  double current,
  double target_base,
  double range) const
{
  const double wrapped_current =
    wrapToRange(
      current,
      range);


  const double wrapped_target =
    wrapToRange(
      target_base,
      range);


  const double err =
    shortestWrappedError(
      wrapped_current,
      wrapped_target,
      range);


  return
    current +
    err;
}


double BldcCommandBridgeNode::getJointPositionRad(
  const std::string & joint_name,
  bool & ok) const
{
  const auto it =
    joint_position_map_rad_.find(
      joint_name);


  if (
    it ==
    joint_position_map_rad_.end())
  {
    ok = false;
    return 0.0;
  }


  ok = true;

  return it->second;
}


// ============================================================
// Joint states
// ============================================================

void BldcCommandBridgeNode::jointStateCallback(
  const sensor_msgs::msg::JointState::SharedPtr msg)
{
  for (
    std::size_t i = 0;
    i < msg->name.size();
    ++i)
  {
    if (
      i <
      msg->position.size())
    {
      joint_position_map_rad_[
        msg->name[i]] =
        msg->position[i];
    }
  }
}


// ============================================================
// Drive command publish
//
// MultiInterfaceForwardCommandController:
//
// interface_names:
//   - velocity
//   - effort
//
// 따라서:
//
// data[0] = velocity
// data[1] = effort
// ============================================================

void BldcCommandBridgeNode::publishDriveCommands()
{
  // ----------------------------------------------------------
  // LEFT
  // ----------------------------------------------------------

  std_msgs::msg::Float64MultiArray
    left_msg;


  left_msg.data =
  {
    velocity_cmds_[0],
    effort_cmds_[0]
  };


  left_drive_cmd_pub_->publish(
    left_msg);


  // ----------------------------------------------------------
  // RIGHT
  // ----------------------------------------------------------

  std_msgs::msg::Float64MultiArray
    right_msg;


  right_msg.data =
  {
    velocity_cmds_[1],
    effort_cmds_[1]
  };


  right_drive_cmd_pub_->publish(
    right_msg);
}


// ============================================================
// Position command
// ============================================================

void BldcCommandBridgeNode::publishPositionCommands()
{
  std_msgs::msg::Float64MultiArray msg;


  msg.data =
  {
    position_cmds_rad_[0],
    position_cmds_rad_[1]
  };


  position_cmd_pub_->publish(
    msg);
}


// ============================================================
// Controller switch request
// ============================================================

void BldcCommandBridgeNode::requestControllerSwitch(
  const std::vector<std::string> & activate_controllers,
  const std::vector<std::string> & deactivate_controllers)
{
  if (switch_in_progress_)
  {
    RCLCPP_WARN_THROTTLE(
      this->get_logger(),
      *this->get_clock(),
      1000,
      "Controller switch already in progress");

    return;
  }


  if (
    !switch_client_->
    service_is_ready())
  {
    if (
      !switch_client_->
      wait_for_service(
        std::chrono::seconds(2)))
    {
      RCLCPP_WARN(
        this->get_logger(),
        "controller_manager switch service not available");

      return;
    }
  }


  auto req =
    std::make_shared<
      controller_manager_msgs::srv::
        SwitchController::Request>();


  req->activate_controllers =
    activate_controllers;


  req->deactivate_controllers =
    deactivate_controllers;


  // STRICT
  req->strictness = 2;

  req->activate_asap = true;

  req->timeout =
    rclcpp::Duration::
      from_seconds(3.0);


  switch_in_progress_ =
    true;


  switch_client_->async_send_request(
    req,

    [this](
      rclcpp::Client<
        controller_manager_msgs::srv::
          SwitchController>::SharedFuture future)
    {
      try
      {
        const auto resp =
          future.get();


        if (!resp->ok)
        {
          RCLCPP_WARN(
            this->get_logger(),
            "Controller switch rejected");
        }
        else
        {
          RCLCPP_INFO(
            this->get_logger(),
            "Controller switch success");
        }
      }
      catch (
        const std::exception & e)
      {
        RCLCPP_ERROR(
          this->get_logger(),
          "Controller switch future exception: %s",
          e.what());
      }


      switch_in_progress_ =
        false;
    });
}


// ============================================================
// Switch to drive
//
// activate:
//   left drive controller
//   right drive controller
//
// deactivate:
//   position controller
// ============================================================

void BldcCommandBridgeNode::switchToDriveControllers()
{
  if (
    current_control_mode_ ==
    "drive")
  {
    return;
  }


  // controller switching 직전에
  // 안전하게 0 명령부터 시작
  velocity_cmds_[0] = 0.0;
  velocity_cmds_[1] = 0.0;

  effort_cmds_[0] = 0.0;
  effort_cmds_[1] = 0.0;


  requestControllerSwitch(
    {
      left_drive_controller_name_,
      right_drive_controller_name_
    },
    {
      position_controller_name_
    });


  current_control_mode_ =
    "drive";


  publishDriveCommands();


  RCLCPP_INFO(
    this->get_logger(),
    "Requested switch to drive controllers");
}


// ============================================================
// Switch to position
//
// activate:
//   position controller
//
// deactivate:
//   left/right drive controllers
// ============================================================

void BldcCommandBridgeNode::switchToPositionController()
{
  if (
    current_control_mode_ ==
    "position")
  {
    return;
  }


  // drive torque를 먼저 0으로
  velocity_cmds_[0] = 0.0;
  velocity_cmds_[1] = 0.0;

  effort_cmds_[0] = 0.0;
  effort_cmds_[1] = 0.0;

  publishDriveCommands();


  // ----------------------------------------------------------
  // 현재 BLDC 위치를 position controller의
  // 초기 hold target으로 사용
  // ----------------------------------------------------------

  bool ok_left = false;
  bool ok_right = false;


  const double current_left =
    getJointPositionRad(
      left_joint_name_,
      ok_left);


  const double current_right =
    getJointPositionRad(
      right_joint_name_,
      ok_right);


  if (ok_left)
  {
    position_cmds_rad_[0] =
      current_left;
  }


  if (ok_right)
  {
    position_cmds_rad_[1] =
      current_right;
  }


  requestControllerSwitch(
    {
      position_controller_name_
    },
    {
      left_drive_controller_name_,
      right_drive_controller_name_
    });


  current_control_mode_ =
    "position";


  publishPositionCommands();


  RCLCPP_INFO(
    this->get_logger(),
    "Requested switch to position controller "
    "with seeded positions: "
    "left=%.3f right=%.3f",
    position_cmds_rad_[0],
    position_cmds_rad_[1]);
}


// ============================================================
// SPEED / MIT callback
//
// 기존:
//   v_des만 사용
//
// 변경:
//   v_des  -> velocity interface
//   tau_ff -> effort interface
//
// kp/kd는 여기서 전달하지 않음.
// 실제 MIT kd는 system.cpp가 URDF의
// mit_vel_kd=3.0을 사용.
// ============================================================

void BldcCommandBridgeNode::speedCmdCallback(
  const robot_msgs::msg::MitCommand::SharedPtr msg)
{
  if (
    msg->motor_id < 1 ||
    msg->motor_id > 2)
  {
    RCLCPP_WARN(
      this->get_logger(),
      "Invalid motor_id=%d",
      msg->motor_id);

    return;
  }


  if (
    current_control_mode_ !=
    "drive")
  {
    switchToDriveControllers();
  }


  const std::size_t index =
    static_cast<std::size_t>(
      msg->motor_id - 1);


  // ==========================================================
  // 핵심
  // ==========================================================

  velocity_cmds_[index] =
    msg->v_des;


  effort_cmds_[index] =
    msg->tau_ff;


  // 좌/우의 마지막 명령을 함께 재전송
  publishDriveCommands();


  RCLCPP_INFO_THROTTLE(
    this->get_logger(),
    *this->get_clock(),
    500,
    "Drive command motor=%d "
    "v_des=%.3f rad/s "
    "tau_ff=%.3f Nm",
    msg->motor_id,
    msg->v_des,
    msg->tau_ff);
}


// ============================================================
// POSITION callback
// ============================================================

void BldcCommandBridgeNode::positionCmdCallback(
  const robot_msgs::msg::MitCommand::SharedPtr msg)
{
  if (
    msg->motor_id < 1 ||
    msg->motor_id > 2)
  {
    return;
  }


  if (
    current_control_mode_ !=
    "position")
  {
    switchToPositionController();
  }


  const double target_rad =
    degToRad(
      msg->p_des);


  if (
    msg->motor_id == 1)
  {
    position_cmds_rad_[0] =
      target_rad;


    RCLCPP_INFO_THROTTLE(
      this->get_logger(),
      *this->get_clock(),
      500,
      "BLDC position motor=1 "
      "raw_target_deg=%.2f "
      "target_rad=%.3f "
      "hold_motor2=%.3f",
      msg->p_des,
      target_rad,
      position_cmds_rad_[1]);
  }
  else
  {
    position_cmds_rad_[1] =
      target_rad;


    RCLCPP_INFO_THROTTLE(
      this->get_logger(),
      *this->get_clock(),
      500,
      "BLDC position motor=2 "
      "raw_target_deg=%.2f "
      "target_rad=%.3f "
      "hold_motor1=%.3f",
      msg->p_des,
      target_rad,
      position_cmds_rad_[0]);
  }


  publishPositionCommands();
}


// ============================================================
// System state
// ============================================================

void BldcCommandBridgeNode::actionStateCallback(
  const std_msgs::msg::Int32::SharedPtr msg)
{
  // ----------------------------------------------------------
  // Normal drive
  // ----------------------------------------------------------

  if (
    msg->data ==
    DRIVE)
  {
    switchToDriveControllers();

    return;
  }


  // ----------------------------------------------------------
  // 현재 구조에서는 transform BLDC도
  // speed command를 사용하므로 drive controllers 유지
  // ----------------------------------------------------------

  if (
    msg->data ==
    TRANSFORM ||
    msg->data ==
    TRANSFORM_PAUSED)
  {
    switchToDriveControllers();

    return;
  }


  // ----------------------------------------------------------
  // IDLE
  //
  // 속도와 추가 torque 모두 0
  // ----------------------------------------------------------

  if (
    msg->data ==
    IDLE)
  {
    velocity_cmds_[0] = 0.0;
    velocity_cmds_[1] = 0.0;

    effort_cmds_[0] = 0.0;
    effort_cmds_[1] = 0.0;


    if (
      current_control_mode_ ==
      "drive")
    {
      publishDriveCommands();
    }


    return;
  }
}


// ============================================================
// MAIN
// ============================================================

int main(
  int argc,
  char ** argv)
{
  rclcpp::init(
    argc,
    argv);


  rclcpp::spin(
    std::make_shared<
      BldcCommandBridgeNode>());


  rclcpp::shutdown();


  return 0;
}
