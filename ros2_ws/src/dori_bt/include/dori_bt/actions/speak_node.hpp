#ifndef DORI_BT_SPEAK_NODE_HPP_
#define DORI_BT_SPEAK_NODE_HPP_

#include <string>
#include <behaviortree_cpp/behavior_tree.h>
#include "nav2_behavior_tree/bt_action_node.hpp"
#include "dori_msgs/action/speak.hpp" // 우리가 정의한 커스텀 Action 메시지

namespace dori_bt
{

class SpeakNode : public nav2_behavior_tree::BtActionNode<dori_msgs::action::Speak>
{
public:
  SpeakNode(
    const std::string & xml_tag_name,
    const std::string & action_name,
    const BT::NodeConfig & conf);

  // XML에서 <Speak text="..."> 형태로 받을 포트를 정의
  static BT::PortsList providedPorts()
  {
    return providedBasicPorts({
      BT::InputPort<std::string>("text", "Text for the robot to speak")
    });
  }

protected:
  // Action Server에 요청(Goal)을 보내기 직전에 호출됨
  void on_tick() override;

  // Action Server에서 성공(Succeed) 결과를 받았을 때 호출됨
  BT::NodeStatus on_success() override;

  // Action Server에서 에러(Abort) 결과를 받았을 때 호출됨
  BT::NodeStatus on_aborted() override;

  // 트리가 도중에 취소(Cancel)되었을 때 호출됨
  BT::NodeStatus on_cancelled() override;
};

}  // namespace dori_bt

#endif  // DORI_BT_SPEAK_NODE_HPP_
