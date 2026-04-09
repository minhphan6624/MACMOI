# Project Runbook

Important setup notes and commands for the TurtleBot3 / Nav2 / Open-RMF /
Free Fleet integration.

## Paths

Repository root:

```bash
/home/minhqphan/projects/MAMCUI
```

Robot workspace:

```bash
/home/minhqphan/projects/MAMCUI/robot_ws
```

RMF site workspace / map source:

```bash
/home/minhqphan/projects/MAMCUI/rmf_site_ws
```

Adapter workspace:

```bash
/home/minhqphan/projects/MAMCUI/adapter_ws
```

Adapter Python venv:

```bash
/home/minhqphan/projects/MAMCUI/adapter_ws/.venv
```

## Common Central-PC Environment

Use this in central-PC shells that run RMF or `free_fleet`:

```bash
source /opt/ros/jazzy/setup.bash
source /home/minhqphan/projects/MAMCUI/adapter_ws/.venv/bin/activate
source /home/minhqphan/projects/MAMCUI/adapter_ws/install/setup.bash
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
```

If using a custom ROS domain, export the same value in every central-PC shell
that participates in RMF:

```bash
export ROS_DOMAIN_ID=<domain_id>
```

## Build Free Fleet

Run on the central PC:

```bash
cd /home/minhqphan/projects/MAMCUI/adapter_ws
source /opt/ros/jazzy/setup.bash
source .venv/bin/activate
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp

rosdep install --from-paths src --ignore-src --rosdistro jazzy -yr
colcon build --cmake-args -DCMAKE_BUILD_TYPE=Release
```

If the venv is active during builds, install ROS build-helper Python packages in
that venv, e.g. `catkin_pkg`.

## Build Robot Workspace

Run where the robot workspace is being built:

```bash
cd /home/minhqphan/projects/MAMCUI/robot_ws
source /opt/ros/jazzy/setup.bash
colcon build --symlink-install
```

## Launch Physical Robot Bringup / Nav2

Run on the robot PC / Raspberry Pi, adjusting source paths if the workspace is
deployed at a different location:

```bash
source /opt/ros/jazzy/setup.bash
source /home/ubuntu/MAMCUI/robot_ws/install/setup.bash
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp

ros2 launch robot_bringup robot.launch.py
```

The robot should localize and accept manual Nav2 goals before testing RMF.

## Start Zenoh Router

Run on the central PC:

```bash
zenohd
```

If using a standalone downloaded router binary, run that binary instead.

## Start Zenoh ROS 2 Bridge

Run on the robot PC / Raspberry Pi.

Example shape:

```bash
source /opt/ros/jazzy/setup.bash
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp

zenoh-bridge-ros2dds -c ~/zenoh/config/<robot_bridge_config>.json5
```

If using a standalone downloaded bridge binary, run the extracted binary
instead of relying on `PATH`.

The bridge namespace must match the robot key in the fleet config. The current
configured robot key is:

```text
tb3_2
```

## Generate RMF Nav Graph

Run after editing the lab `.building.yaml`:

```bash
source /opt/ros/jazzy/setup.bash

ros2 run rmf_building_map_tools building_map_generator nav \
  /home/minhqphan/projects/MAMCUI/rmf_site_ws/maps/maps/aiml-lab.building.yaml \
  /home/minhqphan/projects/MAMCUI/rmf_site_ws/maps/generated_nav_graphs
```

Current generated graph expected by the adapter:

```text
/home/minhqphan/projects/MAMCUI/rmf_site_ws/maps/generated_nav_graphs/1.yaml
```

## Launch RMF Common for the Lab

Run on the central PC before launching the adapter:

```bash
source /opt/ros/jazzy/setup.bash
source /home/minhqphan/projects/MAMCUI/adapter_ws/.venv/bin/activate
source /home/minhqphan/projects/MAMCUI/adapter_ws/install/setup.bash
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp

ros2 launch /home/minhqphan/projects/MAMCUI/adapter_ws/install/free_fleet_examples/share/free_fleet_examples/include/rmf_common.launch.xml \
  use_sim_time:=false \
  headless:=false \
  initial_map:=LG \
  config_file:=/home/minhqphan/projects/MAMCUI/rmf_site_ws/maps/maps/aiml-lab.building.yaml
```

This uses the generic RMF common launch with the lab building file. It is not
the Office demo.

## Launch Lab Free Fleet Adapter

Run on the central PC after RMF common is running:

```bash
source /opt/ros/jazzy/setup.bash
source /home/minhqphan/projects/MAMCUI/adapter_ws/.venv/bin/activate
source /home/minhqphan/projects/MAMCUI/adapter_ws/install/setup.bash
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp

ros2 launch free_fleet_adapter fleet_adapter.launch.xml \
  use_sim_time:=false \
  config_file:=/home/minhqphan/projects/MAMCUI/adapter_ws/config/free_fleet/tb3_lab_fleet.yaml \
  nav_graph_file:=/home/minhqphan/projects/MAMCUI/rmf_site_ws/maps/generated_nav_graphs/1.yaml
```

Known current issue: this adapter process crashes with exit code `-11` in the
current environment.

## Launch Stock Free Fleet Example Control Test

RMF common terminal:

```bash
source /opt/ros/jazzy/setup.bash
source /home/minhqphan/projects/MAMCUI/adapter_ws/.venv/bin/activate
source /home/minhqphan/projects/MAMCUI/adapter_ws/install/setup.bash
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp

ros2 launch free_fleet_examples turtlebot3_world_rmf_common.launch.xml
```

Example adapter terminal:

```bash
source /opt/ros/jazzy/setup.bash
source /home/minhqphan/projects/MAMCUI/adapter_ws/.venv/bin/activate
source /home/minhqphan/projects/MAMCUI/adapter_ws/install/setup.bash
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp

ros2 launch free_fleet_examples nav2_tb3_simulation_fleet_adapter.launch.xml
```

Known current issue: the stock example adapter also crashes with exit code
`-11` once it can discover RMF schedule.

## Debug Adapter Crash with gdb

Run while the matching RMF common launch is already running.

Lab adapter under `gdb`:

```bash
source /opt/ros/jazzy/setup.bash
source /home/minhqphan/projects/MAMCUI/adapter_ws/.venv/bin/activate
source /home/minhqphan/projects/MAMCUI/adapter_ws/install/setup.bash
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp

gdb --args /home/minhqphan/projects/MAMCUI/adapter_ws/.venv/bin/python3 \
  /home/minhqphan/projects/MAMCUI/adapter_ws/install/free_fleet_adapter/lib/free_fleet_adapter/fleet_adapter.py \
  -c /home/minhqphan/projects/MAMCUI/adapter_ws/config/free_fleet/tb3_lab_fleet.yaml \
  -n /home/minhqphan/projects/MAMCUI/rmf_site_ws/maps/generated_nav_graphs/1.yaml
```

At the `(gdb)` prompt:

```gdb
run
```

After the crash:

```gdb
bt
```

Save the `bt` backtrace.

## Intended Startup Order

For the physical robot smoke test, start processes in this order:

1. robot PC: robot hardware / Nav2 bringup
2. central PC: `zenohd`
3. robot PC: `zenoh-bridge-ros2dds`
4. central PC: RMF common launch for the lab building file
5. central PC: lab `free_fleet_adapter`
6. central PC: dispatch a small loop / patrol task only after the adapter stays up

## Important Current Files

Lab building source:

```text
/home/minhqphan/projects/MAMCUI/rmf_site_ws/maps/maps/aiml-lab.building.yaml
```

Lab RMF drawing:

```text
/home/minhqphan/projects/MAMCUI/rmf_site_ws/maps/maps/aiml-lab.png
```

Generated lab nav graph:

```text
/home/minhqphan/projects/MAMCUI/rmf_site_ws/maps/generated_nav_graphs/1.yaml
```

Lab fleet config:

```text
/home/minhqphan/projects/MAMCUI/adapter_ws/config/free_fleet/tb3_lab_fleet.yaml
```

