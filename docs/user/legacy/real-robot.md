# 실기 매핑·자율주행 실행

> 과거 버전의 기록입니다. 아래 패키지·스크립트 명령은 현재 버전에 적용되지 않습니다. 현행 절차는 [AMM R4](../DORI-AMM.md)를 사용하세요.

2026-10-26 정리. 모든 명령은 저장소의 **`ros2_ws` 디렉터리**에서 실행한다. 작업 폴더 이름은 바꿔도 된다. 현재 정리본은 `/home/dori/robot_ws_1026/ros2_ws`이며 원본 `/home/dori/robot_ws`와 독립적으로 빌드한다.

## 설치와 빌드

Ubuntu 22.04, ROS 2 Humble, Python 3.10과 `colcon`, `rosdep`을 사용한다. 새 장치에서는 ROS Humble을 설치한 후 빌드 도구와 SocketCAN 도구를 준비한다.

```bash
sudo apt-get install -y python3-colcon-common-extensions python3-rosdep can-utils
# rosdep sources가 아직 없는 장치에서 한 번만 실행
sudo rosdep init
rosdep update
```

ROS와 rosdep 초기화가 된 장치에서:

```bash
cd ros2_ws
./scripts/install_dependencies.sh
./scripts/build.sh
```

빌드 스크립트는 실기 패키지 15개의 의존성 범위를 선택한다. 같은 저장소의 상위 대화·인지 패키지를 함께 실행할 필요는 없다. 셸 스크립트는 현재 작업공간의 환경을 읽는다. 직접 Python/ROS 명령을 실행할 때는 `source scripts/env.sh`를 먼저 실행한다.

하드웨어는 `can1`, `/dev/slamtec_c1`, Dynamixel FTDI와 Arduino IMU의 `/dev/serial/by-id/` 경로를 사용한다. 다른 장치로 교체했다면 `scripts/run_robot_control.sh`, IMU/DXL 노드의 장치 설정을 확인한다. C1 udev 규칙은 다음으로 설치할 수 있다.

```bash
./src/robot_mapping/scripts/install_udev_rule.sh
```

## 저장 지도에서 시작

```bash
./scripts/start_autonomy.sh
# 다른 지도
./scripts/start_autonomy.sh --map maps/site.yaml
# 상태와 실행 계획만 조회
./scripts/start_autonomy.sh --check
```

기본 지도는 `maps/live_navigation_20261023_1938.yaml`이다. 이 지도는 현재 로봇의 특정 현장 지도이며 다른 장소에서는 새로 매핑한다.

통합 실행기는 구동·IMU·짐벌·LiDAR·LiDAR odometry·AMCL/Nav2·웹을 준비한다. 게임패드를 요구하지 않는다. 완전한 기존 구성은 재사용하고, 일부 노드만 켜져 있거나 다른 지도·중복 odometry가 발견되면 중단한다. 기존 수동 제어를 재사용하면 먼저 정지하고 조이스틱 입력 노드를 종료하므로 이후 컨트롤러 입력에 의존하지 않는다.

CAN 준비나 저장된 HTTPS 설정 복구에 필요한 sudo 인증은 로봇 터미널에서 받는다. 스크립트는 일반 사용자로 실행한다. 실행 자체가 목표를 발행하거나 ESTOP을 해제하지는 않는다.

새 작업공간의 코드를 실기에 적용할 때는 이전 작업공간의 실행기를 먼저 종료한다. 실행 중인 구성을 재사용하는 것은 실행 파일을 새 코드로 교체하는 작업이 아니다.

## 관리자와 사용자 웹

| 화면 | 주소 | 기능 |
| --- | --- | --- |
| 관리자 | `http://<robot-ip>:8080` | 지도·LiDAR·현재 위치·경로·센서·짐벌, 초기 위치 적용, 좌표 목표, 이름 목표 관리 |
| 사용자 | `https://<tailscale-host>:7070` | 지도·현재 목표·로봇 이동, 목적지 선택, 영어 대화·음성, TTS |

관리자 화면에서 **초기 위치 → 대략적인 위치 클릭/방향 드래그 → 적용**으로 현재 위치를 맞춘다. 주변 ±1.5m와 전체 방향을 탐색하므로 정확한 좌표 입력은 필요 없다. 반복 구조에서는 대략적인 방향도 지정한다. 탐색 중에는 로봇을 정지시킨다.

준비 상태가 정상일 때 **주행 활성화 → 목표 지정 → 전송**한다. 자주 쓰는 곳은 지도에서 위치를 고르고 이름을 저장한다. 기본 목표 저장 파일은 현재 작업공간의 `maps/web_goals.json`이다. 원래 현장의 이름 목표를 시작값으로 사용하려면 뷰어 실행 전에 한 번 복사한다.

```bash
cp -n maps/web_goals.example.json maps/web_goals.json
```

지도 내용·원점 등이 달라지면 이전 목표를 그대로 표시하지 않는다. 다른 지도에는 그 지도에 맞는 목표를 등록한다. 지도 수신 전에도 LiDAR를 볼 수 있으며, **화면 초기화**는 화면 캐시만 다시 받는다.

일반 목표는 Nav2 위치 허용 범위 30cm, 상대 거리 목표는 10cm를 사용한다. 정확한 최종 방향은 강제하지 않는다. 움직이면서 회전하는 경로를 사용하며 제자리 회전 요구를 큰 전진 원호로 임의 변환하지 않는다.

실패한 Nav2 목표는 **5초 후 최대 3회** 같은 좌표로 재시도한다. 별도 막힘 복구는 후방 LiDAR와 costmap을 확인하면서 목표 거리 35cm·0.12m/s로 후진한다. 취소·새 목표·ESTOP은 기존 재시도를 취소한다.

## 주기적 지도 재정합

기본 30초마다 목표/재시도가 없는 정지 상태에서 현재 위치 주변을 확인한다. 주행을 강제로 멈추지 않는다. 최근 스캔 3개의 후보가 일치하고 충분히 개선되는 경우에만 한 번에 최대 30cm·8°를 AMCL에 적용한다. LiDAR odometry 원점은 유지한다.

8080의 자동 정합 상태와 최근 일치율을 확인한다. 일치율은 지도 장애물 25cm 이내인 점의 비율이며 위치가 맞을 확률은 아니다. 일치가 낮거나 여러 후보가 비슷하면 **보류**한다. `유의미한 개선이 없어 현재 위치 유지`도 보정을 적용했다는 뜻은 아니다. 큰 오차는 수동 초기 위치를 적용한다.

설정은 웹 노드 시작 시 `auto_alignment.enabled`와 `auto_alignment.period_s`다. 예를 들어 뷰어만 별도로 관리하는 경우:

```bash
./scripts/start_web_viewer.sh --mode auto --ros-args -p auto_alignment.period_s:=30.0
```

## 영어 음성과 HTTPS

Gemini 키는 서버의 `~/.config/dori/gemini_api_key`에 권한 0600으로 보관한다. 저장소에는 키가 포함되지 않는다. `GEMINI_API_KEY`, `GOOGLE_API_KEY`, `DORI_GEMINI_KEY_FILE`도 지원한다. 기본 모델은 `gemini-3.5-flash-lite`이며 `GEMINI_MODEL`로 바꿀 수 있다. 키 없이도 지도·수동 목표·등록 목적지 선택은 사용할 수 있다.

Tailscale Serve를 사용할 경우 로봇 터미널에서:

```bash
sudo tailscale serve --bg --https=7070 http://127.0.0.1:7070
tailscale serve status
```

표시된 사용자 HTTPS URL을 `~/.config/dori/user_https_url`에 한 줄로 저장한 뒤 웹을 시작한다. URL이 설정되면 사용자 백엔드는 `127.0.0.1:7070`, 관리자 화면은 8080에 바인딩한다. `--voice-url` 또는 `DORI_USER_HTTPS_URL`로도 지정할 수 있다. 원격 마이크는 HTTPS 주소에서 사이트 권한을 허용해야 한다.

마이크 버튼으로 녹음하고 **Finish recording**을 누른다. 최대 녹음은 15초다. 예:

- `Go to start point.` — 등록한 이름 목표로 이동.
- `Move forward one meter.` — 수락 시점의 현재 위치에서 1m 앞을 목표로 지정.
- `Move forward fifty centimeters.` — 0.5m 앞 목표.

상대 거리 명령은 **0.4~3m 전진**을 지원한다. 후진·제자리 회전 음성 명령은 지원하지 않는다. Nav2가 장애물을 피해 경로를 계획하므로 실제 경로가 직선이거나 요청 거리와 정확히 같다고 보장하지 않는다. 재시도는 최초 절대 목표를 유지한다.

TTS는 브라우저 `speechSynthesis`로 이동 승인·대화·정지·도착을 영어로 안내한다. `Sound on/off`와 사용자 기기의 음량을 확인한다. 두 웹 포트는 기능 구분이며 별도의 로그인 인증 시스템은 아니다.

## 새 매핑

기존 구동/주행 실행기를 종료한 상태에서:

```bash
./scripts/start_mapping.sh
```

제어·컨트롤러·짐벌·LiDAR odometry·Cartographer·웹을 시작한다. 8080에서 지도를 보며 컨트롤러로 이동한다. `--no-joystick`은 컨트롤러 없는 개발 구성용이며 별도의 이동 입력이 필요하다.

정지한 뒤 다른 터미널에서:

```bash
./scripts/save_map.sh maps/site
```

YAML과 이미지 저장이 성공하면 매핑 터미널을 `Ctrl+C`로 종료하고 `./scripts/start_autonomy.sh --map maps/site.yaml`로 전환한다. 지도 저장은 occupancy map 저장이며 Cartographer 이어 매핑용 전체 상태 저장은 아니다.

## 종료·수동 복귀

웹 **AUTO 정지** 또는 관리자 화면 `ESC`, `./scripts/stop_navigation.sh`는 목표와 재시도를 취소한다. 하드웨어 ESTOP과는 구분한다. 웹 제어 탭 heartbeat가 10초 끊기면 그 탭의 AUTO 세션을 정지한다.

통합 실행 터미널의 `Ctrl+C`는 AUTO를 정지하고 해당 실행기가 시작한 노드를 종료한다. 재사용한 기존 노드는 남는다. 수동 주행으로 복귀하려면 기존 구동 실행기도 종료한 후:

```bash
./scripts/run_robot_control.sh
```

현재 기본은 wheel odometry와 wheel TF를 끈 상태다. 이 명령은 구동·컨트롤러·IMU·짐벌만 시작한다. 지도까지 필요한 수동 주행은 통합 매핑 명령을 사용한다. 게임패드 연결 지연으로 ESTOP이 걸렸다면 연결·스틱 중립을 확인하고 기존 재시작 입력(Y)을 사용한다.

## 상태와 개발 실행

```bash
./scripts/check_navigation.sh
curl --fail --silent http://127.0.0.1:8080/api/state | python3 -m json.tool
source scripts/env.sh
ros2 topic echo --once /localization/auto_alignment
ros2 topic echo --once /navigation/motion_interpreter
ros2 topic echo --once /navigation/retry_status
```

실기 기본 도메인은 0이다. 시험용 도메인 94/95/96과 구분한다. 통합 로그는 `log/autonomy_*/` 또는 `log/session_*/`, ROS 로그는 `~/.ros/log/`에 남는다.

개별 실행은 해당 구성만 꺼져 있을 때 각 터미널에서 수행한다.

```bash
./scripts/run_robot_control.sh --no-joystick
./scripts/run_lidar.sh
# 다음 ros2 명령을 실행할 터미널에서 먼저 source scripts/env.sh
ros2 launch robot_mapping lidar_odometry.launch.py
./scripts/run_navigation.sh map:=maps/site.yaml goal_source:=web publish_laser_tf:=false
./scripts/start_web_viewer.sh --mode auto
```

개별 Nav2의 지도 경로는 절대 경로 사용을 권장한다. 위 통합 실행기는 상대 경로를 절대 경로로 변환한다. Nav2 대신 매핑을 띄울 때는 `./scripts/run_mapping.sh`를 사용한다. `map→odom`을 만드는 AMCL과 Cartographer는 동시에 실행하지 않는다.
