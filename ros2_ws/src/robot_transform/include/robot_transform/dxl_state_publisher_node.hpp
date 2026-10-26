#pragma once

#include <array>
#include <chrono>
#include <string>

#include <rclcpp/rclcpp.hpp>
#include <sensor_msgs/msg/joint_state.hpp>
#include <dynamixel_sdk_custom_interfaces/srv/get_position.hpp>


class DxlStatePublisherNode : public rclcpp::Node
{
public:
  DxlStatePublisherNode();

private:
  double positionValueToRad(
    int value
  ) const;

  void requestTimerCallback();

  void publishTimerCallback();

  rclcpp::Client<
    dynamixel_sdk_custom_interfaces::srv::GetPosition
  >::SharedPtr get_position_client_;

  rclcpp::Publisher<
    sensor_msgs::msg::JointState
  >::SharedPtr joint_state_pub_;

  rclcpp::TimerBase::SharedPtr
    request_timer_;

  rclcpp::TimerBase::SharedPtr
    publish_timer_;

  // DXL IDs
  int logical_motor3_dxl_id_;
  int logical_motor4_dxl_id_;
  int logical_motor5_dxl_id_;

  // Joint names
  std::string motor3_joint_name_;
  std::string motor4_joint_name_;
  std::string motor5_joint_name_;

  // Position conversion
  int dxl_position_min_;
  int dxl_position_max_;


  // Joint positions
  std::array<double, 3>
    joint_pos_rad_;

  std::array<double, 3> joint_velocity_rad_{};
  std::array<std::chrono::steady_clock::time_point, 3> sample_time_{};
  std::array<bool, 3> sample_seen_{};
  int active_index_{0};
  unsigned long request_generation_{0};

  // Valid state
  std::array<bool, 3>
    joint_valid_;

  // Sequential polling
  int next_motor_index_;

  // Prevent overlapping requests
  bool request_in_flight_;
  std::chrono::steady_clock::time_point request_started_;
};
