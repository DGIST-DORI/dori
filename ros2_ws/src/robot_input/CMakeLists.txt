cmake_minimum_required(VERSION 3.8)
project(robot_input)

if(CMAKE_COMPILER_IS_GNUCXX OR CMAKE_CXX_COMPILER_ID MATCHES "Clang")
  add_compile_options(-Wall -Wextra -Wpedantic)
endif()

find_package(ament_cmake REQUIRED)
find_package(rclcpp REQUIRED)
find_package(std_msgs REQUIRED)
find_package(geometry_msgs REQUIRED)
find_package(sensor_msgs REQUIRED)

include_directories(include)

add_executable(keyboard_input_node src/keyboard_input_node.cpp)
ament_target_dependencies(keyboard_input_node
  rclcpp
  std_msgs
  geometry_msgs
)

add_executable(virtual_vlm_input_node src/virtual_vlm_input_node.cpp)
ament_target_dependencies(virtual_vlm_input_node
  rclcpp
  std_msgs
  geometry_msgs
)

add_executable(joystick_input_node src/joystick_input_node.cpp)
ament_target_dependencies(joystick_input_node
  rclcpp
  std_msgs
  geometry_msgs
  sensor_msgs
)

install(TARGETS
  keyboard_input_node
  virtual_vlm_input_node
  joystick_input_node
  DESTINATION lib/${PROJECT_NAME}
)

install(DIRECTORY include/
  DESTINATION include/
)

install(DIRECTORY launch
  DESTINATION share/${PROJECT_NAME}
)

ament_package()
