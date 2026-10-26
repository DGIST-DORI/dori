# Physical robot workspace

Run these commands from this directory (`ros2_ws`):

```bash
./scripts/install_dependencies.sh
./scripts/build.sh
./scripts/start_autonomy.sh
```

Default map: `maps/live_navigation_20261023_1938.yaml`. Select another with `--map`.
Start fresh mapping with `./scripts/start_mapping.sh`. Use the administrator on
`http://<robot-ip>:8080` to set the initial pose and goals. Scripts resolve this
workspace from their own location; no path to another checkout is required.

- [실행 안내](../docs/user/real-robot.md)
- [코드 구성·토픽 계약](../docs/dev/real-robot-architecture.md)
- [조이스틱 역모델·지연 보상·TTA](../docs/dev/real-robot-motion-interpreter.md)
- [검증·메인 저장소 반영 범위](../docs/dev/real-robot-validation.md)

`./scripts/test.sh` runs hardware-free tests in ROS domain 96. Nav2 integration
scenarios run separately in domain 95. Runtime logs, local goal edits and build
outputs are excluded from version control.
