cmake_minimum_required(VERSION 3.8)
project(robot_supervisor)

if(CMAKE_COMPILER_IS_GNUCXX OR CMAKE_CXX_COMPILER_ID MATCHES "Clang")
  add_compile_options(-Wall -Wextra -Wpedantic)
endif()

find_package(ament_cmake REQUIRED)
find_package(rclcpp REQUIRED)
find_package(std_msgs REQUIRED)
find_package(geometry_msgs REQUIRED)
find_package(sensor_msgs REQUIRED)
find_package(robot_msgs REQUIRED)

include_directories(include)

add_executable(mode_manager_node src/mode_manager_node.cpp)
ament_target_dependencies(mode_manager_node
  rclcpp
  std_msgs
  geometry_msgs
  sensor_msgs
  robot_msgs
)

install(TARGETS
  mode_manager_node
  DESTINATION lib/${PROJECT_NAME}
)

install(DIRECTORY include/
  DESTINATION include/
)

install(DIRECTORY launch config
  DESTINATION share/${PROJECT_NAME}
)

ament_package()
