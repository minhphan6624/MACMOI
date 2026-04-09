# Project Runbook

Important setup notes and commands for the TurtleBot3 / Nav2 / Open-RMF /
Free Fleet integration.

# 1. Intended Startup Order

For the physical robot smoke test, start processes in this order:

1. Robot PC: robot hardware / Nav2 bringup
2. Central PC: run zenoh router via: `zenohd`
3. Robot PC: run zenoh bridge `zenoh-bridge-ros2dds`
4. Central PC: RMF common launch for the lab building file
5. Central PC: lab `free_fleet_adapter`
6. Central PC: dispatch a small loop / patrol task only after the adapter stays up

## 1.1. Launch Physical Robot Bringup / Nav2

Run on the robot PC / Raspberry Pi, adjusting source paths if the workspace is
deployed at a different location:

```bash
source /home/ubuntu/MAMCUI/robot_ws/install/setup.bash
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp

ros2 launch robot_bringup robot.launch.py
```

## 1.2. Start Zenoh Router

Run on the central PC: `zenohd` (Run this where the zeno binary was installed, likely `~/zenoh`)
If using a standalone downloaded router binary, run that binary instead.

## 1.3. Start Zenoh ROS 2 Bridge

Run on the robot PC / Raspberry Pi.

```bash
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp

zenoh-bridge-ros2dds -c ~/zenoh/config/<robot_bridge_config>.json5
```

## 1.4. Launch RMF Common for the Lab

Run on the central PC before launching the adapter. This uses the rmf common launch file from the free_fleet_examples package:

```bash
source /home/minhqphan/projects/MAMCUI/adapter_ws/.venv/bin/activate
source /home/minhqphan/projects/MAMCUI/adapter_ws/install/setup.bash
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp

ros2 launch /home/minhqphan/projects/MAMCUI/adapter_ws/install/free_fleet_examples/share/free_fleet_examples/include/rmf_common.launch.xml \
  use_sim_time:=false \
  headless:=false \
  initial_map:=LG \
  config_file:=/home/minhqphan/projects/MAMCUI/rmf_site_ws/maps/maps/aiml-lab.building.yaml
```

This uses the generic RMF common launch with the lab building file.

## 1.5. Launch Lab Free Fleet Adapter

Run on the central PC after RMF common is running:

```bash
source /home/minhqphan/projects/MAMCUI/adapter_ws/.venv/bin/activate
source /home/minhqphan/projects/MAMCUI/adapter_ws/install/setup.bash
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp

ros2 launch free_fleet_adapter fleet_adapter.launch.xml \
  use_sim_time:=false \
  config_file:=/home/minhqphan/projects/MAMCUI/adapter_ws/config/free_fleet/tb3_lab_fleet.yaml \
  nav_graph_file:=/home/minhqphan/projects/MAMCUI/rmf_site_ws/maps/generated_nav_graphs/1.yaml
```

Healthy adapter startup should include a message that the configured robot was
added to the `tb3_lab` fleet and that its charger waypoint was set.

## 1.6. Task Dispatch

Only dispatch RMF tasks after the robot has been localized, direct Nav2 goals
work, RMF common is running, and the free fleet adapter has added the robot.

Central-PC environment for task dispatch:

```bash
source /home/minhqphan/projects/MAMCUI/adapter_ws/.venv/bin/activate
source /home/minhqphan/projects/MAMCUI/adapter_ws/install/setup.bash
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
```

Single waypoint smoke test:

```bash
ros2 run rmf_demos_tasks dispatch_patrol \
  -p wp1 \
  -n 1 \
  -st 0
```

Four-waypoint loop, repeated 4 times:

```bash
ros2 run rmf_demos_tasks dispatch_patrol \
  -p wp1 wp2 wp3 wp4 \
  -n 4 \
  -st 0
```

Watch the fleet adapter terminal for:

```text
Commanding [<robot_name>] to navigate ...
Navigation goal [...] accepted
Navigation goal [...] reached
```

# 2. Build scripts

## 2.1. Build Free Fleet

After cloning the free-fleet rpository to the src directory of the adapter_ws workspace, Run this to build the free_fleet packages on the central PC:

```bash
cd /home/minhqphan/projects/MAMCUI/adapter_ws
source /opt/ros/jazzy/setup.bash
source .venv/bin/activate
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp

rosdep install --from-paths src --ignore-src --rosdistro jazzy -yr
colcon build --cmake-args -DCMAKE_BUILD_TYPE=Release
```

If the venv is active during builds, make sure to  install ROS build-helper Python packages in that venv, e.g. `catkin_pkg`.

## 2.2. Build robot workspace

If the robot_ws has not been built, build it with colcon

# 3. Common Central-PC Environment

Use this in central-PC shells that run RMF or `free_fleet`:

```bash
source /home/minhqphan/projects/MAMCUI/adapter_ws/.venv/bin/activate
source /home/minhqphan/projects/MAMCUI/adapter_ws/install/setup.bash
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
```

If using a custom ROS domain, export the same value in every central-PC shell that participates in RMF:

```bash
export ROS_DOMAIN_ID=<domain_id>
```

# 4. Other utilities
The robot should localize and accept manual Nav2 goals before testing RMF.

If using a standalone downloaded bridge binary, run the extracted binary instead of relying on `PATH`.
The bridge namespace must match the robot key in the fleet config. The current
configured robot key is: `tb3_2`.

## Check RMF Fleet State

Run on the central PC after RMF common and the adapter are running:

```bash
ros2 topic echo /fleet_states
```

Expect fleet `tb3_lab` and the configured robot name.

## Test Nav2 Through Zenoh

Run on the central PC after `zenohd`, the robot-side bridge, and robot Nav2 are
running. Replace `tb3_2` if the bridge namespace / fleet robot name is
different.

```bash
source /home/minhqphan/projects/MAMCUI/adapter_ws/.venv/bin/activate
source /home/minhqphan/projects/MAMCUI/adapter_ws/install/setup.bash

ros2 run free_fleet_examples nav2_send_navigate_to_pose.py \
  --frame-id map \
  --namespace tb3_2 \
  -x 0.5564 \
  -y 2.0371
```

Known waypoint-to-Nav2-map correspondences:

```text
wp1 -> [ 0.5564,  2.0371]
wp2 -> [-2.1961,  2.1682]
wp3 -> [-2.3108,  0.2512]
wp4 -> [ 0.6056, -0.0110]
```

## Generate RMF Nav Graph

This should be run after editing the lab `.building.yaml` to generate a navigation graph to be used for launching free-fleet:

```bash
source /opt/ros/jazzy/setup.bash

ros2 run rmf_building_map_tools building_map_generator nav \
  /home/minhqphan/projects/MAMCUI/rmf_site_ws/maps/maps/aiml-lab.building.yaml \
  /home/minhqphan/projects/MAMCUI/rmf_site_ws/maps/generated_nav_graphs
```

# Launch Stock Free Fleet Example Control Test

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

Historical issue: the adapter segfaulted with exit code `-11` in one
environment. That was resolved by using a compatible `numpy` version. If this
returns, debug with `gdb` before editing maps or bridge configs.

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
