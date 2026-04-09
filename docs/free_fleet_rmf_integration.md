# Open-RMF / Free Fleet Integration Notes

This document records the current integration approach for connecting the
physical TurtleBot3 robots to Open-RMF using `free_fleet`.

## Tooling and Runtime Roles

### Open-RMF

Open-RMF is the central coordination system. For this project it is expected to
run on a central lab PC and provide the traffic schedule, task dispatcher,
building map server, supervisors, and visualization.

For early testing, start the generic/common RMF services instead of a demo map
such as `office.launch.xml`. The common launch can be pointed at this project's
lab building file.

### Free Fleet

`free_fleet` is the RMF fleet adapter used for this integration. It connects an
RMF fleet to robots that already have a ROS navigation stack.

For the first integration pass, the target stack is Nav2 on a physical
TurtleBot3.

### Zenoh Router: `zenohd`

`zenohd` is the Zenoh router. It runs on the central PC and acts as the hub that
the robot-side bridge and the adapter-side Zenoh client communicate through.

### Zenoh ROS 2 Bridge: `zenoh-bridge-ros2dds`

`zenoh-bridge-ros2dds` runs on the robot PC / Raspberry Pi. It bridges selected
ROS 2 interfaces between the robot's local DDS graph and the central Zenoh
network.

For `free_fleet`, the robot's local Nav2 stack should remain non-namespaced,
while the bridge exposes it with the robot name as its namespace.

### Python Zenoh Package: `eclipse-zenoh`

`eclipse-zenoh` is a Python dependency used on the adapter side. It belongs in
the adapter workspace virtual environment. It does not replace `zenohd` or
`zenoh-bridge-ros2dds`.

### Python Virtual Environment

The central adapter side uses a Python venv at:

```bash
/home/minhqphan/projects/MAMCUI/adapter_ws/.venv
```

Use the venv for `free_fleet` Python dependencies instead of installing them
system-wide with `--break-system-packages`.

The venv must also contain Python packages needed by ROS build tooling when
building inside the activated venv, e.g. `catkin_pkg`.

## Repository Layout Decision

Use the repository workspaces as separate layers:

```text
robot_ws/
  Robot-local bringup, TurtleBot3 hardware config, Nav2 config, Nav2 map.

rmf_site_ws/
  RMF building map source, RMF drawing, generated RMF navigation graph.

adapter_ws/
  Built free_fleet workspace, adapter-side fleet config, future launch/deployment glue.
```
Do not move the runtime robot-side Zenoh bridge config off the Pi. It can stay in `~/zenoh/config` on the robot. Optionally copy a template into this repo later for version control.

## Current Site / Map State

Lab building file:

```text
/home/minhqphan/projects/MAMCUI/rmf_site_ws/maps/maps/aiml-lab.building.yaml
```

Lab drawing:

```text
/home/minhqphan/projects/MAMCUI/rmf_site_ws/maps/maps/aiml-lab.png
```

Generated RMF nav graph:

```text
/home/minhqphan/projects/MAMCUI/rmf_site_ws/maps/generated_nav_graphs/1.yaml
```

The current RMF graph is intentionally minimal for smoke testing:

```text
wp1 <-> wp2 <-> wp3 <-> wp4 <-> wp1
```

The level name is `LG`.

`wp1` is currently marked as a charger waypoint so it can match the temporary
robot `charger` field in the fleet config.

## Current Fleet Config

Fleet config:

```text
/home/minhqphan/projects/MAMCUI/adapter_ws/config/free_fleet/tb3_lab_fleet.yaml
```

Current fleet:

```text
tb3_lab
```

Current configured robot:

```text
tb3_2
```

The robot name in the fleet config must match the namespace exposed by the
robot's `zenoh-bridge-ros2dds` config.

The config currently treats `wp1` as a temporary charger/home waypoint. This is
good enough for smoke testing, but it is not a full docking or charging workflow.

Delivery tasks are disabled. Loop / patrol-style motion is the first target.

## Coordinate Alignment Decision

The RMF PNG drawing was converted directly from the Nav2 PGM map. This means
the raster image can be used to derive a first-pass coordinate relationship.

Important correction:

`reference_coordinates.rmf` in the fleet config must use coordinates from the
generated RMF nav graph, not the raw pixel coordinates from the
`.building.yaml` file.

After this correction, the adapter reported a transform error near `1e-09`,
which indicates that the current RMF-to-robot reference pairs are internally
consistent.

## Commands Used

### Generate RMF Navigation Graph

```bash
source /opt/ros/jazzy/setup.bash
ros2 run rmf_building_map_tools building_map_generator nav \
  /home/minhqphan/projects/MAMCUI/rmf_site_ws/maps/maps/aiml-lab.building.yaml \
  /home/minhqphan/projects/MAMCUI/rmf_site_ws/maps/generated_nav_graphs
```

### Launch RMF Common Services for the Lab

Run on the central PC:

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

### Launch the Lab Free Fleet Adapter

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

## Completed Tasks

- Verified that `robot_ws` is the robot-side TurtleBot3 / Nav2 workspace.
- Installed Zenoh router on the central PC.
- Installed Zenoh ROS 2 bridge on the robot.
- Verified that the router and bridge can find each other.
- Created the robot-side Zenoh bridge config under `~/zenoh/config` on the Pi.
- Built `free_fleet` in `adapter_ws`.
- Created the adapter-side fleet config for the lab TurtleBot3 fleet.
- Generated an RMF nav graph from the lab `.building.yaml`.
- Corrected `reference_coordinates` to use generated RMF nav graph coordinates.
- Marked `wp1` as a charger waypoint for the current temporary charger config.
- Launched RMF common services with the lab building file.

## Current Blocker

`free_fleet_adapter` currently crashes with exit code `-11`.

This has been observed with both the custom lab adapter launch and the stock
`free_fleet` Nav2 TurtleBot3 example after RMF schedule is reachable.

Because the stock example also crashes, the current blocker is probably not the
lab map, physical robot, robot-side Zenoh bridge, or lab fleet config.

The suspected failure area is the native RMF / `free_fleet` adapter startup,
around the point after the transform is computed and before robot initialization
logs appear.

Recommended next debug step:

```text
Run the adapter under gdb, reproduce the crash, then capture the `bt` backtrace.
```

