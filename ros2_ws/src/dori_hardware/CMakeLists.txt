cmake_minimum_required(VERSION 3.8)
project(dori_hardware)

if(CMAKE_COMPILER_IS_GNUCXX OR CMAKE_CXX_COMPILER_ID MATCHES "Clang")
  add_compile_options(-Wall -Wextra -Wpedantic)
endif()

find_package(ament_cmake REQUIRED)
find_package(ament_cmake_python REQUIRED)
find_package(rclcpp REQUIRED)
find_package(std_msgs REQUIRED)
find_package(geometry_msgs REQUIRED)
find_package(sensor_msgs REQUIRED)
find_package(dori_msgs REQUIRED)
find_package(dynamixel_sdk REQUIRED)
find_package(dynamixel_sdk_custom_interfaces REQUIRED)

include_directories(include)

add_executable(dxl_driver_node src/dxl_driver_node.cpp)
ament_target_dependencies(dxl_driver_node
  rclcpp std_msgs dynamixel_sdk dynamixel_sdk_custom_interfaces
)

add_executable(dxl_bridge_node src/dxl_bridge_node.cpp)
ament_target_dependencies(dxl_bridge_node
  rclcpp
  std_msgs
  geometry_msgs
  sensor_msgs
  dori_msgs
  dynamixel_sdk_custom_interfaces
)

add_executable(dxl_state_publisher_node src/dxl_state_publisher_node.cpp)
ament_target_dependencies(dxl_state_publisher_node
  rclcpp
  std_msgs
  geometry_msgs
  sensor_msgs
  dori_msgs
  dynamixel_sdk_custom_interfaces
)

install(TARGETS
  dxl_driver_node
  dxl_bridge_node
  dxl_state_publisher_node
  DESTINATION lib/${PROJECT_NAME}
)

install(DIRECTORY include/
  DESTINATION include/
)

# Remove renamed launch files from existing overlays, including dangling symlinks.
foreach(retired_launch real_hardware system_real system_real_with_imu)
  install(CODE "file(REMOVE \"\$ENV{DESTDIR}${CMAKE_INSTALL_PREFIX}/share/${PROJECT_NAME}/launch/${retired_launch}.launch.py\")")
endforeach()
install(DIRECTORY launch config
  DESTINATION share/${PROJECT_NAME}
  PATTERN "__pycache__" EXCLUDE
)

# Installable host service assets. Building ROS never changes /etc or starts CAN.
install(DIRECTORY systemd DESTINATION share/${PROJECT_NAME})
install(PROGRAMS scripts/can_service.py scripts/install_can_service.py
  DESTINATION share/${PROJECT_NAME}/scripts
)

ament_python_install_package(${PROJECT_NAME})
install(PROGRAMS
  scripts/controller_spawner
  scripts/motor4_servo_node
  scripts/imu_node
  scripts/body_pitch_node
  scripts/body_stabilizer_node
  scripts/servo3_pitch_follower_node
  DESTINATION lib/${PROJECT_NAME}
)

ament_package()
