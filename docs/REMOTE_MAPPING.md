# Tailscale 노트북에서 매핑 보기 → Nav2 초기 위치 지정

2026-09-08 확인: 로봇 ubuntu=100.103.150.5, 온라인 Linux 노트북 omen=100.87.51.42. 다른 노트북이면 해당 IP로 변경. 아래 노트북 명령은 ROS 2 Humble이 설치된 Linux를 전제로 합니다.

기존 `.bashrc`가 `~/.config/ros2-tailscale/setup.bash`를 불러옵니다. 로봇 설정은 Fast DDS, ROS_DOMAIN_ID=0, ROS_LOCALHOST_ONLY=0이며 기존 fastdds.xml을 사용합니다. 새 DDS 설정을 source하지 않습니다. 실행 스크립트는 이 네트워크 환경을 보존하고 패키지만 robot_ws에서 불러옵니다.

SSH는 22번이 아니라 2020번 포트를 사용합니다. RViz는 로봇에 SSH 접속한 셸이 아니라 노트북의 그래픽 데스크톱 터미널에서 실행합니다.

## 1. 노트북 RViz

기존 ROS/Tailscale 설정이 적용된 새 터미널에서:

```bash
mkdir -p ~/robot_remote
scp -P 2020 dori@100.103.150.5:/home/dori/robot_ws/src/robot_navigation/config/remote_monitor.rviz ~/robot_remote/
scp -P 2020 dori@100.103.150.5:/home/dori/robot_ws/src/robot_navigation/scripts/named_points_editor.py ~/robot_remote/
rviz2 -d ~/robot_remote/remote_monitor.rviz
```

## 2. 로봇에서 매핑 시작

기존 실행은 해당 터미널에서 Ctrl+C로 종료. 기존 .bashrc 설정이 적용된 터미널을 사용합니다.

```bash
cd /home/dori/robot_ws
source scripts/env.sh
ros2 daemon stop
./scripts/start_mapping.sh
```

로봇 모터·서보와 라이다가 켜집니다. sudo 인증은 이 터미널에서 입력합니다. 조이스틱으로 이동하며 매핑합니다. 조이스틱이 없으면 `--no-joystick`을 추가하지만 이동 입력은 별도 필요합니다. 원격으로 볼 때 `--rviz`는 불필요합니다. 실측 라이다 위치가 기본 0과 다르면 `--laser-x/y/z`, `--laser-roll/pitch/yaw`를 추가하세요.

노트북 다른 터미널에서 기존 .bashrc 환경에서:

```bash
ros2 topic list
ros2 topic hz /scan
ros2 topic echo /map --once --field info --qos-durability transient_local
```

RViz Map=/map, LaserScan=/scan, Fixed Frame=map. 제공한 RViz 설정에 이미 적용되어 있습니다. 토픽이 안 보이면 양쪽 환경·peer IP·DDS UDP 방화벽·Tailscale 상태를 점검합니다. 주행 제어 입력이나 비상 정지를 네트워크 시험용으로 발행하지 마세요.

## 3. 지도 저장 및 목적지 등록

로봇의 새 터미널에서 `source scripts/env.sh`를 실행한 뒤:

```bash
cd /home/dori/robot_ws
./scripts/save_map.sh /home/dori/robot_ws/maps/site
```

매핑 중 먼저 로봇을 정지하고 저장합니다. 저장한 뒤 매핑 시작 터미널에서 Ctrl+C. 노트북에서 지도와 목적지 편집:

```bash
scp -P 2020 'dori@100.103.150.5:/home/dori/robot_ws/maps/site.*' ~/robot_remote/
python3 ~/robot_remote/named_points_editor.py --map_yaml ~/robot_remote/site.yaml --points_csv ~/robot_remote/site.points.csv
scp -P 2020 ~/robot_remote/site.points.csv dori@100.103.150.5:/home/dori/robot_ws/maps/
```

편집기에서 실제 자유 공간에 이름 있는 목적지를 최소 1개 지정하고 저장합니다. 현재 통합 Nav2 실행은 지도에 맞는 목적지 CSV를 요구합니다.

## 4. 로봇에서 Nav2를 켜 두기

```bash
cd /home/dori/robot_ws
source scripts/env.sh
./scripts/start_navigation.sh --map /home/dori/robot_ws/maps/site.yaml --points /home/dori/robot_ws/maps/site.points.csv
```

매핑과 Nav2를 동시에 켜지 않습니다. 초기 위치를 아직 모르더라도 먼저 이 명령으로 켜둘 수 있습니다. /map이 노트북에 표시되고 /scan, /odom, /tf, /tf_static이 제공됩니다. 초기 위치가 없으면 map→odom이 없어 일부 Nav2 lifecycle/costmap 활성화가 대기할 수 있으며 아직 주행 준비 완료는 아닙니다.

## 5. 나중에 노트북에서 초기 위치 지정

RViz의 **2D Pose Estimate**를 선택해 지도에서 현재 로봇 위치를 클릭하고 바라보는 방향으로 드래그합니다. /initialpose에 PoseWithCovarianceStamped가 발행되어 로봇 AMCL이 처리합니다. 지도와 scan이 맞는지 확인합니다.

로봇의 같은 네트워크 환경 터미널에서:

```bash
./scripts/check_navigation.sh
./scripts/navigate.sh 'CSV에 등록한 목적지명'
./scripts/stop_navigation.sh
```

노트북에서 목표를 보낼 경우, ROS 환경을 source한 터미널에서 다음 순서로 발행합니다. 문자열은 실제 등록 이름으로 바꾸세요.

```bash
ros2 topic pub --once /NAVIGATION_TEXT std_msgs/msg/String "{data: '목적지명'}"
ros2 topic pub --once /NAVIGATION_MODE std_msgs/msg/Int32 '{data: 1}'
# 주행 취소
ros2 topic pub --once /NAVIGATION_MODE std_msgs/msg/Int32 '{data: 0}'
```

정확한 이름은 API 없이 동작합니다. 자연어는 로봇 Nav2를 시작한 터미널의 OPENAI_API_KEY가 필요합니다. RViz 직접 NavigateToPose 목표는 현재 goal_active 계약과 연결되지 않으므로 이동에는 위 텍스트/이름 경로를 사용합니다. 2D Pose Estimate는 정상 지원합니다.
