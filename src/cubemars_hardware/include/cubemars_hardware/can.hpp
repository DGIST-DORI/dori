#ifndef CUBEMARS_HARDWARE__CAN_HPP_
#define CUBEMARS_HARDWARE__CAN_HPP_

#include <linux/can.h>

#include <cstdint>
#include <string>
#include <vector>

namespace cubemars_hardware
{

class CanSocket
{
public:
  enum class FrameType : std::uint8_t
  {
    STANDARD = 0,
    EXTENDED = 1
  };

  bool connect(std::string can_itf, const std::vector<canid_t> & can_ids, canid_t can_mask);
  bool disconnect();
  bool read_nonblocking(std::uint32_t & id, std::uint8_t data[], std::uint8_t & len);

  bool write_message(
    std::uint32_t id,
    const std::uint8_t data[],
    std::uint8_t len,
    FrameType frame_type = FrameType::EXTENDED);

private:
  int socket_{-1};
  canid_t can_mask_{0};
};

}  // namespace cubemars_hardware

#endif  // CUBEMARS_HARDWARE__CAN_HPP_
