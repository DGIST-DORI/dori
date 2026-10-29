# Package refactor P0/P2 validation — 2026-10-28

## Scope

Baseline: `d35f313` following the `3a081be` package consolidation. This follow-up
repairs compilation, package installation and launch references, and replaces
deleted root-script instructions with ROS commands. It preserves the deletion
of root scripts/preflight. See [ownership](package-ownership.md) and
[AMM R4](../user/DORI-AMM.md).

The local working overlay was rebuilt from empty build/install/log directories;
the previous artifacts are archived under `.state/build-backups`. No physical
drivers, ROS nodes or simulation campaigns were started for this validation.
Comparison with the baseline confirms that 67 first-party implementation,
configuration and interface files are unchanged apart from the package-name
substitutions. The local hash report is `log/refactor-p0p2/preservation.json`.
The launch inspection evaluates substitutions, parameter files and xacro URDF,
but rejects execution of Node/ExecuteProcess actions.

## Acceptance and reproduction

Use AMM 20-10/20-12 to install dependencies, build the dashboard before ROS, and
source the clean Humble/Python 3.10 environment. Run from the repository root:

```bash
mkdir -p log/refactor-p0p2
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/contracts -q \
  --junitxml=log/refactor-p0p2/packages.xml
ctest --test-dir ros2_ws/build/dori_control --output-on-failure
ctest --test-dir ros2_ws/build/cubemars_hardware --output-on-failure
(cd web && npm ci && npm run lint && npm test && npm run build)
```

| Check | Local result / acceptance |
|---|---|
| Clean build with `BUILD_TESTING=ON` | 21 packages built |
| Dedicated pytest checks | 19 passed; includes installed contracts and active documentation |
| Source/install inventory and dependency graph | Exact expected package set; no removed identities, self-dependencies or cycles |
| Installed executables | Control 10, hardware 6, diagnostics 1 and navigation 3 |
| IMU Python integration | All four installed wrappers import their installed modules without opening serial devices or initializing ROS |
| Custom interfaces | Native serialization of five messages and four action goals |
| Launch resolution | Hardware, wheel odometry, LiDAR odometry, mapping, Nav2, desktop and full robot profiles |
| Integrated launch ownership | One drive/supervisor; inherited virtual input blocked; IMU, HRI, navigation and dashboard executables resolved |
| C++ regression targets | Wheel servo, wheel odometry and CAN faults: 3/3 passed |
| Web | ESLint and Vite production build passed; installed assets checked |
| Active documentation | Relative links resolve and removed root-script commands are absent |

The build may report existing vendor warnings and unused `PYTHON_EXECUTABLE`
CMake-variable warnings. RealSense is optional in the existing camera CMake:
the package can build without the native camera executable when that SDK is
absent. Camera operation is outside this acceptance scope.

The dependency declarations use the resolvable `nlohmann-json-dev` rosdep key
([upstream mapping](https://github.com/ros/rosdistro/blob/master/rosdep/base.yaml)).
`python-multipart` has no rosdep key and remains declared in dashboard `setup.py`
and `requirements-runtime.txt`; AMM/CI install it into the Python 3.10 venv.
The dashboard exports `ament_python` as its build type, following the
[Humble Python package pattern](https://github.com/ros2/examples/blob/humble/rclpy/topics/minimal_publisher/package.xml),
without declaring that build-type identifier as a rosdep package dependency.
Strict `rosdep install --simulate` resolves the complete source tree without
unknown keys; actual apt installation on a fresh host is performed by CI.

On this development host, rosbridge/rosapi package discovery uses previously
extracted official apt files under `/tmp/dori-rosbridge-runtime`; normal robot
and CI installation uses rosdep/apt. This affects non-actuating launch inspection
only; there was no new browser/rosbridge runtime test in this follow-up.

## CI and retained evidence

[DORI CI workflow](../../.github/workflows/ci.yml) uses a clean
Ubuntu 22.04 / ROS Humble container, builds the web first, builds all ROS packages,
then runs the dedicated package/launch/documentation checks and three C++ targets.
It runs on pull requests and pushes to main/feature/control-and-navigation.
Its step summary states the limited scope; logs and JUnit output are retained as
`refactor-p0p2-<commit>` artifacts for 14 days. Raw evidence stays outside Git.
Local logs are under `log/refactor-p0p2`. A local result does not imply that a
remote GitHub Actions run completed; check the run status for the delivered SHA.

## Explicit P1 backlog

The existing full test directories are not collected by this workflow. They
still contain references to removed `autonomy`, `drive_contract`, `dori_stack`,
mapping helpers and the previous package inventory. P1 must migrate those
dependencies and re-run HRI/Nav2/TTA driving, mapping/map saving, retry/reverse/
cancel behavior and the actual browser flow. These are pending work, not skipped
tests reported as passing. The earlier 123-test and closed-loop results do not
certify this revision. Physical acceptance remains AMM 72-20.
