#include "dori_bt/conditions/is_user_visible_node.hpp"

namespace dori_bt
{

IsUserVisibleNode::IsUserVisibleNode(
  const std::string & xml_tag_name,
  const BT::NodeConfig & conf)
: BT::ConditionNode(xml_tag_name, conf)
{
  if (!config().blackboard->get("node", node_)) {
    throw BT::RuntimeError("IsUserVisibleNode: Missing 'node' in Blackboard");
  }
}

BT::NodeStatus IsUserVisibleNode::tick()
{
  // Blackboard에서 사람 인식 모듈(HRI)이 갱신해둔 플래그를 읽습니다.
  bool is_visible = false;
  
  // 만약 변수가 세팅되어 있지 않다면, 기본적으로 안 보이는 것(false)으로 간주합니다.
  if (config().blackboard->get("user_visible", is_visible)) {
    if (is_visible) {
      // RCLCPP_DEBUG를 써서 로그가 너무 많이 찍히는 것을 방지
      RCLCPP_DEBUG(node_->get_logger(), "IsUserVisibleNode: SUCCESS (User is visible)");
      return BT::NodeStatus::SUCCESS;
    }
  }

  return BT::NodeStatus::FAILURE;
}

}  // namespace dori_bt
