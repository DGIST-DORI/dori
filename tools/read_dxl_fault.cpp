#include <dynamixel_sdk/dynamixel_sdk.h>
#include <cstdint>
#include <iostream>
int main() {
  auto *p=dynamixel::PortHandler::getPortHandler("/dev/serial/by-id/usb-FTDI_USB__-__Serial_Converter_FTAU591Z-if00-port0");
  auto *h=dynamixel::PacketHandler::getPacketHandler(2.0);
  if (!p->openPort() || !p->setBaudRate(57600)) return 1;
  for (uint8_t id=1; id<=3; ++id) {
    std::cout << "ID=" << int(id) << '\n';
    for (auto a : {11,63,64,70,146}) {
      uint8_t v=0,e=0; int r=h->read1ByteTxRx(p,id,a,&v,&e);
      std::cout << " addr="<<a<<" value="<<int(v)<<" comm="<<r<<" alert="<<int(e)<<'\n';
    }
    for (auto a : {126,144}) {
      uint16_t v=0;uint8_t e=0;int r=h->read2ByteTxRx(p,id,a,&v,&e);
      std::cout << " addr="<<a<<" value="<<(a==126?int(static_cast<int16_t>(v)):int(v))<<" comm="<<r<<" alert="<<int(e)<<'\n';
    }
    for (auto a : {108,112,116,132}) {
      uint32_t v=0;uint8_t e=0;int r=h->read4ByteTxRx(p,id,a,&v,&e);
      std::cout << " addr="<<a<<" value="<<static_cast<int32_t>(v)<<" comm="<<r<<" alert="<<int(e)<<'\n';
    }
  }
  p->closePort();
}
