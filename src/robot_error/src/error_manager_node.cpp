#include "robot_error/error_manager_node.hpp"

ErrorManagerNode::ErrorManagerNode()
: Node("error_manager_node")
{
  error_sub_ = this->create_subscription<robot_msgs::msg::SystemError>(
    "/system/error", 20,
    std::bind(&ErrorManagerNode::errorCallback, this, std::placeholders::_1));

  error_log_pub_ = this->create_publisher<std_msgs::msg::String>("/error/log", 20);

  RCLCPP_INFO(this->get_logger(), "error_manager_node started");
}

void ErrorManagerNode::errorCallback(const robot_msgs::msg::SystemError::SharedPtr msg)
{
  RCLCPP_ERROR(
    this->get_logger(),
    "[%s] error_code=%d description=%s",
    msg->source_node.c_str(),
    msg->error_code,
    msg->description.c_str());

  std_msgs::msg::String log_msg;
  log_msg.data =
    "[" + msg->source_node + "] error_code=" +
    std::to_string(msg->error_code) +
    " description=" + msg->description;

  error_log_pub_->publish(log_msg);
}

int main(int argc, char ** argv)
{
  rclcpp::init(argc, argv);
  rclcpp::spin(std::make_shared<ErrorManagerNode>());
  rclcpp::shutdown();
  return 0;
}
