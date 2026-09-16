#ifndef DORI_BT_IS_ROBOT_MODE_NODE_HPP_
#define DORI_BT_IS_ROBOT_MODE_NODE_HPP_

#include <string>
#include <behaviortree_cpp/condition_node.h>
#include <rclcpp/rclcpp.hpp>

namespace dori_bt
{

class IsRobotModeNode : public BT::ConditionNode
{
public:
  IsRobotModeNode(const std::string & xml_tag_name, const BT::NodeConfig & conf);

  // XML에서 <IsRobotMode mode="..."/> 형태로 받을 포트 정의
  static BT::PortsList providedPorts()
  {
    return { BT::InputPort<std::string>("mode", "Target mode to check against") };
  }

  // 조건 노드는 on_tick()이 아니라 tick()을 바로 오버라이딩합니다.
  BT::NodeStatus tick() override;

private:
  rclcpp::Node::SharedPtr node_;
};

}  // namespace dori_bt

#endif  // DORI_BT_IS_ROBOT_MODE_NODE_HPP_
