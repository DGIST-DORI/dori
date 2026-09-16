#include "dori_bt/actions/speak_node.hpp"

namespace dori_bt
{

SpeakNode::SpeakNode(
  const std::string & xml_tag_name,
  const std::string & action_name,
  const BT::NodeConfig & conf)
: nav2_behavior_tree::BtActionNode<dori_msgs::action::Speak>(xml_tag_name, action_name, conf)
{
}

void SpeakNode::on_tick()
{
  std::string text_to_speak;
  
  // XML 태그의 'text' 속성값(또는 Blackboard 변수)을 가져옵니다.
  // 예: <Speak text="{answer}"/> 이면 {answer} 변수의 실제 문자열을 가져옴
  if (!getInput("text", text_to_speak)) {
    RCLCPP_ERROR(node_->get_logger(), "SpeakNode: Missing required input [text]");
    throw BT::RuntimeError("Missing required input [text]");
  }

  // Action Server로 보낼 Goal 객체에 데이터 세팅
  goal_.text = text_to_speak;
  
  RCLCPP_INFO(node_->get_logger(), "SpeakNode requesting TTS: '%s'", text_to_speak.c_str());
}

BT::NodeStatus SpeakNode::on_success()
{
  RCLCPP_INFO(node_->get_logger(), "SpeakNode: TTS Playback Succeeded");
  return BT::NodeStatus::SUCCESS;
}

BT::NodeStatus SpeakNode::on_aborted()
{
  RCLCPP_ERROR(node_->get_logger(), "SpeakNode: TTS Playback Aborted/Failed");
  return BT::NodeStatus::FAILURE;
}

BT::NodeStatus SpeakNode::on_cancelled()
{
  RCLCPP_INFO(node_->get_logger(), "SpeakNode: TTS Playback Cancelled");
  // 취소되었을 때 트리의 부모 노드(Fallback 등)가 어떻게 반응할지 결정
  return BT::NodeStatus::SUCCESS; 
}

}  // namespace dori_bt