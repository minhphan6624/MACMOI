# Free Fleet / RMF Troubleshooting Log

This document tracks issues found while integrating the physical TurtleBot3
robot with Open-RMF through `free_fleet`.

For setup context, see `docs/free_fleet_rmf_integration.md`.

## Current Unresolved Blocker

### `free_fleet_adapter` exits with code `-11`

Status: unresolved.

Symptom:

```text
[ERROR] [fleet_adapter.py-*]: process has died [..., exit code -11, cmd '.../fleet_adapter.py ...']
```

Observed in:

- the lab adapter launch using `tb3_lab_fleet.yaml` and the generated lab nav graph
- the stock `free_fleet` Nav2 TurtleBot3 example, once it can discover the RMF schedule node

Current conclusion:

This is probably not caused by the lab building map, physical robot, robot-side
Zenoh bridge, lab fleet config, or lab coordinate alignment. The stock
`free_fleet` example also crashes in a similar startup phase.

The suspected crash point is native RMF / adapter startup around fleet
registration. In the logs, the adapter computes the coordinate transform and
then dies before robot initialization logs appear.

Recommended next step:

```text
Run the stock example adapter or lab adapter under gdb.
After the crash, run `bt` and inspect / save the backtrace.
```

## Resolved / Investigated Issues

### Missing Python `catkin_pkg` while building `free_fleet`

Status: resolved.

Symptom:

```text
ModuleNotFoundError: No module named 'catkin_pkg'
```

Context:

`colcon build` was being run with the adapter workspace venv activated, so ROS
build scripts were executed with the venv's Python interpreter.

Fix:

Install ROS build-helper Python packages into the same venv, including
`catkin_pkg`.

Notes:

If building ROS packages inside an activated venv, the venv needs the Python
modules required by `ament` / ROS build tooling.

### Adapter could not initialize because RMF schedule node was missing

Status: resolved for the lab RMF common launch.

Symptom:

```text
AssertionError: Unable to initialize fleet adapter. Please ensure RMF Schedule Node is running
```

Cause:

`free_fleet_adapter` was launched before RMF common / core services were
running.

Fix:

Launch the RMF common services first, then launch the adapter in a second shell
with the same ROS environment and ROS domain.

Important check:

If this error appears again, verify that the RMF common terminal is still
running and that both terminals have the same `ROS_DOMAIN_ID`.

### RMF building map server could not find the lab building file

Status: resolved.

Symptom:

```text
building_map_server ... FileNotFoundError: [Errno 2] No such file or directory
```

Cause:

The launch command referenced an old building filename.

Current building file:

```text
/home/minhqphan/projects/MAMCUI/rmf_site_ws/maps/maps/aiml-lab.building.yaml
```

Result after fix:

`building_map_server` successfully opens the lab PNG and reports that it is
ready to serve the map.

### `reference_coordinates` used raw building / image coordinates

Status: resolved.

Symptom:

The adapter reported a high transform error estimate:

```text
Transformation error estimate for LG: 2.63...
```

Cause:

The fleet config's `reference_coordinates.rmf` used the raw coordinates from
the `.building.yaml` file. `free_fleet_adapter` needs the RMF-world coordinates
from the generated nav graph.

Fix:

Update `reference_coordinates.rmf` in the fleet config to use waypoint
coordinates from:

```text
/home/minhqphan/projects/MAMCUI/rmf_site_ws/maps/generated_nav_graphs/1.yaml
```

Result after fix:

The transform error estimate dropped to roughly `1e-09` in the lab adapter
launch.

### Temporary charger was referenced but not marked in the building map

Status: corrected; did not resolve the adapter segfault.

Symptom / concern:

The fleet config referenced:

```text
charger: "wp1"
```

but `wp1` was not marked as a charger in the building file.

Fix:

Mark `wp1` as a charger in the lab `.building.yaml`:

```yaml
{is_charger: [4, true]}
```

Then regenerate the nav graph.

Result:

This made the lab site semantics more consistent, but the adapter still exits
with code `-11`.

### RMF dispatcher reports no bids for dispatched tasks

Status: understood; not the current blocker.

Symptom:

```text
Task action for [...] did not receive any bids
Dispatcher Bidding Result: task [...] has no submissions during bidding
```

Meaning:

RMF task dispatcher is running, but no active fleet adapter submitted a bid for
the task.

Likely causes:

- adapter is not running
- adapter crashed
- adapter did not initialize a robot
- task is unsupported by the fleet
- robot is unavailable / not registered with the fleet

In the stock example attempt, tasks were dispatched while no healthy example
fleet adapter / robot was available to bid.

### RMF common terminal prints schedule update timeout messages

Status: observed; not proven fatal.

Symptom:

```text
Requesting new schedule update because update timed out
```

Current interpretation:

This can be noisy while visualizer / mirror nodes request schedule updates. It
was not the primary cause of the adapter crash. The building map server and RMF
common services should still be checked for crashes separately.

### `building_map_server` reports unable to generate GeoJSON

Status: observed; not treated as blocker for smoke testing.

Symptom:

```text
unable to generate GeoJSON for this map.
```

Current interpretation:

The map server can still open the lab PNG and serve the building map. This was
not treated as the adapter crash cause.

### RViz reports stereo is not supported

Status: harmless.

Symptom:

```text
[rviz2]: Stereo is NOT SUPPORTED
```

Current interpretation:

This is an RViz / graphics capability warning and is not related to the
`free_fleet_adapter` crash.

## Debugging Notes

Useful question for each failure:

```text
Does the stock free_fleet example fail the same way?
```

If yes, debug environment / runtime compatibility before editing the lab map.

If no, compare the lab fleet config, generated nav graph, charger waypoints,
level names, robot names, and reference coordinates against the stock example.

