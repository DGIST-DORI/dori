# DORI 주행·TTA 재감사 — 2026-10-27

**작업 번호:** AMM 30-20 / 72-10, **개정:** R2. 기준은 최초 통합 `3fd41c6`이며, 적용 소스의 정확한 내용은 [SHA-256 목록](source-sha256.txt)으로 식별한다. [정비·운용 매뉴얼](../../../user/DORI-AMM.md)의 R2 작업 카드를 함께 적용한다.

## 판정

기본 실물 launch의 AUTO 경로는 SI 속도를 조이스틱 기준 실측 역모델·PI·TTA에 통과시킨다. `cmd_vel`이라는 메시지 이름 자체가 우회를 의미하지 않는다. `/nav/cmd_vel`은 m/s·rad/s, `/auto/cmd_vel` 및 `/drive/cmd_vel`은 정규화 입력이다. 실제 ROS 프로세스에서 발행자·수신자 및 로드된 파라미터를 조회해 이 연결을 확인했다.

`0.3 m/s` 요구의 초기 역모델은 `0.22 + 0.3/0.62 = 0.704`이며, 새 폐루프 시험의 실제 출력은 `0.7053`, 합성 지면 속도는 `0.3007 m/s`였다. 단순 `0.3/1.72 = 0.174` 환산은 이 모델의 시동 입력보다 작다. AUTO 해석기는 그 환산만으로 하위 제어기에 명령하지 않는다.

## 발견 사항과 수정

| 발견 사항 | 수정 및 증거 |
|---|---|
| 웹의 일반 토픽 발행 패널에 연결되지 않은 `/cmd_vel` 선택지가 남음 | 항목 제거. 실제 Firefox에서 주행 토픽 선택지 부재와 HRI 입력 보존 확인 |
| bridge는 속도 스케일 2개만 대조하고 바퀴 반경/간격은 미대조 | 4개 기구학 값 대조. 잘못된 간격으로 C++ drive를 재시작하면 `hardware_scale_unverified` 및 모터 목표 0 |
| 실행 중 파라미터 변경을 ROS는 수락하지만 제어기 멤버 값은 그대로임 | drive 기구학은 read-only, bridge는 기동 시 설정만 허용. 실제 SetParameters 호출 거절 확인 |
| CAN 나이와 ROS 전달 시간을 따로 검사해 합계가 한도를 넘을 수 있음 | bridge와 C++ drive가 합계 0.2초 적용. CAN 0.12초 + 전달 0.12초 주입으로 출력 차단 |
| NaN encoder 또는 odom twist가 기존 추정/다른 축 출력을 남길 가능성 | position/velocity와 pose/twist 유한성 확인, 잘못된 encoder 이력 초기화, 주행 차단 |
| 제한기 후 입력을 수신 시간만으로 신선하다고 판단 | header 시각 사용. 오래된·미래·NaN applied 샘플은 최근 입력과 TTA 학습 이력을 폐기 |
| 구형 virtual VLM 키보드는 정규화 AUTO를 직접 발행하는 별도 시험 도구 | 통합 하드웨어 include에서 `use_input_nodes=false` 명시. preflight는 AUTO 소유자와 중복 발행 검출 |
| 종료 중 ROS context가 사라지는 경합에서 bridge traceback 가능 | context 종료 예외만 처리. 운용 중 발생한 RCLError는 숨기지 않음 |

실측 파일 5개는 원래 feature 기준과 바이트 단위로 동일하다. [calibration.json](calibration.json). 보정 gain, 시동 입력, 속도/가감속 튜닝, 기구 상수를 다시 튜닝하지 않았다.

## 수행 시험

| 항목 | 결과 / 원시 기록 |
|---|---|
| 전체 ROS 빌드 | 28개 패키지 성공 — [build.txt](build.txt) |
| Python/ROS 액션·BT | 120개 회귀 항목 및 CTest 3/3 — [tests.txt](tests.txt); 종료 처리 변경 후 관련 회귀 및 launch 인자 상속 검사 20개 추가 확인 — [targeted-tests.txt](targeted-tests.txt) |
| 웹 | ESLint, Vite 7.3.1 build 성공, Node 2/2 — [web-tests.txt](web-tests.txt) |
| 실제 TTA bridge → supervisor → C++ drive | 직진·곡선·온라인 gain 적응·오류 차단·수동 전환·기구학 불일치 — [drive-chain.json](drive-chain.json) |
| HRI → 실제 Nav2 → 실측 응답 모델 | QA 무이동, GUIDING → ARRIVED → IDLE, 도착 발화, 웹 stop/lease — [hri-nav2-calibrated.json](hri-nav2-calibrated.json) |
| 상대 전진 1 m | 실제 public goal/중계/Nav2/drive, 고정 언어 intent — [relative-1m.json](relative-1m.json) |
| 후진 복구 / 후방 장애물 | 실제 BackUp 실행 및 후방 차단 — [reverse-recovery.json](reverse-recovery.json), [blocked-rear.json](blocked-rear.json) |
| 재시도 / 목표 방향 / 모터 동특성 / 웹 목표 | [retry.json](retry.json), [heading-test.json](heading-test.json), [motor-dynamics.json](motor-dynamics.json), [web-goal.json](web-goal.json) |
| 정지 상태 자동 위치 정렬 | [auto-alignment-test.json](auto-alignment-test.json) |
| 실제 Firefox + HTTP + rosbridge | 지도, 프록시, CSRF/origin, 배포 잠금, TTS, 재연결, 구형 주행 발행 선택지 제거 — [dashboard-browser.json](dashboard-browser.json) |

drive-chain 시험에서 `v=0.3, w=0.4` 요구는 `v=0.3000, w=0.4021`로 수렴했으며 두 바퀴가 같은 방향으로 굴렀다. 합성 지면 gain을 0.62에서 0.52로 바꾸자 TTA 추정은 약 0.5200, 조이스틱 입력은 약 0.8004, 속도는 0.3019 m/s가 됐다. encoder는 ground와 다르게 선형 1.94배, 각 2.17배를 사용해 두 계측을 혼동하지 않는지 검사했다.

odom·encoder·지연 오류는 약 0.19–0.21초 안에 출력 0과 **추가 0.15초 정지 유지까지** 확인했다. 이 숫자는 실제 기구의 정지 시간이 아니다. 권한 heartbeat 중단은 약 0.54초 후 모터 목표 0을 확인했다. 수동 전환 뒤 정규화 입력 0.25가 그대로 drive까지 전달되는 것도 확인했다.

새 검사 개발 중 telemetry 필드명을 잘못 참조한 시험, Nav2 lifecycle 준비 전 너무 이른 graph 검사, Humble behavior plugin별 복수 publisher를 오류로 본 검사, ros2 run 부모에만 종료 신호를 보낸 시험 runner를 수정했다. 합격 기준을 제거하지 않고 실제 상태 필드·활성화 순서·노드 소유권·프로세스 그룹 종료에 맞췄다.

## 재현과 범위

```bash
source scripts/env.sh
ROS_DOMAIN_ID=99 ROS_LOCALHOST_ONLY=1 OPENBLAS_NUM_THREADS=1 \
  python3 tests/control_and_nav/integration_drive_chain.py
scripts/validate_release.sh --browser
```

브라우저는 AMM 72-10의 Firefox 준비가 필요하다. 전체 반복 실행기는 새 drive-chain 시험과 실측 응답 HRI 시험을 포함한다. 이번 환경의 rosbridge/rosapi는 최초 시험과 동일하게 공식 apt 패키지를 임시 경로에 풀어 사용했고, 로봇 설치 스크립트에는 그 경로가 없다.

이 시험은 **실제 ROS 소프트웨어 + 합성 센서/차체**다. CAN, 실물 모터, 바닥 마찰, 하중, LiDAR 장착, 실제 음성 인식·스피커·카메라는 이번에 시험하지 않았다. 시뮬레이션 domain 94–99 외의 로봇에는 명령을 보내지 않았다. 실제 장치가 필요한 전체 hardware preflight 합격이나 실물 주행 무결성을 주장하지 않는다. AMM 72-20 현장 인수 카드를 수행해야 한다. 변경하지 않은 매핑·음성 모델의 이전 실측 소프트웨어 기록은 [최초 통합 기록](../integration-2026-10-27/README.md)에 보존했다.
