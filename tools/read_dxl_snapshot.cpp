// Read-only bus inspection. Does not write torque, mode, profile, or goals.
#include <dynamixel_sdk/dynamixel_sdk.h>
#include <cstdint>
#include <iostream>

int main()
{
  auto * port = dynamixel::PortHandler::getPortHandler(
    "/dev/serial/by-id/usb-FTDI_USB__-__Serial_Converter_FTAU591Z-if00-port0");
  auto * packet = dynamixel::PacketHandler::getPacketHandler(2.0);
  if (!port->openPort() || !port->setBaudRate(57600)) {
    std::cerr << "Unable to open DXL serial port\n";
    return 1;
  }
  bool good = true;
  for (uint8_t id = 1; id <= 3; ++id) {
    uint8_t error = 0, mode = 0, torque = 0;
    uint16_t model = 0;
    uint32_t position = 0;
    auto check = [&](int result) {
      if (result == COMM_SUCCESS && error == 0) { return true; }
      std::cerr << "ID " << int(id) << " read failed: comm=" << result
                << " device_error=" << int(error) << '\n';
      good = false;
      return false;
    };
    if (!check(packet->read2ByteTxRx(port, id, 0, &model, &error)) ||
        !check(packet->read1ByteTxRx(port, id, 11, &mode, &error)) ||
        !check(packet->read1ByteTxRx(port, id, 64, &torque, &error)) ||
        !check(packet->read4ByteTxRx(port, id, 132, &position, &error))) { continue; }
    const int32_t signed_position = static_cast<int32_t>(position);
    std::cout << "DXL_ID=" << int(id) << " model=" << model
              << " mode=" << int(mode) << " torque=" << int(torque)
              << " raw=" << signed_position
              << " degrees=" << signed_position * 360.0 / 4096.0 << '\n';
  }
  port->closePort();
  return good ? 0 : 1;
}
