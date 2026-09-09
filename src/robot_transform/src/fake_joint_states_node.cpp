#include "robot_transform/fake_joint_states_node.hpp"

#include <chrono>
#include <termios.h>
#include <unistd.h>
#include <sys/select.h>

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

FakeJointStatesNode::FakeJointStatesNode()
: Node("fake_joint_states_node"),
  motor1_joint_name_("motor_1_joint"),
  motor2_joint_name_("motor_2_joint"),
  motor3_joint_name_("motor_3_joint"),
  motor4_joint_name_("motor_4_joint"),
  joint_pos_deg_{0.0, 0.0, 0.0, 0.0},
  joint_vel_rad_{0.0, 0.0, 0.0, 0.0}
{
  this->declare_parameter("motor1_joint_name", motor1_joint_name_);
  this->declare_parameter("motor2_joint_name", motor2_joint_name_);
  this->declare_parameter("motor3_joint_name", motor3_joint_name_);
  this->declare_parameter("motor4_joint_name", motor4_joint_name_);

  this->get_parameter("motor1_joint_name", motor1_joint_name_);
  this->get_parameter("motor2_joint_name", motor2_joint_name_);
  this->get_parameter("motor3_joint_name", motor3_joint_name_);
  this->get_parameter("motor4_joint_name", motor4_joint_name_);

  joint_state_pub_ = this->create_publisher<sensor_msgs::msg::JointState>("/joint_states", 20);

  bldc_position_sub_ = this->create_subscription<robot_msgs::msg::MitCommand>(
    "/bldc_mit_position_cmd", 20,
    std::bind(&FakeJointStatesNode::bldcPositionCmdCallback, this, std::placeholders::_1));

  dxl_position_sub_ = this->create_subscription<std_msgs::msg::Float64MultiArray>(
    "/dxl_position_cmd", 20,
    std::bind(&FakeJointStatesNode::dxlPositionCmdCallback, this, std::placeholders::_1));

  publish_timer_ = this->create_wall_timer(
    100ms, std::bind(&FakeJointStatesNode::publishTimerCallback, this));

  input_timer_ = this->create_wall_timer(
    50ms, std::bind(&FakeJointStatesNode::inputTimerCallback, this));

  RCLCPP_INFO(this->get_logger(), "fake_joint_states_node started");
  RCLCPP_INFO(
    this->get_logger(),
    "joint names: m1=%s m2=%s m3=%s m4=%s",
    motor1_joint_name_.c_str(),
    motor2_joint_name_.c_str(),
    motor3_joint_name_.c_str(),
    motor4_joint_name_.c_str());
  RCLCPP_INFO(this->get_logger(), "keys:");
  RCLCPP_INFO(this->get_logger(), "  a : set pose A (all 0 deg)");
  RCLCPP_INFO(this->get_logger(), "  b : set pose B (all 90 deg)");
  RCLCPP_INFO(this->get_logger(), "  z : zero all joints");
  RCLCPP_INFO(this->get_logger(), "  1/2/3/4 : motor1~4 +10 deg");
  RCLCPP_INFO(this->get_logger(), "  !/@/#/$ : motor1~4 -10 deg");
  RCLCPP_INFO(this->get_logger(), "Focus this terminal and press keys directly.");
}

double FakeJointStatesNode::degToRad(double deg) const
{
  return deg * 3.14159265358979323846 / 180.0;
}

void FakeJointStatesNode::setPoseA()
{
  joint_pos_deg_[0] = 0.0;
  joint_pos_deg_[1] = 0.0;
  joint_pos_deg_[2] = 0.0;
  joint_pos_deg_[3] = 0.0;
  joint_vel_rad_[0] = 0.0;
  joint_vel_rad_[1] = 0.0;
  joint_vel_rad_[2] = 0.0;
  joint_vel_rad_[3] = 0.0;
  RCLCPP_INFO(this->get_logger(), "Set pose A");
}

void FakeJointStatesNode::setPoseB()
{
  joint_pos_deg_[0] = 90.0;
  joint_pos_deg_[1] = 90.0;
  joint_pos_deg_[2] = 90.0;
  joint_pos_deg_[3] = 90.0;
  joint_vel_rad_[0] = 0.0;
  joint_vel_rad_[1] = 0.0;
  joint_vel_rad_[2] = 0.0;
  joint_vel_rad_[3] = 0.0;
  RCLCPP_INFO(this->get_logger(), "Set pose B");
}

void FakeJointStatesNode::publishJointStates()
{
  sensor_msgs::msg::JointState msg;
  msg.header.stamp = this->now();

  msg.name = {
    motor1_joint_name_,
    motor2_joint_name_,
    motor3_joint_name_,
    motor4_joint_name_
  };

  msg.position = {
    degToRad(joint_pos_deg_[0]),
    degToRad(joint_pos_deg_[1]),
    degToRad(joint_pos_deg_[2]),
    degToRad(joint_pos_deg_[3])
  };

  msg.velocity = {
    joint_vel_rad_[0],
    joint_vel_rad_[1],
    joint_vel_rad_[2],
    joint_vel_rad_[3]
  };

  joint_state_pub_->publish(msg);
}

void FakeJointStatesNode::bldcPositionCmdCallback(const robot_msgs::msg::MitCommand::SharedPtr msg)
{
  const int motor_id = msg->motor_id;
  if (motor_id < 1 || motor_id > 4) {
    return;
  }

  joint_pos_deg_[motor_id - 1] = msg->p_des;
  joint_vel_rad_[motor_id - 1] = 0.0;

  RCLCPP_INFO(
    this->get_logger(),
    "Applied BLDC position cmd: motor%d -> %.2f deg",
    motor_id, msg->p_des);
}

void FakeJointStatesNode::dxlPositionCmdCallback(const std_msgs::msg::Float64MultiArray::SharedPtr msg)
{
  if (msg->data.size() < 2) {
    return;
  }

  const int motor_id = static_cast<int>(msg->data[0]);
  const double target_deg = msg->data[1];

  if (motor_id < 1 || motor_id > 4) {
    return;
  }

  joint_pos_deg_[motor_id - 1] = target_deg;
  joint_vel_rad_[motor_id - 1] = 0.0;

  RCLCPP_INFO(
    this->get_logger(),
    "Applied DXL position cmd: motor%d -> %.2f deg",
    motor_id, target_deg);
}

void FakeJointStatesNode::publishTimerCallback()
{
  publishJointStates();
}

void FakeJointStatesNode::processKey(char key)
{
  switch (key) {
    case 'a':
      setPoseA();
      break;
    case 'b':
      setPoseB();
      break;
    case 'z':
      setPoseA();
      break;
    case '1':
      joint_pos_deg_[0] += 10.0;
      joint_vel_rad_[0] = 0.0;
      RCLCPP_INFO(this->get_logger(), "motor1 -> %.1f deg", joint_pos_deg_[0]);
      break;
    case '2':
      joint_pos_deg_[1] += 10.0;
      joint_vel_rad_[1] = 0.0;
      RCLCPP_INFO(this->get_logger(), "motor2 -> %.1f deg", joint_pos_deg_[1]);
      break;
    case '3':
      joint_pos_deg_[2] += 10.0;
      joint_vel_rad_[2] = 0.0;
      RCLCPP_INFO(this->get_logger(), "motor3 -> %.1f deg", joint_pos_deg_[2]);
      break;
    case '4':
      joint_pos_deg_[3] += 10.0;
      joint_vel_rad_[3] = 0.0;
      RCLCPP_INFO(this->get_logger(), "motor4 -> %.1f deg", joint_pos_deg_[3]);
      break;
    case '!':
      joint_pos_deg_[0] -= 10.0;
      joint_vel_rad_[0] = 0.0;
      RCLCPP_INFO(this->get_logger(), "motor1 -> %.1f deg", joint_pos_deg_[0]);
      break;
    case '@':
      joint_pos_deg_[1] -= 10.0;
      joint_vel_rad_[1] = 0.0;
      RCLCPP_INFO(this->get_logger(), "motor2 -> %.1f deg", joint_pos_deg_[1]);
      break;
    case '#':
      joint_pos_deg_[2] -= 10.0;
      joint_vel_rad_[2] = 0.0;
      RCLCPP_INFO(this->get_logger(), "motor3 -> %.1f deg", joint_pos_deg_[2]);
      break;
    case '$':
      joint_pos_deg_[3] -= 10.0;
      joint_vel_rad_[3] = 0.0;
      RCLCPP_INFO(this->get_logger(), "motor4 -> %.1f deg", joint_pos_deg_[3]);
      break;
    default:
      break;
  }
}

void FakeJointStatesNode::inputTimerCallback()
{
  const char key = getchNonBlocking();
  if (key != 0) {
    processKey(key);
  }
}

int main(int argc, char ** argv)
{
  rclcpp::init(argc, argv);
  rclcpp::spin(std::make_shared<FakeJointStatesNode>());
  rclcpp::shutdown();
  return 0;
}
