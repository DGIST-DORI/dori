#include "dori_bt/actions/wait_for_intent_node.hpp"

namespace dori_bt
{

WaitForIntentNode::WaitForIntentNode(
  const std::string & xml_tag_name,
  const std::string & action_name,
  const BT::NodeConfig & conf)
: nav2_behavior_tree::BtActionNode<dori_msgs::action::LLMQuery>(xml_tag_name, action_name, conf)
{
}

void WaitForIntentNode::on_tick()
{
  std::string user_text;
  if (!getInput("text", user_text)) {
    RCLCPP_ERROR(node_->get_logger(), "WaitForIntentNode: Missing required input [text]");
    throw BT::RuntimeError("Missing required input [text]");
  }

  // LLM 서버로 보낼 Goal 설정
  goal_.text = user_text;
  
  // 위치 컨텍스트는 선택사항으로 처리
  std::string loc_context;
  if (getInput("location_context", loc_context)) {
    goal_.location_context = loc_context;
  } else {
    goal_.location_context = "";
  }
  
  RCLCPP_INFO(node_->get_logger(), "WaitForIntentNode sending text to LLM: '%s'", user_text.c_str());
}

BT::NodeStatus WaitForIntentNode::on_success()
{
  // LLM 처리가 성공하면 결과를 Blackboard 포트로 출력 (xml 변수로 매핑됨)
  setOutput("intent", result_.result->intent);
  setOutput("destination", result_.result->target_location);
  setOutput("answer", result_.result->response_text);
  
  RCLCPP_INFO(node_->get_logger(), "WaitForIntentNode Success! Intent: %s", result_.result->intent.c_str());
  
  return BT::NodeStatus::SUCCESS;
}

}  // namespace dori_bt
