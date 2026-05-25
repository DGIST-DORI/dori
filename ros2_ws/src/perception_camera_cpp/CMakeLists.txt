cmake_minimum_required(VERSION 3.8)
project(perception_camera_cpp)

if(CMAKE_COMPILER_IS_GNUCXX OR CMAKE_CXX_COMPILER_ID MATCHES "Clang")
  add_compile_options(-Wall -Wextra -Wpedantic)
endif()

find_package(ament_cmake REQUIRED)
find_package(rclcpp REQUIRED)
find_package(sensor_msgs REQUIRED)
find_package(std_msgs REQUIRED)
find_package(cv_bridge REQUIRED)
find_package(OpenCV REQUIRED)
find_package(realsense2 QUIET)

if(NOT realsense2_FOUND)
  message(WARNING "realsense2 was not found. Skipping depth_camera_node build for perception_camera_cpp.")
else()
  add_executable(depth_camera_node src/depth_camera_node.cpp)
  ament_target_dependencies(depth_camera_node
    rclcpp
    sensor_msgs
    std_msgs
    cv_bridge
  )
  target_link_libraries(depth_camera_node
    ${OpenCV_LIBRARIES}
    realsense2::realsense2
  )

  target_compile_features(depth_camera_node PUBLIC cxx_std_17)

  install(TARGETS depth_camera_node
    DESTINATION lib/${PROJECT_NAME}
  )
endif()

ament_package()
