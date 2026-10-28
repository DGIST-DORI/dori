# DORI

DGIST 안내 로봇의 HRI·실물 주행·웹 통합 저장소입니다. Ubuntu 22.04 / ROS 2 Humble / Python 3.10을 사용합니다.

**운용 기준: [DORI 정비·운용 매뉴얼 R4](docs/user/DORI-AMM.md)**

제어·입력·변형 제어는 `dori_control`, IMU·DXL과 하드웨어 기동은 `dori_hardware`, 오류 기록은 `dori_diagnostics`가 담당합니다. 전체 workspace는 21개 패키지이며 기존 주행 보정값과 TTA 경로는 유지합니다. [패키지 소유권](docs/dev/package-ownership.md)을 참고하세요.

## 설치 및 실행

신규 설치는 AMM 20-10, 이전 설치본의 클린 이전은 20-15, 터미널 환경은 20-12를 따릅니다. 루트 scripts와 preflight는 삭제됐으며, ROS 기본 명령을 사용합니다. 이전 설치 overlay를 재사용하지 마세요.

AMM 05·20-20·20-30의 장치/음성 준비를 마치고, 저장소 루트에서 다음을 실행합니다. **이 명령은 실제 구동기를 실행합니다.**

```bash
cp -n maps/web_goals.example.json maps/web_goals.json
ros2 launch dori_bringup real_robot.launch.py \
  map:="$PWD/maps/live_navigation_20261023_1938.yaml" \
  named_goals_file:="$PWD/maps/web_goals.json" \
  whisper_model:="$PWD/.state/voice/whisper-small"
```

지도와 예제 목적지는 특정 실측 장소용입니다. 다른 현장에는 그 현장의 지도·목적지를 사용하세요. launch는 CAN/권한/모델을 자동 준비하지 않으며 기존 제어 세션을 재사용하지 않습니다.

- 대시보드: `http://<로봇 IP>:3000`, ROS WebSocket: `ws://<로봇 IP>:9090`
- 지도·초기 위치·목적지·정지: Navigation 메뉴 또는 `http://<로봇 IP>:8080`
- 사용자 주행·대화 화면: `http://<로봇 IP>:7070`
- 마이크 없이 HRI를 쓰려면 `enable_stt:=false tts_playback_mode:=publish_only`를 추가합니다. 실물 구동은 계속 켜집니다.

## 이번 검증 범위

AMM 20-12 환경과 클린 빌드 이후:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/refactor -q
ctest --test-dir ros2_ws/build/dori_control --output-on-failure
ctest --test-dir ros2_ws/build/cubemars_hardware --output-on-failure
(cd web && npm ci && npm run lint && npm run build)
```

이 검증은 P0·P2의 빌드·설치·launch 해석·C++ 시험·웹 빌드 범위입니다. ROS 노드나 구동기를 실행하지 않습니다. **기존 전체 HRI/Nav2/매핑/브라우저 회귀 시험 복구(P1)와 실물 인수는 미완료**입니다. 과거의 통합 시험 통과 결과를 현재 소스의 검증 결과로 사용하지 않습니다.

[검증 기록과 CI](docs/dev/refactor-validation.md) · [지도 운용](maps/README.md) · [과거 운용 참고 자료](docs/user/legacy/real-robot.md)
