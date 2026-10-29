cmake_minimum_required(VERSION 3.8)
project(dori_mapping)
find_package(ament_cmake REQUIRED)
find_package(ament_cmake_python REQUIRED)
ament_python_install_package(lidar_odometry)
install(DIRECTORY launch config scripts DESTINATION share/${PROJECT_NAME} USE_SOURCE_PERMISSIONS
  PATTERN "__pycache__" EXCLUDE)
install(PROGRAMS scripts/lidar_odometry_node.py DESTINATION lib/${PROJECT_NAME})
ament_package()
