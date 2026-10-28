cmake_minimum_required(VERSION 3.16)
project(cubemars_hardware LANGUAGES CXX)

if(CMAKE_CXX_COMPILER_ID MATCHES "(GNU|Clang)")
  add_compile_options(-Wall -Wextra)
endif()

# find dependencies
set(THIS_PACKAGE_INCLUDE_DEPENDS
  hardware_interface
  pluginlib
  rclcpp
  rclcpp_lifecycle
)
find_package(ament_cmake REQUIRED)
foreach(Dependency IN ITEMS ${THIS_PACKAGE_INCLUDE_DEPENDS})
  find_package(${Dependency} REQUIRED)
endforeach()

## COMPILE
add_library(
  cubemars_hardware
  SHARED
  src/system.cpp
  src/can.cpp
)
target_compile_features(cubemars_hardware PUBLIC cxx_std_17)
target_include_directories(cubemars_hardware PUBLIC
  $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
  $<INSTALL_INTERFACE:include/cubemars_hardware>)
ament_target_dependencies(
  cubemars_hardware PUBLIC
  ${THIS_PACKAGE_INCLUDE_DEPENDS}
)

# Causes the visibility macros to use dllexport rather than dllimport,
# which is appropriate when building the dll but not consuming it.
target_compile_definitions(${PROJECT_NAME} PRIVATE "CUBEMARS_HARDWARE_BUILDING_DLL")

# Export hardware plugins
pluginlib_export_plugin_description_file(hardware_interface cubemars_hardware.xml)

## INSTALL
install(
  DIRECTORY include/
  DESTINATION include/${PROJECT_NAME}
)
install(TARGETS cubemars_hardware
  EXPORT export_${PROJECT_NAME}
  ARCHIVE DESTINATION lib
  LIBRARY DESTINATION lib
  RUNTIME DESTINATION bin
)

## EXPORTS
ament_export_targets(export_${PROJECT_NAME} HAS_LIBRARY_TARGET)
ament_export_dependencies(${THIS_PACKAGE_INCLUDE_DEPENDS})

include(CTest)
if(BUILD_TESTING)
  add_executable(can_fault_test test/can_fault_test.cpp src/can.cpp src/system.cpp)
  target_compile_features(can_fault_test PRIVATE cxx_std_17)
  target_include_directories(can_fault_test PRIVATE include)
  ament_target_dependencies(can_fault_test ${THIS_PACKAGE_INCLUDE_DEPENDS})
  target_link_options(can_fault_test PRIVATE "-Wl,--wrap=send" "-Wl,--wrap=recv")
  add_test(NAME can_fault_test COMMAND can_fault_test)
endif()
ament_package()
