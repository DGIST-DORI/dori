#include "cubemars_hardware/can.hpp"

#include <linux/can.h>
#include <linux/can/raw.h>
#include <net/if.h>
#include <sys/ioctl.h>
#include <sys/socket.h>
#include <unistd.h>

#include <cerrno>
#include <cstring>
#include <vector>

#include "rclcpp/rclcpp.hpp"

namespace cubemars_hardware
{

bool CanSocket::connect(std::string can_itf, const std::vector<canid_t> & can_ids, canid_t can_mask)
{
  socket_ = socket(PF_CAN, SOCK_RAW, CAN_RAW);
  if (socket_ < 0) {
    RCLCPP_ERROR(
      rclcpp::get_logger("CubeMarsSystemHardware"),
      "Could not create socket");
    return false;
  }

  struct ifreq ifr;
  std::memset(&ifr, 0, sizeof(ifr));
  std::strncpy(ifr.ifr_name, can_itf.c_str(), IFNAMSIZ - 1);
  ifr.ifr_name[IFNAMSIZ - 1] = '\0';

  if (ioctl(socket_, SIOCGIFINDEX, &ifr) < 0) {
    RCLCPP_ERROR(
      rclcpp::get_logger("CubeMarsSystemHardware"),
      "Could not get CAN interface index");
    return false;
  }

  struct sockaddr_can addr;
  std::memset(&addr, 0, sizeof(addr));
  addr.can_family = AF_CAN;
  addr.can_ifindex = ifr.ifr_ifindex;

  if (bind(socket_, reinterpret_cast<struct sockaddr *>(&addr), sizeof(addr)) < 0)
  {
    RCLCPP_ERROR(
      rclcpp::get_logger("CubeMarsSystemHardware"),
      "Could not bind CAN interface");
    return false;
  }

  can_mask_ = can_mask;

  if (!can_ids.empty())
  {
    std::vector<struct can_filter> rfilter(can_ids.size());
    for (std::size_t i = 0; i < can_ids.size(); i++)
    {
      rfilter[i].can_id = can_ids[i];
      rfilter[i].can_mask = can_mask_;
    }

    if (setsockopt(
          socket_,
          SOL_CAN_RAW,
          CAN_RAW_FILTER,
          rfilter.data(),
          static_cast<socklen_t>(rfilter.size() * sizeof(struct can_filter))) < 0)
    {
      RCLCPP_WARN(
        rclcpp::get_logger("CubeMarsSystemHardware"),
        "Could not set CAN filter, continuing without strict filtering");
    }
  }

  return true;
}

bool CanSocket::disconnect()
{
  if (socket_ >= 0)
  {
    if (close(socket_) < 0)
    {
      RCLCPP_ERROR(
        rclcpp::get_logger("CubeMarsSystemHardware"),
        "Could not close CAN socket");
      return false;
    }
    socket_ = -1;
  }
  return true;
}

bool CanSocket::read_nonblocking(std::uint32_t & id, std::uint8_t data[], std::uint8_t & len)
{
  struct can_frame frame;
  const ssize_t nbytes = recv(socket_, &frame, sizeof(frame), MSG_DONTWAIT);

  if (nbytes < 0)
  {
    if (errno != EAGAIN && errno != EWOULDBLOCK)
    {
      RCLCPP_ERROR(
        rclcpp::get_logger("CubeMarsSystemHardware"),
        "Could not read CAN socket");
    }
    return false;
  }

  if (nbytes != static_cast<ssize_t>(sizeof(frame)))
  {
    RCLCPP_ERROR(
      rclcpp::get_logger("CubeMarsSystemHardware"),
      "Short CAN frame read");
    return false;
  }

  id = frame.can_id;
  len = frame.can_dlc > 8 ? 8 : frame.can_dlc;
  std::memcpy(data, frame.data, len);

  return true;
}

bool CanSocket::write_message(
  std::uint32_t id,
  const std::uint8_t data[],
  std::uint8_t len,
  FrameType frame_type)
{
  struct can_frame frame;
  std::memset(&frame, 0, sizeof(frame));

  if (frame_type == FrameType::EXTENDED) {
    frame.can_id = (id & CAN_EFF_MASK) | CAN_EFF_FLAG;
  } else {
    frame.can_id = (id & CAN_SFF_MASK);
  }

  frame.can_dlc = len > 8 ? 8 : len;

  if (data != nullptr && frame.can_dlc > 0) {
    std::memcpy(frame.data, data, frame.can_dlc);
  }

  if (write(socket_, &frame, sizeof(struct can_frame)) != static_cast<ssize_t>(sizeof(struct can_frame)))
  {
    RCLCPP_ERROR(
      rclcpp::get_logger("CubeMarsSystemHardware"),
      "Could not write message to CAN socket");
    return false;
  }

  return true;
}

}  // namespace cubemars_hardware
