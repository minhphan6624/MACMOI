# Project Runbook

Important setup notes and commands for the TurtleBot3 / Nav2 / Open-RMF /
Free Fleet integration.

# 1. Common Environments

## 1.1. Central PC Environment

Use this in central-PC shells that run RMF, `free_fleet`, or RMF task dispatch:

```bash
source /home/minhqphan/projects/MAMCUI/adapter_ws/.venv/bin/activate
source /home/minhqphan/projects/MAMCUI/adapter_ws/install/setup.bash
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
export RMF_ASSET_SHARE=$(ros2 pkg prefix rmf_asset)/share/rmf_asset
```

If using a custom ROS domain, export the same value in every central-PC shell
that participates in RMF:

```bash
export ROS_DOMAIN_ID=<domain_id>
```

## 1.2. Robot PC Environment

Use this on each robot PC / Raspberry Pi:

```bash
source /home/ubuntu/MAMCUI/robot_ws/install/setup.bash
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
```

# 2. Build and Asset Maintenance

## 2.1. Build `adapter_ws`

Run on the central PC after cloning the `free_fleet` repository into
`adapter_ws/src`:

```bash
cd /home/minhqphan/projects/MAMCUI/adapter_ws
source /opt/ros/jazzy/setup.bash
source .venv/bin/activate
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp

rosdep install --from-paths src --ignore-src --rosdistro jazzy -yr
colcon build --cmake-args -DCMAKE_BUILD_TYPE=Release
```

If the venv is active during builds, install ROS build-helper Python packages in
that venv as needed, e.g. `catkin_pkg`.

## 2.2. Build `robot_ws`

If `robot_ws` has not been built on the robot PC, build it with `colcon` before
starting robot bringup.

## 2.3. Regenerate the RMF Nav Graph

Run this after editing the lab `.building.yaml` in `adapter_ws/src/rmf_asset`:

```bash
source /opt/ros/jazzy/setup.bash

ros2 run rmf_building_map_tools building_map_generator nav \
  $HOME/projects/MAMCUIadapter_ws/src/rmf_asset/maps/aiml-lab.building.yaml \
  $HOME/projects/MAMCUI/adapter_ws/src/rmf_asset/nav_graphs
```

The current lab adapter commands use the installed nav graph:

```bash
$RMF_ASSET_SHARE/nav_graphs/1.yaml
```

# 3. Single-Robot System Test

Use this flow for a physical smoke test with one TurtleBot3. The current
single-robot fleet config is:

```text
/home/minhqphan/projects/MAMCUI/adapter_ws/config/free_fleet/tb3_lab_fleet.yaml
```

That config currently enables `tb3_1`.

## 3.1. Startup Order

Start processes in this order:

1. Robot PC: robot hardware / Nav2 bringup
2. Central PC: Zenoh router
3. Robot PC: Zenoh ROS 2 bridge
4. Central PC: RMF common for the lab
5. Central PC: lab `free_fleet_adapter`
6. Central PC: dispatch a small patrol task only after the adapter stays up

## 3.2. Launch Robot Bringup / Nav2

Run on the robot PC:

```bash
source /home/ubuntu/MAMCUI/robot_ws/install/setup.bash
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp

ros2 launch robot_bringup robot.launch.py robot_id:=tb3_1
```

If you need to test a non-default Nav2 config, keep `robot_id:=...` and add an
explicit override:

```bash
ros2 launch robot_bringup robot.launch.py \
  robot_id:=tb3_1 \
  params_file:=$HOME/MAMCUI/robot_ws/install/robot_bringup/share/robot_bringup/config/nav2_waffle_pi_rpp.yaml
```

## 3.3. Start the Zenoh Router

Run on the central PC:

```bash
zenohd
```

If using a standalone downloaded router binary, run that binary instead.

## 3.4. Start the Zenoh ROS 2 Bridge

Run on the robot PC:

```bash
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp

zenoh-bridge-ros2dds -c ~/zenoh/config/tb3_robot1_zenoh.json5
# zenoh-bridge-ros2dds -c ~/zenoh/config/tb3_robot1_zenoh.json5

```

The bridge namespace must match the robot key in the fleet config.

## 3.5. Launch RMF Common for the Lab

Run on the central PC before launching the adapter:

```bash
source /home/minhqphan/projects/MAMCUI/adapter_ws/.venv/bin/activate
source /home/minhqphan/projects/MAMCUI/adapter_ws/install/setup.bash
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
export RMF_ASSET_SHARE=$(ros2 pkg prefix rmf_asset)/share/rmf_asset

ros2 launch rmf_asset aiml_lab_rmf_common.launch.xml \
  use_sim_time:=false \
  headless:=false \
  initial_map:=LG
```

## 3.6. Launch the Single-Robot Fleet Adapter

Run on the central PC after RMF common is running:

```bash
source /home/minhqphan/projects/MAMCUI/adapter_ws/.venv/bin/activate
source /home/minhqphan/projects/MAMCUI/adapter_ws/install/setup.bash
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
export RMF_ASSET_SHARE=$(ros2 pkg prefix rmf_asset)/share/rmf_asset

ros2 launch free_fleet_adapter fleet_adapter.launch.xml \
  use_sim_time:=false \
  config_file:=/home/minhqphan/projects/MAMCUI/adapter_ws/config/free_fleet/tb3_lab_fleet.yaml \
  nav_graph_file:=$RMF_ASSET_SHARE/nav_graphs/1.yaml
```

Healthy adapter startup should include a message that `tb3_1` was added to the
`tb3_lab` fleet and that its charger waypoint was set.

## 3.7. Dispatch a Small RMF Task

Only dispatch RMF tasks after the robot has localized, direct Nav2 goals work,
RMF common is running, and the free fleet adapter has added the robot.

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

Four-waypoint loop, repeated 2 times:

```bash
ros2 run rmf_demos_tasks dispatch_patrol \
  -p wp1 wp2 wp3 wp4 \
  -n 2 \
  -st 0
```

# 4. Two-Robot System Test

Use this flow when testing both TurtleBot3 robots together. The current
two-robot fleet config is:

```text
/home/minhqphan/projects/MAMCUI/adapter_ws/config/free_fleet/tb3_lab_two_robot_fleet.yaml
```

That config currently enables both `tb3_1` and `tb3_2`.

## 4.1. Startup Order

Start processes in this order:

1. Robot 1 PC: robot hardware / Nav2 bringup
2. Robot 2 PC: robot hardware / Nav2 bringup
3. Central PC: Zenoh router
4. Robot 1 PC: Zenoh ROS 2 bridge
5. Robot 2 PC: Zenoh ROS 2 bridge
6. Central PC: RMF common for the lab
7. Central PC: two-robot `free_fleet_adapter`
8. Central PC: dispatch RMF tasks only after both robots appear in fleet state

## 4.2. Launch Robot 1 Bringup / Nav2

Run on robot 1:

```bash
source /home/ubuntu/MAMCUI/robot_ws/install/setup.bash
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp

ros2 launch robot_bringup robot.launch.py robot_id:=tb3_1
```

## 4.3. Launch Robot 2 Bringup / Nav2

Run on robot 2:

```bash
source /home/ubuntu/MAMCUI/robot_ws/install/setup.bash
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp

ros2 launch robot_bringup robot.launch.py robot_id:=tb3_2
```

## 4.4. Start the Zenoh Router

Run on the central PC:

```bash
zenohd
```

## 4.5. Start a Zenoh ROS 2 Bridge on Each Robot

Run on each robot PC:

```bash
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp

zenoh-bridge-ros2dds -c ~/zenoh/config/tb3_robot1_zenoh.json5
# zenoh-bridge-ros2dds -c ~/zenoh/config/tb3_robot2_zenoh.json5
```

The first robot's bridge config should expose Nav2 as namespace `tb3_1`. The second robot's bridge config should expose Nav2 as namespace `tb3_2`.

## 4.6. Launch RMF Common for the Lab

Run on the central PC before launching the adapter:

```bash
source /home/minhqphan/projects/MAMCUI/adapter_ws/.venv/bin/activate
source /home/minhqphan/projects/MAMCUI/adapter_ws/install/setup.bash
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
export RMF_ASSET_SHARE=$(ros2 pkg prefix rmf_asset)/share/rmf_asset

ros2 launch rmf_asset aiml_lab_rmf_common.launch.xml \
  use_sim_time:=false \
  headless:=false \
  initial_map:=LG
```

## 4.7. Launch the Two-Robot Fleet Adapter

Run on the central PC after RMF common is running:

```bash
source /home/minhqphan/projects/MAMCUI/adapter_ws/.venv/bin/activate
source /home/minhqphan/projects/MAMCUI/adapter_ws/install/setup.bash
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
export RMF_ASSET_SHARE=$(ros2 pkg prefix rmf_asset)/share/rmf_asset

ros2 launch free_fleet_adapter fleet_adapter.launch.xml \
  use_sim_time:=false \
  config_file:=/home/minhqphan/projects/MAMCUI/adapter_ws/config/free_fleet/tb3_lab_two_robot_fleet.yaml \
  nav_graph_file:=$RMF_ASSET_SHARE/nav_graphs/1.yaml
```

Both configured robots must be on, localized, bridged, and publishing TF before
the two-robot adapter starts. Healthy startup should add both `tb3_1` and
`tb3_2` to fleet `tb3_lab`.

The current charger assignment is:

```text
tb3_1 -> wp1
tb3_2 -> wp2
```

## 4.8. Dispatch Two-Robot RMF Tasks

Dispatch one patrol task per robot so both robots patrol different waypoint
pairs at the same time:

```bash
ros2 run rmf_demos_tasks dispatch_patrol \
  -F tb3_lab \
  -R tb3_1 \
  -p wp1 wp4 \
  -n 1 \
  -st 0
```

```bash
ros2 run rmf_demos_tasks dispatch_patrol \
  -F tb3_lab \
  -R tb3_2 \
  -p wp2 wp3 \
  -n 1 \
  -st 0
```

Submit those from separate terminals, or run them sequentially from the central
PC once both robots are visible in `/fleet_states`.

Dispatch a simple patrol task to a specific robot:

```bash
ros2 run rmf_demos_tasks dispatch_patrol \
  -F tb3_lab \
  -R tb3_1 \
  -p wp1 wp2 \
  -n 2 \
  -st 0
```

Dispatch a second task to the same robot from another terminal:

```bash
ros2 run rmf_demos_tasks dispatch_patrol \
  -F tb3_lab \
  -R tb3_1 \
  -p wp3 wp4 \
  -n 2 \
  -st 0
```

If you want both requests submitted from one shell with a slight offset, use:

```bash
ros2 run rmf_demos_tasks dispatch_patrol \
  -F tb3_lab \
  -R tb3_1 \
  -p wp1 wp2 \
  -n 2 \
  -st 0

ros2 run rmf_demos_tasks dispatch_patrol \
  -F tb3_lab \
  -R tb3_1 \
  -p wp3 wp4 \
  -n 2 \
  -st 2
```

A single robot will still execute accepted tasks one after the other.

# 5. Verification and Checks

Put all checks here after the system is up.

## 5.1. Verify Robot Localization

Run on each robot PC before starting the fleet adapter:

```bash
ros2 run tf2_ros tf2_echo map base_footprint
```

Expected automatic initial pose from the current robot-specific Nav2 params:

```text
tb3_1 -> [0.0, 1.0, 0.0]
tb3_2 -> [1.0, 1.0, 0.0]
```

The robot should localize and accept manual Nav2 goals before testing RMF.

## 5.2. Verify Nav2 Through Zenoh

Run on the central PC after `zenohd`, the robot-side bridge, and robot Nav2 are
running.

Single-robot example:

```bash
source /home/minhqphan/projects/MAMCUI/adapter_ws/.venv/bin/activate
source /home/minhqphan/projects/MAMCUI/adapter_ws/install/setup.bash

ros2 run free_fleet_examples nav2_send_navigate_to_pose.py \
  --frame-id map \
  --namespace tb3_1 \
  -x 0.5564 \
  -y 2.0371
```

Two-robot example:

```bash
source /home/minhqphan/projects/MAMCUI/adapter_ws/.venv/bin/activate
source /home/minhqphan/projects/MAMCUI/adapter_ws/install/setup.bash

ros2 run free_fleet_examples nav2_send_navigate_to_pose.py \
  --frame-id map \
  --namespace tb3_1 \
  -x 0.5564 \
  -y 2.0371

ros2 run free_fleet_examples nav2_send_navigate_to_pose.py \
  --frame-id map \
  --namespace tb3_2 \
  -x -2.1961 \
  -y 2.1682
```

Known waypoint-to-Nav2-map correspondences:

```text
wp1 -> [ 0.5564,  2.0371]
wp2 -> [-2.1961,  2.1682]
wp3 -> [-2.3108,  0.2512]
wp4 -> [ 0.6056, -0.0110]
```

## 5.3. Verify RMF Fleet State

Run on the central PC after RMF common and the adapter are running:

```bash
ros2 topic echo /fleet_states
```

Expect fleet `tb3_lab` and the configured robot names.

## 5.4. Verify Adapter Command Flow

Watch the fleet adapter terminal for:

```text
Commanding [<robot_name>] to navigate ...
Navigation goal [...] accepted
Navigation goal [...] reached
```

## 5.5. Debug the Adapter with `gdb`

Run while the matching RMF common launch is already running.

```bash
source /opt/ros/jazzy/setup.bash
source /home/minhqphan/projects/MAMCUI/adapter_ws/.venv/bin/activate
source /home/minhqphan/projects/MAMCUI/adapter_ws/install/setup.bash
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp

gdb --args /home/minhqphan/projects/MAMCUI/adapter_ws/.venv/bin/python3 \
  /home/minhqphan/projects/MAMCUI/adapter_ws/install/free_fleet_adapter/lib/free_fleet_adapter/fleet_adapter.py \
  -c /home/minhqphan/projects/MAMCUI/adapter_ws/config/free_fleet/tb3_lab_fleet.yaml \
  -n $(ros2 pkg prefix rmf_asset)/share/rmf_asset/nav_graphs/1.yaml
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

Historical issue: the adapter segfaulted with exit code `-11` in one
environment. That was resolved by using a compatible `numpy` version. If this
returns, debug with `gdb` before editing maps or bridge configs.

## 5.6. Stock Free Fleet Example Control Test

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
