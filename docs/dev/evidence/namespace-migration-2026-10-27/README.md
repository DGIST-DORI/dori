# DORI namespace migration verification — 2026-10-27

**AMM revision:** R3. **Baseline:** `5291d2fbf0c32541eebad8938469fafb14324aec`.
See the [package ownership map](../../package-ownership.md) and
[AMM 20-15 upgrade task](../../../user/DORI-AMM.md).

## Result and scope

All nine project-owned `robot_*` packages were renamed or merged into `dori_*`.
The clean workspace contains **24 unique, acyclic ROS packages**; its installed
package index matches its source manifests. Four overlapping package pairs were
consolidated instead of keeping aliases. [Package inventory](packages.json).

- Physical bringup belongs to `dori_hardware`; `dori_bringup` composes the full
  system without a dependency cycle.
- `dori_mapping` contains the real LiDAR launch instead of a self-including
  wrapper after renaming.
- `dori_navigation` installs the C++ planner, two Python modules, public action
  executables and map web assets using `ament_cmake_python`.
- `dori_msgs` generates all five control messages and four existing actions.
  Native serialization/deserialization passes, and the software drive plant
  receives the newly typed C++ motor commands through real DDS transport.
- Helpers, local symbols, imports, C++ namespaces/includes, manifest references,
  launch lookups, plugin IDs, scripts and active documentation were updated.
- Standard ROS/Nav2 names (`robot_state_publisher`, `robot_description`,
  `robot_base_frame`, `robot_radius`, `robot_model_type`) remain intact.
  Old-name detection in migration checks and historical records is intentional.

The 94 moved implementation, configuration and interface files are equal to the
baseline after naming substitution alone, excluding intentionally merged
CMake/package manifests. [Preservation proof](preservation.json). Numerical drive
calibration, motor scaling, watchdog thresholds and operational topic paths did
not change. Old and new custom message **type names** are different: stop/rebuild/
restart all affected participants instead of mixing their overlays.

## Executed validation

| Check | Evidence |
|---|---|
| Clean ROS build, 24 packages | [build.txt](build.txt) |
| 123 Python/ROS/BT tests and CTest 3/3 | [tests.txt](tests.txt) |
| ESLint, Vite production build, Node 2/2 | [web-build.txt](web-build.txt) |
| Installed executables, Python ABI, voice assets and dashboard | [deployment-check.json](deployment-check.json) |
| Physical launch argument resolution without starting actuators | [launch-args.txt](launch-args.txt) |
| Actual renamed TTA bridge/supervisor/C++ drive and injected faults | [drive-chain.json](drive-chain.json) |
| Web goal → actual Nav2 → software plant | [web-goal.json](web-goal.json) |
| Relative 1 m goal | [relative-1m.json](relative-1m.json) |
| HRI → actual Nav2 with calibrated ground response | [hri-nav2.json](hri-nav2.json) |
| Retry, reverse, rear obstacle, heading and motor dynamics | [retry.json](retry.json), [reverse-recovery.json](reverse-recovery.json), [blocked-rear.json](blocked-rear.json), [heading-test.json](heading-test.json), [motor-dynamics.json](motor-dynamics.json) |
| AMCL correction without movement | [auto-alignment-test.json](auto-alignment-test.json) |
| Actual LiDAR odometry/Cartographer/map saving with synthetic scans | [mapping.json](mapping.json) |
| Actual Firefox + HTTP + rosbridge, map, TTS, reconnect and publisher UI | [dashboard-browser.json](dashboard-browser.json), [dashboard.png](dashboard.png) |
| User web retry/voice completion behavior | [browser-retry.json](browser-retry.json) |

A prior regression test inspected the removed Python setup.py. It now checks the
installed navigation executables, keeping the original assertion that no legacy
navigator is installed. A duplicate key created when two executable-check entries
merged into one package was changed to a list so all three navigation executables
remain checked. The consecutive-run fixture also now waits for both live scan and odometry samples before requesting an initial pose; the real server still rejects missing/stale sensors. These corrections do not relax the runtime acceptance conditions.

The clean build reported existing vendor compiler warnings and unused Python
CMake-variable warnings; it had no build errors. `git diff --check`, Python
syntax, package dependency checks and installed message serialization passed.
The [source SHA-256 manifest](source-sha256.txt) identifies the tested source.

## Reproduction and limitations

```bash
# Stop the affected stack and use a fresh shell.
scripts/build.sh --clean
source scripts/env.sh
scripts/validate_release.sh
# After preparing Firefox as described in AMM 72-10:
ROS_DOMAIN_ID=97 ROS_LOCALHOST_ONLY=1 python3 tests/integration/browser_dashboard.py
```

The old build/install/log directories were archived under `.state/build-backups`.
The new test runtime sources only the clean overlay. rosbridge/rosapi and PortAudio
on this development host use official apt files extracted into a temporary path,
as in the earlier reports; deploy with the normal dependency installer on the
robot. The unrelated running workspace in ROS domain 86 was not modified or
stopped. Test traffic was restricted to localhost domains 94–97 and 99.

These results cover real ROS software with synthetic sensors/actuators. Physical
CAN, motors, ground friction, real microphone/audio and camera performance were
not retested. AMM 72-20 remains the on-robot acceptance procedure. Prior evidence
retains the package names it tested and is not rewritten as new evidence.
