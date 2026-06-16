# MACMOI Helper Scripts

Thin wrappers for repeated commands from `docs/project_runbook.md`.

Run these from the project root:

```bash
scripts/build-rmf.sh
scripts/launch-rmf.sh
scripts/launch-rmf-common.sh
scripts/launch-free-fleet.sh
scripts/mission-manager.sh
scripts/echo-mission-topic.sh
scripts/regenerate-nav-graph.sh
```

Set up an interactive RMF terminal:

```bash
source scripts/env-rmf.sh
cd rmf_ws
```

Run the mission manager with custom values:

```bash
scripts/mission-manager.sh m2 5 true
```

The mission manager arguments are:

```text
scripts/mission-manager.sh <mission_id> <total_packages> <auto_start>
```

Echo another mission topic:

```bash
scripts/echo-mission-topic.sh /mission_debug_state
scripts/echo-mission-topic.sh /mission_events
```

Pass launch arguments through to RMF:

```bash
scripts/launch-rmf.sh server_uri:=http://localhost:8000/_internal
scripts/launch-rmf-common.sh server_uri:=http://localhost:8000/_internal
scripts/launch-free-fleet.sh server_uri:=http://localhost:8000/_internal
```

Override the RMF common map defaults when needed:

```bash
scripts/launch-rmf-common.sh config_file:=src/macmoi_assets/maps/aiml-lab.building.yaml initial_map:=LG
```
