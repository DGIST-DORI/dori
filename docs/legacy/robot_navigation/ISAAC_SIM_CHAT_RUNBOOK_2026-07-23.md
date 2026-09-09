# Isaac Sim + Chat Logic Runbook

작성일: 2026-07-23

이 문서는 현재 `/home/data1/isaac_sim_ros/python_codes` 워크스페이스 기준으로, 다음 두 가지를 어떻게 실행하는지 정리한 문서다.

1. Isaac Sim + ROS 2 Nav2 실행
2. `prompt.txt` 기반 채팅 로직 실행

중요:

- 현재 채팅 스크립트 `prompt_chat.py`, `ollama_prompt_chat.py` 는 `stateless` 테스트용이다.
- 즉, 채팅 결과를 화면에 출력만 하고, 자동으로 `/named_goal` 을 publish 하지는 않는다.
- 실제 로봇을 움직이려면 채팅이 선택한 목적지 이름을 `/named_goal` 로 publish 해야 한다.
- 현재 워크스페이스에는 `ros2_2d_slam/maps/test_loop.yaml` 과 `ros2_2d_slam/maps/test_loop.points.csv` 가 있으므로, 아래 문서는 `test_loop` 맵 기준으로 작성한다.

## 1. 전제 조건

다음이 준비되어 있어야 한다.

- ROS 2 Humble 설치
- Isaac Sim 실행 가능 환경
- Ollama 설치 및 `qwen2.5:3b` 다운로드 완료
- Isaac Sim 쪽에서 아래 ROS 토픽이 살아 있어야 함
  - `/scan`
  - `/odom`
  - `/clock`
  - `/cmd_vel` subscriber

현재 확인된 로컬 Ollama 모델:

- `qwen2.5:3b`

## 2. Isaac Sim 실행

터미널 1:

```bash
cd /home/data1/isaac_sim_ros/python_codes
./IsaacSim.sh --gui
```

참고:

- `IsaacSim.sh` 는 내부적으로 `launch_isaacsim_stage.py` 를 호출한다.
- 기본 USD 는 `/home/data1/isaac_sim_ros/isaac_sim/carter_flattened.usd` 이다.
- GUI 대신 headless 를 쓰고 싶으면 `./IsaacSim.sh --headless` 를 사용하면 된다.

## 3. Nav2 + RViz + Named Goal 브리지 실행

터미널 2:

```bash
export ROOT=/home/data1/isaac_sim_ros/python_codes
export MAP_BASE=$ROOT/ros2_2d_slam/maps/test_loop
source /opt/ros/humble/setup.bash

ros2 launch $ROOT/ros2_2d_slam/launch/isaac_nav2.launch.py \
  map:="$MAP_BASE.yaml" \
  rviz:=true \
  keyboard:=true \
  auto_initial_pose:=false \
  named_nav:=true \
  named_points_file:="$MAP_BASE.points.csv"
```

이 launch 가 해주는 것:

- `base_link -> base_scan` 정적 TF 게시
- `/odom` 을 Nav2 쪽 TF/odom 으로 재게시
- `/scan` 타임스탬프 재작성
- AMCL + Nav2 bringup
- RViz 실행
- named goal bridge 실행
- `keyboard:=true` 일 때 viewer-only FPV 창 실행

중요:

- 여기서 `keyboard:=true` 는 조종용이 아니라 viewer-only FPV 다.
- 즉 `/cmd_vel` 을 추가로 publish 하지 않아서 Nav2 와 충돌하지 않는다.

## 4. 초기 localization

위 명령은 `auto_initial_pose:=false` 로 되어 있으므로, AMCL 초기 위치는 직접 잡아야 한다.

권장 순서:

1. RViz 에서 `2D Pose Estimate` 클릭
2. 로봇의 실제 시작 위치와 방향에 맞게 대략 지정
3. 필요하면 Isaac Sim 에서 로봇을 아주 조금 움직여 스캔 정합이 안정되는지 확인

확인 포인트:

- RViz 에서 `map`, `plan`, `local_plan`, `particle_cloud` 가 정상 표시되는지 본다.
- `map` frame 이 보이지 않으면 아직 localization 이 안 잡힌 상태다.

## 5. 목적지 이름으로 직접 자율주행 테스트

채팅 로직과 별개로, named goal 이 실제로 잘 가는지 먼저 확인하는 편이 좋다.

터미널 3:

```bash
source /opt/ros/humble/setup.bash
ros2 topic pub --once /named_goal std_msgs/msg/String "{data: E6}"
```

상태 확인:

```bash
source /opt/ros/humble/setup.bash
ros2 topic echo /named_goal_status
```

유용한 명령:

```bash
source /opt/ros/humble/setup.bash
ros2 topic pub --once /named_goal std_msgs/msg/String "{data: list}"
ros2 topic pub --once /named_goal std_msgs/msg/String "{data: reload}"
```

- `list`: 현재 목적지 key 목록 요청
- `reload`: CSV 수정 후 재로드

## 6. 채팅 로직 실행: Ollama 버전

이 버전은 `ros2_2d_slam/prompt.txt` 를 system prompt 로 사용한다.

터미널 4:

```bash
export ROOT=/home/data1/isaac_sim_ros/python_codes
/usr/bin/python3 $ROOT/ros2_2d_slam/scripts/ollama_prompt_chat.py
```

기본값:

- system prompt: `ros2_2d_slam/prompt.txt`
- model: `qwen2.5:3b`
- endpoint: `http://127.0.0.1:11434`
- 대화 상태: stateless

즉, 매 입력은 완전히 새 요청으로 처리된다.

### 6-1. 한 줄 입력 예시

```text
user> 박준혁 교수님 있는 곳으로 가고 싶어
E6
```

### 6-2. 여러 줄 붙여넣기 예시

```text
user> /paste
... 선택 가능한 목적지 후보 목록:
... - E5
... - E6
... - 화장실
...
... 사용자 요청:
... 박준혁 교수님 있는 곳으로 가고 싶어
... /send
E6
```

지원 명령:

- `/paste`: 멀티라인 입력 모드
- `/send`: 멀티라인 입력 전송
- `/reload`: `prompt.txt` 재로드
- `/show`: 현재 prompt 파일/모델/endpoint 확인
- `/quit`: 종료

## 7. 채팅 로직 실행: OpenAI 버전

이 버전도 `ros2_2d_slam/prompt.txt` 를 system prompt 로 사용한다.

터미널 4:

```bash
export ROOT=/home/data1/isaac_sim_ros/python_codes
/usr/bin/python3 $ROOT/ros2_2d_slam/scripts/prompt_chat.py
```

기본값:

- system prompt: `ros2_2d_slam/prompt.txt`
- model: `gpt-5.4`
- 대화 상태: stateless

주의:

- 이 스크립트는 `OPENAI_API_KEY` 가 필요하다.
- 현재 코드상 하드코딩 키를 찾는 fallback 도 있지만, 장기적으로는 권장되지 않는다.

## 8. 현재 채팅 로직과 실제 주행의 연결 방식

현재 구조는 아래와 같다.

1. 채팅 스크립트가 목적지 이름 하나를 고른다.
2. 사용자가 그 결과를 확인한다.
3. 그 이름을 `/named_goal` 로 publish 한다.
4. `named_goal_bridge.py` 가 CSV 좌표를 찾아 Nav2 goal 로 바꾼다.
5. Nav2 가 실제 주행한다.

즉, 현재 `prompt_chat.py` 와 `ollama_prompt_chat.py` 는 목적지 선택기이고, 주행 명령 발행기까지는 아니다.

예:

```text
채팅 출력: E6
```

그 다음:

```bash
source /opt/ros/humble/setup.bash
ros2 topic pub --once /named_goal std_msgs/msg/String "{data: E6}"
```

## 9. 참고: OpenAI 기반 ROS 직결 스크립트

현재 워크스페이스에는 ROS 에 직접 붙는 스크립트도 이미 있다.

파일:

- `ros2_2d_slam/scripts/text_llm_named_goal.py`

실행 예:

```bash
export ROOT=/home/data1/isaac_sim_ros/python_codes
export MAP_BASE=$ROOT/ros2_2d_slam/maps/test_loop
source /opt/ros/humble/setup.bash

/usr/bin/python3 $ROOT/ros2_2d_slam/scripts/text_llm_named_goal.py \
  --ros-args \
  -p points_file:="$MAP_BASE.points.csv"
```

차이점:

- 이 스크립트는 목적지 이름을 고른 뒤 바로 `/named_goal` 로 publish 할 수 있다.
- 하지만 현재 `prompt.txt` 를 읽어 쓰는 구조는 아니다.
- 현재는 파일 내부 `SYSTEM_PROMPT` 를 사용한다.
- 그리고 Ollama 가 아니라 OpenAI 기반이다.

## 10. 추천 운영 순서

가장 덜 헷갈리는 순서는 아래다.

1. Isaac Sim 실행
2. Nav2 + RViz + named goal bridge 실행
3. RViz 에서 localization 완료
4. `/named_goal` 수동 publish 로 주행 확인
5. `ollama_prompt_chat.py` 로 목적지 선택 테스트
6. 채팅 결과를 `/named_goal` 로 수동 publish
7. 전부 안정되면, 그 다음에 채팅 출력과 `/named_goal` publish 를 자동으로 연결

## 11. 자주 막히는 지점

### 11-1. `map` frame 이 안 보임

- 아직 localization 이 안 잡힌 경우가 많다.
- `2D Pose Estimate` 를 먼저 넣고 다시 본다.

### 11-2. Nav2 는 떠 있는데 로봇이 안 감

- `/named_goal` 이 실제 CSV key 와 일치하는지 본다.
- `/named_goal_status` 를 확인한다.
- RViz 에서 global/local plan 이 생기는지 본다.

### 11-3. 채팅은 되는데 로봇은 안 움직임

- 정상일 수 있다.
- `prompt_chat.py`, `ollama_prompt_chat.py` 는 원래 stateless 목적지 선택기다.
- 자동 publish 기능은 현재 없다.

### 11-4. Ollama 모델 오류

확인:

```bash
ollama list
```

없으면:

```bash
ollama pull qwen2.5:3b
```

## 12. 최소 실행 세트 요약

터미널 1:

```bash
cd /home/data1/isaac_sim_ros/python_codes
./IsaacSim.sh --gui
```

터미널 2:

```bash
export ROOT=/home/data1/isaac_sim_ros/python_codes
export MAP_BASE=$ROOT/ros2_2d_slam/maps/test_loop
source /opt/ros/humble/setup.bash

ros2 launch $ROOT/ros2_2d_slam/launch/isaac_nav2.launch.py \
  map:="$MAP_BASE.yaml" \
  rviz:=true \
  keyboard:=true \
  auto_initial_pose:=false \
  named_nav:=true \
  named_points_file:="$MAP_BASE.points.csv"
```

터미널 3:

```bash
/usr/bin/python3 /home/data1/isaac_sim_ros/python_codes/ros2_2d_slam/scripts/ollama_prompt_chat.py
```

채팅이 `E6` 를 내놓으면:

```bash
source /opt/ros/humble/setup.bash
ros2 topic pub --once /named_goal std_msgs/msg/String "{data: E6}"
```
