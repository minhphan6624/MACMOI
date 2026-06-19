# Project Runbook

Runbook for the TurtleBot3 / Nav2 / Open-RMF / Free Fleet integration.

The main workflow is the two-robot RMF deployment. Optional sections cover the
web UI, running RMF components separately, and maintenance/debug tasks.

Run the command snippets from the workspace/project root unless a section says
otherwise.

## Helper Scripts

Common central-PC commands are wrapped in `scripts/` to avoid repeating the ROS
and workspace setup in every terminal. The wrappers resolve paths from the repo
root, so run them from the project root:

```bash
scripts/build-rmf.sh
scripts/launch-rmf.sh
scripts/launch-rmf-common.sh
scripts/launch-free-fleet.sh
scripts/mission-manager.sh
scripts/echo-mission-topic.sh
scripts/regenerate-nav-graph.sh
```

For an interactive RMF terminal, source the shared environment helper:

```bash
source scripts/env-rmf.sh
cd rmf_ws
```

The mission manager wrapper accepts optional positional arguments:

```bash
scripts/mission-manager.sh <mission_id> <total_packages> <auto_start>
```

Example:

```bash
scripts/mission-manager.sh m2 5 true
```

Launch wrappers pass through ROS launch arguments:

```bash
scripts/launch-rmf.sh server_uri:=http://localhost:8000/_internal
scripts/launch-rmf-common.sh server_uri:=http://localhost:8000/_internal
scripts/launch-free-fleet.sh server_uri:=http://localhost:8000/_internal
```

The manual commands below are kept as the source of truth for what each helper
does.

# 1. Initial Setup

## 1.1. Central PC Environment

Use this in every central-PC terminal that runs RMF, Free Fleet, mission
manager, or RMF task commands:

```bash
source /opt/ros/jazzy/setup.bash
source .venv/bin/activate
source install/setup.bash
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
```

If using a custom ROS domain, export the same value in every terminal:

```bash
export ROS_DOMAIN_ID=<domain_id>
```

## 1.2. Robot PC Environment

Use this on each TurtleBot3 PC / Raspberry Pi:

```bash
source robot_ws/install/setup.bash
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
```

## 1.3. Build Workspaces

Build `rmf_ws` on the central PC:

```bash
cd rmf_ws
source /opt/ros/jazzy/setup.bash
source .venv/bin/activate
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp

rosdep install --from-paths src --ignore-src --rosdistro jazzy -yr
colcon build --symlink-install --cmake-args -DCMAKE_BUILD_TYPE=Release
source install/setup.bash
```

Helper equivalent from the project root `scripts/build-rmf.sh`


Build `robot_ws` on each robot PC if it has not already been built:

```bash
cd robot_ws
source /opt/ros/jazzy/setup.bash
colcon build --symlink-install
source install/setup.bash
```

If only a few packages are needed to rebuilt, use `--packages-select <package name>` cli arg in the build command

Install web dependencies only if you plan to use the web UI:

```bash
cd web
pnpm install
```

## 1.4. Current Map Semantics

Active building file:

```text
rmf_ws/src/macmoi_assets/maps/aiml-lab.building.yaml
```

Active RMF nav graph:

```text
rmf_ws/src/macmoi_assets/nav_graphs/0.yaml
```

Current waypoint meaning:

```text
robot1_home = tb3_1 charger/home
robot2_home = tb3_2 charger/home
source = source
upstream_exit = tb3_1 directional wait/clear point near transfer
downstream_exit = tb3_2 directional wait/clear point near transfer
transfer = transfer
destination = destination
```

Current traffic graph:

```text
robot1_home <-> source
source <-> upstream_exit
upstream_exit <-> transfer      mutex: transfer_zone
transfer <-> downstream_exit    mutex: transfer_zone
downstream_exit <-> destination
destination <-> robot2_home
```

Only `robot1_home` and `robot2_home` should be marked as chargers.

# 2. Main Workflow: Two-Robot RMF Run

Use this flow for the normal lab run with both robots connected to RMF.

## 2.1. Start Robot Bringup

On robot 1:

```bash
source robot_ws/install/setup.bash
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp

ros2 launch robot_bringup robot.launch.py robot_id:=tb3_1
```

On robot 2:

```bash
source robot_ws/install/setup.bash
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

`robot.launch.py` starts one `handling_simulator_node` by default. The simulator
listens for `HANDLE_ITEM` commands for its `robot_id`, waits
`handling_duration_sec` seconds, and publishes a success result. It also calls
the TurtleBot3 `sound` service as a best-effort start/end cue; simulated
handling still succeeds if the sound service is unavailable.

Disable the simulator only when replacing simulated handling with another
confirmation source:

```bash
ros2 launch robot_bringup robot.launch.py \
  robot_id:=tb3_1 \
  enable_handling_simulator:=false
```

To change the simulated load/unload duration:

```bash
ros2 launch robot_bringup robot.launch.py \
  robot_id:=tb3_1 \
  handling_duration_sec:=3.0
```

## 2.2. Start Zenoh

On the central PC:

```bash
zenohd
```

On the central PC, also start the Zenoh bridge that matches the central-side
deployment:

```bash
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
~/zenoh/bin/zenoh-bridge-ros2dds -c <central_bridge_config.json5>
```

On robot 1:

```bash
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
~/zenoh/bin/zenoh-bridge-ros2dds -c ~/zenoh/config/tb3_robot1_zenoh.json5
```

On robot 2:

```bash
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
~/zenoh/bin/zenoh-bridge-ros2dds -c ~/zenoh/config/tb3_robot2_zenoh.json5
```

The bridge namespaces must match the fleet robot names: `tb3_1` and `tb3_2`.
Versioned templates are installed by `robot_bringup` from
`config/zenoh/`; copy the matching file to `~/zenoh/config/` on each robot
before starting the bridge.

## 2.3. Launch RMF And Free Fleet

On the central PC:

```bash
source /opt/ros/jazzy/setup.bash
source .venv/bin/activate
source install/setup.bash
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp

ros2 launch rmf_bringup system.launch.py
```

Helper equivalent from the project root: `scripts/launch-rmf.sh`

Healthy startup should add both robots to fleet `tb3_lab` at their respective chargers

## 2.4. Run The Mission Manager

Start this only after both robots are visible in fleet state. The node is now a
ROS shell around the refactored task-flow mission runtime:

```text
MissionManagerNode
  -> MissionManager
  -> TransportTaskScheduler
  -> TransportTaskRunner
  -> ExecutionManager
  -> RmfAdapter / robot handling simulator
```

The node publishes RMF movement requests for `MOVE_ROBOT` commands and publishes
`HANDLE_ITEM` load/unload commands on `mission_execution_commands`. Robot-side
`handling_simulator_node` instances simulate handling and report completion on
`mission_execution_results`. Movement requests are sent to RMF as composed
`go_to_place` robot tasks.

Movement command completion is driven by `mission_execution_results`, not RMF
`task_summaries`. The Free Fleet Nav2 adapter verifies the final robot pose is
within `verified_arrival_tolerance_m` before publishing a successful movement
result and before calling RMF `execution.finished()`. RMF task summaries remain
useful lifecycle/debug events, but they do not advance the mission behavior tree
or start item handling.

Handling command payloads include `mission_id`, `command_id`, `task_id`,
`robot_id`, `item_id`, and `handling_type`. The mission manager updates item
state only after it receives the matching execution result.

```bash
source /opt/ros/jazzy/setup.bash
source .venv/bin/activate
source install/setup.bash
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp

ros2 run mission_manager mission_manager_node \
  --ros-args \
  -p mission_id:=m1 \
  -p total_packages:=3 \
  -p auto_start:=true
```

Helper equivalent from the project root:

```bash
scripts/mission-manager.sh m1 3 true
```

For more packages:

```bash
-p total_packages:=3
```

Use a fresh `mission_id` for each new run if old task state is still visible in
the dashboard or RMF logs.

To start manually instead of using `auto_start`, run the node with
`auto_start:=false` and publish a mission command:

```bash
ros2 topic pub --once /mission_commands std_msgs/msg/String \
  "{data: '{\"command\":\"start\",\"mission_id\":\"m1\"}'}"
```

Current mission model:

```text
transportItem(P1, source, transfer, tb3_1)
transportItem(P1, transfer, destination, tb3_2)
```

Expected command flow for one package:

```text
tb3_1 move robot1_home -> source through RMF
tb3_1 load P1 at source
tb3_1 move source -> upstream_exit -> transfer through RMF
tb3_1 unload P1 into the transfer buffer
tb3_1 move transfer -> upstream_exit and release transfer
tb3_2 move robot2_home -> destination -> downstream_exit -> transfer through RMF
tb3_2 load P1 from the transfer buffer
tb3_2 move transfer -> downstream_exit and release transfer
tb3_2 move downstream_exit -> destination through RMF
tb3_2 unload P1 at destination
mission status -> completed
```

If the transfer resource is occupied when a task needs it, the task runner sends
the robot to its directional wait point, marks the task blocked, and retries the
transfer resource when mission state changes.

Monitor the runtime state:

```bash
ros2 topic echo --full-length /mission_state std_msgs/msg/String \
  --qos-reliability reliable \
  --qos-durability transient_local \
  --field data
```

Helper equivalent from the project root:

```bash
scripts/echo-mission-topic.sh /mission_state
```

The `mission_state` JSON is the compact dashboard/operator snapshot. Use the
verbose debug topic for raw mission internals:

```bash
ros2 topic echo --full-length /mission_debug_state std_msgs/msg/String \
  --qos-reliability reliable \
  --qos-durability transient_local \
  --field data
```

Helper equivalent from the project root:

```bash
scripts/echo-mission-topic.sh /mission_debug_state
```

Mission events are also published one at a time:

```bash
ros2 topic echo --full-length /mission_events std_msgs/msg/String \
  --qos-reliability reliable \
  --qos-durability transient_local \
  --field data
```

Helper equivalent from the project root:

```bash
scripts/echo-mission-topic.sh /mission_events
```

These mission topics are `std_msgs/msg/String` values containing JSON, so
`ros2 topic echo` does not print them as typed ROS fields. For readable
inspection, pipe the `data` field through a JSON formatter:

```bash
ros2 topic echo --full-length /mission_debug_state std_msgs/msg/String \
  --qos-reliability reliable \
  --qos-durability transient_local \
  --field data | python3 -m json.tool
```

To verify the web bridge without live robots, run the API server and dashboard,
then publish a small mission state manually:

```bash
cd web
pnpm --filter api-server start
```

```bash
cd web/packages/rmf-dashboard-framework
pnpm exec vite --host 127.0.0.1 --port 5173 examples/demo -c examples/shared/vite.config.ts
```

Open the Mission tab at `http://127.0.0.1:5173/mission`. Without mission ROS
topics, it shows fallback scenario data. Publish a sample state to verify the
live overlay path:

```bash
ros2 topic pub --once /mission_state std_msgs/msg/String "{data: '{\"schema_version\":1,\"mission\":{\"id\":\"dry_run\",\"name\":\"Dry Run Mission\",\"status\":\"active\",\"phase\":\"moving_to_pickup\",\"current_step\":1,\"total_steps\":4,\"active_robot\":\"tb3_1\",\"current_blocker\":null,\"next_step\":\"load\",\"last_update\":1710000000},\"packages\":{},\"robots\":[],\"tasks\":[],\"zones\":[],\"operator\":{\"active_command_count\":0,\"blocked_task_count\":0},\"last_event\":null,\"last_update_time\":1710000000}'}"
```

Current Mission tab UI direction:

```text
Mission tab:
  mission overview
  mission-relevant robot cards
  Mission Flow panel for Source -> Transfer -> Destination semantics
  grouped Mission Steps
  selected Detail Panel
  Activity panel with Events and Alerts tabs

Map tab:
  real Open-RMF map, robot pose, lanes, doors/lifts, and spatial inspection
```

The Mission Flow panel is not a real map. It is a mission coordination view. Use
the `Open RMF Map` action when the operator needs physical robot/map context.

If the local Vite dev server fails with a file watcher error such as:

```text
ENOSPC: System limit for number of file watchers reached
```

build and preview the demo instead:

```bash
cd web/packages/rmf-dashboard-framework
pnpm exec vite build examples/demo -c examples/shared/vite.config.ts
pnpm exec vite preview --host 127.0.0.1 --port 5173 --outDir examples/demo/dist
```

Useful execution-completion logs:

```text
Published mission execution result: ... "arrival_verified": true ...
Mission command completed from nav2_result: cmd_X
```

# 3. Optional: Web UI Run

Use this when running the RMF dashboard against the lab deployment.

## 3.1. Start The API Server

On the central PC:

```bash
source /opt/ros/jazzy/setup.bash
source install/setup.bash

cd web/packages/api-server
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
source .venv/bin/activate
source install/setup.bash
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp

ros2 launch rmf_bringup system.launch.py \
  server_uri:=http://localhost:8000/_internal
```

## 3.3. Start The Dashboard

On the central PC:

```bash
cd web/packages/rmf-dashboard-framework
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
source .venv/bin/activate
source install/setup.bash
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp

ros2 launch rmf_bringup rmf_core.launch.xml \
  config_file:=src/macmoi_assets/maps/aiml-lab.building.yaml \
  initial_map:=LG
```

Helper equivalent from the project root:

```bash
scripts/launch-rmf-common.sh
```

For web UI integration, set:

```bash
server_uri:=http://localhost:8000/_internal
```

With the helper:

```bash
scripts/launch-rmf-common.sh server_uri:=http://localhost:8000/_internal
```

## 4.2. Free Fleet Adapter Only

On the central PC:

```bash
source /opt/ros/jazzy/setup.bash
source .venv/bin/activate
source install/setup.bash
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp

ros2 launch macmoi_free_fleet_bringup aiml_lab_ff_bringup.launch.xml
```

Helper equivalent from the project root:

```bash
scripts/launch-free-fleet.sh
```

For web UI integration, set:

```bash
server_uri:=http://localhost:8000/_internal
```

With the helper:

```bash
scripts/launch-free-fleet.sh server_uri:=http://localhost:8000/_internal
```

# 5. Optional Checks And Tests

These are not part of the main run path. Use them only when validating a change
or diagnosing a problem.

## 5.1. Check ROS Topics

```bash
ros2 topic list --no-daemon
ros2 topic echo /fleet_states rmf_fleet_msgs/msg/FleetState
ros2 topic echo --full-length /mission_state std_msgs/msg/String --qos-reliability reliable --qos-durability transient_local --field data
ros2 topic echo --full-length /mission_debug_state std_msgs/msg/String --qos-reliability reliable --qos-durability transient_local --field data
ros2 topic echo --full-length /mission_events std_msgs/msg/String --qos-reliability reliable --qos-durability transient_local --field data
ros2 topic echo /mission_execution_commands std_msgs/msg/String
ros2 topic echo /mission_execution_results std_msgs/msg/String
ros2 service list | grep sound
```

## 5.2. Direct Zenoh/Nav2 Goal

Use this after robot Nav2 and Zenoh bridge are running:

```bash
ros2 action send_goal /tb3_1/navigate_to_pose nav2_msgs/action/NavigateToPose \
  "{pose: {header: {frame_id: map}, pose: {position: {x: 2.1766, y: 2.1308, z: 0.0}, orientation: {w: 1.0}}}}"
```

Current estimated Nav2 map-frame coordinates:

```text
robot1_home -> [ 2.1766,  2.1308]
robot2_home -> [-2.7358,  2.2426]
source      -> [ 2.3845,  0.7899]
upstream_exit   -> [approx. source-side transfer wait point]
downstream_exit -> [approx. destination-side transfer wait point]
transfer    -> [-0.4699,  0.1098]
destination -> [-3.3064,  0.9062]
```

These are derived from the previous RMF-to-Nav2 transform. Replace them with
measured Nav2 coordinates if robot positions appear offset.

## 5.3. Dispatch Manual RMF Go-To-Place Tasks

Run after both robots are visible in `/fleet_states`:

```bash
ros2 run rmf_demos_tasks dispatch_go_to_place \
  -F tb3_lab \
  -R tb3_1 \
  -p source \
  -st 0
```

```bash
ros2 run rmf_demos_tasks dispatch_go_to_place \
  -F tb3_lab \
  -R tb3_2 \
  -p downstream_exit \
  -st 0
```

Use patrol tasks only when you intentionally want loop/patrol semantics. The
mission layer uses composed `go_to_place` requests for one-shot movement
commands.

# 6. Asset Maintenance

## 6.1. Regenerate The RMF Nav Graph

Run this after editing the Traffic Editor building file:

```bash
source /opt/ros/jazzy/setup.bash
source .venv/bin/activate
source install/setup.bash

rm -f src/macmoi_assets/nav_graphs/*.yaml

ros2 run rmf_building_map_tools building_map_generator nav \
  src/macmoi_assets/maps/aiml-lab.building.yaml \
  src/macmoi_assets/nav_graphs
```

Then rebuild and re-source the bringup packages (macmoi_assets and macmoi_free_fleet_bringup). See section [1.3](#13-build-workspaces) for commands

Helper equivalent from the project root:`scripts/regenerate-nav-graph.sh`

## 6.2. Update Reference Coordinates

If Traffic Editor vertices move, update `reference_coordinates` in both fleet
configs:

```text
rmf_ws/src/macmoi_free_fleet_bringup/config/fleet/aiml_lab_multi_tb3_fleet.yaml
rmf_ws/src/macmoi_free_fleet_bringup/config/fleet/aiml_lab_single_tb3_fleet.yaml
```

The `rmf` points must come from the generated `nav_graphs/0.yaml`. The `robot`
points must be matching Nav2 `map` coordinates.

After editing, rebuild `macmoi_free_fleet_bringup`:


# Start simulated handling node
```bash
source /opt/ros/jazzy/setup.bash
source robot_ws/install/setup.bash

ros2 run robot_bringup handling_simulator_node --ros-args \
  -p robot_id:=tb3_1 \
  -p mission_id:=m1 \
  -p handling_duration_sec:=5.0
```
