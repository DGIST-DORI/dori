#include "dori_bt/conditions/is_robot_mode_node.hpp"

namespace dori_bt
{

IsRobotModeNode::IsRobotModeNode(
  const std::string & xml_tag_name,
  const BT::NodeConfig & conf)
: BT::ConditionNode(xml_tag_name, conf)
{
  // Blackboard에서 ROS 2 메인 노드 포인터를 가져옵니다.
  if (!config().blackboard->get("node", node_)) {
    throw BT::RuntimeError("IsRobotModeNode: Missing 'node' in Blackboard");
  }
}

BT::NodeStatus IsRobotModeNode::tick()
{
  std::string target_mode;
  if (!getInput("mode", target_mode)) {
    RCLCPP_ERROR(node_->get_logger(), "IsRobotModeNode: Missing input [mode]");
    return BT::NodeStatus::FAILURE;
  }

  // 현재 로봇의 모드를 Blackboard에서 읽어옵니다.
  // (메인 실행 노드나 별도의 토픽 콜백이 이 값을 주기적으로 갱신해 주어야 합니다)
  std::string current_mode = "IDLE"; 
  config().blackboard->get("current_robot_mode", current_mode);

  if (current_mode == target_mode) {
    return BT::NodeStatus::SUCCESS;
  }
  
  return BT::NodeStatus::FAILURE;
}

}  // namespace dori_bt
