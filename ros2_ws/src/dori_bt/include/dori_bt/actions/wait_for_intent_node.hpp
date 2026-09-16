#ifndef DORI_BT_WAIT_FOR_INTENT_NODE_HPP_
#define DORI_BT_WAIT_FOR_INTENT_NODE_HPP_

#include <string>
#include <behaviortree_cpp/behavior_tree.h>
#include "nav2_behavior_tree/bt_action_node.hpp"
// LLM Action 메시지 헤더 (패키지 환경에 맞게 수정)
#include "dori_msgs/action/llm_query.hpp" 

namespace dori_bt
{

class WaitForIntentNode : public nav2_behavior_tree::BtActionNode<dori_msgs::action::LLMQuery>
{
public:
  WaitForIntentNode(
    const std::string & xml_tag_name,
    const std::string & action_name,
    const BT::NodeConfig & conf);

  // XML 포트 정의: 입력(text, location)과 출력(intent, destination, answer)
  static BT::PortsList providedPorts()
  {
    return providedBasicPorts({
      BT::InputPort<std::string>("text", "User speech text from STT"),
      BT::InputPort<std::string>("location_context", "Current location context (optional)"),
      BT::OutputPort<std::string>("intent", "Classified intent (e.g., GUIDE, QA)"),
      BT::OutputPort<std::string>("destination", "Target location for navigation"),
      BT::OutputPort<std::string>("answer", "LLM response text for TTS")
    });
  }

protected:
  void on_tick() override;
  BT::NodeStatus on_success() override;
};

}  // namespace dori_bt

#endif  // DORI_BT_WAIT_FOR_INTENT_NODE_HPP_