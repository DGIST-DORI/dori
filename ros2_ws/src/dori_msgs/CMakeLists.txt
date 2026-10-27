cmake_minimum_required(VERSION 3.8)
project(dori_msgs)

find_package(ament_cmake REQUIRED)
find_package(geometry_msgs REQUIRED)
find_package(std_msgs REQUIRED)
find_package(sensor_msgs REQUIRED)
find_package(rosidl_default_generators REQUIRED)

rosidl_generate_interfaces(${PROJECT_NAME}
  "action/Navigate.action"
  "action/NavigateNamed.action"
  "action/Speak.action"
  "action/LLMQuery.action"
  "msg/CommandFeedback.msg"
  "msg/MitCommand.msg"
  "msg/SystemError.msg"
  "msg/TransformStep.msg"
  "msg/TransformStepResult.msg"
  DEPENDENCIES geometry_msgs std_msgs sensor_msgs
)

ament_export_dependencies(rosidl_default_runtime)
ament_package()
