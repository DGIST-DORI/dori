// Read-only TF publisher attribution for ROS 2 Humble (rclpy omits publisher GID).
#include <rclcpp/rclcpp.hpp>
#include <tf2_msgs/msg/tf_message.hpp>
#include <chrono>
#include <map>
#include <set>
#include <array>
#include <algorithm>
#include <iostream>
int main(int argc, char **argv) {
  rclcpp::init(argc, argv);
  auto n=std::make_shared<rclcpp::Node>("tf_authority_check");
  double duration=n->declare_parameter("duration",5.0);
  using Gid=std::array<uint8_t,RMW_GID_STORAGE_SIZE>;
  std::map<std::pair<std::string,std::string>,std::set<Gid>> edges;
  auto sub=n->create_subscription<tf2_msgs::msg::TFMessage>("/tf",rclcpp::SensorDataQoS(),
    [&](tf2_msgs::msg::TFMessage::ConstSharedPtr msg,const rclcpp::MessageInfo &info) {
      Gid gid; auto raw=info.get_rmw_message_info().publisher_gid;
      std::copy(raw.data,raw.data+RMW_GID_STORAGE_SIZE,gid.begin());
      for(const auto &t:msg->transforms) edges[{t.header.frame_id,t.child_frame_id}].insert(gid);
    });
  auto end=std::chrono::steady_clock::now()+std::chrono::duration<double>(duration);
  while(rclcpp::ok() && std::chrono::steady_clock::now()<end) {
    rclcpp::spin_some(n); std::this_thread::sleep_for(std::chrono::milliseconds(5));
  }
  auto pubs=n->get_publishers_info_by_topic("/tf");
  for(const auto &edge:edges) for(const auto &gid:edge.second) {
    std::string owner="unknown";
    for(const auto &p:pubs) if(p.endpoint_gid()==gid) owner=p.node_name();
    std::cout<<"EDGE\t"<<edge.first.first<<"\t"<<edge.first.second<<"\t"<<owner<<"\n";
  }
  rclcpp::shutdown(); return 0;
}
