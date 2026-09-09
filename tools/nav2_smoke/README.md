# Jetson Real-C1 Nav2 Load Smoke

Isaac Sim을 실행하지 않는다. 예전에 Isaac 주행 테스트에서 만든 저장 맵을 Jetson에서 실제로
`map_server`에 올리고, 실물 SLAMTEC C1의 `/scan`을 AMCL과 Nav2가 처리할 때 전체 자원 사용량을
`htop`으로 보는 무로봇 부하 테스트다.

## 맵 근거

- 원본 `map_preview.png`: 1505 × 828
- 원본 `map_1782733848.pgm`: 1505 × 828
- 두 이미지는 디코딩한 1,246,140개 픽셀이 모두 동일하다.
- 이 폴더에는 `maps/isaac_saved_map.pgm/.yaml` 이름으로 포함했다.
- 기존 `test_loop.points.csv`도 61픽셀만 다른 사실상 같은 맵에서 사용했던 좌표라 함께 포함했다.

## 실제 실행되는 것

- `sllidar_ros2` C1 드라이버: 460800 baud, Standard mode, `/scan`, `laser` frame
- C1 원본 `/scan_raw`을 현재 ROS clock으로 restamp한 `/scan`
- 저장 occupancy map을 읽는 `map_server`
- AMCL localization
- local/global costmap
- NavFn global planner, DWB controller, BT Navigator, velocity smoother
- 가짜 `/odom`과 `odom -> base_link` TF 30 Hz
- AMCL 갱신을 유발하는 작은 odom 변화
- 기존 목적지 좌표를 순회하는 반복 NavigateToPose workload

로봇이나 모터 드라이버는 실행하지 않는다. Nav2가 `/cmd_vel`을 계산하지만 subscriber가 없으므로
물리 장치에는 전달되지 않는다.

## Jetson 준비

```bash
sudo apt update
sudo apt install -y \
  ros-humble-navigation2 \
  ros-humble-nav2-bringup \
  python3-colcon-common-extensions \
  git
```

C1 USB 규칙은 Jetson에서 한 번만 설치한다.

```bash
cd /home/ubuntu/python_codes/jetson_real_nav_smoke
bash ./scripts/install_udev_rule.sh
```

라이다를 다시 연결한 뒤 `/dev/slamtec_c1`이 생기는지 확인한다.

## 부하 테스트

첫 터미널:

```bash
cd /home/ubuntu/python_codes/jetson_real_nav_smoke
bash ./scripts/run_nav_htop.sh
```

기본적으로 `ROS_DOMAIN_ID=73`, `ROS_LOCALHOST_ONLY=1`을 사용해 다른 PC, Isaac Sim, 다른 ROS 2
배포판의 DDS 트래픽과 격리한다. 상태 확인 스크립트도 같은 값을 자동 사용한다.

이전 실행이 남았을 때:

```bash
bash ./scripts/stop_smoke.sh
```

둘째 터미널:

```bash
htop
```

Jetson 전력·온도까지 볼 때는 `jtop` 또는 다음 명령을 추가로 사용한다.

```bash
tegrastats
```

종료는 첫 터미널에서 `Ctrl-C`다. launch가 C1과 Nav2를 함께 종료한다.

이미 C1 드라이버가 `/scan`을 내고 있으면 중복 실행을 끈다.

```bash
./scripts/run_nav_htop.sh start_lidar_driver:=false
```

직렬 포트가 다른 경우:

```bash
SLLIDAR_PORT=/dev/ttyUSB1 ./scripts/run_nav_htop.sh
```

라이다 장착 위치가 base_link와 다르면 실제 미터/radian 오프셋을 준다.

```bash
./scripts/run_nav_htop.sh laser_x:=0.12 laser_z:=0.18 laser_yaw:=0.0
```

## 맵과 노드 활성 확인

Nav2 실행 중 다른 터미널에서:

```bash
./scripts/check_runtime.sh
```

다음 lifecycle 노드가 `active [3]`이어야 한다.

- map_server
- amcl
- planner_server
- controller_server
- bt_navigator

출력되는 `/map` 정보는 폭 1505, 높이 828, 해상도 0.05여야 한다.

이어서 20초 동안 실제 입력 파이프라인을 측정한다.

- `/scan_raw`: C1 드라이버가 직렬 입력에서 만든 실제 프레임 수와 Hz
- `/scan`: 시간 보정 후 AMCL/costmap으로 전달되는 프레임 수와 Hz
- `raw->scan delivery`: 입력 대비 전달률(기본 합격선 95%)
- `scan age`: 보정된 프레임의 median/p95 지연(기본 p95 합격선 250 ms)
- `beams/frame`, `valid-range`: 프레임에 실제 거리 샘플이 들어 있는지
- `odom`, `amcl_pose`, `plan`, costmap: Nav2 후단이 실제로 동작한 횟수

기본 C1 입력 합격선은 5 Hz다. 장시간 구간은 다음처럼 직접 측정한다.

```bash
python3 ./scripts/monitor_scan_pipeline.py --duration 300
```

이 측정을 실행한 상태에서 `htop`을 보면 입력이 끊긴 유휴 상태가 아니라, 실제 C1 프레임을
Nav2가 받고 있는 상태의 CPU·메모리 사용량인지 확인할 수 있다.

## htop에서 볼 값

코어별 수치 대신 상단의 전체 CPU%, Mem 사용량과 아래 프로세스 합을 본다.

- `sllidar_node`
- `map_server`, `amcl`
- `controller_server`, `planner_server`, `bt_navigator`
- `behavior_server`, `smoother_server`, `velocity_smoother`
- `no_robot_workload.py` — 부하 생성용 가짜 odom/goal 프로세스

최소 1분 warm-up 뒤 5~10분 정도 관찰하고, 최대값보다 안정 구간의 범위를 기록하는 것이 좋다.

## 실주행 부하와 얼마나 비슷한가

메모리는 상당히 유사하다. 동일한 Nav2 노드, 플러그인, 맵, costmap 크기와 AMCL particle 설정을
실제로 로드하기 때문이다.

CPU는 대략적인 범위만 유사하다. 실 C1 데이터의 직렬 수신·DDS 전달·AMCL laser update·costmap
ray tracing·planner/controller/BT 계산은 실제 코드 경로를 탄다. 반면 아래는 실주행과 다르다.

- odom이 실제 wheel encoder가 아니라 작은 가짜 변화다.
- 라이다가 물리적으로 이동하지 않아 scan과 fake odom이 일치하지 않는다.
- motor controller, MCU 통신, robot_state_publisher 등 실제 베이스 프로세스는 없다.
- 속도 변화, 미끄러짐, 동적 장애물, 실제 localization convergence는 재현하지 않는다.
- 반복 goal은 실제 임무 분포보다 planner/controller를 더 자주 깨울 수 있다.

따라서 이 테스트는 Jetson 메모리 용량 확인과 Nav2 포함 전체 CPU의 1차 범위 파악에는 적합하지만,
실주행 CPU를 정확히 예측하는 벤치마크는 아니다. 가장 가까운 무로봇 시험은 실제 주행에서 기록한
`/scan`, `/odom`, `/tf`, `/tf_static` rosbag을 실시간 속도(`--rate 1.0`)로 재생하는 방식이다.
