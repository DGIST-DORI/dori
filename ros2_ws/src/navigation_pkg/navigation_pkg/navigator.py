import math
import threading
import time
from enum import Enum
from queue import PriorityQueue
from typing import List, Optional, Tuple

import numpy as np
import rclpy
from geometry_msgs.msg import Point, PoseStamped, Twist
from nav_msgs.msg import OccupancyGrid, Odometry, Path
from dori_msgs.action import Navigate
from rclpy.action import ActionServer, CancelResponse, GoalResponse
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node
from sensor_msgs.msg import LaserScan


class NavigationState(Enum):
    IDLE = 0
    PLANNING = 1
    NAVIGATING = 2
    OBSTACLE_AVOIDANCE = 3
    GOAL_REACHED = 4
    FAILED = 5


class NavigatorNode(Node):
    def __init__(self):
        super().__init__('navigator_node')

        # Parameters
        self.declare_parameter('max_speed', 0.5)
        self.declare_parameter('max_angular_speed', 1.0)
        self.declare_parameter('goal_tolerance', 0.2)
        self.declare_parameter('obstacle_distance', 0.5)
        self.declare_parameter('control_frequency', 20.0)
        self.declare_parameter('actions.navigate', 'nav/navigate_to')

        self.max_speed = self.get_parameter('max_speed').value
        self.max_angular_speed = self.get_parameter('max_angular_speed').value
        self.goal_tolerance = self.get_parameter('goal_tolerance').value
        self.obstacle_distance = self.get_parameter('obstacle_distance').value
        self.control_freq = self.get_parameter('control_frequency').value

        # State
        self.state = NavigationState.IDLE
        self.current_pose: Optional[PoseStamped] = None
        self.current_goal: Optional[PoseStamped] = None
        self.global_path: Optional[Path] = None
        self.local_obstacles: List[Point] = []
        self.active_goal_handle = None

        self.state_lock = threading.Lock()

        # Map
        self.map: Optional[OccupancyGrid] = None
        self.map_resolution = 0.05
        self.map_origin = (0.0, 0.0)

        # Publishers
        self.cmd_vel_pub = self.create_publisher(Twist, 'cmd_vel', 10)
        self.global_path_pub = self.create_publisher(Path, 'nav/global_path', 10)
        self.local_path_pub = self.create_publisher(Path, 'nav/local_path', 10)

        # Subscribers
        self.odom_sub = self.create_subscription(
            Odometry,
            'odom',
            self.odom_callback,
            10,
        )

        self.scan_sub = self.create_subscription(
            LaserScan,
            'scan',
            self.scan_callback,
            10,
        )

        self.map_sub = self.create_subscription(
            OccupancyGrid,
            '/map',
            self.map_callback,
            10,
        )

        # Action Server
        cbg = ReentrantCallbackGroup()
        self.navigate_action_server = ActionServer(
            self,
            Navigate,
            self.get_parameter('actions.navigate').value,
            execute_callback=self.execute_navigate_callback,
            goal_callback=self.goal_request_callback,
            cancel_callback=self.cancel_request_callback,
            callback_group=cbg,
        )

        # Control timer
        self.control_timer = self.create_timer(
            1.0 / self.control_freq,
            self.control_loop,
            callback_group=cbg,
        )

        self.get_logger().info('Navigator node initialized with action server')

    def goal_request_callback(self, goal_request: Navigate.Goal):
        if goal_request.destination.header.frame_id == '':
            self.get_logger().warn('Rejected navigation goal: destination frame_id is empty')
            return GoalResponse.REJECT
        return GoalResponse.ACCEPT

    def cancel_request_callback(self, _goal_handle):
        self.get_logger().info('Navigation cancel requested')
        with self.state_lock:
            self._stop_robot()
            self.state = NavigationState.IDLE
            self.current_goal = None
        return CancelResponse.ACCEPT

    def execute_navigate_callback(self, goal_handle):
        destination = goal_handle.request.destination

        with self.state_lock:
            if self.active_goal_handle and self.active_goal_handle.is_active:
                self.get_logger().warn('Preempting previous navigation goal')
                self.active_goal_handle.abort()
                self._stop_robot()
            self.active_goal_handle = goal_handle
            self.current_goal = destination
            self.state = NavigationState.PLANNING

        self.get_logger().info(
            f'New navigation goal: ({destination.pose.position.x:.2f}, '
            f'{destination.pose.position.y:.2f})'
        )

        self._plan_global_path()

        result = Navigate.Result()
        try:
            while rclpy.ok():
                with self.state_lock:
                    is_current_goal = self.active_goal_handle is goal_handle
                    is_goal_active = goal_handle.is_active

                if not is_current_goal or not is_goal_active:
                    self.get_logger().info(
                        'Ending execute loop for goal due to preemption/state change: '
                        f'is_current_goal={is_current_goal}, is_goal_active={is_goal_active}'
                    )
                    result.code = Navigate.Result.INVALID_STATE
                    result.message = 'Preempted by newer goal'
                    return result

                if goal_handle.is_cancel_requested:
                    self.get_logger().info('Navigation canceled by client')
                    with self.state_lock:
                        self._stop_robot()
                        self.state = NavigationState.IDLE
                        self.current_goal = None
                    if not goal_handle.is_active:
                        result.code = Navigate.Result.INVALID_STATE
                        result.message = 'Goal became inactive before cancel transition'
                        return result
                    goal_handle.canceled()
                    result.code = Navigate.Result.CANCELED
                    result.message = 'Navigation canceled'
                    return result

                with self.state_lock:
                    state = self.state
                    distance = self._distance_to_goal()

                feedback = Navigate.Feedback()
                feedback.distance_remaining = float(distance)
                feedback.state = state.name
                feedback.status_message = self._state_to_status(state)
                goal_handle.publish_feedback(feedback)

                if state == NavigationState.GOAL_REACHED:
                    with self.state_lock:
                        self._stop_robot()
                        self.state = NavigationState.IDLE
                        self.current_goal = None
                    if not goal_handle.is_active:
                        result.code = Navigate.Result.INVALID_STATE
                        result.message = 'Goal became inactive before succeed transition'
                        return result
                    goal_handle.succeed()
                    result.code = Navigate.Result.SUCCESS
                    result.message = 'Goal reached'
                    return result

                if state == NavigationState.FAILED:
                    with self.state_lock:
                        self._stop_robot()
                        self.state = NavigationState.IDLE
                        self.current_goal = None
                    if not goal_handle.is_active:
                        result.code = Navigate.Result.INVALID_STATE
                        result.message = 'Goal became inactive before abort transition'
                        return result
                    goal_handle.abort()
                    result.code = Navigate.Result.PLANNING_FAILED
                    result.message = 'Navigation failed'
                    return result

                time.sleep(0.2)

            result.code = Navigate.Result.INVALID_STATE
            result.message = 'Navigation interrupted by shutdown'
            return result
        finally:
            with self.state_lock:
                if self.active_goal_handle is goal_handle:
                    self.active_goal_handle = None

    def odom_callback(self, msg: Odometry):
        pose = PoseStamped()
        pose.header = msg.header
        pose.pose = msg.pose.pose
        self.current_pose = pose

    def scan_callback(self, msg: LaserScan):
        obstacles = []

        for i, distance in enumerate(msg.ranges):
            if distance < self.obstacle_distance and distance > msg.range_min:
                angle = msg.angle_min + i * msg.angle_increment
                point = Point()
                point.x = distance * math.cos(angle)
                point.y = distance * math.sin(angle)
                point.z = 0.0
                obstacles.append(point)

        self.local_obstacles = obstacles

    def map_callback(self, msg: OccupancyGrid):
        self.map = msg
        self.map_resolution = msg.info.resolution
        self.map_origin = (msg.info.origin.position.x, msg.info.origin.position.y)

    def control_loop(self):
        with self.state_lock:
            if self.state in (NavigationState.IDLE, NavigationState.PLANNING):
                return

            if self.state == NavigationState.NAVIGATING:
                self._navigate_to_goal()
            elif self.state == NavigationState.OBSTACLE_AVOIDANCE:
                self._avoid_obstacles()
            elif self.state == NavigationState.GOAL_REACHED:
                self._stop_robot()
            elif self.state == NavigationState.FAILED:
                self._stop_robot()

    def _plan_global_path(self):
        if not self.current_pose or not self.current_goal:
            self.state = NavigationState.FAILED
            return

        if not self.map:
            self.get_logger().warn('No map available, using direct path')
            self._create_direct_path()
            self.state = NavigationState.NAVIGATING
            return

        try:
            path = self._astar_planning(
                (self.current_pose.pose.position.x, self.current_pose.pose.position.y),
                (self.current_goal.pose.position.x, self.current_goal.pose.position.y),
            )

            if path:
                self.global_path = self._create_path_msg(path)
                self.global_path_pub.publish(self.global_path)
                self.state = NavigationState.NAVIGATING
            else:
                self.get_logger().error('Failed to find path')
                self.state = NavigationState.FAILED

        except Exception as e:
            self.get_logger().error(f'Path planning error: {e}')
            self.state = NavigationState.FAILED

    def _astar_planning(
        self,
        start: Tuple[float, float],
        goal: Tuple[float, float],
    ) -> Optional[List[Tuple[float, float]]]:
        if not self.map:
            return None

        start_grid = self._world_to_grid(start)
        goal_grid = self._world_to_grid(goal)

        if not self._is_valid_cell(start_grid) or not self._is_valid_cell(goal_grid):
            self.get_logger().error('Invalid start or goal position')
            return None

        open_set = PriorityQueue()
        open_set.put((0, start_grid))

        came_from = {}
        g_score = {start_grid: 0}
        f_score = {start_grid: self._heuristic(start_grid, goal_grid)}

        while not open_set.empty():
            current = open_set.get()[1]

            if current == goal_grid:
                path = []
                while current in came_from:
                    path.append(self._grid_to_world(current))
                    current = came_from[current]
                path.append(start)
                path.reverse()
                return path

            for dx, dy in [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]:
                neighbor = (current[0] + dx, current[1] + dy)

                if not self._is_valid_cell(neighbor) or self._is_occupied(neighbor):
                    continue

                tentative_g = g_score[current] + math.sqrt(dx**2 + dy**2)

                if neighbor not in g_score or tentative_g < g_score[neighbor]:
                    came_from[neighbor] = current
                    g_score[neighbor] = tentative_g
                    f_score[neighbor] = tentative_g + self._heuristic(neighbor, goal_grid)
                    open_set.put((f_score[neighbor], neighbor))

        return None

    def _navigate_to_goal(self):
        if not self.current_pose or not self.current_goal:
            return

        if self._detect_obstacle_ahead():
            self.state = NavigationState.OBSTACLE_AVOIDANCE
            return

        distance = self._distance_to_goal()
        if distance < self.goal_tolerance:
            self.state = NavigationState.GOAL_REACHED
            return

        dx = self.current_goal.pose.position.x - self.current_pose.pose.position.x
        dy = self.current_goal.pose.position.y - self.current_pose.pose.position.y

        desired_heading = math.atan2(dy, dx)
        current_heading = self._get_yaw_from_quaternion(self.current_pose.pose.orientation)
        heading_error = self._normalize_angle(desired_heading - current_heading)

        cmd = Twist()
        cmd.angular.z = float(np.clip(2.0 * heading_error, -self.max_angular_speed, self.max_angular_speed))

        if abs(heading_error) < math.pi / 4:
            cmd.linear.x = float(np.clip(0.5 * distance, 0.0, self.max_speed))
        else:
            cmd.linear.x = 0.1

        self.cmd_vel_pub.publish(cmd)

    def _avoid_obstacles(self):
        if not self.local_obstacles:
            self.state = NavigationState.NAVIGATING
            return

        repulsive_x = 0.0
        repulsive_y = 0.0

        for obs in self.local_obstacles:
            dist = math.sqrt(obs.x**2 + obs.y**2)
            if dist > 0.01:
                repulsive_x -= obs.x / (dist**2)
                repulsive_y -= obs.y / (dist**2)

        if self.current_pose and self.current_goal:
            dx = self.current_goal.pose.position.x - self.current_pose.pose.position.x
            dy = self.current_goal.pose.position.y - self.current_pose.pose.position.y
            dist_to_goal = math.sqrt(dx**2 + dy**2)
            if dist_to_goal > 0.01:
                attractive_x = dx / dist_to_goal
                attractive_y = dy / dist_to_goal
            else:
                attractive_x = 0.0
                attractive_y = 0.0
        else:
            attractive_x = 0.0
            attractive_y = 0.0

        total_x = attractive_x + 2.0 * repulsive_x
        total_y = attractive_y + 2.0 * repulsive_y

        cmd = Twist()
        desired_heading = math.atan2(total_y, total_x)
        current_heading = self._get_yaw_from_quaternion(self.current_pose.pose.orientation)
        heading_error = self._normalize_angle(desired_heading - current_heading)

        cmd.angular.z = float(np.clip(2.0 * heading_error, -self.max_angular_speed, self.max_angular_speed))
        cmd.linear.x = 0.2

        self.cmd_vel_pub.publish(cmd)

        if not self._detect_obstacle_ahead():
            self.state = NavigationState.NAVIGATING

    def _detect_obstacle_ahead(self) -> bool:
        for obs in self.local_obstacles:
            angle = math.atan2(obs.y, obs.x)
            if abs(angle) < math.pi / 6 and obs.x < self.obstacle_distance:
                return True
        return False

    def _create_direct_path(self):
        if not self.current_pose or not self.current_goal:
            return

        path = Path()
        path.header.frame_id = 'map'
        path.header.stamp = self.get_clock().now().to_msg()
        path.poses.append(self.current_pose)
        path.poses.append(self.current_goal)

        self.global_path = path
        self.global_path_pub.publish(path)

    def _create_path_msg(self, waypoints: List[Tuple[float, float]]) -> Path:
        path = Path()
        path.header.frame_id = 'map'
        path.header.stamp = self.get_clock().now().to_msg()

        for x, y in waypoints:
            pose = PoseStamped()
            pose.header = path.header
            pose.pose.position.x = x
            pose.pose.position.y = y
            pose.pose.position.z = 0.0
            pose.pose.orientation.w = 1.0
            path.poses.append(pose)

        return path

    def _distance_to_goal(self) -> float:
        if not self.current_pose or not self.current_goal:
            return float('inf')

        dx = self.current_goal.pose.position.x - self.current_pose.pose.position.x
        dy = self.current_goal.pose.position.y - self.current_pose.pose.position.y
        return math.sqrt(dx**2 + dy**2)

    def _state_to_status(self, state: NavigationState) -> str:
        mapping = {
            NavigationState.IDLE: 'Idle',
            NavigationState.PLANNING: 'Planning path',
            NavigationState.NAVIGATING: 'Navigating to goal',
            NavigationState.OBSTACLE_AVOIDANCE: 'Avoiding obstacle',
            NavigationState.GOAL_REACHED: 'Goal reached',
            NavigationState.FAILED: 'Navigation failed',
        }
        return mapping.get(state, 'Unknown state')

    def _stop_robot(self):
        self.cmd_vel_pub.publish(Twist())

    def _world_to_grid(self, pos: Tuple[float, float]) -> Tuple[int, int]:
        x = int((pos[0] - self.map_origin[0]) / self.map_resolution)
        y = int((pos[1] - self.map_origin[1]) / self.map_resolution)
        return (x, y)

    def _grid_to_world(self, grid: Tuple[int, int]) -> Tuple[float, float]:
        x = grid[0] * self.map_resolution + self.map_origin[0]
        y = grid[1] * self.map_resolution + self.map_origin[1]
        return (x, y)

    def _is_valid_cell(self, cell: Tuple[int, int]) -> bool:
        if not self.map:
            return False
        return 0 <= cell[0] < self.map.info.width and 0 <= cell[1] < self.map.info.height

    def _is_occupied(self, cell: Tuple[int, int]) -> bool:
        if not self.map:
            return False

        idx = cell[1] * self.map.info.width + cell[0]
        if 0 <= idx < len(self.map.data):
            return self.map.data[idx] > 50
        return True

    def _heuristic(self, a: Tuple[int, int], b: Tuple[int, int]) -> float:
        return math.sqrt((a[0] - b[0])**2 + (a[1] - b[1])**2)

    def _get_yaw_from_quaternion(self, q) -> float:
        siny_cosp = 2 * (q.w * q.z + q.x * q.y)
        cosy_cosp = 1 - 2 * (q.y * q.y + q.z * q.z)
        return math.atan2(siny_cosp, cosy_cosp)

    def _normalize_angle(self, angle: float) -> float:
        while angle > math.pi:
            angle -= 2 * math.pi
        while angle < -math.pi:
            angle += 2 * math.pi
        return angle


def main():
    rclpy.init()
    node = NavigatorNode()

    executor = MultiThreadedExecutor()
    executor.add_node(node)

    try:
        executor.spin()
    except KeyboardInterrupt:
        node.get_logger().info('Shutting down...')
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
