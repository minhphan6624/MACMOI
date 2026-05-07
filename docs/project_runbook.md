# Project Runbook

Runbook for the TurtleBot3 / Nav2 / Open-RMF / Free Fleet integration.

The main workflow is the two-robot RMF deployment. Optional sections cover the
web UI, running RMF components separately, and maintenance/debug tasks.

# 1. Initial Setup

## 1.1. Central PC Environment

Use this in every central-PC terminal that runs RMF, Free Fleet, mission
manager, or RMF task commands:

```bash
source /opt/ros/jazzy/setup.bash
source /home/minhqphan/projects/MACMOI/rmf_ws/.venv/bin/activate
source /home/minhqphan/projects/MACMOI/rmf_ws/install/setup.bash
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
export SYSTEM_RMF_SHARE=$(ros2 pkg prefix system_rmf_bringup)/share/system_rmf_bringup
export FREE_FLEET_BRINGUP_SHARE=$(ros2 pkg prefix free_fleet_bringup)/share/free_fleet_bringup
```

If using a custom ROS domain, export the same value in every terminal:

```bash
export ROS_DOMAIN_ID=<domain_id>
```

## 1.2. Robot PC Environment

Use this on each TurtleBot3 PC / Raspberry Pi:

```bash
source /home/ubuntu/MACMOI/robot_ws/install/setup.bash
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
```

## 1.3. Build Workspaces

Build `rmf_ws` on the central PC:

```bash
cd /home/minhqphan/projects/MACMOI/rmf_ws
source /opt/ros/jazzy/setup.bash
source .venv/bin/activate
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp

rosdep install --from-paths src --ignore-src --rosdistro jazzy -yr
colcon build --symlink-install --cmake-args -DCMAKE_BUILD_TYPE=Release
source install/setup.bash
```

Build `robot_ws` on each robot PC if it has not already been built:

```bash
cd /home/ubuntu/MACMOI/robot_ws
source /opt/ros/jazzy/setup.bash
colcon build --symlink-install
source install/setup.bash
```

Install web dependencies only if you plan to use the web UI:

```bash
cd /home/minhqphan/projects/MACMOI/web
pnpm install
```

## 1.4. Current Map Semantics

Active building file:

```text
rmf_ws/src/system_rmf_bringup/maps/aiml-lab.building.yaml
```

Active RMF nav graph:

```text
rmf_ws/src/system_rmf_bringup/nav_graphs/1.yaml
```

Current waypoint meaning:

```text
robot1_home = tb3_1 charger/home
robot2_home = tb3_2 charger/home
wp1 = source
wp2 = staging
wp3 = transfer
wp4 = destination
```

Current traffic graph:

```text
robot1_home <-> wp1
robot1_home <-> wp2
robot2_home <-> wp2
robot2_home <-> wp3
wp1 <-> wp3
wp2 <-> wp3
wp3 <-> wp4
```

Only `robot1_home` and `robot2_home` should be marked as chargers.

# 2. Main Workflow: Two-Robot RMF Run

Use this flow for the normal lab run with both robots connected to RMF.

## 2.1. Start Robot Bringup

On robot 1:

```bash
source /home/ubuntu/MACMOI/robot_ws/install/setup.bash
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp

ros2 launch robot_bringup robot.launch.py robot_id:=tb3_1
```

On robot 2:

```bash
source /home/ubuntu/MACMOI/robot_ws/install/setup.bash
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp

ros2 launch robot_bringup robot.launch.py robot_id:=tb3_2
```

Both robots should be localized in Nav2 before starting the fleet adapter.
The robot-specific Nav2 configs currently initialize AMCL near the RMF home
zones:

```text
tb3_1 initial_pose -> [ 2.1766, 2.1308, 0.0]
tb3_2 initial_pose -> [-2.7358, 2.2426, 0.0]
```

Physically place the robots at those home-zone poses before launching Nav2, or
update the initial poses to match the robots' actual physical poses.

## 2.2. Start Zenoh

On the central PC:

```bash
zenohd
```

On robot 1:

```bash
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
zenoh-bridge-ros2dds -c ~/zenoh/config/tb3_robot1_zenoh.json5
```

On robot 2:

```bash
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
zenoh-bridge-ros2dds -c ~/zenoh/config/tb3_robot2_zenoh.json5
```

The bridge namespaces must match the fleet robot names: `tb3_1` and `tb3_2`.

## 2.3. Launch RMF And Free Fleet

On the central PC:

```bash
source /opt/ros/jazzy/setup.bash
source /home/minhqphan/projects/MACMOI/rmf_ws/.venv/bin/activate
source /home/minhqphan/projects/MACMOI/rmf_ws/install/setup.bash
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
export FREE_FLEET_BRINGUP_SHARE=$(ros2 pkg prefix free_fleet_bringup)/share/free_fleet_bringup

ros2 launch system_rmf_bringup system.launch.py \
  use_sim_time:=false \
  headless:=false \
  config_file:=$FREE_FLEET_BRINGUP_SHARE/config/fleet/aiml_lab_multi_tb3_fleet.yaml
```

Healthy startup should add both robots to fleet `tb3_lab`, with chargers:

```text
tb3_1 -> robot1_home
tb3_2 -> robot2_home
```

## 2.4. Run The Mission Manager

Start this only after both robots are visible in fleet state.

```bash
source /opt/ros/jazzy/setup.bash
source /home/minhqphan/projects/MACMOI/rmf_ws/.venv/bin/activate
source /home/minhqphan/projects/MACMOI/rmf_ws/install/setup.bash
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp

ros2 run mrd_mission_manager mission_manager_node \
  --ros-args \
  -p mission_id:=m1 \
  -p total_packages:=1 \
  -p auto_start:=true \
  -p fleet_name:=tb3_lab \
  -p upstream_robot:=tb3_1 \
  -p downstream_robot:=tb3_2 \
  -p source_waypoint:=wp1 \
  -p staging_waypoint:=wp2 \
  -p transfer_waypoint:=wp3 \
  -p destination_waypoint:=wp4 \
  -p upstream_home_waypoint:=robot1_home \
  -p downstream_home_waypoint:=robot2_home \
  -p task_summaries_topic:=task_summaries
```

For more packages:

```bash
-p total_packages:=3
```

Use a fresh `mission_id` for each new run if old task state is still visible in
the dashboard or RMF logs.

Expected mission route:

```text
tb3_1: robot1_home/source area -> wp1 -> wp3
tb3_2: robot2_home/staging area -> wp2 -> wp3
tb3_2: wp3 -> wp4
```

# 3. Optional: Web UI Run

Use this when running the RMF dashboard against the lab deployment.

## 3.1. Start The API Server

On the central PC:

```bash
source /opt/ros/jazzy/setup.bash
source /home/minhqphan/projects/MACMOI/rmf_ws/install/setup.bash

cd /home/minhqphan/projects/MACMOI/web/packages/api-server
pnpm start
```

The API server listens on:

```text
http://localhost:8000
```

## 3.2. Launch RMF With API Integration

Use the same main RMF launch, but pass the API server internal endpoint:

```bash
source /opt/ros/jazzy/setup.bash
source /home/minhqphan/projects/MACMOI/rmf_ws/.venv/bin/activate
source /home/minhqphan/projects/MACMOI/rmf_ws/install/setup.bash
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
export FREE_FLEET_BRINGUP_SHARE=$(ros2 pkg prefix free_fleet_bringup)/share/free_fleet_bringup

ros2 launch system_rmf_bringup system.launch.py \
  use_sim_time:=false \
  headless:=false \
  server_uri:=http://localhost:8000/_internal \
  config_file:=$FREE_FLEET_BRINGUP_SHARE/config/fleet/aiml_lab_multi_tb3_fleet.yaml
```

## 3.3. Start The Dashboard

On the central PC:

```bash
cd /home/minhqphan/projects/MACMOI/web/packages/rmf-dashboard-framework
pnpm start:example examples/demo
```

Dashboard URL:

```text
http://localhost:5173
```

# 4. Optional: Run RMF Components Separately

Use this when you want RMF core and the fleet adapter in separate terminals.
Robot bringup and Zenoh still follow sections 2.1 and 2.2.

## 4.1. RMF Core Only

On the central PC:

```bash
source /opt/ros/jazzy/setup.bash
source /home/minhqphan/projects/MACMOI/rmf_ws/.venv/bin/activate
source /home/minhqphan/projects/MACMOI/rmf_ws/install/setup.bash
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
export SYSTEM_RMF_SHARE=$(ros2 pkg prefix system_rmf_bringup)/share/system_rmf_bringup

ros2 launch system_rmf_bringup rmf_core.launch.xml \
  use_sim_time:=false \
  headless:=false \
  config_file:=$SYSTEM_RMF_SHARE/maps/aiml-lab.building.yaml \
  initial_map:=LG
```

For web UI integration, set:

```bash
server_uri:=http://localhost:8000/_internal
```

## 4.2. Free Fleet Adapter Only

On the central PC:

```bash
source /opt/ros/jazzy/setup.bash
source /home/minhqphan/projects/MACMOI/rmf_ws/.venv/bin/activate
source /home/minhqphan/projects/MACMOI/rmf_ws/install/setup.bash
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
export SYSTEM_RMF_SHARE=$(ros2 pkg prefix system_rmf_bringup)/share/system_rmf_bringup
export FREE_FLEET_BRINGUP_SHARE=$(ros2 pkg prefix free_fleet_bringup)/share/free_fleet_bringup

ros2 launch free_fleet_bringup aiml_lab_ff_bringup.launch.xml \
  use_sim_time:=false \
  config_file:=$FREE_FLEET_BRINGUP_SHARE/config/fleet/aiml_lab_multi_tb3_fleet.yaml \
  nav_graph_file:=$SYSTEM_RMF_SHARE/nav_graphs/1.yaml
```

For web UI integration, set:

```bash
server_uri:=http://localhost:8000/_internal
```

# 5. Optional Checks And Tests

These are not part of the main run path. Use them only when validating a change
or diagnosing a problem.

## 5.1. Check ROS Topics

```bash
ros2 topic list --no-daemon
ros2 topic echo /fleet_states rmf_fleet_msgs/msg/FleetState
ros2 topic echo /mission_state std_msgs/msg/String --qos-reliability reliable --qos-durability transient_local
```

## 5.2. Direct Zenoh/Nav2 Goal

Use this after robot Nav2 and Zenoh bridge are running:

```bash
source /opt/ros/jazzy/setup.bash
source /home/minhqphan/projects/MACMOI/rmf_ws/.venv/bin/activate
source /home/minhqphan/projects/MACMOI/rmf_ws/install/setup.bash

ros2 run free_fleet_examples nav2_send_navigate_to_pose.py \
  --frame-id map \
  --namespace tb3_1 \
  -x 2.1766 \
  -y 2.1308
```

Current estimated Nav2 map-frame coordinates:

```text
robot1_home -> [ 2.1766,  2.1308]
robot2_home -> [-2.7358,  2.2426]
wp1         -> [ 2.3845,  0.7899]
wp2         -> [-0.5594,  2.0784]
wp3         -> [-0.4699,  0.1098]
wp4         -> [-3.3064,  0.9062]
```

These are derived from the previous RMF-to-Nav2 transform. Replace them with
measured Nav2 coordinates if robot positions appear offset.

## 5.3. Dispatch Manual RMF Patrols

Run after both robots are visible in `/fleet_states`:

```bash
ros2 run rmf_demos_tasks dispatch_patrol \
  -F tb3_lab \
  -R tb3_1 \
  -p wp1 wp3 \
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

## 5.4. Mission Manager Tests

```bash
cd /home/minhqphan/projects/MACMOI
source /opt/ros/jazzy/setup.bash
source rmf_ws/.venv/bin/activate
source rmf_ws/install/setup.bash

PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest rmf_ws/src/mrd_mission_manager/test -q
```

## 5.5. Debug Fleet Adapter Segfaults

Run this while RMF core is already running:

```bash
source /opt/ros/jazzy/setup.bash
source /home/minhqphan/projects/MACMOI/rmf_ws/.venv/bin/activate
source /home/minhqphan/projects/MACMOI/rmf_ws/install/setup.bash
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
export SYSTEM_RMF_SHARE=$(ros2 pkg prefix system_rmf_bringup)/share/system_rmf_bringup

gdb --args /home/minhqphan/projects/MACMOI/rmf_ws/.venv/bin/python3 \
  /home/minhqphan/projects/MACMOI/rmf_ws/install/free_fleet_adapter/lib/free_fleet_adapter/fleet_adapter.py \
  -c /home/minhqphan/projects/MACMOI/rmf_ws/src/free_fleet_bringup/config/fleet/aiml_lab_multi_tb3_fleet.yaml \
  -n $SYSTEM_RMF_SHARE/nav_graphs/1.yaml
```

In `gdb`:

```gdb
run
bt
```

# 6. Asset Maintenance

## 6.1. Regenerate The RMF Nav Graph

Run this after editing the Traffic Editor building file:

```bash
source /opt/ros/jazzy/setup.bash
source /home/minhqphan/projects/MACMOI/rmf_ws/.venv/bin/activate
source /home/minhqphan/projects/MACMOI/rmf_ws/install/setup.bash

rm -f /home/minhqphan/projects/MACMOI/rmf_ws/src/system_rmf_bringup/nav_graphs/1.yaml

ros2 run rmf_building_map_tools building_map_generator nav \
  /home/minhqphan/projects/MACMOI/rmf_ws/src/system_rmf_bringup/maps/aiml-lab.building.yaml \
  /home/minhqphan/projects/MACMOI/rmf_ws/src/system_rmf_bringup/nav_graphs
```

Then rebuild the bringup packages:

```bash
cd /home/minhqphan/projects/MACMOI/rmf_ws
source /opt/ros/jazzy/setup.bash
source .venv/bin/activate

colcon build --packages-select system_rmf_bringup free_fleet_bringup --symlink-install
source install/setup.bash
```

## 6.2. Update Reference Coordinates

If Traffic Editor vertices move, update `reference_coordinates` in both fleet
configs:

```text
rmf_ws/src/free_fleet_bringup/config/fleet/aiml_lab_multi_tb3_fleet.yaml
rmf_ws/src/free_fleet_bringup/config/fleet/aiml_lab_single_tb3_fleet.yaml
```

The `rmf` points must come from the generated `nav_graphs/1.yaml`. The `robot`
points must be matching Nav2 `map` coordinates.

After editing, rebuild `free_fleet_bringup`:

```bash
cd /home/minhqphan/projects/MACMOI/rmf_ws
source /opt/ros/jazzy/setup.bash
source .venv/bin/activate

colcon build --packages-select free_fleet_bringup --symlink-install
source install/setup.bash
```
