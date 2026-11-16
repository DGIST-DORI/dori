cmake_minimum_required(VERSION 3.8)
project(dori_perception_camera)

if(CMAKE_COMPILER_IS_GNUCXX OR CMAKE_CXX_COMPILER_ID MATCHES "Clang")
  add_compile_options(-Wall -Wextra -Wpedantic)
endif()

find_package(ament_cmake REQUIRED)
find_package(rclcpp REQUIRED)
find_package(sensor_msgs REQUIRED)
find_package(std_msgs REQUIRED)
find_package(OpenCV REQUIRED COMPONENTS core videoio)
find_package(yaml-cpp REQUIRED)

add_executable(rgb_camera_node src/rgb_camera_node.cpp)
ament_target_dependencies(rgb_camera_node
  rclcpp
  sensor_msgs
  std_msgs
)
target_link_libraries(rgb_camera_node
  ${OpenCV_LIBRARIES}
  yaml-cpp
)

target_compile_features(rgb_camera_node PUBLIC cxx_std_17)

install(TARGETS rgb_camera_node
  DESTINATION lib/${PROJECT_NAME}
)

if(BUILD_TESTING)
  find_package(ament_cmake_gtest REQUIRED)
  ament_add_gtest(test_camera_calibration test/test_camera_calibration.cpp)
  ament_target_dependencies(test_camera_calibration sensor_msgs)
  target_include_directories(test_camera_calibration PRIVATE src)
  target_link_libraries(test_camera_calibration yaml-cpp)
  target_compile_features(test_camera_calibration PUBLIC cxx_std_17)
endif()

ament_package()
