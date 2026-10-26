cmake_minimum_required(VERSION 3.8)
project(robot_error)

if(CMAKE_COMPILER_IS_GNUCXX OR CMAKE_CXX_COMPILER_ID MATCHES "Clang")
  add_compile_options(-Wall -Wextra -Wpedantic)
endif()

find_package(ament_cmake REQUIRED)
find_package(rclcpp REQUIRED)
find_package(std_msgs REQUIRED)
find_package(robot_msgs REQUIRED)

include_directories(include)

add_executable(error_manager_node src/error_manager_node.cpp)
ament_target_dependencies(error_manager_node
  rclcpp
  std_msgs
  robot_msgs
)

install(TARGETS
  error_manager_node
  DESTINATION lib/${PROJECT_NAME}
)

install(DIRECTORY include/
  DESTINATION include/
)

install(DIRECTORY launch
  DESTINATION share/${PROJECT_NAME}
)

ament_package()
