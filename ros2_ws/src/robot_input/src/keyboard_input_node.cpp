#include <chrono>
#include <cstdio>
#include <cstring>
#include <memory>
#include <string>
#include <termios.h>
#include <unistd.h>

#include <geometry_msgs/msg/twist.hpp>
#include <rclcpp/rclcpp.hpp>
#include <std_msgs/msg/bool.hpp>
#include <std_msgs/msg/int32.hpp>
#include <std_msgs/msg/string.hpp>

using namespace std::chrono_literals;

namespace
{
class KeyboardReader
{
public:
  KeyboardReader()
  {
    tcgetattr(STDIN_FILENO, &original_terminal_state_);
    termios raw = original_terminal_state_;
    raw.c_lflag &= static_cast<unsigned>(~(ICANON | ECHO));
    raw.c_cc[VMIN] = 0;
    raw.c_cc[VTIME] = 1;
    tcsetattr(STDIN_FILENO, TCSANOW, &raw);
  }

  ~KeyboardReader()
  {
    tcsetattr(STDIN_FILENO, TCSANOW, &original_terminal_state_);
  }

  bool readOne(char & c)
  {
    const int rc = ::read(STDIN_FILENO, &c, 1);
    return rc == 1;
  }

private:
  termios original_terminal_state_{};
};
}  // namespace

class KeyboardInputNode : public rclcpp::Node
{
public:
  KeyboardInputNode()
  : Node("keyboard_input_node"),
    linear_speed_(0.30),
    angular_speed_(0.80),
    current_linear_(0.0),
    current_angular_(0.0)
  {
    this->declare_parameter("linear_speed", linear_speed_);
    this->declare_parameter("angular_speed", angular_speed_);

    this->get_parameter("linear_speed", linear_speed_);
    this->get_parameter("angular_speed", angular_speed_);

    manual_cmd_pub_ =
      this->create_publisher<geometry_msgs::msg::Twist>("/manual/cmd_vel", 20);
    transform_cmd_pub_ =
      this->create_publisher<std_msgs::msg::Int32>("/manual/transform_cmd", 20);
    control_mode_pub_ =
      this->create_publisher<std_msgs::msg::Int32>("/control_mode_cmd", 20);
    estop_pub_ =
      this->create_publisher<std_msgs::msg::Bool>("/emergency_stop", 20);
    ego_pub_ =
      this->create_publisher<std_msgs::msg::Bool>("/emergency_go", 20);
    drive_profile_pub_ =
      this->create_publisher<std_msgs::msg::String>("/drive/profile_cmd", 20);
    transform_profile_pub_ =
      this->create_publisher<std_msgs::msg::String>("/transform/profile_cmd", 20);

    timer_ = this->create_wall_timer(
      50ms, std::bind(&KeyboardInputNode::timerCallback, this));

    printHelp();

    RCLCPP_INFO(this->get_logger(), "keyboard_input_node started");
    RCLCPP_INFO(
      this->get_logger(),
      "latched speeds: linear=%.2f m/s angular=%.2f rad/s",
      linear_speed_,
      angular_speed_);
  }

private:
  void printHelp()
  {
    printf("\n");
    printf("=== Keyboard Control ===\n");
    printf("w : forward latch\n");
    printf("s : backward latch\n");
    printf("a : rotate left latch\n");
    printf("d : rotate right latch\n");
    printf("q : forward + left\n");
    printf("e : forward + right\n");
    printf("z : backward + left\n");
    printf("x : backward + right\n");
    printf("c : stop\n");
    printf("\n");
    printf("1 : TRANSFORM_TO_A\n");
    printf("2 : TRANSFORM_TO_B\n");
    printf("m : MANUAL mode\n");
    printf("o : AUTO mode\n");
    printf("SPACE : emergency stop\n");
    printf("g : emergency go\n");
    printf("\n");
    printf("r : drive profile normal\n");
    printf("t : drive profile slope\n");
    printf("y : drive profile obstacle\n");
    printf("f : transform profile precise\n");
    printf("h : transform profile fast\n");
    printf("j : transform profile soft\n");
    printf("========================\n");
    printf("\n");
    fflush(stdout);
  }

  void publishCurrentTwist()
  {
    geometry_msgs::msg::Twist msg;
    msg.linear.x = current_linear_;
    msg.angular.z = current_angular_;
    manual_cmd_pub_->publish(msg);

    RCLCPP_INFO(
      this->get_logger(),
      "Published /manual/cmd_vel linear=%.3f angular=%.3f",
      current_linear_, current_angular_);
  }

  void publishTransformCommand(int target)
  {
    std_msgs::msg::Int32 msg;
    msg.data = target;
    transform_cmd_pub_->publish(msg);

    RCLCPP_INFO(this->get_logger(), "Published /manual/transform_cmd: %d", target);
  }

  void publishControlMode(int mode)
  {
    std_msgs::msg::Int32 msg;
    msg.data = mode;
    control_mode_pub_->publish(msg);

    RCLCPP_INFO(this->get_logger(), "Published /control_mode_cmd: %d", mode);
  }

  void publishBool(
    const rclcpp::Publisher<std_msgs::msg::Bool>::SharedPtr & pub,
    bool value,
    const char * name)
  {
    std_msgs::msg::Bool msg;
    msg.data = value;
    pub->publish(msg);

    RCLCPP_INFO(this->get_logger(), "Published %s: %s", name, value ? "true" : "false");
  }

  void publishString(
    const rclcpp::Publisher<std_msgs::msg::String>::SharedPtr & pub,
    const std::string & value,
    const char * name)
  {
    std_msgs::msg::String msg;
    msg.data = value;
    pub->publish(msg);

    RCLCPP_INFO(this->get_logger(), "Published %s: %s", name, value.c_str());
  }

  void handleKey(char c)
  {
    switch (c) {
      case 'w':
        current_linear_ = linear_speed_;
        current_angular_ = 0.0;
        publishCurrentTwist();
        break;
      case 's':
        current_linear_ = -linear_speed_;
        current_angular_ = 0.0;
        publishCurrentTwist();
        break;
      case 'a':
        current_linear_ = 0.0;
        current_angular_ = angular_speed_;
        publishCurrentTwist();
        break;
      case 'd':
        current_linear_ = 0.0;
        current_angular_ = -angular_speed_;
        publishCurrentTwist();
        break;
      case 'q':
        current_linear_ = linear_speed_;
        current_angular_ = angular_speed_;
        publishCurrentTwist();
        break;
      case 'e':
        current_linear_ = linear_speed_;
        current_angular_ = -angular_speed_;
        publishCurrentTwist();
        break;
      case 'z':
        current_linear_ = -linear_speed_;
        current_angular_ = angular_speed_;
        publishCurrentTwist();
        break;
      case 'x':
        current_linear_ = -linear_speed_;
        current_angular_ = -angular_speed_;
        publishCurrentTwist();
        break;
      case 'c':
        current_linear_ = 0.0;
        current_angular_ = 0.0;
        publishCurrentTwist();
        break;

      case '1':
        publishTransformCommand(1);
        break;
      case '2':
        publishTransformCommand(2);
        break;

      case 'm':
        publishControlMode(0);
        break;
      case 'o':
        publishControlMode(1);
        break;

      case ' ':
        publishBool(estop_pub_, true, "/emergency_stop");
        break;
      case 'g':
        publishBool(ego_pub_, true, "/emergency_go");
        break;

      case 'r':
        publishString(drive_profile_pub_, "normal", "/drive/profile_cmd");
        break;
      case 't':
        publishString(drive_profile_pub_, "slope", "/drive/profile_cmd");
        break;
      case 'y':
        publishString(drive_profile_pub_, "obstacle", "/drive/profile_cmd");
        break;

      case 'f':
        publishString(transform_profile_pub_, "precise", "/transform/profile_cmd");
        break;
      case 'h':
        publishString(transform_profile_pub_, "fast", "/transform/profile_cmd");
        break;
      case 'j':
        publishString(transform_profile_pub_, "soft", "/transform/profile_cmd");
        break;

      default:
        break;
    }
  }

  void timerCallback()
  {
    char c = 0;
    if (keyboard_reader_.readOne(c)) {
      handleKey(c);
    }
  }

  KeyboardReader keyboard_reader_;

  rclcpp::Publisher<geometry_msgs::msg::Twist>::SharedPtr manual_cmd_pub_;
  rclcpp::Publisher<std_msgs::msg::Int32>::SharedPtr transform_cmd_pub_;
  rclcpp::Publisher<std_msgs::msg::Int32>::SharedPtr control_mode_pub_;
  rclcpp::Publisher<std_msgs::msg::Bool>::SharedPtr estop_pub_;
  rclcpp::Publisher<std_msgs::msg::Bool>::SharedPtr ego_pub_;
  rclcpp::Publisher<std_msgs::msg::String>::SharedPtr drive_profile_pub_;
  rclcpp::Publisher<std_msgs::msg::String>::SharedPtr transform_profile_pub_;

  rclcpp::TimerBase::SharedPtr timer_;

  double linear_speed_;
  double angular_speed_;
  double current_linear_;
  double current_angular_;
};

int main(int argc, char ** argv)
{
  rclcpp::init(argc, argv);
  rclcpp::spin(std::make_shared<KeyboardInputNode>());
  rclcpp::shutdown();
  return 0;
}
