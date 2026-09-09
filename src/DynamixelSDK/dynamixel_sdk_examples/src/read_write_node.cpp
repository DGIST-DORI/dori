// Copyright 2021 ROBOTIS CO., LTD.
//
// Licensed under the Apache License, Version 2.0

#include <cstdio>
#include <memory>
#include <mutex>
#include <string>

#include "dynamixel_sdk/dynamixel_sdk.h"
#include "dynamixel_sdk_custom_interfaces/msg/set_position.hpp"
#include "dynamixel_sdk_custom_interfaces/srv/get_position.hpp"

#include "rclcpp/rclcpp.hpp"

#include "read_write_node.hpp"


// ============================================================
// X-Series Control Table
// ============================================================

#define ADDR_OPERATING_MODE        11
#define ADDR_TORQUE_ENABLE         64

// Position PID
#define ADDR_POSITION_D_GAIN       80
#define ADDR_POSITION_P_GAIN       84

// Motion Profile
#define ADDR_PROFILE_ACCELERATION  108
#define ADDR_PROFILE_VELOCITY      112

// Position
#define ADDR_GOAL_POSITION         116
#define ADDR_PRESENT_POSITION      132


// ============================================================
// Communication
// ============================================================

#define PROTOCOL_VERSION 2.0
#define BAUDRATE 57600
#define DEVICE_NAME "/dev/serial/by-id/usb-FTDI_USB__-__Serial_Converter_FTAU591Z-if00-port0"


// ============================================================
// Servo 3 settings
//
// Physical DXL ID 3
// = logical motor 5
// ============================================================

#define SERVO3_DXL_ID 3

// Position PID
#define SERVO3_POSITION_D_GAIN 250
#define SERVO3_POSITION_P_GAIN 1500

// ============================================================
// Motion Profile OFF
//
// Profile Velocity = 0
// -> profile trajectory 사용 안 함
//
// Profile Acceleration도 0으로 설정
// ============================================================

#define SERVO3_PROFILE_ACCELERATION 400
#define SERVO3_PROFILE_VELOCITY     500


// ============================================================
// Dynamixel SDK globals
// ============================================================

dynamixel::PortHandler * portHandler = nullptr;
dynamixel::PacketHandler * packetHandler = nullptr;


// ============================================================
// Serial bus mutex
// ============================================================

std::mutex dxl_bus_mutex;


// ============================================================
// ReadWriteNode
// ============================================================

ReadWriteNode::ReadWriteNode()
: Node("read_write_node")
{
  RCLCPP_INFO(
    this->get_logger(),
    "Run read_write_node"
  );


  // ============================================================
  // QoS
  // ============================================================

  this->declare_parameter(
    "qos_depth",
    10
  );

  const int qos_depth =
    this->get_parameter(
      "qos_depth"
    ).as_int();

  const auto qos =
    rclcpp::QoS(
      rclcpp::KeepLast(
        qos_depth
      )
    )
    .reliable()
    .durability_volatile();


  stop_position_subscriber_ = create_subscription<SetPosition>(
    "/stop_position", 20, [this](const SetPosition::SharedPtr msg) {
      if (msg->id < 1 || msg->id > 3) { return; }
      std::lock_guard<std::mutex> lock(dxl_bus_mutex);
      uint8_t error = 0;
      uint32_t present = 0;
      int result = packetHandler->read4ByteTxRx(
        portHandler, msg->id, ADDR_PRESENT_POSITION, &present, &error);
      if (result == COMM_SUCCESS && error == 0) {
        result = packetHandler->write4ByteTxRx(
          portHandler, msg->id, ADDR_GOAL_POSITION, present, &error);
      }
      if (result != COMM_SUCCESS || error != 0) {
        packetHandler->write1ByteTxOnly(portHandler, msg->id, ADDR_TORQUE_ENABLE, 0);
        RCLCPP_ERROR(get_logger(), "DXL %d hold failed; sent torque-off", msg->id);
      }
    });

  // ============================================================
  // Goal Position subscriber
  //
  // /set_position
  // ============================================================

  set_position_subscriber_ =
    this->create_subscription<SetPosition>(
      "set_position",
      qos,

      [this](
        const SetPosition::SharedPtr msg
      ) -> void
      {
        if (msg->id < 1 || msg->id > 3 ||
          (msg->id == 3 && (msg->position < 0 || msg->position > 4095)) ||
          msg->position < -1048575 || msg->position > 1048575)
        {
          RCLCPP_ERROR(get_logger(), "Rejected out-of-range DXL position command");
          return;
        }
        const uint32_t goal_position =
          static_cast<uint32_t>(
            msg->position
          );

        int comm_result =
          COMM_TX_FAIL;
        uint8_t write_error = 0;


        // ======================================================
        // Write Goal Position
        // ======================================================

        {
          std::lock_guard<std::mutex> lock(
            dxl_bus_mutex
          );

          comm_result =
            packetHandler->write4ByteTxRx(
              portHandler,
              static_cast<uint8_t>(
                msg->id
              ),
              ADDR_GOAL_POSITION,
              goal_position,
              &write_error
            );
        }


        // ======================================================
        // Communication result
        // ======================================================

        if (
          comm_result
          != COMM_SUCCESS
        ) {
          RCLCPP_WARN(
            this->get_logger(),

            "Failed to send goal position "
            "for ID %d: %s",

            msg->id,

            packetHandler->getTxRxResult(
              comm_result
            )
          );

          return;
        }


        if (write_error != 0) {
          RCLCPP_WARN(get_logger(), "DXL goal write error for ID %d: %s",
            msg->id, packetHandler->getRxPacketError(write_error));
          return;
        }

        RCLCPP_DEBUG(
          this->get_logger(),

          "Sent [ID: %d] "
          "[Goal Position: %d]",

          msg->id,
          msg->position
        );
      }
    );


  // ============================================================
  // Present Position service
  //
  // /get_position
  // ============================================================

  auto get_present_position =
    [this](
      const std::shared_ptr<
        GetPosition::Request
      > request,

      std::shared_ptr<
        GetPosition::Response
      > response
    ) -> void
    {
      int32_t present_position =
        0;

      uint8_t local_dxl_error =
        0;

      int comm_result =
        COMM_TX_FAIL;


      response->position =
        0;

      response->success =
        false;


      // ========================================================
      // Read Present Position
      // ========================================================

      {
        std::lock_guard<std::mutex> lock(
          dxl_bus_mutex
        );

        comm_result =
          packetHandler->read4ByteTxRx(
            portHandler,

            static_cast<uint8_t>(
              request->id
            ),

            ADDR_PRESENT_POSITION,

            reinterpret_cast<uint32_t *>(
              &present_position
            ),

            &local_dxl_error
          );
      }


      // ========================================================
      // Communication error
      // ========================================================

      if (
        comm_result
        != COMM_SUCCESS
      ) {
        RCLCPP_WARN_THROTTLE(
          this->get_logger(),

          *this->get_clock(),

          1000,

          "Failed to read present position "
          "for ID %d: %s",

          request->id,

          packetHandler->getTxRxResult(
            comm_result
          )
        );

        return;
      }


      // ========================================================
      // Dynamixel packet error
      // ========================================================

      if (
        local_dxl_error
        != 0
      ) {
        RCLCPP_WARN_THROTTLE(
          this->get_logger(),

          *this->get_clock(),

          1000,

          "DXL error while reading "
          "present position for ID %d: %s",

          request->id,

          packetHandler->getRxPacketError(
            local_dxl_error
          )
        );

        return;
      }


      // ========================================================
      // Success
      // ========================================================

      response->position =
        present_position;

      response->success =
        true;


      RCLCPP_DEBUG(
        this->get_logger(),

        "Get [ID: %d] "
        "[Present Position RAW: %d]",

        request->id,
        present_position
      );
    };


  get_position_server_ =
    this->create_service<GetPosition>(
      "get_position",
      get_present_position
    );
}


// ============================================================
// Destructor
// ============================================================

ReadWriteNode::~ReadWriteNode()
{
}


// ============================================================
// Setup one Dynamixel
// ============================================================

// Read-only hardware discovery on 2026-09-09: IDs 1/2 are XH540-V270-R.
// Mode 4 supports signed goals across the encoder zero.
// https://emanual.robotis.com/docs/en/dxl/x/xh540-v270/#operating-mode11
bool setupDynamixel(uint8_t dxl_id)
{
  std::lock_guard<std::mutex> lock(dxl_bus_mutex);
  uint8_t error = 0;
  const auto ok = [&](int result) {
      if (result == COMM_SUCCESS && error == 0) { return true; }
      RCLCPP_ERROR(rclcpp::get_logger("read_write_node"),
        "DXL %d initialization failed: comm=%d error=%u", dxl_id, result, error);
      return false;
    };
  const auto write1 = [&](uint16_t address, uint8_t value) {
      error = 0;
      return ok(packetHandler->write1ByteTxRx(portHandler, dxl_id, address, value, &error));
    };
  const auto write2 = [&](uint16_t address, uint16_t value) {
      error = 0;
      return ok(packetHandler->write2ByteTxRx(portHandler, dxl_id, address, value, &error));
    };
  const auto write4 = [&](uint16_t address, uint32_t value) {
      error = 0;
      return ok(packetHandler->write4ByteTxRx(portHandler, dxl_id, address, value, &error));
    };
  const auto read4 = [&](uint16_t address, uint32_t & value) {
      error = 0;
      return ok(packetHandler->read4ByteTxRx(portHandler, dxl_id, address, &value, &error));
    };
  // Verify the model recorded in this robot's source before changing modes.
  if (dxl_id == 1 || dxl_id == 2) {
    uint16_t model = 0;
    error = 0;
    if (!ok(packetHandler->read2ByteTxRx(portHandler, dxl_id, 0, &model, &error)) ||
      model != 1140)
    {
      RCLCPP_ERROR(rclcpp::get_logger("read_write_node"),
        "DXL %d: expected XH540-V270-R (1140), read %u", dxl_id, model);
      return false;
    }
  }
  uint32_t acceleration = 0, velocity = 0;
  if (!read4(ADDR_PROFILE_ACCELERATION, acceleration) ||
    !read4(ADDR_PROFILE_VELOCITY, velocity) || !write1(ADDR_TORQUE_ENABLE, 0))
  { return false; }
  const uint8_t mode = dxl_id == SERVO3_DXL_ID ? 3 : 4;
  uint8_t old_mode = 0;
  error = 0;
  if (!ok(packetHandler->read1ByteTxRx(
      portHandler, dxl_id, ADDR_OPERATING_MODE, &old_mode, &error))) { return false; }
  if (old_mode != mode && !write1(ADDR_OPERATING_MODE, mode)) { return false; }
  uint8_t actual_mode = 0;
  error = 0;
  if (!ok(packetHandler->read1ByteTxRx(
      portHandler, dxl_id, ADDR_OPERATING_MODE, &actual_mode, &error)) || actual_mode != mode)
  { return false; }
  if (dxl_id == SERVO3_DXL_ID) {
    if (!write2(ADDR_POSITION_D_GAIN, SERVO3_POSITION_D_GAIN) ||
      !write2(ADDR_POSITION_P_GAIN, SERVO3_POSITION_P_GAIN)) { return false; }
    acceleration = SERVO3_PROFILE_ACCELERATION;
    velocity = SERVO3_PROFILE_VELOCITY;
  }
  // Mode switches reset profiles. Restore the existing per-servo settings.
  if (!write4(ADDR_PROFILE_ACCELERATION, acceleration) ||
    !write4(ADDR_PROFILE_VELOCITY, velocity)) { return false; }
  uint32_t present = 0;
  if (!read4(ADDR_PRESENT_POSITION, present)) { return false; }
  int32_t signed_present = static_cast<int32_t>(present);
  if (mode == 3) {
    signed_present = ((signed_present % 4096) + 4096) % 4096;
  }
  if (signed_present < -1048575 || signed_present > 1048575) { return false; }
  // Do not enable torque with an old/default goal left in the register.
  if (!write4(ADDR_GOAL_POSITION, static_cast<uint32_t>(signed_present)) ||
    !write1(ADDR_TORQUE_ENABLE, 1)) { return false; }
  RCLCPP_INFO(rclcpp::get_logger("read_write_node"),
    "DXL %d initialized: mode=%u hold=%d", dxl_id, mode, signed_present);
  return true;
}


// ============================================================
// Main
// ============================================================

int main(
  int argc,
  char * argv[]
)
{
  rclcpp::init(
    argc,
    argv
  );


  // ============================================================
  // SDK handlers
  // ============================================================

  portHandler =
    dynamixel::PortHandler::getPortHandler(
      DEVICE_NAME
    );

  packetHandler =
    dynamixel::PacketHandler::getPacketHandler(
      PROTOCOL_VERSION
    );


  // ============================================================
  // Open port
  // ============================================================

  if (
    !portHandler->openPort()
  ) {
    RCLCPP_ERROR(
      rclcpp::get_logger(
        "read_write_node"
      ),

      "Failed to open port %s",

      DEVICE_NAME
    );

    rclcpp::shutdown();

    return -1;
  }


  RCLCPP_INFO(
    rclcpp::get_logger(
      "read_write_node"
    ),

    "Succeeded to open port %s",

    DEVICE_NAME
  );


  // ============================================================
  // Baudrate
  // ============================================================

  if (
    !portHandler->setBaudRate(
      BAUDRATE
    )
  ) {
    RCLCPP_ERROR(
      rclcpp::get_logger(
        "read_write_node"
      ),

      "Failed to set baudrate %d",

      BAUDRATE
    );

    portHandler->closePort();

    rclcpp::shutdown();

    return -1;
  }


  RCLCPP_INFO(
    rclcpp::get_logger(
      "read_write_node"
    ),

    "Succeeded to set baudrate %d",

    BAUDRATE
  );


  // ============================================================
  // Initialize Dynamixels
  //
  // ID 1 = XH540-V270-R (read model 1140)
  // ID 2 = XH540-V270-R (read model 1140)
  // ID 3 = XH430-V350-R (read model 1040)
  // ============================================================

  if (!setupDynamixel(1) || !setupDynamixel(2) || !setupDynamixel(3)) {
    packetHandler->write1ByteTxOnly(portHandler, BROADCAST_ID, ADDR_TORQUE_ENABLE, 0);
    portHandler->closePort();
    rclcpp::shutdown();
    return 1;
  }

  // ============================================================
  // ROS node
  // ============================================================

  auto node =
    std::make_shared<
      ReadWriteNode
    >();


  rclcpp::spin(
    node
  );


  // ============================================================
  // Shutdown
  // ============================================================

  {
    std::lock_guard<std::mutex> lock(
      dxl_bus_mutex
    );

    packetHandler->write1ByteTxOnly(
      portHandler,

      BROADCAST_ID,

      ADDR_TORQUE_ENABLE,

      0
    );
  }


  portHandler->closePort();

  rclcpp::shutdown();

  return 0;
}
