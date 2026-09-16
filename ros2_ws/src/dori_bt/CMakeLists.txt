cmake_minimum_required(VERSION 3.8)
project(dori_bt)

if(CMAKE_COMPILER_IS_GNUCXX OR CMAKE_CXX_COMPILER_ID MATCHES "Clang")
  add_compile_options(-Wall -Wextra -Wpedantic)
endif()

# BehaviorTree.CPP v4는 C++17 이상을 필수적으로 요구합니다.
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# 1. 의존성 패키지 찾기
find_package(ament_cmake REQUIRED)
find_package(rclcpp REQUIRED)
find_package(rclcpp_action REQUIRED)
find_package(behaviortree_cpp REQUIRED)
find_package(dori_msgs REQUIRED)
find_package(nav2_behavior_tree REQUIRED)

include_directories(
  include
)

# 2. 메인 실행 노드 (BT Executor) 빌드 설정
add_executable(dori_tree_executor
  src/dori_bt_main.cpp
  # TODO: 앞으로 만들 커스텀 노드들의 .cpp 파일들을 여기에 추가하게 됩니다.
  # 예: src/actions/speak_node.cpp
)

target_include_directories(dori_tree_executor PUBLIC
  $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
  $<INSTALL_INTERFACE:include>
)

# 3. 타겟에 의존성 링크
ament_target_dependencies(dori_tree_executor
  rclcpp
  rclcpp_action
  behaviortree_cpp
  dori_msgs
  nav2_behavior_tree
)

# 4. Install 규칙 지정

# 4-1. 실행 파일 (바이너리) 복사
install(TARGETS dori_tree_executor
  DESTINATION lib/${PROJECT_NAME}
)

# 4-2. 헤더 파일 디렉토리 복사
install(DIRECTORY include/
  DESTINATION include
)

# 4-3. BehaviorTree XML 파일 복사 (매우 중요!)
install(DIRECTORY behavior_trees
  DESTINATION share/${PROJECT_NAME}
)

ament_package()
