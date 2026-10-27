#include <algorithm>
#include <chrono>
#include <cmath>
#include <deque>
#include <memory>
#include <string>
#include <nlohmann/json.hpp>
#include <behaviortree_cpp_v3/bt_factory.h>
#include <ament_index_cpp/get_package_share_directory.hpp>
#include <std_msgs/msg/string.hpp>
#include <std_msgs/msg/bool.hpp>
#include <std_msgs/msg/int32.hpp>
#include <nav2_msgs/msg/speed_limit.hpp>
#include <std_srvs/srv/set_bool.hpp>
#include "dori_bt/ros_action.hpp"
#include "dori_msgs/action/llm_query.hpp"
#include "dori_msgs/action/speak.hpp"
#include "dori_msgs/action/navigate_named.hpp"

using namespace std::chrono_literals;
using Json = nlohmann::json;
using String = std_msgs::msg::String;
using Bool = std_msgs::msg::Bool;
using Int = std_msgs::msg::Int32;
using Clock = std::chrono::steady_clock;

class Query : public dori_bt::RosAction<dori_msgs::action::LLMQuery> {
public:
  Query(const std::string &n, const BT::NodeConfiguration &c)
    : RosAction(n,c,"llm/query",45.) {}
  static BT::PortsList providedPorts() { return {BT::InputPort<std::string>("text"),
    BT::OutputPort<std::string>("intent"), BT::OutputPort<std::string>("destination"),
    BT::OutputPort<std::string>("answer")}; }
  bool prepare(dori_msgs::action::LLMQuery::Goal &g) override {
    config().blackboard->get("location_context",g.location_context);
    return getInput("text",g.text) && !g.text.empty();
  }
  bool complete(const dori_msgs::action::LLMQuery::Result &r) override {
    setOutput("intent",r.intent); setOutput("destination",r.target_location);
    setOutput("answer",r.response_text);
    return r.intent != "error" && r.intent != "canceled";
  }
};
class Speak : public dori_bt::RosAction<dori_msgs::action::Speak> {
public:
  Speak(const std::string &n, const BT::NodeConfiguration &c) : RosAction(n,c,"tts/speak",60.) {}
  static BT::PortsList providedPorts() { return {BT::InputPort<std::string>("text")}; }
  bool prepare(dori_msgs::action::Speak::Goal &g) override { return getInput("text",g.text) && !g.text.empty(); }
  bool complete(const dori_msgs::action::Speak::Result &r) override { return r.success; }
};
class Navigate : public dori_bt::RosAction<dori_msgs::action::NavigateNamed> {
public:
  Navigate(const std::string &n, const BT::NodeConfiguration &c) : RosAction(n,c,"nav/navigate_named",930.) {}
  static BT::PortsList providedPorts() { return {BT::InputPort<std::string>("goal")}; }
  bool prepare(dori_msgs::action::NavigateNamed::Goal &g) override {
    return getInput("goal",g.destination) && !g.destination.empty();
  }
  bool complete(const dori_msgs::action::NavigateNamed::Result &r) override { return r.code == 0; }
};

class DoriTreeExecutor : public rclcpp::Node {
public:
  DoriTreeExecutor() : Node("dori_tree_executor") {
    auto xml = declare_parameter<std::string>("tree_xml_file", "");
    tracking_required_ = declare_parameter("require_user_tracking", false);
    mic_required_ = declare_parameter("require_mic_return", false);
    recovery_timeout_ = declare_parameter("user_recovery_timeout", 10.);
    access_timeout_ = declare_parameter("access_timeout", 60.);
    idle_goals_ = declare_parameter<std::vector<std::string>>("idle_goals", std::vector<std::string>{});
    idle_interval_ = declare_parameter("idle_interval", 60.);
    auto latch = rclcpp::QoS(1).transient_local();
    state_pub_ = create_publisher<String>("hri/manager_state", latch);
    status_pub_ = create_publisher<String>("hri/status", latch);
    cue_pub_ = create_publisher<String>("hri/audio_cue", 10);
    speech_pub_ = create_publisher<String>("tts/text", 10);
    mode_pub_ = create_publisher<Int>("/NAVIGATION_MODE",10);
    speed_pub_ = create_publisher<nav2_msgs::msg::SpeedLimit>("/speed_limit",10);
    follow_ = create_client<std_srvs::srv::SetBool>("hri/set_follow_mode");
    bb_ = BT::Blackboard::create();
    bb_->set<rclcpp::Node*>("node",this);
    bb_->set("location_context",std::string{});
    BT::BehaviorTreeFactory factory;
    factory.registerNodeType<Query>("WaitForIntent");
    factory.registerNodeType<Speak>("Speak");
    factory.registerNodeType<Navigate>("NavigateToNamedGoal");
    factory.registerSimpleCondition("HasRequest",[this](BT::TreeNode&) {
      if (pending_.empty()) return BT::NodeStatus::FAILURE;
      current_text_ = pending_.front(); pending_.pop_front();
      bb_->set("location_context",std::chrono::duration<double>(Clock::now()-landmark_time_).count()<5. ? landmark_context_ : "");
      bb_->set("user_text",current_text_); return BT::NodeStatus::SUCCESS;
    });
    factory.registerSimpleAction("SetRobotMode",[this](BT::TreeNode &self) {
      std::string mode; if (!self.getInput("mode",mode)) return BT::NodeStatus::FAILURE;
      set_mode(mode); return BT::NodeStatus::SUCCESS;
    },{BT::InputPort<std::string>("mode")});
    factory.registerSimpleCondition("IsGuide",[this](BT::TreeNode&) {
      std::string intent, dest; bb_->get("intent",intent); bb_->get("destination",dest);
      return intent == "navigation" && !dest.empty() ? BT::NodeStatus::SUCCESS : BT::NodeStatus::FAILURE;
    });
    factory.registerSimpleAction("PrepareGuide",[this](BT::TreeNode&) {
      if (blocked_ || (tracking_required_ && !user_visible())) return BT::NodeStatus::FAILURE;
      set_mode("GUIDING"); return BT::NodeStatus::SUCCESS;
    });
    factory.registerSimpleAction("CompleteSession",[this](BT::TreeNode&) {
      current_text_.clear(); follow(false);
      if (mic_required_ && !mic_attached_) { set_mode("WAIT_MIC_RETURN"); say("마이크를 제자리에 돌려주세요."); }
      else set_mode("IDLE");
      return BT::NodeStatus::SUCCESS;
    });
    if (xml.empty()) xml = ament_index_cpp::get_package_share_directory("dori_bt")+"/behavior_trees/dori_tree.xml";
    tree_ = factory.createTreeFromFile(xml,bb_);
    stt_ = create_subscription<String>("stt/result",10,[this](String::SharedPtr msg) {
      try {
        auto data=Json::parse(msg->data);
        auto text=data.value("text",std::string{});
        if (data.value("event",std::string{"stt_result"}) != "stt_result" ||
            data.value("confidence",1.) < .55 || text.empty() || text.size()>2400) return;
        if (is_stop(text)) { interrupt("CANCELED",false); return; }
        if (mode_ == "IDLE" || mode_ == "LISTENING" || mode_ == "INTERACTION") {
          pending_.clear(); pending_.push_back(text); follow(true);
        }
      } catch (const std::exception &e) { RCLCPP_WARN(get_logger(),"Invalid STT: %s",e.what()); }
    });
    wake_ = create_subscription<Bool>("stt/wake_word_detected",10,[this](Bool::SharedPtr m) {
      if (!m->data) return;
      wake();
    });
    trigger_ = create_subscription<Bool>("hri/interaction_trigger",10,[this](Bool::SharedPtr m) {
      if(m->data && !nearby_ && mode_=="IDLE") wake();
      nearby_=m->data;
    });
    landmark_ = create_subscription<String>("landmark/context",10,[this](String::SharedPtr m) {
      if(m->data.size()<=2000) { landmark_context_=m->data; landmark_time_=Clock::now(); }
    });
    gesture_ = create_subscription<String>("hri/gesture_command",10,[this](String::SharedPtr m) {
      try {
        auto j=Json::parse(m->data); auto command=j.value("command",std::string{});
        if(command=="STOP") interrupt("CANCELED",false);
        else if(command=="CALL") wake();
        else if(command=="CONFIRM" && (mode_=="IDLE" || mode_=="LISTENING")) say("확인했습니다. 목적지를 말씀해주세요.");
        else if(command=="DIRECTION_HINT" && mode_=="LISTENING") say("안내할 목적지 이름을 말씀해주세요.");
      } catch (...) { RCLCPP_WARN(get_logger(),"Invalid gesture command"); }
    });
    expression_ = create_subscription<String>("hri/expression_command",10,[this](String::SharedPtr m) {
      try {
        auto j=Json::parse(m->data); auto command=j.value("command",std::string{});
        if(command=="REPEAT_GUIDANCE" && (mode_=="IDLE" || mode_=="LISTENING" || mode_=="GUIDING")) {
          std::string answer; bb_->get("answer",answer);
          say(answer.empty() ? "어떤 내용을 다시 설명해드릴까요?" : answer);
        } else if(command=="GUIDANCE_COMPLETE" && (mode_=="IDLE" || mode_=="LISTENING")) {
          say("안내가 도움이 되셨다니 다행입니다!"); follow(false); set_mode("IDLE");
        }
        // Visual approval cannot mark an in-progress navigation as arrived.
      } catch (...) { RCLCPP_WARN(get_logger(),"Invalid expression command"); }
    });
    mic_ = create_subscription<Bool>("hri/mic_attached",10,[this](Bool::SharedPtr m) {
      bool detached=mic_attached_ && !m->data; mic_attached_=m->data;
      if (detached) { interrupt("LISTENING",false); cue("wake_chime"); follow(true); }
      if (mic_attached_ && mode_=="WAIT_MIC_RETURN") set_mode("IDLE");
    });
    track_ = create_subscription<String>("hri/tracking_state",10,[this](String::SharedPtr m) {
      try { auto j=Json::parse(m->data); visible_=j.value("state",std::string{})=="tracking";
        distance_=j.value("last_distance_m",0.); tracking_time_=Clock::now();
      } catch (...) { visible_=false; }
    });
    access_ = create_subscription<Bool>("hri/access_blocked",10,[this](Bool::SharedPtr m) { blocked_=m->data; });
    cancel_ = create_subscription<Bool>("hri/cancel",10,[this](Bool::SharedPtr m) { if(m->data) interrupt("CANCELED",false); });
    estop_ = create_subscription<Bool>("/emergency_stop",10,[this](Bool::SharedPtr m) { if(m->data) interrupt("CANCELED",false); });
    hardware_ = create_subscription<Int>("/system/action_state",latch,[this](Int::SharedPtr m) {
      if(m->data>=2 && mode_=="GUIDING") interrupt("ERROR",false);
    });
    timer_=create_wall_timer(100ms,[this] { tick(); });
    set_mode("IDLE");
  }
  void stop() { tree_.haltTree(); stop_motion(); }
private:
  void wake() {
    if(std::chrono::duration<double>(Clock::now()-wake_time_).count()<1.5) return;
    wake_time_=Clock::now(); interrupt("LISTENING",false); cue("wake_chime"); follow(true);
  }
  static bool is_stop(std::string text) {
    std::transform(text.begin(),text.end(),text.begin(),[](unsigned char c) { return std::tolower(c); });
    return text=="stop" || text=="cancel" || text=="정지" || text=="멈춰" || text=="취소" || text=="그만" || text=="멈춰줘" || text=="취소해줘" ||
      text=="안내 취소" || text=="please stop" || text=="stop please" || text=="cancel navigation";
  }
  void set_mode(const std::string &mode) {
    mode_=mode; changed_=Clock::now(); publish_state();
    RCLCPP_INFO(get_logger(),"HRI state: %s",mode.c_str());
  }
  void publish_state() {
    double elapsed=std::chrono::duration<double>(Clock::now()-changed_).count();
    String msg; msg.data=Json{{"state",mode_},{"state_elapsed_sec",elapsed}}.dump(); state_pub_->publish(msg);
    msg.data=Json{{"state",mode_},{"user_visible",user_visible()},{"mic_attached",mic_attached_},
      {"access_blocked",blocked_},{"tracking_required",tracking_required_}}.dump(); status_pub_->publish(msg);
  }
  bool user_visible() const { return visible_ && std::chrono::duration<double>(Clock::now()-tracking_time_).count()<1.; }
  void say(const std::string &text) { String m; m.data=text; speech_pub_->publish(m); }
  void cue(const std::string &name) { String m; m.data=name; cue_pub_->publish(m); }
  void follow(bool enable) {
    if (follow_->service_is_ready()) { auto r=std::make_shared<std_srvs::srv::SetBool::Request>(); r->data=enable; follow_->async_send_request(r); }
  }
  void stop_motion() { Int m; m.data=0; mode_pub_->publish(m); }
  void interrupt(const std::string &state,bool recover) {
    resume_text_=recover ? current_text_ : "";
    tree_.haltTree(); stop_motion(); pending_.clear(); current_text_.clear();
    set_mode(state);
    if(state=="USER_LOST_CONFIRM") say("잘 따라오고 계신가요?");
    if(state=="ACCESS_HELP") say("문이나 엘리베이터 이용을 도와주세요.");
    if(!recover) follow(false);
  }
  void tick() {
    publish_state();
    double elapsed=std::chrono::duration<double>(Clock::now()-changed_).count();
    if(mode_=="GUIDING") {
      if(blocked_) { interrupt("ACCESS_HELP",true); return; }
      if(tracking_required_ && !user_visible()) { interrupt("USER_LOST_CONFIRM",true); return; }
      nav2_msgs::msg::SpeedLimit limit; limit.header.stamp=now(); limit.percentage=true;
      limit.speed_limit=user_visible() && distance_>2. ? 50. : 100.; speed_pub_->publish(limit);
    }
    if(mode_=="USER_LOST_CONFIRM" || mode_=="ACCESS_HELP") {
      bool recovered=mode_=="ACCESS_HELP" ? !blocked_ : user_visible();
      double timeout=mode_=="ACCESS_HELP" ? access_timeout_ : recovery_timeout_;
      if(elapsed>timeout) { resume_text_.clear(); follow(false); set_mode("IDLE"); return; }
      // Allow downstream cancellation to finish before reissuing a session.
      if(!recovered || elapsed<1.) return;
      pending_.push_back(resume_text_); resume_text_.clear(); set_mode("INTERACTION");
    }
    if(mode_=="ERROR" || mode_=="CANCELED") { if(elapsed>2.) set_mode("IDLE"); return; }
    if(mode_=="WAIT_MIC_RETURN") { if(elapsed>30.) { say("마이크를 돌려주세요. 안내를 종료합니다."); set_mode("IDLE"); } return; }
    if(mode_=="LISTENING" && elapsed>30.) { follow(false); set_mode("IDLE"); }
    if(mode_=="IDLE" && mic_attached_ && !blocked_ && pending_.empty() && !idle_goals_.empty() && elapsed>idle_interval_) {
      // Optional patrol is constrained to registered map destinations.
      pending_.push_back("안내해줘 "+idle_goals_[patrol_index_++ % idle_goals_.size()]);
    }
    if(pending_.empty() && (mode_=="IDLE" || mode_=="LISTENING")) return;
    try {
      auto result=tree_.tickRoot();
      if(result==BT::NodeStatus::FAILURE) { interrupt("ERROR",false); say("요청을 완료하지 못했습니다. 상태를 확인해주세요."); }
    } catch(const std::exception &e) { RCLCPP_ERROR(get_logger(),"BT failure: %s",e.what()); interrupt("ERROR",false); }
  }
  BT::Tree tree_; BT::Blackboard::Ptr bb_;
  std::string mode_="IDLE",current_text_,resume_text_,landmark_context_;
  std::deque<std::string> pending_;
  bool tracking_required_,mic_required_,visible_=false,blocked_=false,mic_attached_=true,nearby_=false;
  double distance_=0.,recovery_timeout_,access_timeout_,idle_interval_;
  std::vector<std::string> idle_goals_; size_t patrol_index_=0;
  Clock::time_point changed_=Clock::now(),tracking_time_{},landmark_time_{},wake_time_{};
  rclcpp::Publisher<String>::SharedPtr state_pub_,status_pub_,cue_pub_,speech_pub_;
  rclcpp::Publisher<Int>::SharedPtr mode_pub_;
  rclcpp::Publisher<nav2_msgs::msg::SpeedLimit>::SharedPtr speed_pub_;
  rclcpp::Client<std_srvs::srv::SetBool>::SharedPtr follow_;
  rclcpp::Subscription<String>::SharedPtr stt_,track_,gesture_,expression_,landmark_;
  rclcpp::Subscription<Bool>::SharedPtr wake_,mic_,access_,cancel_,estop_,trigger_;
  rclcpp::Subscription<Int>::SharedPtr hardware_;
  rclcpp::TimerBase::SharedPtr timer_;
};
int main(int argc,char **argv) {
  rclcpp::init(argc,argv);
  auto node=std::make_shared<DoriTreeExecutor>();
  rclcpp::spin(node);
  if (rclcpp::ok()) node->stop();
  rclcpp::shutdown();
  return 0;
}
