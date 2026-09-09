# API Execution Guide

작성일: 2026-08-10

이 문서는 현재 워크스페이스에서 OpenAI API를 이용해 목적지 선택을 실행하는 방법만 깔끔하게 정리한 문서다.

현재 기준으로 API 경로는 두 가지다.

1. `prompt.txt` 기반 stateless 채팅 테스트
2. `prompt.txt` 기반 ROS `/named_goal` 발행

중요:

- `prompt_chat.py` 는 목적지 이름만 출력한다.
- `text_llm_named_goal.py` 는 목적지 이름을 고른 뒤 `/named_goal` 로 바로 publish 한다.
- 2026년 8월 10일 기준으로 `text_llm_named_goal.py` 도 `prompt.txt` 를 직접 읽도록 맞춰 두었다.

## 1. 파일 위치

- system prompt: `ros2_2d_slam/prompt.txt`
- stateless API chat: `ros2_2d_slam/scripts/prompt_chat.py`
- ROS publish API chat: `ros2_2d_slam/scripts/text_llm_named_goal.py`

## 2. 가장 단순한 API 테스트

이 모드는 OpenAI API가 실제로 잘 붙는지만 보는 용도다.

터미널:

```bash
export ROOT=/home/data1/isaac_sim_ros/python_codes
/usr/bin/python3 $ROOT/ros2_2d_slam/scripts/prompt_chat.py
```

동작:

- `prompt.txt` 를 system prompt 로 사용
- 사용자 입력을 매번 새 요청으로 전송
- 이전 대화 히스토리는 유지하지 않음
- 결과는 터미널에 텍스트로만 출력

예:

```text
user> 박준혁 교수님 있는 곳으로 가고 싶어
E6
```

멀티라인 입력:

```text
user> /paste
... 선택 가능한 목적지 후보 목록:
... - E5
... - E6
...
... 사용자 요청:
... 박준혁 교수님 있는 곳으로 가고 싶어
... /send
E6
```

지원 명령:

- `/paste`
- `/send`
- `/reload`
- `/show`
- `/quit`

## 3. API로 바로 `/named_goal` 발행

이 모드는 OpenAI API가 목적지 이름을 고르고, 그 결과를 ROS topic `/named_goal` 에 바로 publish 한다.

즉, 실제 Nav2 named goal 흐름에 연결되는 모드다.

먼저 Nav2 + named goal bridge 가 떠 있어야 한다.

예시 터미널 1:

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

그 다음 API 목적지 선택기를 실행한다.

터미널 2:

```bash
export ROOT=/home/data1/isaac_sim_ros/python_codes
export MAP_BASE=$ROOT/ros2_2d_slam/maps/test_loop
source /opt/ros/humble/setup.bash

/usr/bin/python3 $ROOT/ros2_2d_slam/scripts/text_llm_named_goal.py \
  --ros-args \
  -p points_file:="$MAP_BASE.points.csv" \
  -p prompt_file:="$ROOT/ros2_2d_slam/prompt.txt"
```

이제 이렇게 입력하면:

```text
destination> 박준혁 교수님 있는 곳으로 가고 싶어
```

다음 순서로 동작한다.

1. `prompt.txt` 를 system prompt 로 사용
2. `test_loop.points.csv` 의 point name 목록을 후보로 구성
3. OpenAI API로 목적지 이름 하나 선택
4. 선택 결과를 `/named_goal` 로 publish
5. `named_goal_bridge.py` 가 좌표 goal 로 변환
6. Nav2 가 해당 좌표로 이동

## 4. 현재 points 파일 기준 예시

현재 `test_loop.points.csv` 에 들어 있는 이름 예시는 아래와 같다.

- `doctor's office`
- `point1`
- `point2`
- `seat`
- `stair`
- `upward stair`
- `water`

즉, API가 실제로 고를 수 있는 이름은 이 CSV 안에 있는 것만 유효하다.

확인:

```bash
sed -n '1,120p' /home/data1/isaac_sim_ros/python_codes/ros2_2d_slam/maps/test_loop.points.csv
```

## 5. 실행 전에 확인할 것

### 5-1. OpenAI API 키

가장 먼저 확인:

```bash
echo $OPENAI_API_KEY
```

비어 있으면:

```bash
export OPENAI_API_KEY=YOUR_KEY_HERE
```

### 5-2. 목적지 bridge 상태

`text_llm_named_goal.py` 는 `/named_goal` 만 publish 한다.

따라서 아래 둘 중 하나는 반드시 떠 있어야 한다.

- `isaac_nav2.launch.py` 안의 `named_goal_bridge.py`
- 사용자가 별도로 띄운 같은 역할의 bridge 노드

### 5-3. localization

Nav2 쪽은 `/named_goal` 이 들어와도 localization 이 안 잡히면 안 움직인다.

즉:

- RViz 에서 `map` frame 이 보여야 함
- 필요하면 `2D Pose Estimate` 먼저 수행

## 6. 가장 추천하는 실행 순서

1. `prompt_chat.py` 로 API 응답만 먼저 확인
2. `text_llm_named_goal.py` 로 `/named_goal` publish 연결 확인
3. Nav2 실제 이동 확인

이 순서가 가장 디버깅하기 쉽다.

## 7. 라이다 전용 폴더와의 관계

`lidar_only_slam` 폴더는 현재 `mapping` 전용이다.

즉 2026년 8월 10일 기준으로는:

- `lidar_only_slam`: 라이다만으로 맵 생성
- `ros2_2d_slam/scripts/text_llm_named_goal.py`: API 기반 목적지 선택 + `/named_goal` 발행

이 둘이 아직 한 launch 로 완전히 합쳐진 것은 아니다.

정리하면:

- 지금 당장 API 실행을 가장 깔끔하게 쓰려면 `ros2_2d_slam` 쪽 스크립트를 쓴다.
- `lidar_only_slam` 쪽은 우선 맵핑 전용으로 본다.

## 8. 최소 명령 세트

### A. API 응답만 보기

```bash
export ROOT=/home/data1/isaac_sim_ros/python_codes
/usr/bin/python3 $ROOT/ros2_2d_slam/scripts/prompt_chat.py
```

### B. API + ROS goal publish

```bash
export ROOT=/home/data1/isaac_sim_ros/python_codes
export MAP_BASE=$ROOT/ros2_2d_slam/maps/test_loop
source /opt/ros/humble/setup.bash

/usr/bin/python3 $ROOT/ros2_2d_slam/scripts/text_llm_named_goal.py \
  --ros-args \
  -p points_file:="$MAP_BASE.points.csv" \
  -p prompt_file:="$ROOT/ros2_2d_slam/prompt.txt"
```

### C. `/named_goal` 수신측까지 포함

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

## 9. 자주 막히는 지점

### `OPENAI_API_KEY is not set`

- 환경변수가 비어 있음

### `Could not resolve destination`

- 모델 출력이 CSV 안의 이름과 정확히 안 맞음
- `prompt.txt` 와 `points.csv` 후보 이름 체계를 같이 봐야 함

### `/named_goal` 은 publish 되는데 로봇이 안 움직임

- localization 문제
- `named_goal_bridge` 미실행
- point name 이 실제 CSV key 와 불일치

### `map` frame 이 안 보임

- AMCL/localization 이 아직 안 잡힘

## 10. 한 줄 요약

- API만 시험: `prompt_chat.py`
- API로 바로 goal 발행: `text_llm_named_goal.py`
- 실제 주행까지 보려면 Nav2 + `named_goal_bridge` 가 먼저 떠 있어야 함
