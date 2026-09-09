#ifndef CUBEMARS_HARDWARE__SYSTEM_HPP_
#define CUBEMARS_HARDWARE__SYSTEM_HPP_

#include <memory>
#include <chrono>
#include <string>
#include <vector>
#include <cstdint>
#include <cmath>

#include "hardware_interface/handle.hpp"
#include "hardware_interface/hardware_info.hpp"
#include "hardware_interface/system_interface.hpp"
#include "hardware_interface/types/hardware_interface_return_values.hpp"
#include "rclcpp/macros.hpp"
#include "rclcpp_lifecycle/node_interfaces/lifecycle_node_interface.hpp"
#include "rclcpp_lifecycle/state.hpp"
#include "cubemars_hardware/visibility_control.h"
#include "cubemars_hardware/can.hpp"

namespace cubemars_hardware
{

class CubeMarsSystemHardware : public hardware_interface::SystemInterface
{
public:
  RCLCPP_SHARED_PTR_DEFINITIONS(CubeMarsSystemHardware);

  virtual ~CubeMarsSystemHardware();

  CUBEMARS_HARDWARE_PUBLIC
  hardware_interface::CallbackReturn on_init(
    const hardware_interface::HardwareInfo & info) override;

  CUBEMARS_HARDWARE_PUBLIC
  hardware_interface::CallbackReturn on_configure(
    const rclcpp_lifecycle::State & previous_state) override;

  CUBEMARS_HARDWARE_PUBLIC
  hardware_interface::CallbackReturn on_cleanup(
    const rclcpp_lifecycle::State & previous_state) override;

  CUBEMARS_HARDWARE_PUBLIC
  std::vector<hardware_interface::StateInterface> export_state_interfaces() override;

  CUBEMARS_HARDWARE_PUBLIC
  std::vector<hardware_interface::CommandInterface> export_command_interfaces() override;

  CUBEMARS_HARDWARE_PUBLIC
  hardware_interface::return_type prepare_command_mode_switch(
    const std::vector<std::string> & start_interfaces,
    const std::vector<std::string> & stop_interfaces) override;

  CUBEMARS_HARDWARE_PUBLIC
  hardware_interface::return_type perform_command_mode_switch(
    const std::vector<std::string> & start_interfaces,
    const std::vector<std::string> & stop_interfaces) override;

  CUBEMARS_HARDWARE_PUBLIC
  hardware_interface::CallbackReturn on_activate(
    const rclcpp_lifecycle::State & previous_state) override;

  CUBEMARS_HARDWARE_PUBLIC
  hardware_interface::CallbackReturn on_deactivate(
    const rclcpp_lifecycle::State & previous_state) override;

  CUBEMARS_HARDWARE_PUBLIC
  hardware_interface::return_type read(
    const rclcpp::Time & time, const rclcpp::Duration & period) override;

  CUBEMARS_HARDWARE_PUBLIC
  hardware_interface::return_type write(
    const rclcpp::Time & time, const rclcpp::Duration & period) override;

private:
  enum protocol_mode_t : std::uint8_t
  {
    SERVO_PROTOCOL = 0,
    MIT_PROTOCOL = 1
  };

  enum control_mode_t : std::uint8_t
  {
    CURRENT_LOOP = 1,
    SPEED_LOOP = 3,
    POSITION_LOOP = 4,
    POSITION_SPEED_LOOP = 6,
    UNDEFINED
  };

  std::vector<double> hw_commands_positions_;
  std::vector<double> hw_commands_velocities_;
  std::vector<double> hw_commands_accelerations_;
  std::vector<double> hw_commands_efforts_;
  std::vector<double> hw_states_positions_;
  std::vector<double> hw_states_velocities_;
  std::vector<double> hw_states_efforts_;
  std::vector<double> hw_states_temperatures_;
  std::vector<double> feedback_ages_;
  std::vector<std::chrono::steady_clock::time_point> last_feedback_;

  std::vector<double> erpm_conversions_;
  std::vector<double> torque_constants_;
  std::vector<double> enc_offs_;
  std::vector<double> trq_limits_;
  std::vector<std::pair<std::int16_t, std::int16_t>> limits_;
  std::vector<bool> read_only_;

  std::vector<double> mit_p_min_;
  std::vector<double> mit_p_max_;
  std::vector<double> mit_v_min_;
  std::vector<double> mit_v_max_;
  std::vector<double> mit_t_min_;
  std::vector<double> mit_t_max_;
  std::vector<double> mit_kp_min_;
  std::vector<double> mit_kp_max_;
  std::vector<double> mit_kd_min_;
  std::vector<double> mit_kd_max_;
  std::vector<double> mit_pos_kp_;
  std::vector<double> mit_pos_kd_;
  std::vector<double> mit_vel_kd_;

  protocol_mode_t protocol_mode_{SERVO_PROTOCOL};

  CanSocket can_;
  std::string can_itf_;
  std::vector<std::uint32_t> can_ids_;

  std::vector<bool> stop_modes_;
  std::vector<control_mode_t> start_modes_;
  std::vector<control_mode_t> control_mode_;

  static int float_to_uint(double x, double x_min, double x_max, unsigned int bits);
  static double uint_to_float(int x_int, double x_min, double x_max, unsigned int bits);

  bool send_mit_enable(std::uint32_t can_id);
  bool send_mit_disable(std::uint32_t can_id);
  bool send_mit_zero(std::uint32_t can_id);

  bool send_mit_command(
    std::size_t i,
    double p_des,
    double v_des,
    double kp,
    double kd,
    double t_ff);

  bool parse_mit_feedback(
    std::uint32_t read_id,
    const std::uint8_t data[],
    std::uint8_t len);

  bool parse_servo_feedback(
    std::uint32_t read_id,
    const std::uint8_t data[],
    std::uint8_t len);
};

}  // namespace cubemars_hardware

#endif  // CUBEMARS_HARDWARE__SYSTEM_HPP_
