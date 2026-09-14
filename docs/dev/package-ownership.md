# ROS 2 package naming and ownership decision

**Status:** Accepted — this is the target namespace for the next package-renaming migration.

This document fixes the final ROS 2 package names and the responsibility of every
package currently under `ros2_ws/src/`.  It is a design decision, not a partial
rename: source directories, manifests, imports, and launch references must be
changed together in the implementation change that adopts it.

## Rules

- Every first-party ROS 2 package uses the `dori_` prefix.  `dori_msgs` is
  reserved for ROS interface definitions.
- A ROS package name is unique in a workspace.  In particular, there must never
  be two packages named `dori_perception`, even if one is Python and the other
  is C++.
- A package boundary follows deployable/runtime ownership, not a desire to put
  every related file under one directory.  Build type and native dependency
  boundaries are valid reasons for separate ROS packages.
- The mappings below are one-way replacements.  We do **not** create compatibility
  aliases, deprecated launch files, or wrappers under any previous name.

## Final package map

| Current package | Final ROS package | Owner area | Decision and boundary |
| --- | --- | --- | --- |
| `dori_msgs` | `dori_msgs` | Shared ROS interfaces | Interface-only package.  It owns `Navigate.action` and future cross-domain messages, services, and actions; it owns no application node. |
| `bringup` | `dori_bringup` | System composition | Owns top-level and subsystem launch composition, common launch arguments, namespaces, and remappings.  It does not own functional nodes. |
| `navigation_pkg` | `dori_navigation` | Navigation | Owns navigation execution, planning/control integration, and navigation configuration. |
| `llm_pkg` | `dori_llm` | Language intelligence | Owns intent handling, retrieval/index access, model integration, and navigation-action client behavior. |
| `perception_pkg` | `dori_perception` | Perception (Python vision) | Owns Python person, landmark, gesture, facial-expression, and any Python camera nodes, plus their models/configuration. |
| `perception_camera_cpp` | `dori_perception_camera` | Perception (native camera adapter) | Auxiliary C++ camera-driver package owned by the perception area.  It isolates `ament_cmake`, RealSense/native SDK, and C++ ABI dependencies from Python vision dependencies. |
| `interaction_pkg` | `dori_hri` | HRI orchestration | The central HRI state-machine/coordinator package.  It owns interaction state, session transitions, and orchestration contracts. |
| `hri_pkg` | `dori_hri_expression` | HRI expression | Auxiliary HRI package for emotion/expression publishing and display-facing behavior. |
| `stt_pkg` | `dori_hri` | HRI speech input | Auxiliary HRI package for wake-word detection, audio intake, and speech-to-text models/runtime dependencies. |
| `tts_pkg` | `dori_hri` | HRI speech output | Auxiliary HRI package for speech synthesis, audio cues, playback, and audio assets. |
| `dashboard_pkg` | `dori_dashboard` | Dashboard | Owns the ROS/web bridge, dashboard API/server, packaged frontend assets, and dashboard launch entry point. |
| `system_monitor_pkg` | `dori_observability` | Operations and observability | Separate auxiliary package for host/robot metrics collection.  It is consumed by the dashboard but is not included in `dori_dashboard`, so monitoring remains usable without the web deployment and can be deployed independently. |

### Perception decision

We retain Python/C++ build boundaries rather than forcing a single hybrid ROS
package.  `dori_perception` is the canonical perception package and
`dori_perception_camera` is its explicitly named auxiliary package.  Dori bringup
selects the camera implementation by package/executable; it must not try to
install both implementations as packages with the same ROS package name.

### HRI decision

We retain deployable HRI subpackages rather than merging all four current
packages into one.  `dori_hri` is the coordinator and public HRI ownership
center.  `dori_hri_expression`, and `dori_hri` own their
specialized model, audio, and expression dependencies.  This allows the
coordinator to evolve independently of GPU/model and audio-runtime dependencies
while preserving an unambiguous ownership hierarchy.

## Rename scope contract

The migration changes identity at package and Python-module boundaries.  Runtime
node and graph names remain stable unless a later, separately approved ROS API
change says otherwise.

| Identifier kind | Target convention | What changes in this migration | What remains stable / is out of scope |
| --- | --- | --- | --- |
| ROS package name | Exact final name in the package map, lowercase snake case, `dori_` prefix. | Directory name, `package.xml` `<name>`, ament resource marker, CMake/setup package name, dependency declarations, `get_package_share_directory()` calls, and `ros2 launch`/`ros2 run` package argument. | No old package name remains discoverable in the workspace. |
| Python import package | Exact final Python package name for every `ament_python` package: `dori_navigation`, `dori_llm`, `dori_perception`, `dori_hri`, `dori_hri_expression`, `dori_dashboard`, or `dori_observability`. | On-disk import directory, `setup.py` entry-point target, and all first-party imports.  Generated action imports change to `dori_msgs.action`. | Third-party import names are not renamed.  No import shim for `*_pkg` is supplied. |
| Executable / console script | Functional, lowercase snake case name; existing unique names are retained (for example `navigator_node`, `llm_node`, `stt_node`, and `depth_camera_node`). | Entry-point module paths and launch `package=` fields change; the C++ target/install reference moves with `dori_perception_camera`. | Executable spelling does not gain a `dori_` prefix solely because its package did. |
| ROS node name | Functional, lowercase snake case; launch may continue to assign instance names such as `depth_camera_front`. | Launch `package=` changes and node implementation/import movement are updated. | `name=`, node constructor names, namespaces, and node graph identities stay unchanged. |
| Topic, service, and action graph names | Existing relative API names (for example `stt/result`, `tts/text`, and `nav/navigate_to`) with final routing owned by launch namespace/remapping. | Type references change from `dori_msgs/...` to `dori_msgs/...`; documentation and code imports follow that type package name. | Topic/service/action paths, parameter keys that carry them, and `/dori` namespace behavior do not change. |
| Launch file name | Existing launch filenames remain functional entry points under `dori_bringup`, `dori_navigation`, and `dori_dashboard`. | Every included launch and package lookup changes to the final package name. | No copied `bringup`/`*_pkg` launch package and no deprecated launch filename are retained. |

## Required migration acceptance checks

1. `colcon list` reports exactly the twelve final package names in the table and
   reports none of the current names.
2. `ros2 pkg executables` and every launch file resolve final package names and
   their retained executable names.
3. `dori_msgs` remains a member of `rosidl_interface_packages`; all action
   imports and action type references use `dori_msgs/action/Navigate`.
4. A workspace search finds no old package import, dependency, launch lookup,
   resource marker, alias package, deprecated launch, or wrapper retained for
   compatibility.
