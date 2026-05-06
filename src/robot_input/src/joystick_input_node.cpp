#include "robot_input/joystick_input_node.hpp"

JoystickInputNode::JoystickInputNode()
: Node("joystick_input_node"),
  linear_axis_(1),
  angular_axis_(0),
  linear_scale_(1.0),
  angular_scale_(1.0),
  deadzone_(0.1),
  transform_to_a_button_(0),
  transform_to_b_button_(1),
  manual_mode_button_(4),
  auto_mode_button_(5),
  emergency_stop_button_(6),
  emergency_go_button_(7),
  publish_zero_on_idle_(true)
{
  this->declare_parameter("linear_axis", linear_axis_);
  this->declare_parameter("angular_axis", angular_axis_);
  this->declare_parameter("linear_scale", linear_scale_);
  this->declare_parameter("angular_scale", angular_scale_);
  this->declare_parameter("deadzone", deadzone_);

  this->declare_parameter("transform_to_a_button", transform_to_a_button_);
  this->declare_parameter("transform_to_b_button", transform_to_b_button_);
  this->declare_parameter("manual_mode_button", manual_mode_button_);
  this->declare_parameter("auto_mode_button", auto_mode_button_);
  this->declare_parameter("emergency_stop_button", emergency_stop_button_);
  this->declare_parameter("emergency_go_button", emergency_go_button_);

  this->declare_parameter("publish_zero_on_idle", publish_zero_on_idle_);

  this->get_parameter("linear_axis", linear_axis_);
  this->get_parameter("angular_axis", angular_axis_);
  this->get_parameter("linear_scale", linear_scale_);
  this->get_parameter("angular_scale", angular_scale_);
  this->get_parameter("deadzone", deadzone_);

  this->get_parameter("transform_to_a_button", transform_to_a_button_);
  this->get_parameter("transform_to_b_button", transform_to_b_button_);
  this->get_parameter("manual_mode_button", manual_mode_button_);
  this->get_parameter("auto_mode_button", auto_mode_button_);
  this->get_parameter("emergency_stop_button", emergency_stop_button_);
  this->get_parameter("emergency_go_button", emergency_go_button_);

  this->get_parameter("publish_zero_on_idle", publish_zero_on_idle_);

  joy_sub_ = this->create_subscription<sensor_msgs::msg::Joy>(
    "/joy", 20,
    std::bind(&JoystickInputNode::joyCallback, this, std::placeholders::_1));

  manual_cmd_vel_pub_ = this->create_publisher<geometry_msgs::msg::Twist>("/manual/cmd_vel", 20);
  manual_transform_cmd_pub_ = this->create_publisher<std_msgs::msg::Int32>("/manual/transform_cmd", 20);
  control_mode_cmd_pub_ = this->create_publisher<std_msgs::msg::Int32>("/control_mode_cmd", 20);
  emergency_stop_pub_ = this->create_publisher<std_msgs::msg::Bool>("/emergency_stop", 20);
  emergency_go_pub_ = this->create_publisher<std_msgs::msg::Bool>("/emergency_go", 20);

  RCLCPP_INFO(this->get_logger(), "joystick_input_node started");
}

bool JoystickInputNode::isButtonPressed(const sensor_msgs::msg::Joy::SharedPtr & msg, int index) const
{
  if (index < 0) return false;
  if (static_cast<std::size_t>(index) >= msg->buttons.size()) return false;
  return msg->buttons[index] != 0;
}

void JoystickInputNode::joyCallback(const sensor_msgs::msg::Joy::SharedPtr msg)
{
  if (prev_buttons_.size() != msg->buttons.size()) {
    prev_buttons_.assign(msg->buttons.size(), 0);
  }

  auto risingEdge = [&](int index) -> bool {
    if (index < 0 || static_cast<std::size_t>(index) >= msg->buttons.size()) return false;
    const bool current = (msg->buttons[index] != 0);
    const bool previous = (prev_buttons_[index] != 0);
    return current && !previous;
  };

  double linear = 0.0;
  double angular = 0.0;

  if (linear_axis_ >= 0 && static_cast<std::size_t>(linear_axis_) < msg->axes.size()) {
    linear = msg->axes[linear_axis_];
    if (std::abs(linear) < deadzone_) linear = 0.0;
    linear *= linear_scale_;
  }

  if (angular_axis_ >= 0 && static_cast<std::size_t>(angular_axis_) < msg->axes.size()) {
    angular = msg->axes[angular_axis_];
    if (std::abs(angular) < deadzone_) angular = 0.0;
    angular *= angular_scale_;
  }

  if (publish_zero_on_idle_ || linear != 0.0 || angular != 0.0) {
    geometry_msgs::msg::Twist cmd;
    cmd.linear.x = linear;
    cmd.angular.z = angular;
    manual_cmd_vel_pub_->publish(cmd);
  }

  if (risingEdge(transform_to_a_button_)) {
    std_msgs::msg::Int32 msg_out;
    msg_out.data = 1;  // TF_TO_A
    manual_transform_cmd_pub_->publish(msg_out);
    RCLCPP_INFO(this->get_logger(), "Published transform request: A");
  }

  if (risingEdge(transform_to_b_button_)) {
    std_msgs::msg::Int32 msg_out;
    msg_out.data = 2;  // TF_TO_B
    manual_transform_cmd_pub_->publish(msg_out);
    RCLCPP_INFO(this->get_logger(), "Published transform request: B");
  }

  if (risingEdge(manual_mode_button_)) {
    std_msgs::msg::Int32 msg_out;
    msg_out.data = 0;  // MANUAL
    control_mode_cmd_pub_->publish(msg_out);
    RCLCPP_INFO(this->get_logger(), "Published control mode: MANUAL");
  }

  if (risingEdge(auto_mode_button_)) {
    std_msgs::msg::Int32 msg_out;
    msg_out.data = 1;  // AUTO
    control_mode_cmd_pub_->publish(msg_out);
    RCLCPP_INFO(this->get_logger(), "Published control mode: AUTO");
  }

  if (risingEdge(emergency_stop_button_)) {
    std_msgs::msg::Bool msg_out;
    msg_out.data = true;
    emergency_stop_pub_->publish(msg_out);
    RCLCPP_WARN(this->get_logger(), "Published emergency_stop");
  }

  if (risingEdge(emergency_go_button_)) {
    std_msgs::msg::Bool msg_out;
    msg_out.data = true;
    emergency_go_pub_->publish(msg_out);
    RCLCPP_INFO(this->get_logger(), "Published emergency_go");
  }

  prev_buttons_ = msg->buttons;
}

int main(int argc, char ** argv)
{
  rclcpp::init(argc, argv);
  rclcpp::spin(std::make_shared<JoystickInputNode>());
  rclcpp::shutdown();
  return 0;
}
