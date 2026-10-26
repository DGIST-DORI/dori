#include "robot_transform/dxl_state_publisher_node.hpp"
#include <cmath>
#include <limits>
using namespace std::chrono_literals;

DxlStatePublisherNode::DxlStatePublisherNode()
: Node("dxl_state_publisher_node"), joint_pos_rad_{}, joint_valid_{},
  next_motor_index_(0), request_in_flight_(false)
{
  logical_motor3_dxl_id_ = declare_parameter("logical_motor3_dxl_id", 1);
  logical_motor4_dxl_id_ = declare_parameter("logical_motor4_dxl_id", 2);
  logical_motor5_dxl_id_ = declare_parameter("logical_motor5_dxl_id", 3);
  motor3_joint_name_ = declare_parameter("motor3_joint_name", "motor_3_joint");
  motor4_joint_name_ = declare_parameter("motor4_joint_name", "motor_4_joint");
  motor5_joint_name_ = declare_parameter("motor5_joint_name", "motor_5_joint");
  dxl_position_min_ = declare_parameter("dxl_position_min", 0);
  dxl_position_max_ = declare_parameter("dxl_position_max", 4095);
  get_position_client_ = create_client<dynamixel_sdk_custom_interfaces::srv::GetPosition>(
    "/get_position");
  joint_state_pub_ = create_publisher<sensor_msgs::msg::JointState>("/dxl_joint_states", 20);
  request_timer_ = create_wall_timer(30ms,
    std::bind(&DxlStatePublisherNode::requestTimerCallback, this));
  RCLCPP_INFO(get_logger(), "Polling DXL IDs %d, %d, %d; signed feedback for motors 3/4",
    logical_motor3_dxl_id_, logical_motor4_dxl_id_, logical_motor5_dxl_id_);
}

double DxlStatePublisherNode::positionValueToRad(int value) const
{
  // X-Series: exactly 4096 counts/revolution, including signed extended positions.
  return static_cast<double>(value) * 2.0 * M_PI / 4096.0;
}

void DxlStatePublisherNode::requestTimerCallback()
{
  const auto now = std::chrono::steady_clock::now();
  if (request_in_flight_) {
    if (now - request_started_ < 150ms) { return; }
    get_position_client_->prune_pending_requests();
    joint_valid_[active_index_] = false;
    sample_seen_[active_index_] = false;
    request_in_flight_ = false;
    ++request_generation_;
  }
  if (!get_position_client_->service_is_ready()) { return; }
  const std::array<int, 3> ids = {
    logical_motor3_dxl_id_, logical_motor4_dxl_id_, logical_motor5_dxl_id_};
  const int index = next_motor_index_;
  next_motor_index_ = (next_motor_index_ + 1) % 3;
  active_index_ = index;
  auto request = std::make_shared<dynamixel_sdk_custom_interfaces::srv::GetPosition::Request>();
  request->id = ids[index];
  request_started_ = now;
  request_in_flight_ = true;
  const auto generation = ++request_generation_;
  get_position_client_->async_send_request(request,
    [this, index, generation](
      rclcpp::Client<dynamixel_sdk_custom_interfaces::srv::GetPosition>::SharedFuture future)
    {
      if (generation != request_generation_) { return; }
      request_in_flight_ = false;
      try {
        const auto response = future.get();
        const int raw = response->position;
        const int minimum = index < 2 ? -1048575 : dxl_position_min_;
        const int maximum = index < 2 ? 1048575 : dxl_position_max_;
        if (!response->success || raw < minimum || raw > maximum) {
          joint_valid_[index] = false;
          sample_seen_[index] = false;
          return;
        }
        const auto now = std::chrono::steady_clock::now();
        const double position = positionValueToRad(raw);
        const double dt = std::chrono::duration<double>(now - sample_time_[index]).count();
        joint_valid_[index] = sample_seen_[index] && dt > 0.0 && dt <= 0.5;
        if (joint_valid_[index]) {
          double delta = position - joint_pos_rad_[index];
          if (index == 2) { delta = std::remainder(delta, 2.0 * M_PI); }
          joint_velocity_rad_[index] = delta / dt;
        }
        joint_pos_rad_[index] = position;
        sample_time_[index] = now;
        sample_seen_[index] = true;
        active_index_ = index;
        publishTimerCallback();
      } catch (const std::exception & e) {
        joint_valid_[index] = false;
        sample_seen_[index] = false;
        RCLCPP_WARN(get_logger(), "DXL feedback failed: %s", e.what());
      }
    });
}

void DxlStatePublisherNode::publishTimerCallback()
{
  // Publish only a newly received sample. Never put a new timestamp on cached data.
  const int i = active_index_;
  if (!joint_valid_[i]) { return; }
  const std::array<std::string, 3> names = {
    motor3_joint_name_, motor4_joint_name_, motor5_joint_name_};
  sensor_msgs::msg::JointState msg;
  msg.header.stamp = this->now();
  msg.name = {names[i]};
  msg.position = {joint_pos_rad_[i]};
  msg.velocity = {joint_velocity_rad_[i]};
  joint_state_pub_->publish(msg);
}

int main(int argc, char ** argv)
{
  rclcpp::init(argc, argv);
  rclcpp::spin(std::make_shared<DxlStatePublisherNode>());
  rclcpp::shutdown();
  return 0;
}
