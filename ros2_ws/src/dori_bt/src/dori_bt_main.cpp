#include <memory>
#include <string>
#include <chrono>

#include <rclcpp/rclcpp.hpp>
#include <behaviortree_cpp/bt_factory.h>
#include <ament_index_cpp/get_package_share_directory.hpp>
#include <std_msgs/msg/string.hpp>

// 우리가 작성한 커스텀 노드 헤더 파일들
#include "dori_bt/actions/speak_node.hpp"
#include "dori_bt/actions/wait_for_intent_node.hpp"
#include "dori_bt/conditions/is_robot_mode_node.hpp"
#include "dori_bt/conditions/is_user_visible_node.hpp"

using namespace std::chrono_literals;

class DoriTreeExecutor : public rclcpp::Node
{
public:
  DoriTreeExecutor() : Node("dori_tree_executor")
  {
    // 1. Blackboard 생성 및 메인 노드 포인터 주입
    blackboard_ = BT::Blackboard::create();
    blackboard_->set<rclcpp::Node::SharedPtr>("node", this);
    
    // 초기 상태 세팅
    blackboard_->set<std::string>("current_robot_mode", "IDLE");
    blackboard_->set<bool>("user_visible", false);

    // 2. BehaviorTree Factory 생성 및 커스텀 노드 등록
    BT::BehaviorTreeFactory factory;
    factory.registerNodeType<dori_bt::SpeakNode>("Speak");
    factory.registerNodeType<dori_bt::WaitForIntentNode>("WaitForIntent");
    factory.registerNodeType<dori_bt::IsRobotModeNode>("IsRobotMode");
    factory.registerNodeType<dori_bt::IsUserVisibleNode>("IsUserVisible");

    // Nav2 기본 BT 플러그인 등록 (주행 관련 노드 사용 시)
    // 예: factory.registerFromPlugin("nav2_navigate_to_pose_bt_node"); 

    // 3. XML 파일 동적 로드 (ament_index_cpp 활용)
    std::string pkg_share_dir = ament_index_cpp::get_package_share_directory("dori_bt");
    std::string xml_path = pkg_share_dir + "/behavior_trees/dori_tree.xml";
    
    RCLCPP_INFO(this->get_logger(), "Loading XML from: %s", xml_path.c_str());
    tree_ = factory.createTreeFromFile(xml_path, blackboard_);

    // 4. ROS 2 Subscriber 세팅 (블랙보드 업데이트용)
    tracking_sub_ = this->create_subscription<std_msgs::msg::String>(
      "hri/tracking_state", 10,
      std::bind(&DoriTreeExecutor::tracking_callback, this, std::placeholders::_1)
    );

    // 5. 트리 실행 타이머 (10Hz)
    timer_ = this->create_wall_timer(
      100ms, std::bind(&DoriTreeExecutor::tick_tree, this)
    );

    RCLCPP_INFO(this->get_logger(), "Dori BT Executor Started successfully.");
  }

private:
  void tick_tree()
  {
    // BehaviorTree.CPP v4 방식의 메인 틱 함수
    // 트리가 RUNNING을 반환할 때까지 노드들을 순회하며 상태를 갱신합니다.
    BT::NodeStatus status = tree_.tickExactlyOnce();
    
    // 전체 트리가 끝났을 때(SUCCESS or FAILURE)의 예외 처리
    if (status == BT::NodeStatus::SUCCESS || status == BT::NodeStatus::FAILURE) {
      RCLCPP_INFO(this->get_logger(), "Tree finished with status: %s. Restarting...", BT::toStr(status).c_str());
      // 필요시 sleep을 주거나 로봇 모드를 IDLE로 리셋하는 로직 추가
    }
  }

  void tracking_callback(const std_msgs::msg::String::SharedPtr msg)
  {
    // 실제로는 nlohmann/json 등을 사용해 파싱하는 것이 좋습니다.
    // 여기서는 예시로 문자열 검색을 사용합니다.
    if (msg->data.find("\"target_id\":") != std::string::npos && 
        msg->data.find("\"state\": \"tracking\"") != std::string::npos) {
      blackboard_->set<bool>("user_visible", true);
    } else {
      blackboard_->set<bool>("user_visible", false);
    }
  }

  BT::Tree tree_;
  BT::Blackboard::Ptr blackboard_;
  rclcpp::TimerBase::SharedPtr timer_;
  rclcpp::Subscription<std_msgs::msg::String>::SharedPtr tracking_sub_;
};

int main(int argc, char **argv)
{
  rclcpp::init(argc, argv);
  auto node = std::make_shared<DoriTreeExecutor>();
  rclcpp::spin(node);
  rclcpp::shutdown();
  return 0;
}
