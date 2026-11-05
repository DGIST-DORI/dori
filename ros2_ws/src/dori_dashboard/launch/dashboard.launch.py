"""
dashboard.launch.py
Launches: rosbridge WebSocket + unified dashboard server (frontend + API on port 3000)
          + loopback navigation viewer (port 8080, no hardware startup)
          + Cloudflare Tunnel (dashboard port 3000 only, optional)

Cloudflare Tunnel is disabled by default.
To enable: ros2 launch dori_dashboard dashboard.launch.py tunnel:=true
"""

import os
import shutil
from pathlib import Path

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, ExecuteProcess, OpaqueFunction, SetEnvironmentVariable
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def _resolve_repo_root(pkg_dir: str) -> str:
    """Resolve repository root from an installed dashboard package path."""
    start = Path(pkg_dir).resolve()
    for candidate in [start, *start.parents]:
        has_ros2_src = (candidate / "ros2_ws" / "src").is_dir()
        has_crawler = (candidate / "tools" / "crawler" / "crawl_campus.py").is_file()
        if has_ros2_src and has_crawler:
            return str(candidate)

    # Fallback: keep legacy relative behavior.
    return os.path.abspath(os.path.join(pkg_dir, "..", "..", "..", ".."))


def _make_tunnel_actions(context, *args, **kwargs):
    """
    OpaqueFunction: runs at launch time so we can check if cloudflared is
    installed and read the 'tunnel' LaunchConfiguration value.
    """
    enable = LaunchConfiguration("tunnel").perform(context).lower()
    if enable not in ("true", "1", "yes"):
        return []

    if shutil.which("cloudflared") is None:
        print(
            "\n[dashboard.launch] WARNING: tunnel:=true but cloudflared not found in PATH.\n"
            "  Install: https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/\n"
            "  Skipping tunnel.\n"
        )
        return []

    # Tunnel script: wraps cloudflared and prints the public URL clearly.
    # The dashboard tunnel writes its URL to stderr; tee it through a small
    # shell one-liner so it appears in the ROS launch console.
    dashboard_tunnel = ExecuteProcess(
        cmd=[
            "bash",
            "-c",
            # cloudflared prints the URL line like:
            #   INF +----------------------------+
            #   INF |  Your quick Tunnel has been created! Visit it at  |
            #   INF | https://xxxx.trycloudflare.com                    |
            # We grep for the https line and re-print it conspicuously.
            "cloudflared tunnel --url http://localhost:3000 2>&1 | "
            "tee /tmp/cloudflared_dashboard.log | "
            r'grep --line-buffered -oP "https://[a-z0-9\-]+\.trycloudflare\.com" | '
            "while read url; do "
            '  echo ""; '
            '  echo "╔══════════════════════════════════════════════════════╗"; '
            '  echo "║  DORI Dashboard (external)                          ║"; '
            '  echo "║  $url"; '
            '  echo "╚══════════════════════════════════════════════════════╝"; '
            '  echo ""; '
            "done",
        ],
        output="screen",
        name="cloudflared_dashboard",
    )

    return [dashboard_tunnel]


def _make_server_actions(context, *args, **kwargs):
    """OpaqueFunction: backend_api 를 환경변수와 함께 실행."""
    pkg_dir = get_package_share_directory("dori_dashboard")
    web_dir = os.path.join(pkg_dir, "web_current")
    if not os.path.isdir(web_dir):
        web_dir = os.path.join(pkg_dir, "web")
    repo_root = _resolve_repo_root(pkg_dir)

    internal_token = os.environ.get("DORI_INTERNAL_TOKEN")
    if not internal_token or len(internal_token.strip()) < 32:
        raise RuntimeError(
            "DORI_INTERNAL_TOKEN must contain at least 32 random characters."
        )

    dashboard_url = LaunchConfiguration("dashboard_url").perform(context)

    additional_env = {"DORI_INTERNAL_TOKEN": internal_token,
                      "DORI_WS": repo_root,
                      "DORI_VISITOR_WEB_DIR": os.path.join(pkg_dir, "visitor_web")}
    if dashboard_url:
        additional_env["DORI_DASHBOARD_URL"] = dashboard_url

    backend_api_script = os.path.join(pkg_dir, "scripts", "backend_api.py")
    bridge_api_script = os.path.join(pkg_dir, "scripts", "bridge_api.py")

    python = os.path.join(repo_root, ".venv", "bin", "python")
    if not os.path.isfile(python):
        python = "python3"
    return [
        ExecuteProcess(
            cmd=[
                python,
                backend_api_script,
                "--repo-root",
                repo_root,
                "--port",
                "3000",
                "--web-dir",
                web_dir,
            ],
            output="both",
            name="backend_api_server",
            emulate_tty=True,
            respawn=True,
            respawn_delay=2.0,
            additional_env=additional_env,
        ),
        ExecuteProcess(
            cmd=[python, bridge_api_script, "--ros-args", "-r", "__ns:=/dori",
                 "-r", "NAVIGATION_MODE:=/NAVIGATION_MODE",
                 "-r", "manual/cmd_vel:=/manual/cmd_vel",
                 "-r", "emergency_stop:=/emergency_stop",
                 "-r", "control_mode_cmd:=/control_mode_cmd",
                 "-r", "system/control_mode:=/system/control_mode",
                 "-r", "system/action_state:=/system/action_state"],
            output="both",
            name="bridge_api_server",
            emulate_tty=True,
            respawn=True,
            respawn_delay=2.0,
            additional_env=additional_env,
        ),
    ]


def _make_navigation_viewer_actions(context, *args, **kwargs):
    """Own the dashboard's map backend unless the parent launch supplies one."""
    enabled = LaunchConfiguration("enable_navigation_viewer").perform(context).lower()
    if enabled not in ("true", "1", "yes"):
        return []
    repo_root = _resolve_repo_root(get_package_share_directory("dori_dashboard"))
    return [
        Node(
            package="dori_navigation",
            executable="web_viewer.py",
            name="dori_web_viewer",
            arguments=[
                "--host", "127.0.0.1",
                "--port", "8080",
                "--user-port", "0",
                "--mode", "auto",
                "--goals-file", str(Path(repo_root) / "maps/web_goals.json"),
            ],
            output="screen",
            respawn=True,
            respawn_delay=2.0,
            additional_env={"DORI_WS": repo_root},
        ),
    ]


def generate_launch_description():
    pkg_dir = get_package_share_directory("dori_dashboard")
    web_dir = os.path.join(pkg_dir, "web_current")
    if not os.path.isdir(web_dir):
        web_dir = os.path.join(pkg_dir, "web")

    if not os.path.isdir(web_dir):
        raise FileNotFoundError(
            "dori_dashboard web assets not found. Expected directory: "
            f"'{web_dir}'. Build the frontend (web/dist), install dori_dashboard, and publish the "
            "completed static tree before launching the dashboard."
        )

    return LaunchDescription(
        [
            SetEnvironmentVariable("DORI_SESSION_ROOT", _resolve_repo_root(pkg_dir)),
            # ── Launch arguments ──────────────────────────────────────────────
            DeclareLaunchArgument(
                "tunnel",
                default_value="false",
                description="Enable Cloudflare Tunnel for external access (true/false). "
                "Disabled by default when using a fixed custom domain.",
            ),
            # 고정 도메인 설정 (Cloudflare 커스텀 도메인 사용 시)
            # Legacy dashboard URL argument; WS always uses the request origin.
            DeclareLaunchArgument(
                "dashboard_url",
                default_value="",
                description="Fixed public dashboard URL (custom Cloudflare domain)",
            ),
            DeclareLaunchArgument(
                "enable_navigation_viewer",
                default_value="true",
                description="Start the loopback map backend without hardware/Nav2. "
                "Set false when another launch already owns port 8080.",
            ),
            # ── rosbridge WebSocket (port 9090) ───────────────────────────────
            Node(
                package="rosbridge_server",
                executable="rosbridge_websocket",
                name="rosbridge_websocket",
                parameters=[{"port": 9090, "address": "127.0.0.1"}],
                namespace="/dori",
            ),
            Node(
                package="rosapi",
                executable="rosapi_node",
                name="rosapi",
                namespace="/dori",
            ),
            # ── Unified dashboard server (frontend + API on port 3000) ────────
            # DORI_DASHBOARD_URL 환경변수로 고정 도메인 주입
            # /api/tunnel-url returns the authenticated request origin.
            OpaqueFunction(function=_make_server_actions),
            OpaqueFunction(function=_make_navigation_viewer_actions),
            # ── Cloudflare Tunnel (optional, default: disabled) ────────────────
            OpaqueFunction(function=_make_tunnel_actions),
        ]
    )
