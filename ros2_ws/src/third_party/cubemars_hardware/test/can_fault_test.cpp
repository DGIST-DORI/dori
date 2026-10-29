#include <sys/socket.h>
#include <linux/can.h>
#include <cerrno>
#include <chrono>
#include <cmath>
#include <cstring>
#include <deque>
#include <iostream>
#include <stdexcept>
#include <vector>
#include <thread>
#include "cubemars_hardware/can.hpp"
#include "cubemars_hardware/system.hpp"

static std::vector<int> errors;
static size_t calls = 0;
static int repeated_error = 0;
static bool short_write = false;
static std::chrono::steady_clock::time_point ready_at{};
static std::vector<can_frame> frames;
static std::deque<can_frame> received;
static void require(bool value, const char * text) {if (!value) {throw std::runtime_error(text);}}
extern "C" ssize_t __wrap_send(int, const void * data, size_t size, int flags)
{
  require(flags & MSG_DONTWAIT, "CAN writes must be nonblocking");
  require(size == sizeof(can_frame), "CAN frame size changed");
  ++calls;
  if (std::chrono::steady_clock::now() < ready_at) {errno=ENOBUFS;return -1;}
  int error = calls <= errors.size() ? errors[calls-1] : repeated_error;
  if (error) {errno = error; return -1;}
  if (short_write) {return 1;}
  frames.push_back(*static_cast<const can_frame *>(data));
  return size;
}
extern "C" ssize_t __wrap_recv(int, void * data, size_t size, int flags)
{
  require(flags & MSG_DONTWAIT, "CAN reads must be nonblocking");
  require(size == sizeof(can_frame), "Read frame size changed");
  if (received.empty()) {errno=EAGAIN;return -1;}
  std::memcpy(data,&received.front(),size);received.pop_front();return size;
}
static void reset() {errors.clear(); calls=0; repeated_error=0; short_write=false; frames.clear();ready_at={};}
int main()
{
  try {
    cubemars_hardware::CanSocket can;
    const uint8_t payload[8] = {1,2,3,4,5,6,7,8};
    errors={ENOBUFS,EAGAIN,EINTR};
    require(can.write_message(2,payload,8,cubemars_hardware::CanSocket::FrameType::STANDARD), "Transient queue pressure should recover");
    require(calls==4 && frames.size()==1 && frames[0].can_id==2 && std::memcmp(frames[0].data,payload,8)==0, "Retry altered frame or duplicated accepted send");
    reset();ready_at=std::chrono::steady_clock::now()+std::chrono::milliseconds(4);
    require(can.write_message(2,payload,8) && frames.size()==1, "A short SLCAN stall must recover within one control period");
    reset(); repeated_error=ENETDOWN;
    require(!can.write_message(2,payload,8) && calls==1, "Permanent bus failure should not retry");
    reset(); repeated_error=ENOBUFS;
    const auto start=std::chrono::steady_clock::now();
    require(!can.write_message(2,payload,8), "Persistent queue pressure must fail");
    require(calls<=101 && std::chrono::steady_clock::now()-start < std::chrono::milliseconds(500), "Retry must be bounded");
    reset(); short_write=true;
    require(!can.write_message(2,payload,8) && calls==1, "Short send must fail");
    reset();
    cubemars_hardware::CubeMarsSystemHardware hardware;
    hardware_interface::HardwareInfo info;
    info.name="CubeMarsSystem";info.type="system";
    info.hardware_parameters={{"can_interface","unused_no_connection"},{"protocol_mode","mit"}};
    for (int id=1;id<=2;++id) {
      hardware_interface::ComponentInfo joint;
      joint.name=id==1?"left_wheel_joint":"right_wheel_joint";
      joint.type="joint";
      joint.parameters={{"can_id",std::to_string(id)},{"kt","0.1"},{"pole_pairs","14"},{"gear_ratio","10"},{"mit_vel_kd","3"}};
      info.joints.push_back(joint);
    }
    require(hardware.on_init(info)==hardware_interface::CallbackReturn::SUCCESS, "Hardware init failed");
    auto states=hardware.export_state_interfaces();
    for (int id=1;id<=2;++id) {
      can_frame feedback{};feedback.can_id=id;feedback.can_dlc=8;
      feedback.data[0]=id;feedback.data[1]=0x7f;feedback.data[2]=0xff;
      feedback.data[3]=0x7f;feedback.data[4]=0xf7;feedback.data[5]=0xff;
      feedback.data[6]=30;
      received.push_back(feedback);
    }
    hardware.read(rclcpp::Time(0),rclcpp::Duration::from_seconds(.01));
    for (auto & state:states) {if (state.get_interface_name()=="feedback_age") {require(std::isfinite(state.get_value()),"Injected feedback must initially be fresh");}}
    const std::vector<std::string> drive_interfaces = {
      "left_wheel_joint/velocity", "left_wheel_joint/effort",
      "right_wheel_joint/velocity", "right_wheel_joint/effort"};
    require(hardware.prepare_command_mode_switch(drive_interfaces, {}) == hardware_interface::return_type::OK, "Speed interfaces rejected");
    hardware.perform_command_mode_switch(drive_interfaces, {});
    auto commands = hardware.export_command_interfaces();
    for (auto & command : commands) command.set_value(0.0);
    reset(); repeated_error = ENOBUFS;
    require(hardware.write(rclcpp::Time(0), rclcpp::Duration::from_seconds(.01)) == hardware_interface::return_type::OK,
      "One congested cycle must not permanently disable hardware");
    require(frames.empty(), "Congested frame cannot be reported as sent");
    reset();
    require(hardware.write(rclcpp::Time(0), rclcpp::Duration::from_seconds(.01)) == hardware_interface::return_type::OK && frames.size() == 2,
      "Both wheels must resume on the next successful cycle");
    reset(); repeated_error = ENOBUFS;
    require(hardware.write(rclcpp::Time(0), rclcpp::Duration::from_seconds(.01)) == hardware_interface::return_type::OK, "New transient window");
    std::this_thread::sleep_for(std::chrono::milliseconds(110));
    require(hardware.write(rclcpp::Time(0), rclcpp::Duration::from_seconds(.01)) == hardware_interface::return_type::ERROR,
      "Persistent backpressure must still stop hardware");
    reset(); repeated_error = ENETDOWN;
    require(hardware.write(rclcpp::Time(0), rclcpp::Duration::from_seconds(.01)) == hardware_interface::return_type::ERROR,
      "Bus down must fail immediately");
    reset();
    require(hardware.on_error(rclcpp_lifecycle::State())==hardware_interface::CallbackReturn::ERROR, "Bus fault must require restart");
    size_t invalid=0;
    for (auto & state:states) {if (state.get_interface_name()=="feedback_age" && std::isinf(state.get_value())) {++invalid;}}
    require(invalid==2, "Both cached feedback ages must become invalid");
    require(frames.size()==4 && frames[1].data[7]==0xFD && frames[3].data[7]==0xFD, "Both motors must receive bounded stop/disable attempts");
    std::cout << "CAN transient/permanent/short-write and hardware-fault tests passed\n";
    return 0;
  } catch (const std::exception & e) {std::cerr<<e.what()<<'\n';return 1;}
}
