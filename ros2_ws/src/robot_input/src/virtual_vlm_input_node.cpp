#include "robot_input/virtual_vlm_input_node.hpp"

#include <chrono>
#include <termios.h>
#include <unistd.h>

using namespace std::chrono_literals;

namespace
{
char getchNonBlocking()
{
  char ch = 0;

  termios oldt{};
  termios newt{};

  tcgetattr(STDIN_FILENO, &oldt);
  newt = oldt;

  newt.c_lflag &= static_cast<unsigned>(~(ICANON | ECHO));
  tcsetattr(STDIN_FILENO, TCSANOW, &newt);

  timeval tv{};
  tv.tv_sec = 0;
  tv.tv_usec = 0;

  fd_set readfds;
  FD_ZERO(&readfds);
  FD_SET(STDIN_FILENO, &readfds);

  const int ret = select(STDIN_FILENO + 1, &readfds, nullptr, nullptr, &tv);
  if (ret > 0 && FD_ISSET(STDIN_FILENO, &readfds)) {
    ::read(STDIN_FILENO, &ch, 1);
  }

  tcsetattr(STDIN_FILENO, TCSANOW, &oldt);
  return ch;
}
}  // namespace

VirtualVlmInputNode::VirtualVlmInputNode()
: Node("virtual_vlm_input_node"),
  auto_linear_speed_(0.8),
  auto_angular_speed_(0.8)
{
  this->declare_parameter("auto_linear_speed", auto_linear_speed_);
  this->declare_parameter("auto_angular_speed", auto_angular_speed_);

  this->get_parameter("auto_linear_speed", auto_linear_speed_);
  this->get_parameter("auto_angular_speed", auto_angular_speed_);

  auto_cmd_pub_ = this->create_publisher<geometry_msgs::msg::Twist>("/auto/cmd_vel", 10);
  auto_transform_pub_ = this->create_publisher<std_msgs::msg::Int32>("/auto/transform_cmd", 10);

  timer_ = this->create_wall_timer(50ms, std::bind(&VirtualVlmInputNode::timerCallback, this));

  RCLCPP_INFO(this->get_logger(), "virtual_vlm_input_node started");
  RCLCPP_INFO(this->get_logger(), "auto keys:");
  RCLCPP_INFO(this->get_logger(), "  i/k/j/l : drive");
  RCLCPP_INFO(this->get_logger(), "  u/p     : diagonal-style drive");
  RCLCPP_INFO(this->get_logger(), "  n       : stop");
  RCLCPP_INFO(this->get_logger(), "  7 / 8   : transform to A / B");
  RCLCPP_INFO(this->get_logger(), "Focus this terminal and press keys directly.");
}

void VirtualVlmInputNode::timerCallback()
{
  const char key = getchNonBlocking();
  if (key != 0) {
    processKey(key);
  }
}

void VirtualVlmInputNode::processKey(char key)
{
  switch (key) {
    case 'i':
      publishAutoTwist(auto_linear_speed_, 0.0);
      break;
    case 'k':
      publishAutoTwist(-auto_linear_speed_, 0.0);
      break;
    case 'j':
      publishAutoTwist(0.0, auto_angular_speed_);
      break;
    case 'l':
      publishAutoTwist(0.0, -auto_angular_speed_);
      break;
    case 'u':
      publishAutoTwist(auto_linear_speed_, auto_angular_speed_);
      break;
    case 'p':
      publishAutoTwist(auto_linear_speed_, -auto_angular_speed_);
      break;
    case 'n':
      publishAutoTwist(0.0, 0.0);
      break;
    case '7':
      publishTransformCmd(1);
      break;
    case '8':
      publishTransformCmd(2);
      break;
    default:
      break;
  }
}

void VirtualVlmInputNode::publishAutoTwist(double linear_x, double angular_z)
{
  geometry_msgs::msg::Twist msg;
  msg.linear.x = linear_x;
  msg.angular.z = angular_z;
  auto_cmd_pub_->publish(msg);

  RCLCPP_INFO(this->get_logger(), "Published /auto/cmd_vel: linear=%.3f angular=%.3f", linear_x, angular_z);
}

void VirtualVlmInputNode::publishTransformCmd(int cmd)
{
  std_msgs::msg::Int32 msg;
  msg.data = cmd;
  auto_transform_pub_->publish(msg);

  RCLCPP_INFO(this->get_logger(), "Published /auto/transform_cmd: %d", cmd);
}

int main(int argc, char ** argv)
{
  rclcpp::init(argc, argv);
  rclcpp::spin(std::make_shared<VirtualVlmInputNode>());
  rclcpp::shutdown();
  return 0;
}
