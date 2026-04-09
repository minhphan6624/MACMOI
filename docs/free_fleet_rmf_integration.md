# Open-RMF / Free Fleet Integration Notes

This document records the current integration approach for connecting the
physical TurtleBot3 robots to Open-RMF using `free_fleet`.

# 1. Tooling and Runtime Roles

## Open-RMF

Open-RMF is the central coordination system. For this project it is expected to
run on a central lab PC and provide the traffic schedule, task dispatcher,
building map server, supervisors, and visualization.

For early testing, start the generic/common RMF services instead of a demo map
such as `office.launch.xml`. The common launch can be pointed at this project's
lab building file.

## Free Fleet

`free_fleet` is the RMF fleet adapter used for this integration. It connects an
RMF fleet to robots that already have a ROS navigation stack.

For the first integration pass, the target stack is Nav2 on a physical
TurtleBot3.

## Zenoh Router: `zenohd`

`zenohd` is the Zenoh router. It runs on the central PC and acts as the hub that
the robot-side bridge and the adapter-side Zenoh client communicate through.

## Zenoh ROS 2 Bridge: `zenoh-bridge-ros2dds`

`zenoh-bridge-ros2dds` runs on the robot PC / Raspberry Pi. It bridges selected
ROS 2 interfaces between the robot's local DDS graph and the central Zenoh
network.

For `free_fleet`, the robot's local Nav2 stack should remain non-namespaced,
while the bridge exposes it with the robot name as its namespace.

## Python Zenoh Package: `eclipse-zenoh`

`eclipse-zenoh` is a Python dependency used on the adapter side. It belongs in
the adapter workspace virtual environment. It does not replace `zenohd` or
`zenoh-bridge-ros2dds`.

## Python Virtual Environment

The central adapter side uses a Python venv at:

```bash
/home/minhqphan/projects/MAMCUI/adapter_ws/.venv
```

When starting fresh, create and activate a virtual environment, then install the dependencies via `pip install -r requirements.txt`.
Use the venv for `free_fleet` Python dependencies instead of installing them system-wide with `--break-system-packages`.

The venv must also contain Python packages needed by ROS build tooling when building inside the activated venv, e.g. `catkin_pkg`.

# 2. Repository Layout Decision

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

# 3.  Current Site / Map State

Lab building file:` /rmf_site_ws/maps/maps/aiml-lab.building.yaml`

Lab drawing:` /rmf_site_ws/maps/maps/aiml-lab.png`

Generated RMF nav graph: `/rmf_site_ws/maps/generated_nav_graphs/1.yaml`

The current RMF graph is intentionally minimal for smoke testing, which includes 4 points  `wp1 <-> wp2 <-> wp3 <-> wp4 <-> wp1 `

The level name is `LG`. `wp1` is currently marked as a charger waypoint so it can match the temporary robot charger field in the fleet config.

# 4. Current Fleet Config

Fleet config: `adapter_ws/config/free_fleet/tb3_lab_fleet.yaml`

Current fleet is called `tb3_lab`

Current configured robot: `tb3_2`.

The robot name in the fleet config must match the namespace exposed by the robot's `zenoh-bridge-ros2dds` config.

The config currently treats `wp1` as a temporary charger/home waypoint. This is good enough for smoke testing, but it is not a full docking or charging workflow.

Delivery tasks are disabled. Loop / patrol-style motion is the first target.

# 5. Coordinate Alignment Decision

The RMF PNG drawing was converted directly from the Nav2 PGM map. This means the raster image can be used to derive a first-pass coordinate relationship.

Important correction: `reference_coordinates.rmf` in the fleet config must use coordinates from the generated RMF nav graph, not the raw pixel coordinates from the `.building.yaml` file. After this correction, the adapter reported a transform error near `1e-09`, which indicates that the current RMF-to-robot reference pairs are internally consistent.

# 6. Completed Tasks

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
- Resolved the adapter startup segfault by using a compatible `numpy` version.
- Added a local `free_fleet_adapter` compatibility patch that treats
  TurtleBot3 battery percentages in the `1..100` range as percent values before
  passing state-of-charge to RMF.
- Reached the adapter registration milestone: the adapter can add the robot to
  fleet `tb3_lab` and set the `wp1` charger waypoint.

# 7. Current Smoke-Test Definition

Treat the integration as an end-to-end smoke-test pass when all of these are
true in the same run:

- Nav2 accepts and executes a direct `navigate_to_pose` goal.
- `zenohd` and the robot-side `zenoh-bridge-ros2dds` are running.
- RMF common services are running with the lab building file.
- The lab `free_fleet_adapter` stays up and prints that the robot was added to
  fleet `tb3_lab`.
- `/fleet_states` contains fleet `tb3_lab` and the configured robot name.
- A small RMF patrol task is awarded to fleet `tb3_lab`.
- The adapter prints that a navigation goal was accepted.
- The physical robot moves to the requested lab waypoints and the task finishes.

This smoke test means Nav2, Zenoh, `free_fleet`, and the RMF dispatcher are
connected. It does not finish production tuning of AMCL startup, coordinate
alignment, lane placement, recovery behavior, charging/docking, or battery
modeling.

# 8. Lab Waypoint Correspondence

The generated RMF nav graph uses waypoints `wp1`, `wp2`, `wp3`, and `wp4`.
The current fleet config maps those RMF waypoints to approximately these Nav2
map-frame coordinates:

```text
wp1 -> [ 0.5564,  2.0371]
wp2 -> [-2.1961,  2.1682]
wp3 -> [-2.3108,  0.2512]
wp4 -> [ 0.6056, -0.0110]
```

Use these coordinates when comparing a direct Nav2 goal against an RMF patrol
task. The robot does not need to start physically at `wp1`; AMCL should be given
the robot's actual pose on the Nav2 map.
