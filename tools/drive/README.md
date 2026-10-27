# Physical robot workspace

Run the real-robot profile from this directory (`ros2_ws`):

```bash
source /opt/ros/humble/setup.bash
colcon build --symlink-install
source install/setup.bash
ros2 launch dori_bringup robot.launch.py dori_mode:=real \
  real_map:=$PWD/maps/live_navigation_20261023_1938.yaml \
  real_named_goals_file:=$PWD/maps/web_goals.example.json
```

Default map: `maps/live_navigation_20261023_1938.yaml`. The real profile owns
hardware, odometry, TF and Nav2, and receives goals only through
`/dori/nav/navigate_to`; do not start the retired standalone web/navigation
scripts alongside it.

Named destinations used by the Behavior Tree are supplied as JSON through
`real_named_goals_file`; `maps/web_goals.example.json` documents the expected
format. The configured goal frame must be `map`.

- [실행 안내](../docs/user/real-robot.md)
- [코드 구성·토픽 계약](../docs/dev/real-robot-architecture.md)
- [조이스틱 역모델·지연 보상·TTA](../docs/dev/real-robot-motion-interpreter.md)
- [검증·메인 저장소 반영 범위](../docs/dev/real-robot-validation.md)

Runtime logs, local calibration overrides and build outputs are excluded from
version control.
