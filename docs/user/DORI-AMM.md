# DORI AMM — 통합 로봇 정비·운용 매뉴얼

| 문서 관리 | 값 |
|---|---|
| 문서 번호 | DORI-AMM-001 |
| 개정 | R4 / 2026-10-28 — 제어·하드웨어 패키지 통합 후속 P0·P2 |
| 적용 대상 | Ubuntu 22.04, ROS 2 Humble, Python 3.10, 기존 DORI 실물 제어장치 |
| 소스 기준 | feature/control-and-navigation `d35f313` 이후 P0·P2 수정 |
| main 대조 | `d4cc1ae079082ef5af94583ce684155c39f58c28` — 위 feature의 조상, 별도 미포함 HRI 커밋 없음 |
| 통합 브랜치 | `integration/robot-hri-navigation` |
| 검증 등급 | 빌드·설치·launch·웹 빌드 검증 / P1 전체 회귀 복구 및 실물 인수 미완료 |
| 관련 기록 | [P0·P2 검증 범위와 재현 절차](../dev/refactor-validation.md) |

이 문서는 항공기 정비서의 작업 번호·선행조건·작업·합격기준·복구 형식을 적용한 로봇 작업 문서다. 항공 인증 또는 현장 로봇의 운용 승인 문서가 아니다. 모든 명령은 별도 표시가 없으면 저장소 루트에서 일반 사용자로 실행한다.

## AMM 00 — 구성 및 개정 통제

### 00-10 적용 기준

실제로 주행한 제어 로직·튜닝은 유지하고 프로젝트 패키지는 `dori_*`로 통일한다. 하드웨어 기동은 `dori_hardware`, 제어는 `dori_control`·`dori_supervisor`, 상위 조합은 `dori_bringup`이 담당한다. Nav2와 HRI 주행 중계는 `dori_navigation`, 센서 지도화는 `dori_mapping`, 메시지와 액션은 `dori_msgs`에 합쳤다. [전체 변경표](../dev/package-ownership.md)를 적용한다. 벤더·장치 패키지와 ROS 표준 파라미터 이름은 유지한다.

`main`의 음성, 규칙/외부 LLM, RAG, 감정 표현, 사람 추적, 제스처, 표정, 랜드마크, 지식 관리 및 대시보드 코드를 포함한다. 카메라 모델·장치·API 키가 필요한 기능은 준비 후 활성화한다. 제거한 것은 빌드에서 제외돼 있던 구형 BT 모의 액션/조건 구현이며, 실제 ROS 액션 클라이언트로 대체했다.

### 00-20 주요 변경

| 결함 | 통합 조치 |
|---|---|
| 디렉터리 이동 후 소스·설치 경로 불일치 | `ros2_ws/src`, `ros2_ws/install` 기준으로 빌드·런처·시험 수정 |
| 삭제된 launch 디렉터리 설치 / 누락된 Python·웹 파일 | CMake·setup·실행 파일 설치 정리 |
| Nav2와 HRI 액션/네임스페이스 불일치 | 공개 DORI 액션 → 단일 권한 중계 → 내부 Nav2 액션 |
| main의 충돌 잔여 코드와 성공 고정 BT | Humble BT.CPP v3 기반 실제 LLM/TTS/주행 결과 대기 |
| 여러 노드가 active/enabled 발행 | `nav2_adapter` 단일 소유, heartbeat 누락 시 주행 차단 |
| 웹 지도 자리표시자 / TTS 입력을 출력으로 오인 | 실측 지도 뷰어 임베드, 실제 TTS 출력 이벤트 연결 |
| API보다 먼저 등록된 SPA 경로 | API 뒤에 정적 페이지 라우트 배치 |
| 재연결 시 ROS 토픽 타입 유실 / rosapi 미기동 | 타입 유지 및 rosapi 기동 |
| 모델 import 중 다운로드·부분 초기화 | 명시적 모델 준비, 초기화 실패 시 종료 |
| Conda Python/라이브러리 혼입 | Ubuntu Python 3.10, 별도 venv, 환경 경로 정리 |
| 음성 의존성이 NumPy 2를 설치해 ROS 바이너리와 충돌 | `constraints-robot.txt`로 NumPy 1.24.4 / SciPy 1.10.1 고정 |

Humble 액션 basename remap의 제약 때문에 내부 Nav2 액션의 send_goal/get_result/cancel_goal/feedback/status 다섯 endpoint를 모두 remap했다. 근거: [ROS 2 upstream 이슈 #1312](https://github.com/ros2/ros2/issues/1312). 도착 성공은 Nav2 성공 상태와 최근 map 좌표 피드백을 함께 확인한다.

## AMM 05 — 운용 전 점검

### TASK 05-10-00 — 정지 상태 및 작업 구역 확보

**선행조건:** 로봇 정지, 기존 제어 세션 종료, 비상 정지 장치 접근 가능, 주행 구역 확보.

**주의:** 실물 hardware/robot launch와 매핑용 하드웨어 launch는 구동기를 실행한다. `enable_stt:=false`는 마이크만 끈다. CAN/장치 준비는 아래 관리 명령으로 별도 수행하며, launch가 자동으로 준비하지 않는다.

1. 차체·바퀴·변형 기구 주변에서 사람과 장애물을 제거한다.
2. 배터리, CANable, 서보, IMU, LiDAR의 전원·결선·커넥터를 확인한다.
3. 적용 지도와 현장 구조가 일치하는지 확인한다. 지도만 같고 초기 위치가 다른 상태에서 출발하지 않는다.
4. 다른 터미널·서비스에서 제어 노드가 실행 중이면 먼저 정상 종료한다.
5. 현재 로봇의 udev 장치 별칭과 포트를 확인한다. LiDAR 기본 별칭은 `/dev/slamtec_c1`, CAN은 `can1`이다. IMU/서보 포트는 `dori_hardware`의 기존 실물 launch 설정을 적용한다.

**합격기준:** 단일 제어 세션을 시작할 수 있고, 현장 정지 수단과 자유 주행 공간이 확보됨.

**불합격 조치:** 장치 식별 불일치 또는 기존 소유 프로세스 발견 시 시작을 중단하고 AMM 80으로 이동한다.

### TASK 05-20-00 — 비구동 설치·장치 점검

AMM 20-12의 환경을 설정한 뒤 실행한다. 아래 명령은 ROS 노드를 시작하지 않는다.

```bash
ros2 pkg executables dori_hardware
ros2 pkg executables dori_control
ros2 pkg executables dori_diagnostics
ros2 interface show dori_msgs/msg/MitCommand
ros2 launch dori_hardware system_real_with_imu.launch.py --show-args
ip -details link show can1
ls -l /dev/serial/by-id/ /dev/slamtec_c1
```

**합격기준:** 하드웨어 실행 파일 6개(DXL 2개, IMU/자세 4개), 제어 10개, 진단 1개가 설치돼 있고 AMM 72-10의 비구동 시험 통과. 현장에서는 can1의 UP 상태, 설정한 serial 장치의 존재·읽기/쓰기 권한, 단일 제어 세션도 확인한다. 장치 없는 개발 PC에서는 CAN/serial 항목을 실물 검증으로 보고하지 않는다.

설치된 Python 파일을 import하는 검사와 launch 경로 검사는 실제 장치 연결·음성 모델 준비를 대신하지 않는다.

## AMM 20 — 설치 및 복원

### TASK 20-10-00 — 신규 설치 및 빌드

**공구/자원:** Ubuntu 22.04, ROS Humble apt 저장소, Node.js 22.12 이상인 22 계열, npm, git, 인터넷. Python은 Ubuntu `/usr/bin/python3`의 3.10 계열을 사용한다. Conda가 활성화되지 않은 새 셸에서 저장소 루트로 이동한다.

```bash
sudo apt-get update
sudo apt-get install -y python3.10-venv python3-pip python3-rosdep \
  python3-colcon-common-extensions python3-serial python3-numpy python3-scipy \
  python3-pil libportaudio2 portaudio19-dev ffmpeg mpg123 can-utils \
  nlohmann-json3-dev ros-humble-navigation2 ros-humble-nav2-bringup \
  ros-humble-cartographer-ros ros-humble-rosbridge-server
source /opt/ros/humble/setup.bash
# rosdep를 처음 설정하는 장치에서만 수행
if [ ! -f /etc/ros/rosdep/sources.list.d/20-default.list ]; then sudo rosdep init; fi
rosdep update --rosdistro humble
rosdep install --from-paths ros2_ws/src --ignore-src --rosdistro humble -y
/usr/bin/python3 -m venv --system-site-packages .venv
.venv/bin/python -m pip install -r requirements-runtime.txt
(cd web && npm ci && npm run lint && npm run build)
source .venv/bin/activate
export PYTHONNOUSERSITE=1
(cd ros2_ws && python -m colcon build --symlink-install --parallel-workers 2 \
  --cmake-args -DBUILD_TESTING=ON \
  -DPython3_EXECUTABLE="$VIRTUAL_ENV/bin/python" \
  -DPYTHON_EXECUTABLE="$VIRTUAL_ENV/bin/python")
```

웹을 먼저 빌드해야 대시보드 설치에 최신 자산이 포함된다. 다른 PC의 `.venv`나 ROS build/install을 복사해 사용하지 않는다. RealSense SDK를 설치하지 않은 환경에서는 기존 CMake 정책에 따라 네이티브 카메라 실행 파일이 생략될 수 있다. 실제 C++ 카메라 사용 전 SDK 설치·재빌드·장치 시험을 수행한다.

**합격기준:** ROS 21개 패키지 빌드 및 웹 lint/build 성공. 마이크 사용 전 AMM 20-20, 실물 기동 전 AMM 20-30을 추가 수행한다.

### TASK 20-12-00 — 실행 터미널 환경

**선행조건:** 저장소 루트, 다른 workspace나 Conda를 활성화하지 않은 새 셸. 이후 모든 실행 터미널에 동일하게 적용한다.

```bash
export DORI_ROOT="$PWD"
unset AMENT_PREFIX_PATH COLCON_PREFIX_PATH CMAKE_PREFIX_PATH PYTHONPATH LD_LIBRARY_PATH
export PYTHONNOUSERSITE=1
source /opt/ros/humble/setup.bash
source "$DORI_ROOT/.venv/bin/activate"
source "$DORI_ROOT/ros2_ws/install/local_setup.bash"
# /usr/bin/python3로 실행되는 ROS 프로그램에도 동일한 Python 의존성을 제공
export PYTHONPATH="$DORI_ROOT/.venv/lib/python3.10/site-packages:${PYTHONPATH:-}"
export ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-0}"
```

`DORI_ROOT`는 이 문서의 절대 경로 변수다. 삭제된 스크립트용 `DORI_WS`, `DORI_CONTROL_*` 환경변수는 실행 설정으로 사용하지 않는다. launch 인자와 YAML을 사용한다. Conda 또는 다른 overlay가 섞였다면 새 셸에서 다시 시작한다.

### TASK 20-15-00 — 이전 설치본에서 R4로 전환

**선행조건:** 기존 로봇 세션 종료, 지도·목적지·현장 설정 백업. 새 셸의 저장소 루트에서 실행한다.

```bash
DORI_BACKUP="$PWD/.state/build-backups/$(date +%Y%m%d_%H%M%S)_$$"
mkdir -p "$DORI_BACKUP"
for artifact in build install log; do
  if [ -e "ros2_ws/$artifact" ]; then mv "ros2_ws/$artifact" "$DORI_BACKUP/$artifact"; fi
done
```

이후 AMM 20-10 빌드와 20-12 환경 설정, 72-10 검증을 순서대로 수행한다. 소스·지도·목적지·음성 모델은 보존한다. 과거 설치물이 남으면 제거한 패키지가 정상인 것처럼 발견될 수 있으므로 증분 빌드만으로 이전을 완료하지 않는다.

- `dori_drive`, `dori_input`, 변형 제어는 `dori_control`로 합쳤다. DXL 통신과 IMU Python 실행 파일은 `dori_hardware`가 소유한다.
- `dori_error`는 `dori_diagnostics`로 바뀌었다. [패키지 소유권](../dev/package-ownership.md)을 기준으로 외부 launch/import도 변경한다.
- R3 이후 `dori_msgs`의 메시지·액션 정의와 DDS 타입은 유지된다. R3 이전 `robot_msgs` 클라이언트는 여전히 `dori_msgs`에 맞춰 재빌드해야 한다.
- 루트 scripts와 preflight는 삭제 상태를 유지한다. 이전 자동 장치 준비·기존 세션 재사용 기능은 제공되지 않는다.

**합격기준:** 소스/설치 패키지가 21개 목록과 일치하고 구형 overlay가 없음. AMM 72-10 통과 후 실물 운용은 별도 인수한다.

### TASK 20-20-00 — 선택 기능 준비

| 기능 | 준비 및 적용 |
|---|---|
| 외부 LLM/RAG | `dori_llm/requirements.txt`를 constraints와 함께 설치; 지식 파일/색인 및 제공자 API 키 준비; `use_external_llm:=true`, `llm_model:=...`, `knowledge_file:=...`, `rag_index_dir:=...` |
| 기본 LLM | 키 없이 규칙 기반 QA와 등록 목적지 안내 사용. 임의 KB 좌표를 주행 목적지로 사용하지 않음 |
| 로봇 스피커 TTS | 기본 `tts_engine:=gtts`, `tts_playback_mode:=local_only`; 인터넷과 mpg123 출력 장치 필요. GCP TTS는 SDK·자격증명 별도 준비 |
| 브라우저 TTS | `tts_playback_mode:=publish_only`; 대시보드 ROS 연결 및 사용자 터치/키 입력으로 브라우저 음성 허용 |
| 카메라/사람 추적 | 아래 vision 의존성 설치, RealSense 장치/SDK 및 YOLO 모델 준비. `enable_perception:=true person_model:=/절대경로/model.pt` |
| 두 번째 카메라 | `enable_rear_camera:=true front_serial:=... rear_serial:=...`; 서로 다른 장치 serial 필수. 기본은 전방 한 대 |
| 사용자 이탈 감시 | 정상적인 tracking 토픽이 있을 때 `require_user_tracking:=true`; 1초 이상 tracking 갱신이 없으면 정지·재확인 |
| 제스처 | `enable_gesture:=true hand_model_path:=/절대경로/hand_landmarker.task` |
| 표정 | `enable_expression:=true face_model_path:=/절대경로/face_landmarker.task` |
| 랜드마크 | `enable_landmark:=true landmark_model:=/절대경로/model.pt`; 인지 결과는 LLM 설명 문맥용이며 지도 위치를 덮어쓰지 않음 |
| 마이크 반환 감시 | 실제 접점/입력 장치가 `/dori/hri/mic_attached`를 발행할 때 `require_mic_return:=true` |

마이크용 모델은 명시적으로 준비한다. 기본 openWakeWord `hey_mycroft`와 Whisper small을 사용하며 Porcupine `.ppn`을 이 설정에 넣지 않는다.

```bash
.venv/bin/python -m pip install -c constraints-robot.txt 'openwakeword>=0.6,<0.7' 'faster-whisper>=1,<2'
mkdir -p .state/voice
.venv/bin/python - <<'PYVOICE'
import openwakeword
from faster_whisper.utils import download_model
openwakeword.utils.download_models(model_names=['hey_mycroft'])
download_model('small', output_dir='.state/voice/whisper-small')
PYVOICE
```

선택 인지·외부 LLM 의존성도 동일한 ABI 제약을 적용한다.

```bash
.venv/bin/python -m pip install -c constraints-robot.txt -r ros2_ws/src/dori_perception/requirements.txt
```

예: 외부 LLM 의존성.

```bash
.venv/bin/python -m pip install -c constraints-robot.txt -r ros2_ws/src/dori_llm/requirements.txt
```

카메라·추론 모델의 성능, API 제공자 응답, 실물 음향은 이번 시험의 검증 범위 밖이다. CPU가 기본이며 GPU는 별도의 장치별 설치 후 선택한다.

### TASK 20-30-00 — 현장 장치 준비

**선행조건:** 로봇 정지, 구동 노드 종료, CANable·IMU·서보의 실제 장치 ID 확인. 다음 명령은 장치 상태를 바꾸므로 로봇의 운영 계정으로 수행한다.

```bash
ls -l /dev/serial/by-id/ /dev/input/
id -nG
# 필요한 그룹이 없는 운영 계정에 한 번 적용하고 재로그인
sudo usermod -aG dialout,input "$USER"
sudo install -m 644 ros2_ws/src/dori_mapping/config/99-slamtec-c1.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules
sudo udevadm trigger --subsystem-match=tty
```

현재 실물의 CANable2는 SLCAN 방식이다. **can1과 해당 어댑터를 소유한 slcand가 모두 없는 경우에만** 실제 by-id 경로를 넣어 생성한다. 이미 연결돼 있으면 재생성하지 않는다.

```bash
CAN_SERIAL=/dev/serial/by-id/실제_CANable2_ID
sudo modprobe slcan
sudo slcand -o -s8 -t hw -S 3000000 "$CAN_SERIAL" can1
sudo ip link set can1 up
ip -details link show can1
```

IMU 포트는 `dori_hardware`의 IMU 노드 파라미터, DXL 포트는 Dynamixel 드라이버 설정과 대조한다. 조이스틱을 사용할 때는 xpad 바인딩·입력 장치 접근 권한과 축/버튼을 먼저 확인한다. 이 절차는 이전 자동 xpad 재바인딩을 수행하지 않는다. 장치 식별이나 드라이버 상태가 맞지 않으면 기동하지 않고 해당 장치를 정비한다.

**합격기준:** can1 UP, 실제 설정과 일치하는 시리얼 장치 및 접근 권한 확보. launch는 CAN 연결이나 권한을 자동으로 수정하지 않는다.

## AMM 30 — 시스템 및 신호 흐름

### 30-10 주행 권한

```text
마이크 STT / 대시보드 텍스트
  → /dori/stt/result → dori_bt → /dori/llm/query → /dori/tts/speak
  → /dori/nav/navigate_named → 지도별 목적지 검증
  → /dori/nav/navigate_to → nav2_adapter
  → /dori/internal/navigate_to_pose → 실제 Nav2
  → /nav/cmd_vel_raw → velocity_smoother → /nav/cmd_vel [m/s, rad/s]
  → nav_drive_bridge [실측 역모델 + PI + 제한된 TTA]
  → /auto/cmd_vel [-1..1 조이스틱 입력] → mode_manager_node
  → /drive/cmd_vel [-1..1 조이스틱 입력] → drive_controller_node
  → 가감속 제한 → /bldc_mit_speed_cmd [바퀴 rad/s 및 토크]

웹 지도 / RViz → /goal_pose 또는 /relative_goal_pose
  → named_goal_bridge → 동일한 /dori/nav/navigate_to
```

액션 수락 시부터 권한을 예약하므로 동시에 받은 주행 목표 중 하나만 실행한다. 모드 해제, 비상 정지, 하드웨어 억제 시 active를 내리고 실제 Nav2 취소 완료를 기다린다. 수락/취소 응답이 제한 시간을 넘으면 오류를 유지하고 재시작을 요구한다. 늦게 도착한 수락도 취소한다.

### TASK 30-20-00 — SI 속도·조이스틱 단위·TTA 경로 점검

**선행조건:** 정지 상태, 통합 세션 실행, 초기 위치 설정 완료. 이 작업은 읽기 검사이며 시험 속도를 직접 발행하지 않는다.

1. `ros2 topic info -v`로 `/nav/cmd_vel_raw`, `/nav/cmd_vel`, `/auto/cmd_vel`, `/drive/cmd_vel`의 발행자·수신자를 각각 확인한다. `ros2 node list`에서 중복 제어 노드가 없는지도 확인한다.
2. 발행자·수신자가 아래 경로와 일치하는지 확인한다. 원시 Nav2 출력의 소유자는 controller/behavior server, 평활화 출력은 velocity_smoother, AUTO 출력은 nav_drive_bridge, 최종 정규화 출력은 mode_manager_node여야 한다. Humble의 BackUp/Wait는 같은 behavior_server 이름으로 각각 publisher를 가지므로 이 경우만 복수 endpoint를 허용한다.
3. `ros2 topic echo /navigation/motion_interpreter --once`로 보정 활성화와 진단 필드를 확인한다. `desired`는 지면 목표 속도, `linear.input`/`angular.input`은 조이스틱 입력, `applied`는 `/drive/wheel_control`의 제한기 후 바퀴 목표에서 복원한 입력이다.
4. 초기 선형 gain `0.62`, 시동 입력 `0.22`, 각 gain `1.67`, `motion.arc_only=true`와 기구 상수를 확인한다. 정속 전진 0.3 m/s의 초기 역모델은 `0.22 + 0.3/0.62 ≈ 0.704`다. 단순 `0.3/1.72 ≈ 0.174`는 실측 시동 입력보다 작아 이 기구의 AUTO 변환에 사용하지 않는다. 가감속·PI·TTA 때문에 순간 출력은 고정값이 아니다.
5. 수동 조이스틱은 `/manual/cmd_vel`로 이미 정규화된 값을 보낸다. 수동 모드에서만 supervisor가 이를 전달하며, 이 입력에 AUTO의 역모델을 중복 적용하지 않는다.

**합격기준:** 정확한 발행자·수신자 연결, TTA 활성화, YAML과 실행 파라미터 일치, 중복 제어 노드 및 일반 `/cmd_vel` 경로 없음.

**불합격 조치:** 구형 `virtual_vlm_input_node`는 AUTO를 직접 발행하는 시험 도구다. 통합 하드웨어 launch는 `use_input_nodes=false`로 강제하고, 별도로 실행된 도구는 위 토픽 정보에서 추가 발행자로 나타난다. 제거 후 다시 점검한다. 웹의 일반 토픽 발행 패널에서는 `/cmd_vel` 항목을 제거했다. 주행은 지도 목표 또는 HRI 안내 인터페이스를 사용한다. 기구 상수와 bridge 파라미터는 실행 중 변경하지 않고 설정 파일 수정 후 전체 세션을 재시작한다.

| 인터페이스 | 소유자 / 의미 |
|---|---|
| `/NAVIGATION_MODE` Int32 | 0 해제, 1 명시적 활성화 요청 |
| `/navigation/enabled`, `/navigation/goal_active` Bool | `nav2_adapter`만 발행. active는 Nav2 목표 수락 및 취소 상태 반영 |
| `/navigation/authority_heartbeat` Bool | 0.1초 주기, 0.5초 이상 미수신 시 drive bridge 차단 |
| `/dori/nav/locations` String JSON | 현재 지도에 속한 유효 목적지 목록, LLM과 HRI가 공유 |
| `/dori/nav/navigate_named` NavigateNamed | 이름/ID → 현재 지도 free cell 확인 → 공개 Navigate |
| `/dori/nav/navigate_to` Navigate | map frame, 유한 planar pose, 정규 quaternion 검증 |
| `/scan`, `/odom`, `/imu/data_raw` | 기존 실측 센서 계약 유지 |
| `/system/action_state` | 0 IDLE / 1 DRIVE에서만 주행, 변형·ESTOP·ERROR에서는 차단 |
| `/dori/hri/manager_state`, `/dori/hri/status` | BT 상태와 감시 조건, 웹에 전달 |
| `/dori/tts/audio_event` | 실제 TTS 출력 이벤트. local_only에서는 브라우저 중복 재생 억제 |
| `/dori/hri/emotion` | 상태 기반 감정 표현 및 수동 override |

TF는 `map → odom → base_link → laser`를 사용한다. `/odom`과 odom TF는 LiDAR odometry가 소유한다. 실물 launch에서는 wheel odometry TF를 동시에 켜지 않는다. LiDAR yaw 기본값은 기존 실측값 π다. 설치 방향이 다르면 실제 외부 파라미터를 측정해 적용한다.

### 30-30 HRI 상태 전이

1. IDLE에서 wake word, 사람 근접의 상승 edge, CALL 제스처, 마이크 분리를 받으면 LISTENING.
2. 신뢰도 0.55 이상의 STT 입력은 INTERACTION → LLM 결과 → RESPONDING → TTS 액션.
3. 정보 질문은 주행하지 않고 세션 완료. 등록되지 않은 목적지는 설명 응답만 반환.
4. 명시적인 안내 요청은 GUIDING → 실제 Nav2 결과 대기 → ARRIVED → 도착 발화 → IDLE.
5. 마이크 반환 감시를 사용하면 세션 완료 후 WAIT_MIC_RETURN. 30초 후 알림과 세션 종료.
6. 추적 필수 모드에서 사용자 정보가 끊기면 정지 후 USER_LOST_CONFIRM. 10초 내 복구되면 취소 완료 간격을 두고 재요청; 미복구 시 IDLE.
7. `access_blocked=true`면 정지 후 ACCESS_HELP. 해제 후 재요청, 60초 초과 시 종료.
8. 음성 정지·STOP 제스처·취소 토픽·비상 정지는 CANCELED. 실패는 ERROR. 도착 발화를 하지 않는다.
9. CONFIRM·GUIDANCE_COMPLETE는 주행 성공을 만들지 않는다. DIRECTION_HINT는 목적지 이름을 요청하고 좌표 없는 이동을 실행하지 않는다. REPEAT_GUIDANCE는 설명을 반복한다.
10. 기본 idle 순찰은 비활성이다. BT의 `idle_goals`를 명시했을 때만 등록 목적지 목록으로 순찰한다.

**주의:** 시각 인식의 STOP이나 음성 정지는 물리 비상 정지 장치를 대체하지 않는다. 가려짐·인식 지연이 존재한다.

## AMM 40 — 정상 운용 절차

### TASK 40-10-00 — 통합 기동

**선행조건:** AMM 05 및 20-30 통과, AMM 20-12 환경 설정, 현장과 적용 지도 일치. 아래 명령은 실제 구동기를 실행한다.

```bash
# 예제 지도를 사용할 때만 그 지도에 맞는 목적지 예제를 복사한다.
cp -n maps/web_goals.example.json maps/web_goals.json
ros2 launch dori_bringup hardware.launch.py \
  map:="$DORI_ROOT/maps/live_navigation_20261023_1938.yaml" \
  named_goals_file:="$DORI_ROOT/maps/web_goals.json" \
  whisper_model:="$DORI_ROOT/.state/voice/whisper-small"
```

새 지도에는 별도 목적지 저장소를 사용한다. 예제 파일을 다른 지도에 그대로 적용하지 않는다. `named_goals_file`을 생략하면 웹에서 사용하는 기본 저장 경로에 의존하므로 운용에서는 쓰기 가능한 절대 경로를 명시한다. 직접 launch는 CAN이나 모델을 준비하지 않고, 기존 제어 세션도 재사용하지 않는다.

마이크 없이 HRI와 브라우저 발화를 사용하려면 같은 명령에 `enable_stt:=false tts_playback_mode:=publish_only`를 추가한다. 이 옵션에서도 실물 구동은 켜진다. 인지는 준비 후 `enable_perception:=true require_user_tracking:=true person_model:=/절대경로/person.pt front_serial:=장치번호`로 선택한다.

대시보드는 3000, 지도 제어는 8080, 사용자 웹은 7070, rosbridge는 9090 포트를 사용한다. Navigation 패널은 `/navigation/` 프록시를 사용한다. 로봇 운영망에서 접근한다.

**합격기준:** 구성 노드가 종료되지 않고 대시보드·지도·스캔이 표시됨. 출발 전 AMM 40-20을 수행한다.

### TASK 40-20-00 — 초기 위치 및 목적지

1. 지도 화면에서 차체의 실제 위치와 전방 방향으로 초기 위치를 지정한다.
2. 스캔이 지도 벽과 겹치는지 확인한다. 반대 방향이면 laser yaw와 초기 yaw를 함께 점검한다.
3. 준비 상태 경고가 사라지는 것을 기다린다.
4. 아래 ROS 명령과 웹 readiness로 센서 갱신·TF·Nav2 상태를 검사하고 AMM 30-20의 토픽 소유자를 대조한다.

```bash
ros2 topic hz /scan
ros2 topic hz /odom
ros2 run tf2_ros tf2_echo map base_link
ros2 lifecycle get /amcl
ros2 lifecycle get /controller_server
```

5. 지도에서 접근 가능한 자유 공간을 선택하고 목적지 이름을 저장한다. 동일 지도에서 이름을 중복하지 않는다.
6. 현재 목록은 다음 명령으로도 확인한다.

```bash
ros2 topic echo /dori/nav/locations std_msgs/msg/String --once --qos-durability transient_local
```

`topic hz`와 `tf2_echo`는 지속 실행하므로 각 확인 후 Ctrl+C로 종료한다.

**합격기준:** 센서 갱신과 TF 연결, Nav2 active 상태, 웹 readiness 정상, 실제 위치와 지도 일치, 목적지 표시 및 HRI 목록 반영. 지도 변경 시 예전 지도에 저장된 목적지는 사용하지 않는다.

### TASK 40-30-00 — 안내 주행 및 정지

웹은 주행 활성화 후 목적지를 지정한다. HRI는 “등록된이름으로 안내해줘”처럼 명시적으로 요청한다. “어디에 있나요?” 같은 정보 질문은 이동 명령으로 취급하지 않는다.

마이크 없이 전체 HRI 경로를 확인할 때는 대시보드 STT 텍스트 입력 또는 아래 형식을 사용한다. **이 명령은 실제 로봇이 켜져 있으면 주행을 요청한다.**

```bash
ros2 topic pub --once /dori/stt/result std_msgs/msg/String \
  '{data: "{\"text\":\"Lobby로 안내해줘\",\"confidence\":1.0,\"event\":\"stt_result\"}"}'
```

정상 정지는 웹 정지 또는 아래 명령을 사용한다.

```bash
ros2 topic pub --once /NAVIGATION_MODE std_msgs/msg/Int32 '{data: 0}'
```

HRI 세션 취소:

```bash
ros2 topic pub --once /dori/hri/cancel std_msgs/msg/Bool '{data: true}'
```

**합격기준:** 주행 중 GUIDING, 실제 도착 후 ARRIVED와 도착 발화, 취소 시 active 해제 및 차체 정지. 웹 소유 브라우저의 heartbeat/lease가 끊기면 해당 웹 제어를 종료한다. HRI 자율 안내는 브라우저를 닫았다는 이유만으로 취소되지 않는다.

### TASK 40-40-00 — 정상 종료

1. 정지 요청 후 차체가 멈추는 것을 확인한다.
2. 기동 터미널에서 Ctrl+C를 누르고 자식 프로세스 종료를 기다린다.
3. 노드가 남거나 응답이 없으면 물리 정지 절차를 적용하고 원인을 기록한다.
4. 통합 launch는 상시 프로세스의 예기치 않은 종료를 감지하면 전체 세션 종료를 요청한다. 정상 완료한 controller spawner와 RViz 종료는 예외다.

## AMM 50 — 지도 생성 및 목적지 교체

### TASK 50-10-00 — 지도 작성

**선행조건:** 통합 주행 세션 완전 종료. AMM 20-30 장치 준비. 각 터미널에서 AMM 20-12 환경을 설정한다. AMCL 내비게이션과 Cartographer 매핑을 동시에 실행하지 않는다.

```bash
# 터미널 A: 실제 하드웨어와 검증된 수동 조이스틱
ros2 launch dori_hardware system_real_with_imu.launch.py \
  use_joystick:=true use_wheel_odometry:=false odom_publish_tf:=false
# 터미널 B: LiDAR
ros2 launch sllidar_ros2 sllidar_c1_launch.py serial_port:=/dev/slamtec_c1 \
  serial_baudrate:=460800 frame_id:=laser scan_mode:=Standard
# 터미널 C: 유일한 odom 및 base_link→laser TF 제공자
ros2 launch dori_mapping lidar_odometry.launch.py
# 터미널 D: 외부 LiDAR odometry를 사용하는 Cartographer
ros2 launch dori_mapping lidar_only_cartographer.launch.py \
  start_lidar_driver:=false use_odometry:=true external_odom_tf:=true publish_laser_tf:=false
# 터미널 E: 지도 저장
mkdir -p maps
ros2 run nav2_map_server map_saver_cli -f "$DORI_ROOT/maps/new_site" -t /map \
  --free 0.25 --occ 0.65 --ros-args -p save_map_timeout:=60.0 \
  -p map_subscribe_transient_local:=false
```

기존 수동 운용 방법으로 낮은 속도로 이동하며 중첩 스캔을 확보한다. YAML/PGM을 한 쌍으로 보관한다. 정지 후 모든 매핑 관련 터미널을 종료하고 AMM 40-10에서 새 지도 경로를 지정한다. 초기 위치와 목적지는 새 지도에 다시 등록한다. 지도 저장은 occupancy map 저장이며 Cartographer 이어 매핑용 상태 저장은 아니다.

**합격기준:** YAML/PGM 생성, 지도 벽·통로 확인, 새 지도에서 초기 위치와 AMM 30-20/40-20 점검 통과. R4의 비구동 패키지 검사만으로 이 실물 절차가 검증된 것은 아니다.

## AMM 60 — 설정 한계 및 보호 동작

아래 값은 이번 통합에서 보존한 기본값 또는 추가한 권한 제한이다. 변경은 실측 재검증 대상이다.

| 항목 | 값 / 동작 |
|---|---|
| 차륜 반경 / 간격 | 0.234 m / 0.184 m |
| Nav2 전진 / 각속도 상한 | 0.3 m/s / 1.2 rad/s |
| 후진 복구 상한 | 0.12 m/s, 후방 여유 확인 필수 |
| 주행 명령 신선도 | 0.4초 |
| odom / scan 신선도 | 0.5초 / 0.8초 |
| CAN 바퀴 피드백 허용 나이 | 각 바퀴 CAN 나이 + ROS 전달/보관 시간 합계 0.2초 이하 |
| 권한 heartbeat | 0.5초 이내 |
| 일반 / 상대 이동 도착 재검증 | 목표와 0.35 m / 0.15 m 이내의 최근 1초 map 피드백 |
| 액션 수락 / 취소 대기 | 기본 각각 5초, 초과 시 오류 유지·해제 |
| 주행 실행 제한 | 기본 900초 |
| 사용자 거리 > 2 m | 유효 추적 시 Nav2 속도 한도 50% |

실측 응답 보정·모터 부호·토크 보상·변형·서보 파라미터는 원본 제어 설정을 사용한다. 상대 이동, 재시도, 후진 복구와 도착 안내는 기존 웹 주행의 의미를 유지한다.

## AMM 72 — 시험 및 실물 인수

### TASK 72-10-00 — P0·P2 비구동 검증

AMM 20-12 환경에서 실행한다. 이 범위는 ROS 노드·실물 구동기를 시작하지 않는다. launch 검사에서 xacro로 URDF를 해석하고 임시 Cartographer 설정을 만들 수 있다.

```bash
mkdir -p log/refactor-p0p2
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/contracts -q \
  --junitxml=log/refactor-p0p2/packages.xml
ctest --test-dir ros2_ws/build/dori_control --output-on-failure
ctest --test-dir ros2_ws/build/cubemars_hardware --output-on-failure
(cd web && npm ci && npm run lint && npm test && npm run build)
```

**합격기준:** 소스와 설치 목록 21개 일치, 구형 overlay 없음, IMU 실행 파일 4개 설치/import, 전체 launch 경로 및 URDF 해석, C++ 시험 타깃 3개, 웹 lint/build 통과. 웹을 변경했다면 다시 ROS 빌드하여 설치 자산도 갱신한다.

[검증 범위와 CI](../dev/refactor-validation.md)에 현재 결과와 제한을 기록한다. 기존 `tests/control_and_nav`, `tests/integration` 전체 회귀 시험은 삭제된 실행기·보조 모듈·이전 패키지 참조의 P1 복구가 남아 있다. 이들을 이번 CI의 통과 범위에 포함하지 않는다. 이전 커밋에서 통과한 123개 시험과 브라우저/DDS 폐루프 결과는 R4의 완료 증거가 아니다.

P1에서 복구할 범위는 합성 LiDAR 매핑/지도 저장, HRI→Nav2→TTA→주행 폐루프, 취소·재시도·후진 차단, 실제 브라우저 통신이다. 실물 인수는 아래 작업 카드로 별도 수행한다.

### TASK 72-20-00 — 실물 인수 작업 카드

**수행자:** 현장 운영자 및 비상 정지 담당자. **기록:** 지도·commit·구성 옵션·배터리 상태·기구 상태·시험 거리·실제 측정 오차·정지 거리·합불·서명.

| 순서 | 작업 | 합격 기준 | 불합격 시 조치 |
|---|---|---|---|
| 1 | AMM 05, 기동, 초기 위치 | 장치 오류 없음, AMM 30-20/40-20 통과 | 구동 해제 및 FIM |
| 2 | 정지 상태에서 QA | 바퀴 명령/차체 이동 없음, 응답 및 감정 표시 | HRI 입력·주행 권한 점검 |
| 3 | 알려진 짧은 목적지 1개 안내 | 하나의 목표만 수락, 저속 전진, 실제 도착 후 발화 | 정지 후 TF/goal/피드백 점검 |
| 4 | 웹과 음성 목표 동시 입력 | 동시에 두 목표를 실행하지 않음 | 권한 중계 중복 점검 |
| 5 | 진행 중 웹/음성/제스처 취소 | active 해제, 정지 확인, 도착 발화 없음 | 비상 정지 후 액션 취소 경로 점검 |
| 6 | 센서 또는 권한 노드 중단 시험 | 설정 watchdog 안에 출력 차단; 실제 관성 정지 거리 측정 | 즉시 물리 정지, 운용 중단 |
| 7 | 전방 정체·후방 장애물 | 후방 막힘 시 후진하지 않음 | LiDAR 외부 파라미터/후방 판정 점검 |
| 8 | 추적 필수 모드 사용자 이탈·복귀 | 정지, 확인 상태, 복귀 후 단일 재개 | 추적 갱신·취소 응답 점검 |
| 9 | 마이크 반환·잡음·스피커 | echo 오인식 없음, wake/STT/발화의 실제 품질 확인 | 오디오 장치/환경 조정 |
| 10 | 변형·오류·비상 정지 상태 | 주행 억제 유지 | supervisor/CAN 경로 점검 |

이 카드의 실물 결과는 현재 기록에 포함되지 않는다. 소프트웨어 시험은 실제 마찰·하중·전원·CAN 결선·센서 장착·음향 인식을 증명하지 않는다.

## FIM 80 — 고장 격리

| 증상 | 격리 순서 | 복구/재시험 |
|---|---|---|
| Python 확장 import/NumPy 오류 | AMM 20-12 환경, `which python3`, NumPy/SciPy 버전 확인 | requirements-runtime 재설치, 필요 시 CMake cache 정리 후 빌드 |
| `/dori/nav/navigate_to` 없음 | `nav2_adapter` 실행·생성 인터페이스 설치 확인 | 전체 workspace 재빌드; 예전 액션 타입 클라이언트도 재빌드 |
| Nav2 action server unavailable | 내부 endpoint remap, lifecycle 상태 확인 | 패키지 설치·launch 경로 정리 후 전체 세션 재시작 |
| 권한 오류 유지 / 수락·취소 timeout | 관련 로그와 실제 Nav2 종료 여부 확인 | 정지 확인 후 세션 재시작; 실행 중 강제로 오류만 해제하지 않음 |
| 주행 준비가 계속 빨간색 | scan/odom/TF/CAN feedback 나이, 초기 위치, lifecycle 확인 | 원인 수정 후 AMM 30-20/40-20 재수행 |
| `hardware_scale_unverified` | drive/bridge의 속도 스케일 2개와 반경·간격 2개 확인 | 네 값 모두 일치하도록 설정 후 재기동 |
| `nonfinite_odom` / `stale_hardware_feedback` | pose 외 twist도 유한한지, encoder position/velocity와 CAN+ROS 총 나이 확인 | 잘못된 센서/전달 경로 복구; 예전 샘플로 학습을 계속하지 않음 |
| TTA 계수가 학습되지 않음 | 새 LiDAR stamp, encoder 부호, 제한기 후 입력의 stamp와 0.15초 응답 지연 확인 | 정지·과도 구간의 학습 억제는 정상. 누락/오래된 applied 샘플의 기록·통신 경로 점검 |
| 지도는 보이나 HRI 목적지 없음 | goals 파일, map_key, 중복 이름, free cell 확인 | 현재 지도에서 목적지 다시 저장 |
| 스캔이 반대 방향 | 실제 장착 방향 및 laser_yaw, 초기 yaw 비교 | 측정한 외부 파라미터로 재기동 |
| 웹 연결만 되고 상태 없음 | WebSocket 9090, ROS domain, rosapi 프로세스 확인 | 동일 도메인으로 재연결 |
| Navigation 프록시 503 | 로컬 8080 viewer 동작 여부 확인 | viewer 원인 해결 후 통합 재기동 |
| 웹 명령 403 | 오래된 세션, CSRF, 다른 origin 여부 | 동일 대시보드 주소 새로고침 |
| API가 HTML 반환 | 오래된 dashboard 설치 자산/서버 여부 | frontend build → ROS build → 재기동 |
| TTS 무음 | local_only/publish_only, 인터넷, mpg123, 브라우저 음성 허용 확인 | 출력 모드에 맞는 실제 음향 시험 |
| STT 시작 실패 | PortAudio, 입력 장치, 모델 경로·완전성 확인 | AMM 20-20 모델 준비 재수행; 마이크 접근 권한 점검 |
| 카메라 두 노드가 같은 장치 사용 | front/rear serial 중복·빈 값 확인 | 서로 다른 serial 지정 또는 후방 비활성 |
| 소프트웨어 배포 버튼 423 | 기본 운용 중 배포 잠금 | 로봇 종료 후 터미널에서 검토된 버전 설치 |

## AMM 90 — 로그, 변경, 복귀

운용 로그는 ROS launch 로그, 실행 파라미터와 운영자의 점검 결과를 함께 보관한다. 삭제된 preflight JSON을 새 운용 기록으로 요구하지 않는다. 재현 기록에는 commit, 실행 명령, 지도 YAML/PGM 해시, goals 파일 복사본, 환경 버전을 포함한다. API 키·오디오 원본·개인 데이터는 공개 기록에 넣지 않는다.

웹의 자동 git 배포는 기본 차단한다. 정비 중 명시적으로 `DORI_ALLOW_LIVE_DEPLOY=1`을 설정하면 기존 기능을 사용할 수 있으나, 실물 기동 프로세스에서 이 값을 설정하지 않는다. 검토한 버전으로 터미널 배포하는 절차를 기본으로 한다.

롤백은 로봇 완전 정지 → 현재 maps/goals/config 백업 → 이전에 실물 인수한 소스를 **별도 디렉터리**에 checkout → 그 디렉터리에서 venv/웹/ROS 재빌드 → AMM 20-12로 해당 overlay만 source → AMM 05/72 재수행 순서다. 두 overlay나 두 제어 세션을 동시에 사용하지 않는다. 하드웨어 수치 변경은 별도 개정과 인수 기록을 남긴다.
