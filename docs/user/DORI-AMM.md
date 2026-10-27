# DORI AMM — 통합 로봇 정비·운용 매뉴얼

| 문서 관리 | 값 |
|---|---|
| 문서 번호 | DORI-AMM-001 |
| 개정 | R3 / 2026-10-27 — DORI 패키지 명칭 통일 |
| 적용 대상 | Ubuntu 22.04, ROS 2 Humble, Python 3.10, 기존 DORI 실물 제어장치 |
| 소스 기준 | feature/control-and-navigation `ec23021db449fbb1cac91740f5a466fb5af9c1c8` |
| main 대조 | `d4cc1ae079082ef5af94583ce684155c39f58c28` — 위 feature의 조상, 별도 미포함 HRI 커밋 없음 |
| 통합 브랜치 | `integration/robot-hri-navigation` |
| 검증 등급 | 소프트웨어 통합 검증 완료 / 실물 인수시험 미수행 |
| 관련 기록 | [최초 통합 검증](../dev/evidence/integration-2026-10-27/README.md), [R2 주행 재감사](../dev/evidence/drive-audit-2026-10-27/README.md), [R3 명칭 변경 검증](../dev/evidence/namespace-migration-2026-10-27/README.md) |

이 문서는 항공기 정비서의 작업 번호·선행조건·작업·합격기준·복구 형식을 적용한 로봇 작업 문서다. 항공 인증 또는 현장 로봇의 운용 승인 문서가 아니다. 모든 명령은 별도 표시가 없으면 저장소 루트에서 일반 사용자로 실행한다.

## AMM 00 — 구성 및 개정 통제

### 00-10 적용 기준

실제로 주행한 제어 로직·튜닝은 유지하고 프로젝트 패키지는 `dori_*`로 통일한다. 하드웨어 기동은 `dori_hardware`, 제어는 `dori_drive`·`dori_supervisor`·`dori_transform`, 상위 조합은 `dori_bringup`이 담당한다. Nav2와 HRI 주행 중계는 `dori_navigation`, 센서 지도화는 `dori_mapping`, 메시지와 액션은 `dori_msgs`에 합쳤다. [전체 변경표](../dev/package-ownership.md)를 적용한다. 벤더·장치 패키지와 ROS 표준 파라미터 이름은 유지한다.

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

**주의:** `start_robot.sh`, `run_dori_control.sh`, `start_mapping.sh`는 실제 구동기를 실행한다. `--text-only`도 구동기를 실행한다. `--prepare-only`는 CAN/장치 상태를 변경한다. `--check`와 `deployment_check.py`는 읽기 점검이다.

1. 차체·바퀴·변형 기구 주변에서 사람과 장애물을 제거한다.
2. 배터리, CANable, 서보, IMU, LiDAR의 전원·결선·커넥터를 확인한다.
3. 적용 지도와 현장 구조가 일치하는지 확인한다. 지도만 같고 초기 위치가 다른 상태에서 출발하지 않는다.
4. 다른 터미널·서비스에서 제어 노드가 실행 중이면 먼저 정상 종료한다.
5. 현재 로봇의 udev 장치 별칭과 포트를 확인한다. LiDAR 기본 별칭은 `/dev/slamtec_c1`, CAN은 `can1`이다. IMU/서보 포트는 `dori_hardware`의 기존 실물 launch 설정을 적용한다.

**합격기준:** 단일 제어 세션을 시작할 수 있고, 현장 정지 수단과 자유 주행 공간이 확보됨.

**불합격 조치:** 장치 식별 불일치 또는 기존 소유 프로세스 발견 시 시작을 중단하고 AMM 80으로 이동한다.

### TASK 05-20-00 — 비구동 설치 점검

```bash
source scripts/env.sh
python3 scripts/deployment_check.py --voice
scripts/run_dori_control.sh --no-joystick --check
```

첫 명령은 지도, Python ABI, ROS overlay, 액션·실행 파일, 웹 설치, Python 라이브러리와 음성 자산을 확인한다. 두 번째는 실제 장치 및 중복 제어 프로세스를 읽기 점검한다. 장치가 없는 개발 PC에서 두 번째 명령이 통과할 필요는 없다.

**합격기준:** deployment 결과 `ok: true`, 장치 점검 오류 없음. 실행 권한만으로 sudo 인증이 생기는 것은 아니다. 의존성 설치·CAN 준비에 sudo가 필요하면 해당 로봇의 운영 계정을 사용한다.

## AMM 20 — 설치 및 복원

### TASK 20-10-00 — 신규 설치

**공구/자원:** Ubuntu 22.04, ROS Humble apt 저장소, Node.js 20.19+ 또는 22.12+, npm, git, 인터넷, 로봇 장치 접근 권한. Python은 정확히 3.10 계열을 사용한다.

```bash
scripts/install_dependencies.sh
(cd web && npm ci && npm run build)
scripts/build.sh
source scripts/env.sh
python3 scripts/deployment_check.py --voice
```

- apt/rosdep는 Nav2, Cartographer, BT.CPP v3, ROS bridge, PortAudio, mpg123, CAN 도구 등을 설치한다.
- `.venv`는 `/usr/bin/python3`로 만든다. ROS Python 바인딩은 apt 설치를 사용한다.
- 음성 모델은 `scripts/prepare_voice.sh`가 준비한다. Whisper small은 `.state/voice/whisper-small`, openWakeWord 자산은 해당 venv 패키지 디렉터리에 저장된다.
- 기존 Porcupine 파일은 보존하지만 기본 STT는 키가 필요 없는 openWakeWord `hey_mycroft`다. Porcupine `.ppn` 파일을 openWakeWord 설정에 넣지 않는다.
- 마이크 없는 준비는 `install_dependencies.sh --no-voice`; 이후 마이크를 켜기 전 `prepare_voice.sh`를 실행한다.
- frontend 빌드 후 ROS 빌드를 해야 설치된 대시보드에 최신 자산이 포함된다.
- 다른 PC의 `.venv`, `ros2_ws/build`, `ros2_ws/install`을 로봇으로 복사해 사용하지 않는다. 콘솔 스크립트의 절대 경로와 아키텍처가 달라질 수 있다.

**합격기준:** ROS 24개 패키지 빌드 성공, 웹 lint/build 성공, 읽기 점검 통과.

### TASK 20-15-00 — 기존 robot 패키지 설치본에서 R3로 전환

**선행조건:** 이전 로봇 세션 종료. 지도·목적지 파일과 현장 설정 백업. 작업 디렉터리는 저장소 루트.

```bash
# 이전 overlay를 source하지 않은 새 셸에서 실행
scripts/build.sh --clean
source scripts/env.sh
python3 scripts/deployment_check.py --voice
scripts/test.sh
```

`--clean`은 기존 `ros2_ws/build`, `install`, `log`를 `.state/build-backups/<시각>_<PID>`로 이동한 뒤 다시 빌드한다. 소스·지도·목적지·음성 모델은 유지한다. 이전 이름의 설치 폴더가 남아 있으면 일반 build/env가 중단되고 clean build를 안내한다.

- `robot_msgs/msg/*` 대신 `dori_msgs/msg/*`를 사용한다. 필드는 같지만 ROS 메시지 타입 이름이 달라지므로 외부 ROS 클라이언트·rosbag 재생 설정도 새 타입으로 맞추고 재빌드한다. 기존 노드와 신규 노드를 섞어서 실행하지 않는다.
- 수동 제어 도구는 `scripts/run_dori_control.sh`, 매핑/내비게이션 조합기는 `scripts/dori_stack.py`다. 저장소 환경변수는 `DORI_WS`, 제어 설정 환경변수는 `DORI_CONTROL_*`, `DORI_ODOM_*`, `DORI_USE_WHEEL_ODOMETRY`다.
- 개발용 launch는 `ros2 launch dori_bringup dori_dev.launch.py`; `robot.launch.py`의 모드 인자는 `dori_mode:=real|desktop|sim`이다. 기본 실물 진입점 `scripts/start_robot.sh`는 동일하다.
- 기존 `robot_bringup`의 장치 설정/launch 경로는 `dori_hardware`로 이동했다. 기존 현장 설정을 새 경로에 대조·반영한 뒤 기동한다.

**합격기준:** workspace의 24개 패키지만 발견되며 구형 패키지 overlay가 없음. `ros2 pkg executables dori_navigation`에서 세 실행 파일이 보이고, `ros2 interface show dori_msgs/msg/MitCommand` 성공. AMM 30-20 및 72 인수 점검 통과.

### TASK 20-20-00 — 선택 기능 준비

| 기능 | 준비 및 적용 |
|---|---|
| 외부 LLM/RAG | `dori_llm/requirements.txt`를 constraints와 함께 설치; 지식 파일/색인 및 제공자 API 키 준비; `use_external_llm:=true`, `llm_model:=...`, `knowledge_file:=...`, `rag_index_dir:=...` |
| 기본 LLM | 키 없이 규칙 기반 QA와 등록 목적지 안내 사용. 임의 KB 좌표를 주행 목적지로 사용하지 않음 |
| 로봇 스피커 TTS | 기본 `tts_engine:=gtts`, `tts_playback_mode:=local_only`; 인터넷과 mpg123 출력 장치 필요. GCP TTS는 SDK·자격증명 별도 준비 |
| 브라우저 TTS | `tts_playback_mode:=publish_only`; 대시보드 ROS 연결 및 사용자 터치/키 입력으로 브라우저 음성 허용 |
| 카메라/사람 추적 | `install_dependencies.sh --vision`, RealSense 장치/SDK 및 YOLO 모델 준비. `enable_perception:=true person_model:=/절대경로/model.pt` |
| 두 번째 카메라 | `enable_rear_camera:=true front_serial:=... rear_serial:=...`; 서로 다른 장치 serial 필수. 기본은 전방 한 대 |
| 사용자 이탈 감시 | 정상적인 tracking 토픽이 있을 때 `require_user_tracking:=true`; 1초 이상 tracking 갱신이 없으면 정지·재확인 |
| 제스처 | `enable_gesture:=true hand_model_path:=/절대경로/hand_landmarker.task` |
| 표정 | `enable_expression:=true face_model_path:=/절대경로/face_landmarker.task` |
| 랜드마크 | `enable_landmark:=true landmark_model:=/절대경로/model.pt`; 인지 결과는 LLM 설명 문맥용이며 지도 위치를 덮어쓰지 않음 |
| 마이크 반환 감시 | 실제 접점/입력 장치가 `/dori/hri/mic_attached`를 발행할 때 `require_mic_return:=true` |

예: 선택 Python 의존성도 동일한 ABI 제약을 적용한다.

```bash
.venv/bin/python -m pip install -c constraints-robot.txt -r ros2_ws/src/dori_llm/requirements.txt
```

카메라·추론 모델의 성능, API 제공자 응답, 실물 음향은 이번 시험의 검증 범위 밖이다. CPU가 기본이며 GPU는 별도의 장치별 설치 후 선택한다.

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

1. `python3 scripts/preflight.py --stage navigation --hri --output log/preflight.json`을 실행한다.
2. `drive_contract.ok`와 전체 `ok`가 모두 참인지 확인한다. 원시 Nav2 출력의 소유자는 controller/behavior server, 평활화 출력은 velocity_smoother, AUTO 출력은 nav_drive_bridge, 최종 정규화 출력은 mode_manager_node여야 한다. Humble의 BackUp/Wait는 같은 behavior_server 이름으로 각각 publisher를 가지므로 이 경우만 복수 endpoint를 허용한다.
3. `ros2 topic echo /navigation/motion_interpreter --once`로 보정 활성화와 진단 필드를 확인한다. `desired`는 지면 목표 속도, `linear.input`/`angular.input`은 조이스틱 입력, `applied`는 `/drive/wheel_control`의 제한기 후 바퀴 목표에서 복원한 입력이다.
4. 초기 선형 gain `0.62`, 시동 입력 `0.22`, 각 gain `1.67`, `motion.arc_only=true`와 기구 상수를 확인한다. 정속 전진 0.3 m/s의 초기 역모델은 `0.22 + 0.3/0.62 ≈ 0.704`다. 단순 `0.3/1.72 ≈ 0.174`는 실측 시동 입력보다 작아 이 기구의 AUTO 변환에 사용하지 않는다. 가감속·PI·TTA 때문에 순간 출력은 고정값이 아니다.
5. 수동 조이스틱은 `/manual/cmd_vel`로 이미 정규화된 값을 보낸다. 수동 모드에서만 supervisor가 이를 전달하며, 이 입력에 AUTO의 역모델을 중복 적용하지 않는다.

**합격기준:** 정확한 발행자·수신자 연결, TTA 활성화, YAML과 실행 파라미터 일치, 중복 제어 노드 및 일반 `/cmd_vel` 경로 없음.

**불합격 조치:** 구형 `virtual_vlm_input_node`는 AUTO를 직접 발행하는 시험 도구다. 통합 하드웨어 launch는 `use_input_nodes=false`로 강제하고, 별도로 실행된 도구는 preflight에서 중복 발행자로 검출한다. 웹의 일반 토픽 발행 패널에서는 `/cmd_vel` 항목을 제거했다. 주행은 지도 목표 또는 HRI 안내 인터페이스를 사용한다. 기구 상수와 bridge 파라미터는 실행 중 변경하지 않고 설정 파일 수정 후 전체 세션을 재시작한다.

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

### 30-20 HRI 상태 전이

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

**선행조건:** AMM 05 통과, 적용 지도 확인.

```bash
scripts/start_robot.sh --map "$PWD/maps/live_navigation_20261023_1938.yaml"
```

이 스크립트는 음성 자산을 먼저 점검하고 CAN/장치를 준비한 다음, 실물 제어·LiDAR·LiDAR odometry·Nav2·HRI·웹을 단일 세션으로 시작한다. named goals 기본 파일이 없으면 예제를 복사한다. 지정한 사용자 goals 파일이 없으면 실패한다.

사용 예:

```bash
scripts/start_robot.sh --map /절대경로/site.yaml --goals /절대경로/goals.json
scripts/start_robot.sh --text-only
scripts/start_robot.sh enable_perception:=true require_user_tracking:=true \
  person_model:=/절대경로/person.pt front_serial:=장치번호
```

대시보드는 3000, 지도 제어는 8080, 기존 사용자 웹은 7070, rosbridge는 9090 포트를 사용한다. 대시보드 Navigation 패널은 `/navigation/` 프록시를 통해 지도·세션·명령 API를 같은 origin으로 제공한다. 로봇 운영망 안에서 접근한다.

**합격기준:** 구성 노드가 종료되지 않음, 대시보드 연결, 지도·스캔 표시. 이것만으로 출발 준비 완료는 아니다. 다음 초기 위치 점검이 필요하다.

### TASK 40-20-00 — 초기 위치 및 목적지

1. 지도 화면에서 차체의 실제 위치와 전방 방향으로 초기 위치를 지정한다.
2. 스캔이 지도 벽과 겹치는지 확인한다. 반대 방향이면 laser yaw와 초기 yaw를 함께 점검한다.
3. 준비 상태 경고가 사라지는 것을 기다린다.
4. 아래 명령으로 신선한 센서·TF·단일 소유자·Nav2 상태를 검사한다.

```bash
source scripts/env.sh
python3 scripts/preflight.py --stage navigation --hri --output /tmp/dori-preflight.json
```

5. 지도에서 접근 가능한 자유 공간을 선택하고 목적지 이름을 저장한다. 동일 지도에서 이름을 중복하지 않는다.
6. 현재 목록은 다음 명령으로도 확인한다.

```bash
ros2 topic echo /dori/nav/locations std_msgs/msg/String --once --qos-durability transient_local
```

**합격기준:** preflight `ok: true`, 실제 위치와 지도 일치, 목적지 표시 및 HRI 목록 반영. 지도 변경 시 예전 지도에 저장된 목적지는 사용하지 않는다.

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

**선행조건:** 통합 주행 세션 완전 종료. 매핑과 내비게이션을 동시에 실행하지 않는다.

```bash
scripts/start_mapping.sh
# 다른 터미널
scripts/save_map.sh "$PWD/maps/new_site"
```

기존 조이스틱 운용 방법으로 낮은 속도로 이동하며 충분한 중첩 스캔을 확보한다. 매핑 세션은 실제 하드웨어를 사용한다. 저장된 YAML과 PGM을 한 쌍으로 보관한다. 매핑 종료 후 새 YAML로 `start_robot.sh --map`을 실행하고, 초기 위치와 목적지를 다시 등록한다.

**합격기준:** YAML/PGM 생성, 지도 벽·통로 확인, 새 지도에서 초기 위치·preflight 통과.

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

### TASK 72-10-00 — 비실물 회귀 시험

```bash
scripts/test.sh
scripts/validate_release.sh
```

| 도메인 | 시험 |
|---|---|
| 94, localhost | 합성 LiDAR → 실제 odometry/Cartographer → 지도 저장 |
| 95, localhost | 가상 차체/센서 → 실제 Nav2·drive·웹·HRI 폐루프 |
| 96, localhost | 실제 ROS 액션 통신과 C++ BT, 제어 가능한 Nav2 시험 서버 |
| 97, localhost | 실제 HTTP·프록시·rosbridge·Firefox 대시보드 |
| 99, localhost | 실제 TTA bridge·supervisor·C++ drive, 실측 응답 모델·온라인 적응·오류 주입 |

브라우저 시험은 개발용 Firefox Marionette 세션을 별도로 준비하고 `.venv/bin/python -m pip install marionette_driver`를 실행한다. 테스트 전용 빈 프로필을 사용한다.

```bash
firefox --headless --marionette --no-remote --profile /사용자쓰기가능경로/빈프로필
scripts/validate_release.sh --browser
```

Snap Firefox라면 프로필은 `~/snap/firefox/common/` 아래에 둔다. 시험은 8080/9090/13000과 브라우저 2828을 사용한다. 실제 로봇 세션과 동시에 실행하지 않는다. 시험 결과는 `log/validation`에 저장한다.

### TASK 72-20-00 — 실물 인수 작업 카드

**수행자:** 현장 운영자 및 비상 정지 담당자. **기록:** 지도·commit·구성 옵션·배터리 상태·기구 상태·시험 거리·실제 측정 오차·정지 거리·합불·서명.

| 순서 | 작업 | 합격 기준 | 불합격 시 조치 |
|---|---|---|---|
| 1 | AMM 05, 기동, 초기 위치 | 장치 오류 없음, preflight 통과 | 구동 해제 및 FIM |
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
| Python 확장 import/NumPy 오류 | `source scripts/env.sh`, `which python3`, NumPy/SciPy 버전 확인 | requirements-runtime 재설치, 필요 시 CMake cache 정리 후 빌드 |
| `/dori/nav/navigate_to` 없음 | `nav2_adapter` 실행·생성 인터페이스 설치 확인 | 전체 workspace 재빌드; 예전 액션 타입 클라이언트도 재빌드 |
| Nav2 action server unavailable | 내부 endpoint remap, lifecycle 상태 확인 | 패키지 설치·launch 경로 정리 후 전체 세션 재시작 |
| 권한 오류 유지 / 수락·취소 timeout | 관련 로그와 실제 Nav2 종료 여부 확인 | 정지 확인 후 세션 재시작; 실행 중 강제로 오류만 해제하지 않음 |
| 주행 준비가 계속 빨간색 | scan/odom/TF/CAN feedback 나이, 초기 위치, lifecycle 확인 | 원인 수정 후 preflight 재수행 |
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
| STT 시작 실패 | PortAudio, 입력 장치, 모델 경로·완전성 확인 | prepare_voice 재실행; 마이크 접근 권한 점검 |
| 카메라 두 노드가 같은 장치 사용 | front/rear serial 중복·빈 값 확인 | 서로 다른 serial 지정 또는 후방 비활성 |
| 소프트웨어 배포 버튼 423 | 기본 운용 중 배포 잠금 | 로봇 종료 후 터미널에서 검토된 버전 설치 |

## AMM 90 — 로그, 변경, 복귀

운용 로그는 ROS launch 로그와 preflight JSON을 함께 보관한다. 재현 기록에는 commit, 실행 명령, 지도 YAML/PGM 해시, goals 파일 복사본, 환경 버전을 포함한다. API 키·오디오 원본·개인 데이터는 공개 기록에 넣지 않는다.

웹의 자동 git 배포는 기본 차단한다. 정비 중 명시적으로 `DORI_ALLOW_LIVE_DEPLOY=1`을 설정하면 기존 기능을 사용할 수 있으나, 실물 기동 프로세스에서 이 값을 설정하지 않는다. 검토한 버전으로 터미널 배포하는 절차를 기본으로 한다.

롤백은 로봇 완전 정지 → 현재 maps/goals/config 백업 → 이전에 실물 인수한 소스를 **별도 디렉터리**에 checkout → 그 디렉터리에서 venv/웹/ROS 재빌드 → 해당 env만 source → AMM 05/72 재수행 순서다. 두 overlay나 두 제어 세션을 동시에 사용하지 않는다. 하드웨어 수치 변경은 별도 개정과 인수 기록을 남긴다.
