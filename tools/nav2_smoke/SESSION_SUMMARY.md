# 세션 정리

- 대상 센서는 실물 SLAMTEC C1이며 Isaac Sim은 실행하지 않는다.
- `map_preview.png`와 완전히 같은 `map_1782733848.pgm`을 찾아 패키지에 포함했다.
- 저장 맵은 1505×828, 0.05 m/cell, origin `[-48.5, -4.43, 0]`이다.
- Jetson에서 C1 `/scan`, map_server, AMCL, Nav2 전체를 함께 띄운다.
- 로봇이 없으므로 workload 노드가 `/odom`과 TF를 제공하고 NavigateToPose를 반복한다.
- `/cmd_vel` subscriber나 모터 드라이버는 실행하지 않는다.
- 측정은 `htop`, 전력·온도는 `tegrastats`/`jtop`으로 직접 관찰한다.
- 메모리는 실주행과 상당히 유사하고 CPU는 1차 범위 파악용이다. 정확한 무로봇 재현은 실제 주행 rosbag 재생이 필요하다.
