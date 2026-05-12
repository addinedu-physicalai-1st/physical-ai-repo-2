cmake_minimum_required(VERSION 3.8)
project(gogoping_msgs)

if(CMAKE_COMPILER_IS_GNUCXX OR CMAKE_CXX_COMPILER_ID MATCHES "Clang")
  add_compile_options(-Wall -Wextra -Wpedantic)
endif()

find_package(ament_cmake REQUIRED)
find_package(rosidl_default_generators REQUIRED)
find_package(std_msgs REQUIRED)
find_package(geometry_msgs REQUIRED)

# 메시지 / 서비스 / 액션 정의 — 실제 정의 추가 시 아래 목록에 등록.
rosidl_generate_interfaces(${PROJECT_NAME}
  "msg/Placeholder.msg"
  "srv/SendCommand.srv"
  DEPENDENCIES std_msgs geometry_msgs
)

ament_export_dependencies(rosidl_default_runtime)
ament_package()
