cmake_minimum_required(VERSION 3.8)
project(MACMOI_free_fleet_assets)

find_package(ament_cmake REQUIRED)

install(DIRECTORY
  config
  launch
  maps
  nav_graphs
  DESTINATION share/${PROJECT_NAME}
)

ament_package()
