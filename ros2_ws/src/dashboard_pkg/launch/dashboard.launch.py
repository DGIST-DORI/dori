"""
dashboard.launch.py
Launches: rosbridge WebSocket + unified dashboard server (frontend + API on port 3000)
          + Cloudflare Tunnel (port 3000 always, 9090 optional)

Cloudflare Tunnel is disabled by default.
To enable dashboard tunnel only:
  ros2 launch dashboard_pkg dashboard.launch.py tunnel:=true
To additionally expose rosbridge (high risk; internal use only):
  ros2 launch dashboard_pkg dashboard.launch.py tunnel:=true tunnel_rosbridge:=true
"""

import os
import shutil
from pathlib import Path

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, ExecuteProcess, OpaqueFunction
from launch.conditions import IfCondition
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def _resolve_repo_root(pkg_dir: str) -> str:
    """Resolve repository root from an installed dashboard package path."""
    start = Path(pkg_dir).resolve()
    for candidate in [start, *start.parents]:
        has_ros2_src = (candidate / 'ros2_ws' / 'src').is_dir()
        has_crawler = (candidate / 'tools' / 'crawler' / 'crawl_campus.py').is_file()
        if has_ros2_src and has_crawler:
            return str(candidate)

    # Fallback: keep legacy relative behavior.
    return os.path.abspath(os.path.join(pkg_dir, '..', '..', '..', '..'))


def _make_tunnel_actions(context, *args, **kwargs):
    """
    OpaqueFunction: runs at launch time so we can check if cloudflared is
    installed and read the 'tunnel' LaunchConfiguration value.
    """
    enable = LaunchConfiguration('tunnel').perform(context).lower()
    if enable not in ('true', '1', 'yes'):
        return []

    if shutil.which('cloudflared') is None:
        print(
            '\n[dashboard.launch] WARNING: tunnel:=true but cloudflared not found in PATH.\n'
            '  Install: https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/\n'
            '  Skipping tunnel.\n'
        )
        return []

    # Tunnel script: wraps cloudflared and prints the public URL clearly.
    # Both tunnels write their URL to stderr; we tee it through a small
    # shell one-liner so it appears in the ROS launch console.
    dashboard_tunnel = ExecuteProcess(
        cmd=[
            'bash', '-c',
            # cloudflared prints the URL line like:
            #   INF +----------------------------+
            #   INF |  Your quick Tunnel has been created! Visit it at  |
            #   INF | https://xxxx.trycloudflare.com                    |
            # We grep for the https line and re-print it conspicuously.
            'cloudflared tunnel --url http://localhost:3000 2>&1 | '
            'tee /tmp/cloudflared_dashboard.log | '
            r'grep --line-buffered -oP "https://[a-z0-9\-]+\.trycloudflare\.com" | '
            'while read url; do '
            '  echo ""; '
            '  echo "╔══════════════════════════════════════════════════════╗"; '
            '  echo "║  DORI Dashboard (external)                          ║"; '
            '  echo "║  $url"; '
            '  echo "╚══════════════════════════════════════════════════════╝"; '
            '  echo ""; '
            'done',
        ],
        output='screen',
        name='cloudflared_dashboard',
    )

    expose_rosbridge = LaunchConfiguration('tunnel_rosbridge').perform(context).lower() in ('true', '1', 'yes')
    if not expose_rosbridge:
        print(
            '\n[dashboard.launch] INFO: rosbridge(9090) tunnel exposure is disabled by default.\n'
            '  External users should use the backend control API instead of direct rosbridge access.\n'
            '  To force-enable rosbridge tunnel, set tunnel_rosbridge:=true explicitly.\n'
        )
        return [dashboard_tunnel]

    ws_tunnel = ExecuteProcess(
        cmd=[
            'bash', '-c',
            'cloudflared tunnel --url http://localhost:9090 2>&1 | '
            'tee /tmp/cloudflared_ws.log | '
            r'grep --line-buffered -oP "https://[a-z0-9\-]+\.trycloudflare\.com" | '
            'while read url; do '
            '  echo ""; '
            '  echo "╔══════════════════════════════════════════════════════╗"; '
            '  echo "║  DORI ROS WebSocket (external)                      ║"; '
            '  echo "║  Replace ws:// → wss:// when pasting into dashboard ║"; '
            '  echo "║  $url"; '
            '  echo "╚══════════════════════════════════════════════════════╝"; '
            '  echo ""; '
            'done',
        ],
        output='screen',
        name='cloudflared_ws',
    )

    return [dashboard_tunnel, ws_tunnel]
    
    
def _make_api_server_action(context, *args, **kwargs):
    """OpaqueFunction: knowledge_api 를 환경변수와 함께 실행."""
    pkg_dir   = get_package_share_directory('dashboard_pkg')
    web_dir   = os.path.join(pkg_dir, 'web_current')
    if not os.path.isdir(web_dir):
        web_dir = os.path.join(pkg_dir, 'web')
    repo_root = _resolve_repo_root(pkg_dir)
    knowledge_api_script = os.path.join(pkg_dir, 'scripts', 'knowledge_api.py')

    dashboard_url = LaunchConfiguration('dashboard_url').perform(context)
    ws_url        = LaunchConfiguration('ws_url').perform(context)
    tunnel_rosbridge = LaunchConfiguration('tunnel_rosbridge').perform(context).lower() in ('true', '1', 'yes')

    additional_env = {}
    if dashboard_url:
        additional_env['DORI_DASHBOARD_URL'] = dashboard_url
    if ws_url:
        additional_env['DORI_WS_URL'] = ws_url
    additional_env['DORI_EXPOSE_ROSBRIDGE_TUNNEL'] = 'true' if tunnel_rosbridge else 'false'

    return [ExecuteProcess(
        cmd=['python3', knowledge_api_script,
             '--repo-root', repo_root,
             '--port', '3000',
             '--web-dir', web_dir],
        output='both',
        name='knowledge_api_server',
        emulate_tty=True,
        respawn=True,
        respawn_delay=2.0,
        additional_env=additional_env,
    )]


def generate_launch_description():
    pkg_dir = get_package_share_directory('dashboard_pkg')
    web_dir = os.path.join(pkg_dir, 'web_current')
    if not os.path.isdir(web_dir):
        web_dir = os.path.join(pkg_dir, 'web')

    if not os.path.isdir(web_dir):
        raise FileNotFoundError(
            'dashboard_pkg web assets not found. Expected directory: '
            f"'{web_dir}'. Build the frontend (web/dist), install dashboard_pkg, and publish the "
            'completed static tree before launching the dashboard.'
        )

    repo_root = _resolve_repo_root(pkg_dir)
    knowledge_api_script = os.path.join(pkg_dir, 'scripts', 'knowledge_api.py')

    return LaunchDescription([

        # ── Launch arguments ──────────────────────────────────────────────
        DeclareLaunchArgument(
            'tunnel',
            default_value='false',
            description='Enable Cloudflare Tunnel for external access (true/false). '
                        'Disabled by default.',
        ),
        DeclareLaunchArgument(
            'tunnel_rosbridge',
            default_value='false',
            description='Expose rosbridge websocket tunnel on 9090 (high risk, disabled by default).',
        ),
        # 고정 도메인 설정 (Cloudflare 커스텀 도메인 사용 시)
        # 기본값을 비워두면 trycloudflare.com 임시 터널 로그 파싱으로 fallback
        DeclareLaunchArgument(
            'dashboard_url',
            default_value='https://dash.dgist-dori.xyz',
            description='Fixed public dashboard URL (custom Cloudflare domain)',
        ),
        DeclareLaunchArgument(
            'ws_url',
            default_value='',
            description='Optional fixed public WebSocket URL (leave empty to avoid external rosbridge exposure)',
        ),

        # ── rosbridge WebSocket (port 9090) ───────────────────────────────
        Node(
            package='rosbridge_server',
            executable='rosbridge_websocket',
            name='rosbridge_websocket',
            parameters=[{'port': 9090}],
        ),

        # ── Unified dashboard server (frontend + API on port 3000) ────────
        # DORI_DASHBOARD_URL / DORI_WS_URL 환경변수로 고정 도메인 주입
        # knowledge_api 의 /api/tunnel-url 이 이 값을 1순위로 반환
        OpaqueFunction(function=_make_api_server_action),

        # ── Cloudflare Tunnel (optional, default: enabled) ────────────────
        OpaqueFunction(function=_make_tunnel_actions),
    ])
