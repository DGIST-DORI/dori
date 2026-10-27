// Keep Smac's collision checks and turning radius. Position destinations can
// use any approach heading, avoiding loops solely to match a saved arrow.
#include <algorithm>
#include <chrono>
#include <cmath>
#include <limits>
#include <vector>
#include "nav2_smac_planner/smac_planner_hybrid.hpp"
#include "nav2_util/node_utils.hpp"
#include "pluginlib/class_list_macros.hpp"

namespace dori_navigation
{
class RelaxedHeadingPlanner : public nav2_smac_planner::SmacPlannerHybrid
{
public:
  void configure(
    const rclcpp_lifecycle::LifecycleNode::WeakPtr & parent, std::string name,
    std::shared_ptr<tf2_ros::Buffer> tf,
    std::shared_ptr<nav2_costmap_2d::Costmap2DROS> costmap) override
  {
    SmacPlannerHybrid::configure(parent, name, tf, costmap);
    auto node = parent.lock();
    nav2_util::declare_parameter_if_not_declared(
      node, name + ".heading_tolerance", rclcpp::ParameterValue(0.6108652381980153));
    nav2_util::declare_parameter_if_not_declared(
      node, name + ".position_only", rclcpp::ParameterValue(true));
    position_only_ = node->get_parameter(name + ".position_only").as_bool();
    tolerance_ = node->get_parameter(name + ".heading_tolerance").as_double();
    if (!std::isfinite(tolerance_) || tolerance_ < 0. || tolerance_ > M_PI / 2.) {
      throw std::invalid_argument("heading_tolerance must be within 0..pi/2");
    }
  }

  nav_msgs::msg::Path createPlan(
    const geometry_msgs::msg::PoseStamped & start,
    const geometry_msgs::msg::PoseStamped & goal) override
  {
    const auto & q = goal.pose.orientation;
    const double heading = std::atan2(2.*(q.w*q.z+q.x*q.y), 1.-2.*(q.y*q.y+q.z*q.z));
    const double dx = goal.pose.position.x-start.pose.position.x;
    const double dy = goal.pose.position.y-start.pose.position.y;
    const double direct = std::hypot(dx, dy);
    const double limit = position_only_ ? M_PI : tolerance_;
    const double toward = std::clamp(std::remainder(std::atan2(dy, dx)-heading, 2.*M_PI),
      -limit, limit);
    // Try the direct approach first; retain the exact request and both edges
    // as alternatives when obstacles or the starting heading require a curve.
    std::vector<double> offsets;
    std::vector<double> choices{toward};
    if (position_only_) {
      const auto & r = start.pose.orientation;
      const double start_heading = std::atan2(2.*(r.w*r.z+r.x*r.y), 1.-2.*(r.y*r.y+r.z*r.z));
      choices.push_back(std::remainder(start_heading-heading, 2.*M_PI));
      choices.push_back(toward-M_PI/2.);
      choices.push_back(toward+M_PI/2.);
    }
    choices.insert(choices.end(), {0., -limit, limit});
    for (double value : choices) {
      if (std::none_of(offsets.begin(), offsets.end(), [value](double old) {
        return std::abs(std::remainder(value-old, 2.*M_PI)) < .02;
      })) {offsets.push_back(value);}
    }
    const auto begun = std::chrono::steady_clock::now();
    nav_msgs::msg::Path best;
    double best_length = std::numeric_limits<double>::infinity();
    for (double offset : offsets) {
      if (std::chrono::duration<double>(std::chrono::steady_clock::now()-begun).count() > 1.) {
        break;
      }
      auto candidate = goal;
      candidate.pose.orientation.x = candidate.pose.orientation.y = 0.;
      candidate.pose.orientation.z = std::sin((heading+offset)/2.);
      candidate.pose.orientation.w = std::cos((heading+offset)/2.);
      nav_msgs::msg::Path path;
      try {path = SmacPlannerHybrid::createPlan(start, candidate);}
      catch (const std::runtime_error &) {continue;}
      if (path.poses.empty()) {continue;}
      double length = 0.;
      for (size_t i=1; i<path.poses.size(); ++i) {
        const auto & a = path.poses[i-1].pose.position;
        const auto & b = path.poses[i].pose.position;
        length += std::hypot(a.x-b.x, a.y-b.y);
      }
      if (length < best_length) {best_length = length; best = std::move(path);}
      if (best_length <= direct*1.03+.10) {break;}
    }
    if (best.poses.empty()) {throw std::runtime_error("No collision-free approach within heading tolerance");}
    // Keep the feasible approach orientation for position goals. Constrained
    // goals still use the requested heading for the goal checker.
    if (!position_only_) {best.poses.back().pose.orientation = goal.pose.orientation;}
    return best;
  }
private:
  double tolerance_{0.};
  bool position_only_{true};
};
}  // namespace dori_navigation
PLUGINLIB_EXPORT_CLASS(dori_navigation::RelaxedHeadingPlanner, nav2_core::GlobalPlanner)
