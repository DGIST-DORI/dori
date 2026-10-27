# DORI

DGIST 캠퍼스 안내 로봇의 HRI·실물 주행·웹 통합 저장소입니다. Ubuntu 22.04 / ROS 2 Humble / **Python 3.10**을 사용합니다.

**운용 기준 문서: [DORI 통합 로봇 정비·운용 매뉴얼](docs/user/DORI-AMM.md)**

`feature/control-and-navigation`의 실물 검증 주행 설정을 기준으로, 해당 브랜치에 이미 포함된 `main`의 HRI와 웹을 통합했습니다. 구동 튜닝·LiDAR 외부 파라미터는 유지하고, HRI와 웹이 하나의 주행 액션 및 목적지 저장소를 사용하도록 연결했습니다.

## 설치 및 실행

저장소 루트에서 실행합니다. ROS Humble apt 저장소와 Node.js 20.19+ 또는 22.12+가 필요합니다. `.venv`, ROS 빌드 결과는 대상 로봇에서 생성하세요.

```bash
scripts/install_dependencies.sh
(cd web && npm ci && npm run build)
scripts/build.sh
source scripts/env.sh
python3 scripts/deployment_check.py --voice
```

기존 `robot_*` 설치본에서 업데이트하면 `scripts/build.sh --clean`으로 이전 overlay를 보관하고 24개 `dori_*`/장치 패키지를 새로 빌드하세요. 메시지 타입도 `dori_msgs`로 통일했으므로 관련 노드를 함께 재시작해야 합니다. [패키지 변경표](docs/dev/package-ownership.md)와 AMM 20-15를 참고하세요.

실물 운용 전 매뉴얼의 AMM 05 및 72 인수 절차를 수행하세요. 다음 명령은 실제 하드웨어를 준비하고 구동 노드를 실행합니다.

```bash
scripts/start_robot.sh --map "$PWD/maps/live_navigation_20261023_1938.yaml"
```

- 통합 대시보드: `http://<로봇 IP>:3000`, ROS WebSocket: `ws://<로봇 IP>:9090`
- 실시간 지도/초기 위치/목적지/정지: 대시보드 Navigation 메뉴 또는 `http://<로봇 IP>:8080`
- 기존 사용자 주행·대화 화면: `http://<로봇 IP>:7070` (해당 화면의 Gemini 기능은 별도 키 필요)
- `--text-only`는 마이크 STT를 끄고 브라우저용 TTS 이벤트를 사용합니다. **실물 구동은 켜지므로 시뮬레이터 옵션이 아닙니다.**
- 카메라·사용자 추적·제스처·표정·랜드마크 옵션, 온라인 TTS 조건, 새 지도 작성, 고장 진단은 매뉴얼에 있습니다.

## 하드웨어 없는 검증

```bash
scripts/test.sh
scripts/validate_release.sh
# Firefox Marionette 준비 후 웹까지 포함:
# scripts/validate_release.sh --browser
```

시험은 전용 localhost ROS 도메인 94–97, 99를 사용합니다. 실제 Nav2, Cartographer, BT, LLM 규칙 엔진, TTS 이벤트, 웹 서버를 실행하고, 센서·차체·일부 장애 응답만 시험 장치로 대체합니다. [최초 통합 기록](docs/dev/evidence/integration-2026-10-27/README.md)과 [R3 명칭 변경 후 재검증 기록](docs/dev/evidence/namespace-migration-2026-10-27/README.md)을 참조하세요. 실제 CAN·모터·마이크·카메라 성능과 현장 정지 거리는 이 시험으로 입증되지 않습니다.

## 구성 자료

- [패키지 책임과 기준](docs/dev/package-ownership.md)
- [기존 실물 주행 설명](docs/user/legacy/real-robot.md)
- [기존 주행 구조](docs/dev/legacy/real-robot-architecture.md)
- [주행 응답 모델](docs/dev/legacy/real-robot-motion-interpreter.md)
- [지도 설명](maps/README.md)

과거 문서와 내용이 다르면 이번 통합본의 AMM을 적용합니다. 저장소의 지도와 예제 목적지는 특정 실측 장소용입니다.
