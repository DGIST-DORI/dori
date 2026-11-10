cmake_minimum_required(VERSION 3.8)
project(dori_bringup)

if(CMAKE_COMPILER_IS_GNUCXX OR CMAKE_CXX_COMPILER_ID MATCHES "Clang")
  add_compile_options(-Wall -Wextra -Wpedantic)
endif()

# find dependencies
find_package(ament_cmake REQUIRED)
find_package(ament_cmake_python REQUIRED)
ament_python_install_package(${PROJECT_NAME})
install(PROGRAMS scripts/readiness_monitor DESTINATION lib/${PROJECT_NAME})
# uncomment the following section in order to fill in
# further dependencies manually.
# find_package(<dependency> REQUIRED)

# Install launch files
# Remove retired/moved entrypoints from existing overlays on incremental builds.
foreach(retired_launch bringup_dev hardware voice interaction perception)
  install(CODE "file(REMOVE \"\$ENV{DESTDIR}${CMAKE_INSTALL_PREFIX}/share/${PROJECT_NAME}/launch/${retired_launch}.launch.py\")")
endforeach()
install(DIRECTORY
  launch
  DESTINATION share/${PROJECT_NAME}/
  PATTERN "__pycache__" EXCLUDE
)

# Install config files
install(DIRECTORY
  config
  DESTINATION share/${PROJECT_NAME}/
)

if(BUILD_TESTING)
  find_package(ament_lint_auto REQUIRED)
  # the following line skips the linter which checks for copyrights
  # comment the line when a copyright and license is added to all source files
  # set(ament_cmake_copyright_FOUND TRUE)
  # the following line skips cpplint (only works in a git repo)
  # comment the line when this package is in a git repo and when
  # a copyright and license is added to all source files
  # set(ament_cmake_cpplint_FOUND TRUE)
  ament_lint_auto_find_test_dependencies()
endif()

ament_package()
