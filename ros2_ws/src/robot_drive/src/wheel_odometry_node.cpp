#include <algorithm>
#include <array>
#include <memory>
#include <string>
#include <vector>

#include "rclcpp/rclcpp.hpp"
#include "sensor_msgs/msg/joint_state.hpp"
#include "nav_msgs/msg/odometry.hpp"
#include "geometry_msgs/msg/transform_stamped.hpp"
#include "tf2_ros/transform_broadcaster.h"
#include "robot_drive/wheel_odometry.hpp"
#include "robot_drive/feedback_freshness.hpp"

class WheelOdometryNode : public rclcpp::Node
{
public:
  WheelOdometryNode() : Node("wheel_odometry_node")
  {
    const auto radius = declare_parameter("wheel_radius", 0.234);
    const auto odom_scale = declare_parameter("odom_scale", 1.0);
    if (!std::isfinite(odom_scale) || odom_scale <= 0.0) {
      throw std::invalid_argument("odom_scale must be finite and positive");
    }
    const auto separation = declare_parameter("wheel_separation", 0.184);
    const auto wrap = declare_parameter("position_wrap_radians", 25.132741228718345);
    timeout_ = declare_parameter("joint_state_timeout_sec", 0.2);
    const auto max_speed = declare_parameter("max_wheel_speed", 30.0);
    odometry_ = std::make_unique<robot_drive::WheelOdometry>(radius * odom_scale, separation, wrap, timeout_, max_speed);
    left_ = declare_parameter("left_joint_name", std::string("left_wheel_joint"));
    right_ = declare_parameter("right_joint_name", std::string("right_wheel_joint"));
    odom_frame_ = declare_parameter("odom_frame", std::string("odom"));
    base_frame_ = declare_parameter("base_frame", std::string("base_link"));
    require_feedback_ = declare_parameter("require_hardware_feedback", false);
    feedback_sub_ = create_subscription<control_msgs::msg::DynamicJointState>(
      "/dynamic_joint_states", rclcpp::SensorDataQoS(),
      [this](control_msgs::msg::DynamicJointState::ConstSharedPtr msg) {
        feedback_valid_ = robot_drive::feedback_fresh(*msg, left_, right_, timeout_);
        feedback_stamp_ = rclcpp::Time(msg->header.stamp).nanoseconds();
      });
    if (left_.empty() || right_.empty() || left_ == right_ || odom_frame_.empty() ||
      base_frame_.empty() || odom_frame_ == base_frame_) {throw std::invalid_argument("Invalid joint/frame names");}
    pose_cov_ = covariance("pose_covariance_diagonal", {0.02, 0.02, 1e6, 1e6, 1e6, 0.05});
    twist_cov_ = covariance("twist_covariance_diagonal", {0.02, 0.02, 1e6, 1e6, 1e6, 0.05});
    if (declare_parameter("publish_tf", true)) {
      tf_ = std::make_unique<tf2_ros::TransformBroadcaster>(*this);
    }
    pub_ = create_publisher<nav_msgs::msg::Odometry>("odom", 20);
    sub_ = create_subscription<sensor_msgs::msg::JointState>(
      "joint_states", rclcpp::SensorDataQoS(),
      [this](sensor_msgs::msg::JointState::ConstSharedPtr msg) {update(*msg);});
    RCLCPP_INFO(get_logger(), "Wheel odometry: radius=%.3f separation=%.3f odom_scale=%.4f TF=%s",
      radius, separation, odom_scale, tf_ ? "on" : "off");
  }

private:
  std::array<double, 36> covariance(const std::string & name, const std::vector<double> & defaults)
  {
    const auto values = declare_parameter(name, defaults);
    if (values.size() != 6) {throw std::invalid_argument(name + " must have six values");}
    std::array<double, 36> result{};
    for (size_t i = 0; i < 6; ++i) {
      if (!std::isfinite(values[i]) || values[i] < 0) {throw std::invalid_argument(name);}
      result[i * 7] = values[i];
    }
    return result;
  }

  void update(const sensor_msgs::msg::JointState & msg)
  {
    const auto current = now();
    if (require_feedback_ && (!feedback_valid_ || feedback_stamp_ <= 0 ||
      current.nanoseconds() < feedback_stamp_ ||
      (current.nanoseconds() - feedback_stamp_) / 1e9 > timeout_)) {
      odometry_->reset_history();
      return;
    }
    if (last_clock_ >= 0 && current.nanoseconds() < last_clock_) {odometry_->reset_history();}
    last_clock_ = current.nanoseconds();
    const rclcpp::Time stamp(msg.header.stamp, get_clock()->get_clock_type());
    const double age = (current - stamp).seconds();
    if (stamp.nanoseconds() <= 0 || age > timeout_ || age < -0.05) {
      RCLCPP_WARN_THROTTLE(get_logger(), *get_clock(), 5000, "Ignoring stale/invalid JointState timestamp");
      return;
    }
    const auto l = std::find(msg.name.begin(), msg.name.end(), left_);
    const auto r = std::find(msg.name.begin(), msg.name.end(), right_);
    if (l == msg.name.end() || r == msg.name.end()) {return;}
    const auto li = static_cast<size_t>(l - msg.name.begin());
    const auto ri = static_cast<size_t>(r - msg.name.begin());
    if (li >= msg.position.size() || ri >= msg.position.size()) {return;}
    const auto result = odometry_->update(stamp.seconds(), msg.position[li], msg.position[ri]);
    if (result == robot_drive::WheelOdometry::Result::rejected) {return;}
    if (result == robot_drive::WheelOdometry::Result::rebased) {
      RCLCPP_WARN_THROTTLE(get_logger(), *get_clock(), 5000, "Rebased wheel samples after a gap or position jump");
    }
    nav_msgs::msg::Odometry out;
    out.header.stamp = msg.header.stamp;
    out.header.frame_id = odom_frame_;
    out.child_frame_id = base_frame_;
    out.pose.pose.position.x = odometry_->x;
    out.pose.pose.position.y = odometry_->y;
    out.pose.pose.orientation.z = std::sin(odometry_->yaw / 2.0);
    out.pose.pose.orientation.w = std::cos(odometry_->yaw / 2.0);
    out.pose.covariance = pose_cov_;
    out.twist.twist.linear.x = odometry_->linear;
    out.twist.twist.angular.z = odometry_->angular;
    out.twist.covariance = twist_cov_;
    pub_->publish(out);
    if (tf_) {
      geometry_msgs::msg::TransformStamped transform;
      transform.header = out.header;
      transform.child_frame_id = base_frame_;
      transform.transform.translation.x = odometry_->x;
      transform.transform.translation.y = odometry_->y;
      transform.transform.rotation = out.pose.pose.orientation;
      tf_->sendTransform(transform);
    }
  }
  std::unique_ptr<robot_drive::WheelOdometry> odometry_;
  std::unique_ptr<tf2_ros::TransformBroadcaster> tf_;
  rclcpp::Publisher<nav_msgs::msg::Odometry>::SharedPtr pub_;
  rclcpp::Subscription<sensor_msgs::msg::JointState>::SharedPtr sub_;
  std::string left_, right_, odom_frame_, base_frame_;
  double timeout_;
  int64_t last_clock_{-1};
  std::array<double, 36> pose_cov_{}, twist_cov_{};
  bool require_feedback_{false}, feedback_valid_{false};
  int64_t feedback_stamp_{0};
  rclcpp::Subscription<control_msgs::msg::DynamicJointState>::SharedPtr feedback_sub_;
};

int main(int argc, char ** argv)
{
  rclcpp::init(argc, argv);
  rclcpp::spin(std::make_shared<WheelOdometryNode>());
  rclcpp::shutdown();
  return 0;
}
