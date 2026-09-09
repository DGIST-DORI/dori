cmake_minimum_required(VERSION 3.8)
project(robot_transform)

if(CMAKE_COMPILER_IS_GNUCXX OR CMAKE_CXX_COMPILER_ID MATCHES "Clang")
  add_compile_options(-Wall -Wextra -Wpedantic)
endif()

find_package(ament_cmake REQUIRED)
find_package(rclcpp REQUIRED)
find_package(std_msgs REQUIRED)
find_package(geometry_msgs REQUIRED)
find_package(sensor_msgs REQUIRED)
find_package(robot_msgs REQUIRED)
find_package(dynamixel_sdk_custom_interfaces REQUIRED)

include_directories(include)

add_executable(transform_manager_node src/transform_manager_node.cpp)
ament_target_dependencies(transform_manager_node
  rclcpp
  std_msgs
  geometry_msgs
  sensor_msgs
  robot_msgs
)

add_executable(transform_controller_node src/transform_controller_node.cpp)
ament_target_dependencies(transform_controller_node
  rclcpp
  std_msgs
  geometry_msgs
  sensor_msgs
  robot_msgs
)

add_executable(fake_joint_states_node src/fake_joint_states_node.cpp)
ament_target_dependencies(fake_joint_states_node
  rclcpp
  std_msgs
  geometry_msgs
  sensor_msgs
  robot_msgs
)

add_executable(dxl_bridge_node src/dxl_bridge_node.cpp)
ament_target_dependencies(dxl_bridge_node
  rclcpp
  std_msgs
  geometry_msgs
  sensor_msgs
  robot_msgs
  dynamixel_sdk_custom_interfaces
)

add_executable(dxl_state_publisher_node src/dxl_state_publisher_node.cpp)
ament_target_dependencies(dxl_state_publisher_node
  rclcpp
  std_msgs
  geometry_msgs
  sensor_msgs
  robot_msgs
  dynamixel_sdk_custom_interfaces
)

install(TARGETS
  transform_manager_node
  transform_controller_node
  fake_joint_states_node
  dxl_bridge_node
  dxl_state_publisher_node
  DESTINATION lib/${PROJECT_NAME}
)

install(DIRECTORY include/
  DESTINATION include/
)

install(DIRECTORY launch config
  DESTINATION share/${PROJECT_NAME}
)

ament_package()
