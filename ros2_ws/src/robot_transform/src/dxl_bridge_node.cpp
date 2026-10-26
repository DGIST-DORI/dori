#include "robot_transform/dxl_bridge_node.hpp"

#include <algorithm>
#include <cmath>

DxlBridgeNode::DxlBridgeNode()
: Node("dxl_bridge_node"),
  logical_motor3_dxl_id_(1),
  logical_motor4_dxl_id_(2),
  logical_motor5_dxl_id_(3),
  dxl_position_min_(0),
  dxl_position_max_(4095)
{
  this->declare_parameter("logical_motor3_dxl_id", logical_motor3_dxl_id_);
  this->declare_parameter("logical_motor4_dxl_id", logical_motor4_dxl_id_);
  this->declare_parameter("logical_motor5_dxl_id", logical_motor5_dxl_id_);
  this->declare_parameter("dxl_position_min", dxl_position_min_);
  this->declare_parameter("dxl_position_max", dxl_position_max_);

  this->get_parameter("logical_motor3_dxl_id", logical_motor3_dxl_id_);
  this->get_parameter("logical_motor4_dxl_id", logical_motor4_dxl_id_);
  this->get_parameter("logical_motor5_dxl_id", logical_motor5_dxl_id_);
  this->get_parameter("dxl_position_min", dxl_position_min_);
  this->get_parameter("dxl_position_max", dxl_position_max_);

  dxl_cmd_sub_ = this->create_subscription<std_msgs::msg::Float64MultiArray>(
    "/dxl_position_cmd", 20,
    std::bind(&DxlBridgeNode::dxlCmdCallback, this, std::placeholders::_1));

  set_position_pub_ =
    this->create_publisher<dynamixel_sdk_custom_interfaces::msg::SetPosition>("/set_position", 20);

  stop_pub_ = create_publisher<dynamixel_sdk_custom_interfaces::msg::SetPosition>(
    "/stop_position", 20);
  stop_sub_ = create_subscription<std_msgs::msg::Int32>("/dxl_stop_cmd", 20,
    [this](const std_msgs::msg::Int32::SharedPtr msg) {
      const int id = logicalMotorToDxlId(msg->data);
      if (id < 0) { return; }
      dynamixel_sdk_custom_interfaces::msg::SetPosition stop;
      stop.id = id;
      stop_pub_->publish(stop);
    });
  RCLCPP_INFO(this->get_logger(), "dxl_bridge_node started");
  RCLCPP_INFO(
    this->get_logger(),
    "logical motor 3 -> dxl id %d, logical motor 4 -> dxl id %d",
    logical_motor3_dxl_id_, logical_motor4_dxl_id_);
}

int DxlBridgeNode::logicalMotorToDxlId(int logical_motor_id) const
{
  if (logical_motor_id == 3) {
    return logical_motor3_dxl_id_;
  }
  if (logical_motor_id == 4) {
    return logical_motor4_dxl_id_;
  }
  if (logical_motor_id == 5) {
    return logical_motor5_dxl_id_;
  }
  return -1;
}

int DxlBridgeNode::degreeToPositionValue(double target_deg) const
{
  return static_cast<int>(std::lround(target_deg * 4096.0 / 360.0));
}

void DxlBridgeNode::dxlCmdCallback(const std_msgs::msg::Float64MultiArray::SharedPtr msg)
{
  if (msg->data.size() < 2) {
    RCLCPP_WARN(this->get_logger(), "Received /dxl_position_cmd with insufficient data");
    return;
  }

  if (!std::isfinite(msg->data[0]) || msg->data[0] < 3 || msg->data[0] > 5 ||
    std::floor(msg->data[0]) != msg->data[0] || !std::isfinite(msg->data[1])) {
    RCLCPP_ERROR(get_logger(), "Invalid DXL motor ID or target");
    return;
  }
  const int logical_motor_id = static_cast<int>(msg->data[0]);
  const double target_deg = msg->data[1];

  const int dxl_id = logicalMotorToDxlId(logical_motor_id);
  if (dxl_id < 0) {
    RCLCPP_WARN(
      this->get_logger(),
      "Unsupported logical motor id for DXL bridge: %d",
      logical_motor_id);
    return;
  }

  const double raw = target_deg * 4096.0 / 360.0;
  const int minimum = logical_motor_id == 5 ? dxl_position_min_ : -1048575;
  const int maximum = logical_motor_id == 5 ? dxl_position_max_ : 1048575;
  if (raw < minimum || raw > maximum) {
    RCLCPP_ERROR(get_logger(), "DXL target out of range: motor=%d target=%.3f",
      logical_motor_id, target_deg);
    return;
  }
  const int position_value = degreeToPositionValue(target_deg);

  dynamixel_sdk_custom_interfaces::msg::SetPosition out;
  out.id = static_cast<uint8_t>(dxl_id);
  out.position = position_value;
  set_position_pub_->publish(out);

  RCLCPP_INFO(
    this->get_logger(),
    "DXL bridge: logical motor %d -> dxl id %d, %.2f deg -> position %d",
    logical_motor_id, dxl_id, target_deg, position_value);
}

int main(int argc, char ** argv)
{
  rclcpp::init(argc, argv);
  rclcpp::spin(std::make_shared<DxlBridgeNode>());
  rclcpp::shutdown();
  return 0;
}
