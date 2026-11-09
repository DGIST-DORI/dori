// Copyright 2026 DORI. Licensed under the Apache License, Version 2.0.
// DORI owns this driver: upstream read_write_node is a demo using /dev/ttyUSB0
// and broadcast initialization, without stop handling or valid error feedback.
#include <array>
#include <cstdint>
#include <limits>
#include <memory>
#include <stdexcept>
#include <string>

#include "dynamixel_sdk/dynamixel_sdk.h"
#include "dynamixel_sdk_custom_interfaces/msg/set_position.hpp"
#include "dynamixel_sdk_custom_interfaces/srv/get_position.hpp"
#include "rclcpp/rclcpp.hpp"
#include "std_msgs/msg/int32.hpp"

namespace
{
constexpr uint16_t MODE = 11, TORQUE = 64, GOAL = 116, PRESENT = 132;
constexpr std::array<uint8_t, 2> IDS{1, 3};  // Motor 4 is now CubeMars CAN ID 4.
constexpr int32_t INVALID_POSITION = std::numeric_limits<int32_t>::min();
bool supported(uint8_t id) {return id == 1 || id == 3;}
bool valid_position(uint8_t id, int32_t value)
{
  return supported(id) && (id == 3 ? value >= 0 && value <= 4095 :
         value >= -1048575 && value <= 1048575);
}
}

class DxlDriverNode : public rclcpp::Node
{
  using SetPosition = dynamixel_sdk_custom_interfaces::msg::SetPosition;
  using GetPosition = dynamixel_sdk_custom_interfaces::srv::GetPosition;

public:
  DxlDriverNode() : Node("dxl_driver_node")
  {
    device_ = declare_parameter<std::string>("device_name",
      "/dev/serial/by-id/usb-FTDI_USB__-__Serial_Converter_FTAU591Z-if00-port0");
    baudrate_ = declare_parameter<int>("baudrate", 57600);
    port_.reset(dynamixel::PortHandler::getPortHandler(device_.c_str()));
    packet_ = dynamixel::PacketHandler::getPacketHandler(2.0);
  }

  ~DxlDriverNode() override
  {
    if (configured_) {
      for (const auto id : IDS) {
        packet_->write1ByteTxOnly(port_.get(), id, TORQUE, 0);
      }
    }
    port_->closePort();
  }

  void start()
  {
    if (baudrate_ <= 0 || !port_->openPort() || !port_->setBaudRate(baudrate_)) {
      throw std::runtime_error("Cannot open DXL port " + device_ + " at " +
              std::to_string(baudrate_) + " baud");
    }
    // Identify both devices before any register writes. Never broadcast or
    // initialize the retired DXL ID 2. Keep the robot's measured profiles.
    for (const auto id : IDS) {
      uint32_t model = 0, drive_mode = 0;
      require(read(id, 0, 2, model) && model == (id == 1 ? 1140u : 1040u),
        "Unexpected/missing DXL model at ID " + std::to_string(id));
      require(read(id, 10, 1, drive_mode) && !(drive_mode & 0x04),
        "DXL requires velocity-based profiles at ID " + std::to_string(id));
    }
    configured_ = true;  // A partial setup also disables torque on cleanup.
    for (const auto id : IDS) {
      uint32_t mode = 0, present = 0;
      const uint32_t target_mode = id == 1 ? 4 : 3;
      require(write(id, TORQUE, 1, 0) && read(id, MODE, 1, mode), "DXL torque/mode read failed");
      if (mode != target_mode) {
        require(write(id, MODE, 1, target_mode), "DXL mode write failed");
      }
      require(read(id, MODE, 1, mode) && mode == target_mode, "DXL mode verification failed");
      if (id == 3) {
        require(write_verified(id, 80, 2, 250) && write_verified(id, 84, 2, 1500),
          "DXL pitch servo gains failed");
      }
      require(write_verified(id, 108, 4, id == 1 ? 5 : 400) &&
        write_verified(id, 112, 4, id == 1 ? 15 : 500), "DXL profile verification failed");
      require(read(id, PRESENT, 4, present), "DXL initial position read failed");
      int32_t position = static_cast<int32_t>(present);
      if (id == 3) {position = ((position % 4096) + 4096) % 4096;}
      require(valid_position(id, position), "DXL initial position out of range");
      // Seed a hold target before torque-on; never use an old/default goal.
      require(write(id, GOAL, 4, static_cast<uint32_t>(position)) &&
        write(id, TORQUE, 1, 1), "DXL initial hold failed");
    }

    state_sub_ = create_subscription<std_msgs::msg::Int32>(
      "/system/action_state", rclcpp::QoS(1).transient_local(),
      [this](const std_msgs::msg::Int32::SharedPtr msg) {
        const bool inhibit = msg->data < 0 || msg->data >= 3;
        if (inhibit && !inhibited_) {for (const auto id : IDS) {hold(id);}}
        inhibited_ = inhibit;
      });
    command_sub_ = create_subscription<SetPosition>("/set_position", 20,
      [this](const SetPosition::SharedPtr msg) {
        if (inhibited_ || faulted_ || !valid_position(msg->id, msg->position)) {
          RCLCPP_WARN_THROTTLE(get_logger(), *get_clock(), 2000,
            "DXL goal rejected: stopped, faulted, awaiting supervisor or invalid ID/position");
          return;
        }
        if (!write(msg->id, GOAL, 4, static_cast<uint32_t>(msg->position))) {hold(msg->id);}
      });
    stop_sub_ = create_subscription<SetPosition>("/stop_position", 20,
      [this](const SetPosition::SharedPtr msg) {if (supported(msg->id)) {hold(msg->id);}});
    service_ = create_service<GetPosition>("/get_position",
      [this](const std::shared_ptr<GetPosition::Request> request,
      std::shared_ptr<GetPosition::Response> response) {
        // The upstream service has no success field. This out-of-range sentinel
        // is rejected by dxl_state_publisher; a timeout must not look like zero.
        response->position = INVALID_POSITION;
        uint32_t raw = 0;
        if (supported(request->id) && read(request->id, PRESENT, 4, raw) &&
          valid_position(request->id, static_cast<int32_t>(raw)))
        {
          response->position = static_cast<int32_t>(raw);
        }
      });
    RCLCPP_INFO(get_logger(), "DXL IDs 1/3 ready on %s; awaiting supervisor", device_.c_str());
  }

private:
  static void require(bool success, const std::string & message)
  {
    if (!success) {throw std::runtime_error(message);}
  }

  bool result_ok(uint8_t id, int result, uint8_t error)
  {
    if (result == COMM_SUCCESS && error == 0) {return true;}
    RCLCPP_ERROR_THROTTLE(get_logger(), *get_clock(), 2000,
      "DXL ID %u communication failed: %s; device error=%u", id,
      packet_->getTxRxResult(result), error);
    return false;
  }

  bool read(uint8_t id, uint16_t address, int size, uint32_t & value)
  {
    uint8_t error = 0, byte = 0;
    uint16_t word = 0;
    int result;
    if (size == 1) {
      result = packet_->read1ByteTxRx(port_.get(), id, address, &byte, &error);
      value = byte;
    } else if (size == 2) {
      result = packet_->read2ByteTxRx(port_.get(), id, address, &word, &error);
      value = word;
    } else {
      result = packet_->read4ByteTxRx(port_.get(), id, address, &value, &error);
    }
    return result_ok(id, result, error);
  }

  bool write(uint8_t id, uint16_t address, int size, uint32_t value)
  {
    uint8_t error = 0;
    int result;
    if (size == 1) {
      result = packet_->write1ByteTxRx(port_.get(), id, address, value, &error);
    } else if (size == 2) {
      result = packet_->write2ByteTxRx(port_.get(), id, address, value, &error);
    } else {
      result = packet_->write4ByteTxRx(port_.get(), id, address, value, &error);
    }
    return result_ok(id, result, error);
  }

  bool write_verified(uint8_t id, uint16_t address, int size, uint32_t value)
  {
    uint32_t actual = 0;
    return write(id, address, size, value) && read(id, address, size, actual) && actual == value;
  }

  void hold(uint8_t id)
  {
    uint32_t present = 0;
    if (read(id, PRESENT, 4, present) && valid_position(id, static_cast<int32_t>(present)) &&
      write(id, GOAL, 4, present)) {return;}
    packet_->write1ByteTxOnly(port_.get(), id, TORQUE, 0);
    faulted_ = true;  // A failed hold requires inspection/restart, not another goal.
    RCLCPP_ERROR(get_logger(), "DXL ID %u hold failed; sent torque-off and inhibited commands", id);
  }

  std::string device_;
  int baudrate_;
  std::unique_ptr<dynamixel::PortHandler> port_;
  dynamixel::PacketHandler * packet_{};
  bool configured_{false}, inhibited_{true}, faulted_{false};
  rclcpp::Subscription<std_msgs::msg::Int32>::SharedPtr state_sub_;
  rclcpp::Subscription<SetPosition>::SharedPtr command_sub_, stop_sub_;
  rclcpp::Service<GetPosition>::SharedPtr service_;
};

int main(int argc, char ** argv)
{
  rclcpp::init(argc, argv);
  int result = 0;
  try {
    auto node = std::make_shared<DxlDriverNode>();
    node->start();
    rclcpp::spin(node);  // Single executor serializes all SDK bus transactions.
  } catch (const std::exception & error) {
    RCLCPP_ERROR(rclcpp::get_logger("dxl_driver_node"), "%s", error.what());
    result = 1;
  }
  rclcpp::shutdown();
  return result;
}
