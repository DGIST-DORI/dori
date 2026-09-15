import json
import re
import shutil
import subprocess
from datetime import datetime, timezone

import psutil
import rclpy
from rclpy.node import Node
from std_msgs.msg import String


class SystemMonitorNode(Node):
    def __init__(self) -> None:
        super().__init__('system_monitor_node')

        self.declare_parameter('topics.metrics_pub', 'system/metrics')
        self.declare_parameter('interval_sec', 1.0)

        topic = self.get_parameter('topics.metrics_pub').get_parameter_value().string_value
        interval_sec = self.get_parameter('interval_sec').get_parameter_value().double_value

        self.publisher_ = self.create_publisher(String, topic, 10)
        self.timer = self.create_timer(interval_sec, self._on_timer)

        self._gpu_mode = self._detect_gpu_mode()
        self._last_cpu_sample = None
        self.get_logger().info(
            f'System monitor started. topic={topic} interval={interval_sec:.2f}s gpu_mode={self._gpu_mode}'
        )

    def _detect_gpu_mode(self) -> str:
        if shutil.which('tegrastats'):
            return 'tegrastats'
        if shutil.which('nvidia-smi'):
            return 'nvidia-smi'
        return 'none'

    def _safe_cmd(self, cmd: list[str]) -> str | None:
        try:
            out = subprocess.check_output(cmd, stderr=subprocess.STDOUT, timeout=1.0, text=True)
            return out.strip()
        except Exception:
            return None

    def _collect_gpu_metrics(self) -> dict:
        base = {
            'provider': self._gpu_mode,
            'utilization_pct': None,
            'memory_used_mb': None,
            'memory_total_mb': None,
            'temperature_c': None,
            'power_w': None,
        }

        if self._gpu_mode == 'nvidia-smi':
            out = self._safe_cmd([
                'nvidia-smi',
                '--query-gpu=utilization.gpu,memory.used,memory.total,temperature.gpu,power.draw',
                '--format=csv,noheader,nounits',
            ])
            if not out:
                return base
            first_line = out.splitlines()[0]
            parts = [p.strip() for p in first_line.split(',')]
            if len(parts) >= 5:
                base.update({
                    'utilization_pct': _to_float_or_none(parts[0]),
                    'memory_used_mb': _to_float_or_none(parts[1]),
                    'memory_total_mb': _to_float_or_none(parts[2]),
                    'temperature_c': _to_float_or_none(parts[3]),
                    'power_w': _to_float_or_none(parts[4]),
                })
            return base

        if self._gpu_mode == 'tegrastats':
            out = self._safe_cmd(['tegrastats', '--interval', '1000', '--count', '1'])
            if not out:
                return base
            line = out.splitlines()[-1]

            gr3d_match = re.search(r'GR3D_FREQ\s+(\d+)%', line)
            ram_match = re.search(r'RAM\s+(\d+)/(\d+)MB', line)
            temp_match = re.search(r'GPU@([\d.]+)C', line)

            base.update({
                'utilization_pct': _to_float_or_none(gr3d_match.group(1)) if gr3d_match else None,
                'memory_used_mb': _to_float_or_none(ram_match.group(1)) if ram_match else None,
                'memory_total_mb': _to_float_or_none(ram_match.group(2)) if ram_match else None,
                'temperature_c': _to_float_or_none(temp_match.group(1)) if temp_match else None,
            })
            return base

        return base

    def _collect_system_metrics(self) -> dict:
        cpu_pct = psutil.cpu_percent(interval=None)
        load_avg = None
        try:
            load_avg = [round(v, 2) for v in psutil.getloadavg()]
        except (AttributeError, OSError):
            load_avg = None

        vm = psutil.virtual_memory()
        disk = psutil.disk_usage('/')

        return {
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'cpu': {
                'usage_pct': round(cpu_pct, 2),
                'count_logical': psutil.cpu_count(logical=True),
                'count_physical': psutil.cpu_count(logical=False),
                'load_avg_1_5_15': load_avg,
            },
            'ram': {
                'usage_pct': round(vm.percent, 2),
                'used_mb': round(vm.used / (1024 * 1024), 2),
                'total_mb': round(vm.total / (1024 * 1024), 2),
                'available_mb': round(vm.available / (1024 * 1024), 2),
            },
            'disk': {
                'usage_pct': round(disk.percent, 2),
                'used_gb': round(disk.used / (1024 * 1024 * 1024), 2),
                'total_gb': round(disk.total / (1024 * 1024 * 1024), 2),
            },
            'gpu': self._collect_gpu_metrics(),
        }

    def _on_timer(self) -> None:
        metrics = self._collect_system_metrics()
        msg = String()
        msg.data = json.dumps(metrics, ensure_ascii=False)
        self.publisher_.publish(msg)


def _to_float_or_none(v: str | None) -> float | None:
    if v is None:
        return None
    try:
        return round(float(v), 2)
    except (TypeError, ValueError):
        return None


def main(args=None) -> None:
    rclpy.init(args=args)
    node = SystemMonitorNode()

    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
