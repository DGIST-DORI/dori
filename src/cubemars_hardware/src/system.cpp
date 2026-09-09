#include "cubemars_hardware/system.hpp"

#include <algorithm>
#include <cmath>
#include <limits>
#include <unordered_set>
#include <vector>

#include <linux/can.h>

#include "hardware_interface/types/hardware_interface_type_values.hpp"
#include "rclcpp/rclcpp.hpp"

namespace
{
constexpr double PI_CONST = 3.14159265358979323846;
}

namespace cubemars_hardware
{

CubeMarsSystemHardware::~CubeMarsSystemHardware()
{
  on_cleanup(rclcpp_lifecycle::State());
}


// ============================================================
// MIT 변환 함수
// ============================================================

int CubeMarsSystemHardware::float_to_uint(
  double x,
  double x_min,
  double x_max,
  unsigned int bits)
{
  const double span = x_max - x_min;

  if (span <= 0.0) {
    return 0;
  }

  if (x < x_min) {
    x = x_min;
  }

  if (x > x_max) {
    x = x_max;
  }

  const double scale =
    static_cast<double>((1u << bits) - 1u) / span;

  return static_cast<int>(
    (x - x_min) * scale);
}


double CubeMarsSystemHardware::uint_to_float(
  int x_int,
  double x_min,
  double x_max,
  unsigned int bits)
{
  const double span = x_max - x_min;

  if (span <= 0.0) {
    return x_min;
  }

  return
    static_cast<double>(x_int) *
    span /
    static_cast<double>((1u << bits) - 1u) +
    x_min;
}


// ============================================================
// MIT Mode 명령
// ============================================================

bool CubeMarsSystemHardware::send_mit_enable(
  std::uint32_t can_id)
{
  const std::uint8_t data[8] =
  {
    0xFF, 0xFF, 0xFF, 0xFF,
    0xFF, 0xFF, 0xFF, 0xFC
  };

  return can_.write_message(
    can_id,
    data,
    8,
    CanSocket::FrameType::STANDARD);
}


bool CubeMarsSystemHardware::send_mit_disable(
  std::uint32_t can_id)
{
  const std::uint8_t data[8] =
  {
    0xFF, 0xFF, 0xFF, 0xFF,
    0xFF, 0xFF, 0xFF, 0xFD
  };

  return can_.write_message(
    can_id,
    data,
    8,
    CanSocket::FrameType::STANDARD);
}


bool CubeMarsSystemHardware::send_mit_zero(
  std::uint32_t can_id)
{
  const std::uint8_t data[8] =
  {
    0xFF, 0xFF, 0xFF, 0xFF,
    0xFF, 0xFF, 0xFF, 0xFE
  };

  return can_.write_message(
    can_id,
    data,
    8,
    CanSocket::FrameType::STANDARD);
}


// ============================================================
// 실제 MIT CAN 명령 전송
//
// tau = kp * (p_des - p)
//     + kd * (v_des - v)
//     + t_ff
//
// 형태로 CubeMars 내부 제어기가 사용
// ============================================================

bool CubeMarsSystemHardware::send_mit_command(
  std::size_t i,
  double p_des,
  double v_des,
  double kp,
  double kd,
  double t_ff)
{
  const int p_int =
    float_to_uint(
      p_des,
      mit_p_min_[i],
      mit_p_max_[i],
      16);

  const int v_int =
    float_to_uint(
      v_des,
      mit_v_min_[i],
      mit_v_max_[i],
      12);

  const int kp_int =
    float_to_uint(
      kp,
      mit_kp_min_[i],
      mit_kp_max_[i],
      12);

  const int kd_int =
    float_to_uint(
      kd,
      mit_kd_min_[i],
      mit_kd_max_[i],
      12);

  const int t_int =
    float_to_uint(
      t_ff,
      mit_t_min_[i],
      mit_t_max_[i],
      12);


  std::uint8_t data[8];

  data[0] = (p_int >> 8) & 0xFF;
  data[1] = p_int & 0xFF;

  data[2] = (v_int >> 4) & 0xFF;

  data[3] =
    ((v_int & 0x0F) << 4) |
    ((kp_int >> 8) & 0x0F);

  data[4] =
    kp_int & 0xFF;

  data[5] =
    (kd_int >> 4) & 0xFF;

  data[6] =
    ((kd_int & 0x0F) << 4) |
    ((t_int >> 8) & 0x0F);

  data[7] =
    t_int & 0xFF;


  return can_.write_message(
    can_ids_[i],
    data,
    8,
    CanSocket::FrameType::STANDARD);
}


// ============================================================
// MIT Feedback Parsing
// ============================================================

bool CubeMarsSystemHardware::parse_mit_feedback(
  std::uint32_t read_id,
  const std::uint8_t data[],
  std::uint8_t len)
{
  if (len < 7) {
    return false;
  }


  const std::uint32_t rx_id =
    read_id & CAN_SFF_MASK;


  auto it =
    std::find(
      can_ids_.begin(),
      can_ids_.end(),
      rx_id);


  if (it == can_ids_.end()) {
    return false;
  }


  const int i =
    std::distance(
      can_ids_.begin(),
      it);


  const int p_int =
    (static_cast<int>(data[1]) << 8) |
    static_cast<int>(data[2]);


  const int v_int =
    (static_cast<int>(data[3]) << 4) |
    (static_cast<int>(data[4]) >> 4);


  const int t_int =
    ((static_cast<int>(data[4]) & 0x0F) << 8) |
    static_cast<int>(data[5]);


  const int temp_raw =
    static_cast<int>(data[6]);


  const double raw_pos =
    uint_to_float(
      p_int,
      mit_p_min_[i],
      mit_p_max_[i],
      16);


  const double vel =
    uint_to_float(
      v_int,
      mit_v_min_[i],
      mit_v_max_[i],
      12);


  const double trq =
    uint_to_float(
      t_int,
      mit_t_min_[i],
      mit_t_max_[i],
      12);


  double direction_sign = 1.0;

  if (
    info_.joints[i].parameters.count(
      "direction_sign") != 0)
  {
    direction_sign =
      std::stod(
        info_.joints[i].parameters.at(
          "direction_sign"));
  }


  last_feedback_[i] = std::chrono::steady_clock::now();

  hw_states_positions_[i] =
    (raw_pos - enc_offs_[i]) *
    direction_sign;


  hw_states_velocities_[i] =
    vel *
    direction_sign;


  hw_states_efforts_[i] =
    trq *
    direction_sign;


  hw_states_temperatures_[i] =
    static_cast<double>(
      temp_raw);


  return true;
}


// ============================================================
// Servo Protocol Feedback
// ============================================================

bool CubeMarsSystemHardware::parse_servo_feedback(
  std::uint32_t read_id,
  const std::uint8_t data[],
  std::uint8_t len)
{
  if (len < 8) {
    return false;
  }


  auto it =
    std::find(
      can_ids_.begin(),
      can_ids_.end(),
      (read_id & 0xFF));


  if (it == can_ids_.end()) {
    return false;
  }


  const int i =
    std::distance(
      can_ids_.begin(),
      it);


  if (data[7] != 0)
  {
    switch (data[7])
    {
      case 1:
        RCLCPP_ERROR(
          rclcpp::get_logger(
            "CubeMarsSystemHardware"),
          "Motor over-temperature fault.");
        break;

      case 2:
        RCLCPP_ERROR(
          rclcpp::get_logger(
            "CubeMarsSystemHardware"),
          "Over-current fault.");
        break;

      case 3:
        RCLCPP_ERROR(
          rclcpp::get_logger(
            "CubeMarsSystemHardware"),
          "Over-voltage fault.");
        break;

      case 4:
        RCLCPP_ERROR(
          rclcpp::get_logger(
            "CubeMarsSystemHardware"),
          "Under-voltage fault.");
        break;

      case 5:
        RCLCPP_ERROR(
          rclcpp::get_logger(
            "CubeMarsSystemHardware"),
          "Encoder fault.");
        break;

      case 6:
        RCLCPP_ERROR(
          rclcpp::get_logger(
            "CubeMarsSystemHardware"),
          "MOSFET over-temperature fault.");
        break;

      case 7:
        RCLCPP_ERROR(
          rclcpp::get_logger(
            "CubeMarsSystemHardware"),
          "Motor stall.");
        break;

      default:
        RCLCPP_ERROR(
          rclcpp::get_logger(
            "CubeMarsSystemHardware"),
          "Unknown servo error code: %d",
          data[7]);
        break;
    }
  }


  const std::int16_t pos_int =
    static_cast<std::int16_t>(
      (static_cast<std::uint16_t>(
        data[0]) << 8) |
      data[1]);


  const std::int16_t spd_int =
    static_cast<std::int16_t>(
      (static_cast<std::uint16_t>(
        data[2]) << 8) |
      data[3]);


  const std::int16_t cur_int =
    static_cast<std::int16_t>(
      (static_cast<std::uint16_t>(
        data[4]) << 8) |
      data[5]);


  double direction_sign = 1.0;

  if (
    info_.joints[i].parameters.count(
      "direction_sign") != 0)
  {
    direction_sign =
      std::stod(
        info_.joints[i].parameters.at(
          "direction_sign"));
  }


  last_feedback_[i] = std::chrono::steady_clock::now();

  hw_states_positions_[i] =
    (
      (pos_int *
      0.1 *
      PI_CONST /
      180.0)
      -
      enc_offs_[i]
    )
    *
    direction_sign;


  hw_states_velocities_[i] =
    (
      spd_int *
      10.0 /
      erpm_conversions_[i]
    )
    *
    direction_sign;


  hw_states_efforts_[i] =
    (
      cur_int *
      0.01 *
      torque_constants_[i] *
      std::stoi(
        info_.joints[i].parameters.at(
          "gear_ratio"))
    )
    *
    direction_sign;


  hw_states_temperatures_[i] =
    static_cast<double>(
      data[6]);


  return true;
}


// ============================================================
// Initialize
// ============================================================

hardware_interface::CallbackReturn
CubeMarsSystemHardware::on_init(
  const hardware_interface::HardwareInfo & info)
{
  if (
    hardware_interface::SystemInterface::on_init(
      info)
    !=
    hardware_interface::CallbackReturn::SUCCESS)
  {
    return
      hardware_interface::CallbackReturn::ERROR;
  }


  if (
    info_.hardware_parameters.count(
      "can_interface") != 0)
  {
    can_itf_ =
      info_.hardware_parameters.at(
        "can_interface");
  }
  else
  {
    RCLCPP_FATAL(
      rclcpp::get_logger(
        "CubeMarsSystemHardware"),
      "No can_interface specified in URDF");

    return
      hardware_interface::CallbackReturn::ERROR;
  }


  if (
    info_.hardware_parameters.count(
      "protocol_mode") != 0)
  {
    const auto mode =
      info_.hardware_parameters.at(
        "protocol_mode");

    protocol_mode_ =
      (mode == "mit")
      ?
      MIT_PROTOCOL
      :
      SERVO_PROTOCOL;
  }
  else
  {
    protocol_mode_ =
      SERVO_PROTOCOL;
  }


  feedback_ages_.assign(info_.joints.size(), std::numeric_limits<double>::infinity());
  last_feedback_.resize(info_.joints.size());

  hw_states_positions_.resize(
    info_.joints.size(),
    0.0);

  hw_states_velocities_.resize(
    info_.joints.size(),
    0.0);

  hw_states_efforts_.resize(
    info_.joints.size(),
    0.0);

  hw_states_temperatures_.resize(
    info_.joints.size(),
    0.0);


  hw_commands_positions_.resize(
    info_.joints.size(),
    std::numeric_limits<double>::quiet_NaN());

  hw_commands_velocities_.resize(
    info_.joints.size(),
    std::numeric_limits<double>::quiet_NaN());

  hw_commands_accelerations_.resize(
    info_.joints.size(),
    std::numeric_limits<double>::quiet_NaN());

  hw_commands_efforts_.resize(
    info_.joints.size(),
    std::numeric_limits<double>::quiet_NaN());


  control_mode_.resize(
    info_.joints.size(),
    control_mode_t::UNDEFINED);


  for (
    const hardware_interface::ComponentInfo & joint :
    info_.joints)
  {
    if (
      joint.parameters.count("can_id") != 0 &&
      joint.parameters.count("kt") != 0 &&
      joint.parameters.count("pole_pairs") != 0 &&
      joint.parameters.count("gear_ratio") != 0)
    {
      can_ids_.emplace_back(
        std::stoul(
          joint.parameters.at(
            "can_id")));


      torque_constants_.emplace_back(
        std::stod(
          joint.parameters.at(
            "kt")));


      double erpm_conversion =
        std::stoi(
          joint.parameters.at(
            "pole_pairs"))
        *
        std::stoi(
          joint.parameters.at(
            "gear_ratio"))
        *
        60.0 /
        (2.0 * PI_CONST);


      erpm_conversions_.emplace_back(
        erpm_conversion);


      if (
        joint.parameters.count(
          "acc_limit") != 0 &&
        joint.parameters.count(
          "vel_limit") != 0)
      {
        std::pair<
          std::int16_t,
          std::int16_t> limits;


        limits.first =
          static_cast<std::int16_t>(
            std::stoi(
              joint.parameters.at(
                "vel_limit"))
            /
            10.0
            *
            erpm_conversion);


        limits.second =
          static_cast<std::int16_t>(
            std::stoi(
              joint.parameters.at(
                "acc_limit"))
            /
            10.0
            *
            erpm_conversion);


        if (
          limits.first >= 32767 ||
          limits.first <= 0)
        {
          RCLCPP_ERROR(
            rclcpp::get_logger(
              "CubeMarsSystemHardware"),
            "velocity limit is not in range 0-32767: %d",
            limits.first);

          return
            hardware_interface::CallbackReturn::ERROR;
        }


        if (
          limits.second >= 32767 ||
          limits.second <= 0)
        {
          RCLCPP_ERROR(
            rclcpp::get_logger(
              "CubeMarsSystemHardware"),
            "acceleration limit is not in range 0-32767: %d",
            limits.second);

          return
            hardware_interface::CallbackReturn::ERROR;
        }


        limits_.emplace_back(
          limits);
      }
      else
      {
        limits_.emplace_back(
          std::make_pair(
            0,
            0));
      }
    }
    else
    {
      RCLCPP_FATAL(
        rclcpp::get_logger(
          "CubeMarsSystemHardware"),
        "Missing parameters in URDF for %s",
        joint.name.c_str());

      return
        hardware_interface::CallbackReturn::ERROR;
    }


    if (
      joint.parameters.count(
        "enc_off") != 0)
    {
      enc_offs_.emplace_back(
        std::stod(
          joint.parameters.at(
            "enc_off")));
    }
    else
    {
      enc_offs_.emplace_back(
        0.0);
    }


    if (
      joint.parameters.count(
        "trq_limit") != 0 &&
      std::stod(
        joint.parameters.at(
          "trq_limit")) > 0.0)
    {
      trq_limits_.emplace_back(
        std::stod(
          joint.parameters.at(
            "trq_limit")));
    }
    else
    {
      trq_limits_.emplace_back(
        0.0);
    }


    if (
      joint.parameters.count(
        "read_only") != 0 &&
      std::stoi(
        joint.parameters.at(
          "read_only")) == 1)
    {
      read_only_.emplace_back(
        true);
    }
    else
    {
      read_only_.emplace_back(
        false);
    }


    auto get_param_or =
      [&](
        const std::string & key,
        double default_value)
      -> double
      {
        if (
          joint.parameters.count(
            key) != 0)
        {
          return
            std::stod(
              joint.parameters.at(
                key));
        }

        return default_value;
      };


    mit_p_min_.push_back(
      get_param_or(
        "mit_p_min",
        -12.5));

    mit_p_max_.push_back(
      get_param_or(
        "mit_p_max",
        12.5));

    mit_v_min_.push_back(
      get_param_or(
        "mit_v_min",
        -30.0));

    mit_v_max_.push_back(
      get_param_or(
        "mit_v_max",
        30.0));

    mit_t_min_.push_back(
      get_param_or(
        "mit_t_min",
        -18.0));

    mit_t_max_.push_back(
      get_param_or(
        "mit_t_max",
        18.0));

    mit_kp_min_.push_back(
      get_param_or(
        "mit_kp_min",
        0.0));

    mit_kp_max_.push_back(
      get_param_or(
        "mit_kp_max",
        500.0));

    mit_kd_min_.push_back(
      get_param_or(
        "mit_kd_min",
        0.0));

    mit_kd_max_.push_back(
      get_param_or(
        "mit_kd_max",
        5.0));


    mit_pos_kp_.push_back(
      get_param_or(
        "mit_pos_kp",
        30.0));

    mit_pos_kd_.push_back(
      get_param_or(
        "mit_pos_kd",
        1.0));

    mit_vel_kd_.push_back(
      get_param_or(
        "mit_vel_kd",
        1.0));
  }


  return
    hardware_interface::CallbackReturn::SUCCESS;
}


// ============================================================
// Configure / Cleanup
// ============================================================

hardware_interface::CallbackReturn
CubeMarsSystemHardware::on_configure(
  const rclcpp_lifecycle::State &)
{
  const hardware_interface::CallbackReturn result =
    can_.connect(
      can_itf_,
      can_ids_,
      0x00000000U)
    ?
    hardware_interface::CallbackReturn::SUCCESS
    :
    hardware_interface::CallbackReturn::FAILURE;


  RCLCPP_INFO(
    rclcpp::get_logger(
      "CubeMarsSystemHardware"),
    "Communication active");


  return result;
}


hardware_interface::CallbackReturn
CubeMarsSystemHardware::on_cleanup(
  const rclcpp_lifecycle::State &)
{
  const hardware_interface::CallbackReturn result =
    can_.disconnect()
    ?
    hardware_interface::CallbackReturn::SUCCESS
    :
    hardware_interface::CallbackReturn::FAILURE;


  RCLCPP_INFO(
    rclcpp::get_logger(
      "CubeMarsSystemHardware"),
    "Communication closed");


  return result;
}


// ============================================================
// State interfaces
// ============================================================

std::vector<hardware_interface::StateInterface>
CubeMarsSystemHardware::export_state_interfaces()
{
  std::vector<
    hardware_interface::StateInterface>
    state_interfaces;


  for (
    std::size_t i = 0;
    i < info_.joints.size();
    i++)
  {
    state_interfaces.emplace_back(
      hardware_interface::StateInterface(
        info_.joints[i].name,
        hardware_interface::HW_IF_POSITION,
        &hw_states_positions_[i]));


    state_interfaces.emplace_back(
      hardware_interface::StateInterface(
        info_.joints[i].name,
        hardware_interface::HW_IF_VELOCITY,
        &hw_states_velocities_[i]));


    state_interfaces.emplace_back(
      hardware_interface::StateInterface(
        info_.joints[i].name,
        hardware_interface::HW_IF_EFFORT,
        &hw_states_efforts_[i]));


    state_interfaces.emplace_back(
      hardware_interface::StateInterface(
        info_.joints[i].name,
        "temperature",
        &hw_states_temperatures_[i]));
    state_interfaces.emplace_back(info_.joints[i].name, "feedback_age", &feedback_ages_[i]);
  }


  return state_interfaces;
}


// ============================================================
// Command interfaces
// ============================================================

std::vector<hardware_interface::CommandInterface>
CubeMarsSystemHardware::export_command_interfaces()
{
  std::vector<
    hardware_interface::CommandInterface>
    command_interfaces;


  for (
    std::size_t i = 0;
    i < info_.joints.size();
    i++)
  {
    command_interfaces.emplace_back(
      hardware_interface::CommandInterface(
        info_.joints[i].name,
        hardware_interface::HW_IF_POSITION,
        &hw_commands_positions_[i]));


    command_interfaces.emplace_back(
      hardware_interface::CommandInterface(
        info_.joints[i].name,
        hardware_interface::HW_IF_VELOCITY,
        &hw_commands_velocities_[i]));


    command_interfaces.emplace_back(
      hardware_interface::CommandInterface(
        info_.joints[i].name,
        hardware_interface::HW_IF_ACCELERATION,
        &hw_commands_accelerations_[i]));


    command_interfaces.emplace_back(
      hardware_interface::CommandInterface(
        info_.joints[i].name,
        hardware_interface::HW_IF_EFFORT,
        &hw_commands_efforts_[i]));
  }


  return command_interfaces;
}


// ============================================================
// Controller mode switching
//
// 지원:
// effort              -> CURRENT_LOOP
// velocity            -> SPEED_LOOP
// velocity + effort   -> SPEED_LOOP + tau_ff
// position            -> POSITION LOOP
// ============================================================

hardware_interface::return_type
CubeMarsSystemHardware::prepare_command_mode_switch(
  const std::vector<std::string> & start_interfaces,
  const std::vector<std::string> & stop_interfaces)
{
  stop_modes_.clear();
  start_modes_.clear();


  stop_modes_.resize(
    info_.joints.size(),
    false);


  const std::unordered_set<std::string>
    eff{"effort"};

  const std::unordered_set<std::string>
    vel{"velocity"};

  const std::unordered_set<std::string>
    pos{"position"};

  // ----------------------------------------------------------
  // 새로 추가
  //
  // velocity + effort를 동시에 command interface로 사용하면
  // MIT SPEED_LOOP에서 effort를 tau_ff로 사용
  // ----------------------------------------------------------

  const std::unordered_set<std::string>
    vel_eff{
      "velocity",
      "effort"
    };


  std::unordered_set<std::string>
    joint_interfaces;


  for (
    std::size_t i = 0;
    i < info_.joints.size();
    i++)
  {
    // --------------------------------------------------------
    // stop할 controller가 현재 joint를 사용하고 있는지 검사
    // --------------------------------------------------------

    for (
      const std::string & key :
      stop_interfaces)
    {
      if (
        key.find(
          info_.joints[i].name)
        !=
        std::string::npos)
      {
        stop_modes_[i] = true;
        break;
      }
    }


    joint_interfaces.clear();


    // --------------------------------------------------------
    // 새 controller가 어떤 interface를 요구하는지 확인
    // --------------------------------------------------------

    for (
      const std::string & key :
      start_interfaces)
    {
      if (
        key.find(
          info_.joints[i].name)
        !=
        std::string::npos)
      {
        const std::size_t slash_pos =
          key.find("/");

        if (
          slash_pos !=
          std::string::npos)
        {
          joint_interfaces.insert(
            key.substr(
              slash_pos + 1));
        }
      }
    }


    // --------------------------------------------------------
    // effort 단독
    //
    // 순수 torque control
    // --------------------------------------------------------

    if (
      joint_interfaces == eff)
    {
      start_modes_.push_back(
        CURRENT_LOOP);
    }


    // --------------------------------------------------------
    // velocity 단독
    // 또는
    // velocity + effort
    //
    // 둘 다 SPEED_LOOP
    //
    // effort가 같이 들어오는 경우 write()에서 tau_ff로 사용
    // --------------------------------------------------------

    else if (
      joint_interfaces == vel ||
      joint_interfaces == vel_eff)
    {
      start_modes_.push_back(
        SPEED_LOOP);
    }


    // --------------------------------------------------------
    // position
    // --------------------------------------------------------

    else if (
      joint_interfaces == pos)
    {
      if (
        limits_[i].first == 0 ||
        limits_[i].second == 0)
      {
        start_modes_.push_back(
          POSITION_LOOP);
      }
      else
      {
        start_modes_.push_back(
          POSITION_SPEED_LOOP);
      }
    }


    // --------------------------------------------------------
    // 새 interface 없음
    // --------------------------------------------------------

    else if (
      joint_interfaces.empty())
    {
      if (stop_modes_[i])
      {
        start_modes_.push_back(
          UNDEFINED);
      }
      else
      {
        start_modes_.push_back(
          control_mode_[i]);
      }
    }


    // --------------------------------------------------------
    // 지원하지 않는 조합
    // --------------------------------------------------------

    else
    {
      RCLCPP_ERROR(
        rclcpp::get_logger(
          "CubeMarsSystemHardware"),
        "Unsupported command interface combination for joint %s",
        info_.joints[i].name.c_str());


      return
        hardware_interface::return_type::ERROR;
    }
  }


  return
    hardware_interface::return_type::OK;
}


// ============================================================
// 실제 controller switch 수행
// ============================================================

hardware_interface::return_type
CubeMarsSystemHardware::perform_command_mode_switch(
  const std::vector<std::string> &,
  const std::vector<std::string> &)
{
  for (
    std::size_t i = 0;
    i < info_.joints.size();
    i++)
  {
    if (stop_modes_[i])
    {
      hw_commands_efforts_[i] =
        std::numeric_limits<double>::quiet_NaN();

      hw_commands_velocities_[i] =
        std::numeric_limits<double>::quiet_NaN();

      hw_commands_positions_[i] =
        std::numeric_limits<double>::quiet_NaN();

      hw_commands_accelerations_[i] =
        std::numeric_limits<double>::quiet_NaN();
    }


    control_mode_[i] =
      start_modes_[i];
  }


  return
    hardware_interface::return_type::OK;
}


// ============================================================
// Activate / Deactivate
// ============================================================

hardware_interface::CallbackReturn
CubeMarsSystemHardware::on_activate(
  const rclcpp_lifecycle::State &)
{
  if (
    protocol_mode_ ==
    MIT_PROTOCOL)
  {
    for (
      std::size_t i = 0;
      i < can_ids_.size();
      ++i)
    {
      if (!read_only_[i])
      {
        if (
          !send_mit_enable(
            can_ids_[i]))
        {
          return
            hardware_interface::CallbackReturn::ERROR;
        }
      }
    }
  }


  return
    hardware_interface::CallbackReturn::SUCCESS;
}


hardware_interface::CallbackReturn
CubeMarsSystemHardware::on_deactivate(
  const rclcpp_lifecycle::State &)
{
  if (
    protocol_mode_ ==
    MIT_PROTOCOL)
  {
    for (
      std::size_t i = 0;
      i < can_ids_.size();
      ++i)
    {
      if (!read_only_[i])
      {
        send_mit_disable(
          can_ids_[i]);
      }
    }
  }


  return
    hardware_interface::CallbackReturn::SUCCESS;
}


// ============================================================
// READ
// ============================================================

hardware_interface::return_type
CubeMarsSystemHardware::read(
  const rclcpp::Time &,
  const rclcpp::Duration &)
{
  std::uint32_t read_id;
  std::uint8_t read_data[8];
  std::uint8_t read_len;


  while (
    can_.read_nonblocking(
      read_id,
      read_data,
      read_len))
  {
    if (
      protocol_mode_ ==
      MIT_PROTOCOL)
    {
      parse_mit_feedback(
        read_id,
        read_data,
        read_len);
    }
    else
    {
      parse_servo_feedback(
        read_id,
        read_data,
        read_len);
    }
  }


  const auto feedback_now = std::chrono::steady_clock::now();
  for (size_t i = 0; i < last_feedback_.size(); ++i) {
    feedback_ages_[i] = last_feedback_[i].time_since_epoch().count() == 0 ?
      std::numeric_limits<double>::infinity() :
      std::chrono::duration<double>(feedback_now - last_feedback_[i]).count();
  }

  // ==========================================================
  // Torque safety limit
  // ==========================================================

  for (
    std::size_t i = 0;
    i < info_.joints.size();
    i++)
  {
    if (
      trq_limits_[i] != 0.0 &&
      std::abs(
        hw_states_efforts_[i])
      >
      trq_limits_[i])
    {
      RCLCPP_ERROR(
        rclcpp::get_logger(
          "CubeMarsSystemHardware"),
        "Joint %lu went over torque limit.",
        i);


      if (
        protocol_mode_ ==
        MIT_PROTOCOL)
      {
        send_mit_disable(
          can_ids_[i]);
      }
      else
      {
        std::uint8_t data[4] =
        {
          0, 0, 0, 0
        };


        can_.write_message(
          can_ids_[i] |
          (CURRENT_LOOP << 8),
          data,
          4,
          CanSocket::FrameType::EXTENDED);
      }


      return
        hardware_interface::return_type::ERROR;
    }
  }


  return
    hardware_interface::return_type::OK;
}


// ============================================================
// WRITE
// ============================================================

hardware_interface::return_type
CubeMarsSystemHardware::write(
  const rclcpp::Time &,
  const rclcpp::Duration &)
{
  for (
    std::size_t i = 0;
    i < info_.joints.size();
    i++)
  {
    if (read_only_[i]) {
      continue;
    }


    double direction_sign = 1.0;

    if (
      info_.joints[i].parameters.count(
        "direction_sign") != 0)
    {
      direction_sign =
        std::stod(
          info_.joints[i].parameters.at(
            "direction_sign"));
    }


    // ========================================================
    // MIT PROTOCOL
    // ========================================================

    if (
      protocol_mode_ ==
      MIT_PROTOCOL)
    {
      switch (
        control_mode_[i])
      {

        // ====================================================
        // 순수 Torque Mode
        // ====================================================

        case CURRENT_LOOP:
        {
          if (
            !std::isnan(
              hw_commands_efforts_[i]))
          {
            const double tau =
              hw_commands_efforts_[i] *
              direction_sign;


            const double safe_tau =
              std::clamp(
                tau,
                mit_t_min_[i],
                mit_t_max_[i]);


            if (
              !send_mit_command(
                i,
                0.0,
                0.0,
                0.0,
                0.0,
                safe_tau))
            {
              return
                hardware_interface::return_type::ERROR;
            }
          }

          break;
        }


        // ====================================================
        // SPEED LOOP
        //
        // 최종 MIT 명령:
        //
        // p_des  = 0
        // v_des  = velocity controller command
        // kp     = 0
        // kd     = mit_vel_kd
        // tau_ff = base_tau_ff + external_tau_ff
        //
        // external_tau_ff에는 이후:
        //
        //   IMU stabilization
        // + obstacle compensation
        // + 기타 feed-forward
        //
        // 가 들어오게 됨.
        // ====================================================

        case SPEED_LOOP:
        {
          if (
            !std::isnan(
              hw_commands_velocities_[i]))
          {
            // ------------------------------------------------
            // 목표 wheel velocity
            // ------------------------------------------------

            const double v_des =
              hw_commands_velocities_[i] *
              direction_sign;


            // ------------------------------------------------
            // 기존 코드에서 사용하던 기본 feed-forward
            //
            // 작은 정지마찰 / 구동 보상
            // ------------------------------------------------

            double base_tau_ff =
              0.0;


            if (
              std::abs(v_des) >
              0.05)
            {
              base_tau_ff =
                (v_des > 0.0)
                ?
                0.35
                :
                -0.35;
            }


            // ------------------------------------------------
            // 새로 추가된 외부 torque feed-forward
            //
            // ros2_control effort command가 들어오면
            // 이를 MIT tau_ff로 사용
            // ------------------------------------------------

            double external_tau_ff =
              0.0;


            if (
              !std::isnan(
                hw_commands_efforts_[i]))
            {
              external_tau_ff =
                hw_commands_efforts_[i] *
                direction_sign;
            }


            // ------------------------------------------------
            // 최종 torque feed-forward
            // ------------------------------------------------

            double tau_ff =
              base_tau_ff +
              external_tau_ff;


            // MIT torque command 범위 제한
            tau_ff =
              std::clamp(
                tau_ff,
                mit_t_min_[i],
                mit_t_max_[i]);


            // ------------------------------------------------
            // CubeMars MIT command
            //
            // 실제 토크는 대략:
            //
            // tau =
            // kd * (v_des - v_actual)
            // + tau_ff
            //
            // ------------------------------------------------

            if (
              !send_mit_command(
                i,
                0.0,
                v_des,
                0.0,
                mit_vel_kd_[i],
                tau_ff))
            {
              return
                hardware_interface::return_type::ERROR;
            }
          }

          break;
        }


        // ====================================================
        // POSITION MODE
        // ====================================================

        case POSITION_LOOP:
        case POSITION_SPEED_LOOP:
        {
          if (
            !std::isnan(
              hw_commands_positions_[i]))
          {
            double p_des =
              hw_commands_positions_[i] *
              direction_sign;


            if (
              p_des >
              mit_p_max_[i])
            {
              p_des =
                mit_p_max_[i];
            }
            else if (
              p_des <
              mit_p_min_[i])
            {
              p_des =
                mit_p_min_[i];
            }


            if (
              !send_mit_command(
                i,
                p_des,
                0.0,
                mit_pos_kp_[i],
                mit_pos_kd_[i],
                0.0))
            {
              return
                hardware_interface::return_type::ERROR;
            }
          }

          break;
        }


        case UNDEFINED:
        default:
          break;
      }


      continue;
    }


    // ========================================================
    // SERVO PROTOCOL
    // ========================================================

    switch (
      control_mode_[i])
    {

      case UNDEFINED:
      {
        break;
      }


      case CURRENT_LOOP:
      {
        if (
          !std::isnan(
            hw_commands_efforts_[i]))
        {
          double commanded_effort =
            hw_commands_efforts_[i] *
            direction_sign;


          std::int32_t current =
            static_cast<std::int32_t>(
              commanded_effort *
              1000.0 /
              torque_constants_[i]);


          if (
            std::abs(current) >=
            60000)
          {
            RCLCPP_ERROR(
              rclcpp::get_logger(
                "CubeMarsSystemHardware"),
              "current command is over maximal allowed value of 60000: %d",
              current);

            return
              hardware_interface::return_type::ERROR;
          }


          std::uint8_t data[4];

          data[0] =
            (current >> 24) &
            0xFF;

          data[1] =
            (current >> 16) &
            0xFF;

          data[2] =
            (current >> 8) &
            0xFF;

          data[3] =
            current &
            0xFF;


          can_.write_message(
            can_ids_[i] |
            (CURRENT_LOOP << 8),
            data,
            4,
            CanSocket::FrameType::EXTENDED);
        }

        break;
      }


      case SPEED_LOOP:
      {
        if (
          !std::isnan(
            hw_commands_velocities_[i]))
        {
          double commanded_velocity =
            hw_commands_velocities_[i] *
            direction_sign;


          std::int32_t speed =
            static_cast<std::int32_t>(
              commanded_velocity *
              erpm_conversions_[i]);


          if (
            std::abs(speed) >=
            100000)
          {
            RCLCPP_ERROR(
              rclcpp::get_logger(
                "CubeMarsSystemHardware"),
              "speed command is over maximal allowed value of 100000: %d",
              speed);

            return
              hardware_interface::return_type::ERROR;
          }


          std::uint8_t data[4];

          data[0] =
            (speed >> 24) &
            0xFF;

          data[1] =
            (speed >> 16) &
            0xFF;

          data[2] =
            (speed >> 8) &
            0xFF;

          data[3] =
            speed &
            0xFF;


          can_.write_message(
            can_ids_[i] |
            (SPEED_LOOP << 8),
            data,
            4,
            CanSocket::FrameType::EXTENDED);
        }

        break;
      }


      case POSITION_LOOP:
      {
        if (
          !std::isnan(
            hw_commands_positions_[i]))
        {
          double commanded_position =
            hw_commands_positions_[i] *
            direction_sign;


          std::int32_t position =
            static_cast<std::int32_t>(
              (
                commanded_position +
                enc_offs_[i]
              )
              *
              10000.0
              *
              180.0 /
              PI_CONST);


          if (
            std::abs(position) >=
            360000000)
          {
            RCLCPP_ERROR(
              rclcpp::get_logger(
                "CubeMarsSystemHardware"),
              "position command is over maximal allowed value of 360000000: %d",
              position);

            return
              hardware_interface::return_type::ERROR;
          }


          std::uint8_t data[4];

          data[0] =
            (position >> 24) &
            0xFF;

          data[1] =
            (position >> 16) &
            0xFF;

          data[2] =
            (position >> 8) &
            0xFF;

          data[3] =
            position &
            0xFF;


          can_.write_message(
            can_ids_[i] |
            (POSITION_LOOP << 8),
            data,
            4,
            CanSocket::FrameType::EXTENDED);
        }

        break;
      }


      case POSITION_SPEED_LOOP:
      {
        if (
          !std::isnan(
            hw_commands_positions_[i]))
        {
          double commanded_position =
            hw_commands_positions_[i] *
            direction_sign;


          std::int32_t position =
            static_cast<std::int32_t>(
              (
                commanded_position +
                enc_offs_[i]
              )
              *
              10000.0
              *
              180.0 /
              PI_CONST);


          std::int16_t vel =
            limits_[i].first;

          std::int16_t acc =
            limits_[i].second;


          if (
            std::abs(position) >=
            360000000)
          {
            RCLCPP_ERROR(
              rclcpp::get_logger(
                "CubeMarsSystemHardware"),
              "position command is over maximal allowed value of 360000000: %d",
              position);

            return
              hardware_interface::return_type::ERROR;
          }


          std::uint8_t data[8];

          data[0] =
            (position >> 24) &
            0xFF;

          data[1] =
            (position >> 16) &
            0xFF;

          data[2] =
            (position >> 8) &
            0xFF;

          data[3] =
            position &
            0xFF;

          data[4] =
            (vel >> 8) &
            0xFF;

          data[5] =
            vel &
            0xFF;

          data[6] =
            (acc >> 8) &
            0xFF;

          data[7] =
            acc &
            0xFF;


          can_.write_message(
            can_ids_[i] |
            (POSITION_SPEED_LOOP << 8),
            data,
            8,
            CanSocket::FrameType::EXTENDED);
        }

        break;
      }
    }
  }


  return
    hardware_interface::return_type::OK;
}

}  // namespace cubemars_hardware


#include "pluginlib/class_list_macros.hpp"


PLUGINLIB_EXPORT_CLASS(
  cubemars_hardware::CubeMarsSystemHardware,
  hardware_interface::SystemInterface)
