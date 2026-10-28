cmake_minimum_required(VERSION 3.8)
project(dori_control)

if(CMAKE_COMPILER_IS_GNUCXX OR CMAKE_CXX_COMPILER_ID MATCHES "Clang")
  add_compile_options(-Wall -Wextra -Wpedantic)
endif()

find_package(ament_cmake REQUIRED)
find_package(rclcpp REQUIRED)
find_package(std_msgs REQUIRED)
find_package(geometry_msgs REQUIRED)
find_package(sensor_msgs REQUIRED)
find_package(dori_msgs REQUIRED)

# Odometry and controller-switching dependencies
find_package(nav_msgs REQUIRED)
find_package(control_msgs REQUIRED)
find_package(tf2_ros REQUIRED)
find_package(tf2_msgs REQUIRED)
find_package(controller_manager_msgs REQUIRED)

include_directories(include)

# ==========================================
# 1. Transform nodes
# ==========================================
add_executable(transform_manager_node src/transform_manager_node.cpp)
ament_target_dependencies(transform_manager_node rclcpp std_msgs geometry_msgs sensor_msgs dori_msgs)

add_executable(transform_controller_node src/transform_controller_node.cpp)
ament_target_dependencies(transform_controller_node rclcpp std_msgs geometry_msgs sensor_msgs dori_msgs)

add_executable(fake_joint_states_node src/fake_joint_states_node.cpp)
ament_target_dependencies(fake_joint_states_node rclcpp std_msgs geometry_msgs sensor_msgs dori_msgs)

# ==========================================
# 2. Input nodes
# ==========================================
add_executable(keyboard_input_node src/keyboard_input_node.cpp)
ament_target_dependencies(keyboard_input_node rclcpp std_msgs geometry_msgs)

add_executable(virtual_vlm_input_node src/virtual_vlm_input_node.cpp)
ament_target_dependencies(virtual_vlm_input_node rclcpp std_msgs geometry_msgs)

add_executable(joystick_input_node src/joystick_input_node.cpp)
ament_target_dependencies(joystick_input_node rclcpp std_msgs geometry_msgs sensor_msgs)

# ==========================================
# 3. Drive nodes
# ==========================================
add_executable(tf_authority_check src/tf_authority_check.cpp)
ament_target_dependencies(tf_authority_check rclcpp tf2_msgs)

add_executable(wheel_odometry_node src/wheel_odometry_node.cpp)
target_compile_features(wheel_odometry_node PUBLIC cxx_std_14)
ament_target_dependencies(wheel_odometry_node rclcpp sensor_msgs nav_msgs geometry_msgs tf2_ros control_msgs)

add_executable(drive_controller_node src/drive_controller_node.cpp)
ament_target_dependencies(drive_controller_node rclcpp geometry_msgs std_msgs sensor_msgs control_msgs dori_msgs)

add_executable(bldc_command_bridge_node src/bldc_command_bridge_node.cpp)
ament_target_dependencies(bldc_command_bridge_node rclcpp geometry_msgs std_msgs dori_msgs controller_manager_msgs)

# ==========================================
# Install & Test Targets
# ==========================================
install(TARGETS
  transform_manager_node
  transform_controller_node
  fake_joint_states_node
  keyboard_input_node
  virtual_vlm_input_node
  joystick_input_node
  tf_authority_check
  wheel_odometry_node
  drive_controller_node
  bldc_command_bridge_node
  DESTINATION lib/${PROJECT_NAME}
)

install(DIRECTORY include/
  DESTINATION include/
)

install(DIRECTORY launch config
  DESTINATION share/${PROJECT_NAME}
)

if(BUILD_TESTING)
  find_package(ament_cmake_gtest REQUIRED)
  
  ament_add_gtest(test_wheel_speed_servo test/test_wheel_speed_servo.cpp)
  target_compile_features(test_wheel_speed_servo PUBLIC cxx_std_14)
  
  ament_add_gtest(test_wheel_odometry test/test_wheel_odometry.cpp)
  ament_target_dependencies(test_wheel_odometry control_msgs)
  target_compile_features(test_wheel_odometry PUBLIC cxx_std_14)
endif()

ament_package()
