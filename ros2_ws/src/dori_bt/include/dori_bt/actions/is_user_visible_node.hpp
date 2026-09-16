#ifndef DORI_BT_IS_USER_VISIBLE_NODE_HPP_
#define DORI_BT_IS_USER_VISIBLE_NODE_HPP_

#include <behaviortree_cpp/condition_node.h>
#include <rclcpp/rclcpp.hpp>

namespace dori_bt
{

class IsUserVisibleNode : public BT::ConditionNode
{
public:
  IsUserVisibleNode(const std::string & xml_tag_name, const BT::NodeConfig & conf);

  static BT::PortsList providedPorts() { return {}; } // 입력 포트 불필요

  BT::NodeStatus tick() override;

private:
  rclcpp::Node::SharedPtr node_;
};

}  // namespace dori_bt

#endif  // DORI_BT_IS_USER_VISIBLE_NODE_HPP_
