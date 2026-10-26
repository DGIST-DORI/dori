cmake_minimum_required(VERSION 3.8)
project(robot_navigation)
find_package(ament_cmake REQUIRED)
find_package(nav2_smac_planner REQUIRED)
find_package(nav2_core REQUIRED)
find_package(nav2_util REQUIRED)
find_package(pluginlib REQUIRED)
add_library(relaxed_heading_planner SHARED src/relaxed_heading_planner.cpp)
target_compile_features(relaxed_heading_planner PUBLIC cxx_std_17)
ament_target_dependencies(relaxed_heading_planner nav2_smac_planner nav2_core nav2_util pluginlib)
pluginlib_export_plugin_description_file(nav2_core planners.xml)
install(TARGETS relaxed_heading_planner LIBRARY DESTINATION lib)
# Only the private velocity gate is installed from this transitional package.
# Goal handling, web control and named-goal APIs are owned by dori_navigation
# or the dashboard and are deliberately not shipped.
install(DIRECTORY launch config DESTINATION share/${PROJECT_NAME} USE_SOURCE_PERMISSIONS
  PATTERN "__pycache__" EXCLUDE)
install(PROGRAMS
  scripts/nav_drive_bridge.py
  scripts/navigation_contract.py
  DESTINATION share/${PROJECT_NAME}/scripts)
ament_package()
