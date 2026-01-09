import rclpy
from rclpy.node import Node
from rclpy.action import ActionServer, CancelResponse, GoalResponse
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.executors import MultiThreadedExecutor

from geometry_msgs.msg import PoseStamped, Twist, Point
from nav_msgs.msg import Odometry, Path, OccupancyGrid
from sensor_msgs.msg import LaserScan
from std_msgs.msg import Bool, String
from action_msgs.msg import GoalStatus

import numpy as np
import math
import time
from enum import Enum
from typing import Optional, Tuple, List
import threading


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
        
        self.state_lock = threading.Lock()
        
        # Map
        self.map: Optional[OccupancyGrid] = None
        self.map_resolution = 0.05
        self.map_origin = (0.0, 0.0)
        
        # Publishers
        self.cmd_vel_pub = self.create_publisher(Twist, '/cmd_vel', 10)
        self.global_path_pub = self.create_publisher(Path, '/navigation/global_path', 10)
        self.local_path_pub = self.create_publisher(Path, '/navigation/local_path', 10)
        self.status_pub = self.create_publisher(String, '/navigation/status', 10)
        
        # Subscribers
        self.goal_sub = self.create_subscription(
            PoseStamped,
            '/navigation/destination',
            self.goal_callback,
            10
        )
        
        self.odom_sub = self.create_subscription(
            Odometry,
            '/odom',
            self.odom_callback,
            10
        )
        
        self.scan_sub = self.create_subscription(
            LaserScan,
            '/scan',
            self.scan_callback,
            10
        )
        
        self.map_sub = self.create_subscription(
            OccupancyGrid,
            '/map',
            self.map_callback,
            10
        )
        
        self.cancel_sub = self.create_subscription(
            Bool,
            '/navigation/cancel',
            self.cancel_callback,
            10
        )
        
        # Control timer
        self.control_timer = self.create_timer(
            1.0 / self.control_freq,
            self.control_loop
        )
        
        self.get_logger().info("Navigator node initialized")
    
    def goal_callback(self, msg: PoseStamped): # New goal received from LLM
        with self.state_lock:
            if self.state == NavigationState.NAVIGATING:
                self.get_logger().warn("Already navigating, canceling current goal")
                self._stop_robot()
            
            self.current_goal = msg
            self.state = NavigationState.PLANNING
            
            self.get_logger().info(
                f"New goal: ({msg.pose.position.x:.2f}, {msg.pose.position.y:.2f})"
            )
            
            # Publish status
            self.status_pub.publish(String(data="Planning path..."))
            
            # Start planning
            self._plan_global_path()
    
    def odom_callback(self, msg: Odometry): # Update current pose from odometry
        pose = PoseStamped()
        pose.header = msg.header
        pose.pose = msg.pose.pose
        self.current_pose = pose
    
    def scan_callback(self, msg: LaserScan): # Process laser scan for obstacle detection
        obstacles = []
        
        for i, distance in enumerate(msg.ranges):
            if distance < self.obstacle_distance and distance > msg.range_min:
                angle = msg.angle_min + i * msg.angle_increment
                
                # Convert to Cartesian coordinates (robot frame)
                x = distance * math.cos(angle)
                y = distance * math.sin(angle)
                
                point = Point()
                point.x = x
                point.y = y
                point.z = 0.0
                obstacles.append(point)
        
        self.local_obstacles = obstacles
    
    def map_callback(self, msg: OccupancyGrid): # Receive map from SLAM
        self.map = msg
        self.map_resolution = msg.info.resolution
        self.map_origin = (msg.info.origin.position.x, msg.info.origin.position.y)
        
        self.get_logger().info(
            f"Map received: {msg.info.width}x{msg.info.height}, res={self.map_resolution}"
        )
    
    def cancel_callback(self, msg: Bool): # Cancel current navigation
        if msg.data:
            with self.state_lock:
                self.get_logger().info("Navigation canceled")
                self._stop_robot()
                self.state = NavigationState.IDLE
                self.current_goal = None
                self.status_pub.publish(String(data="Navigation canceled"))
    
    def control_loop(self): # Main control loop
        with self.state_lock:
            if self.state == NavigationState.IDLE:
                return
            
            if self.state == NavigationState.PLANNING:
                # Path planning is done in goal_callback
                return
            
            if self.state == NavigationState.NAVIGATING:
                self._navigate_to_goal()
            
            elif self.state == NavigationState.OBSTACLE_AVOIDANCE:
                self._avoid_obstacles()
            
            elif self.state == NavigationState.GOAL_REACHED:
                self._stop_robot()
                self.get_logger().info("Goal reached!")
                self.status_pub.publish(String(data="Goal reached"))
                self.state = NavigationState.IDLE
            
            elif self.state == NavigationState.FAILED:
                self._stop_robot()
                self.get_logger().error("Navigation failed")
                self.status_pub.publish(String(data="Navigation failed"))
                self.state = NavigationState.IDLE
    
    def _plan_global_path(self): # Plan global path using A* algorithm
        if not self.current_pose or not self.current_goal:
            self.state = NavigationState.FAILED
            return
        
        if not self.map:
            self.get_logger().warn("No map available, using direct path")
            self._create_direct_path()
            self.state = NavigationState.NAVIGATING
            return
        
        # A* path planning
        try:
            path = self._astar_planning(
                (self.current_pose.pose.position.x, self.current_pose.pose.position.y),
                (self.current_goal.pose.position.x, self.current_goal.pose.position.y)
            )
            
            if path:
                self.global_path = self._create_path_msg(path)
                self.global_path_pub.publish(self.global_path)
                self.state = NavigationState.NAVIGATING
                self.get_logger().info(f"Global path planned: {len(path)} waypoints")
            else:
                self.get_logger().error("Failed to find path")
                self.state = NavigationState.FAILED
        
        except Exception as e:
            self.get_logger().error(f"Path planning error: {e}")
            self.state = NavigationState.FAILED
    
    def _astar_planning(self, start: Tuple[float, float], goal: Tuple[float, float]) -> Optional[List[Tuple[float, float]]]:
        if not self.map:
            return None
        
        # Convert world coordinates to grid coordinates
        start_grid = self._world_to_grid(start)
        goal_grid = self._world_to_grid(goal)
        
        # Check if start and goal are valid
        if not self._is_valid_cell(start_grid) or not self._is_valid_cell(goal_grid):
            self.get_logger().error("Invalid start or goal position")
            return None
        
        # A* implementation
        from queue import PriorityQueue
        
        open_set = PriorityQueue()
        open_set.put((0, start_grid))
        
        came_from = {}
        g_score = {start_grid: 0}
        f_score = {start_grid: self._heuristic(start_grid, goal_grid)}
        
        while not open_set.empty():
            current = open_set.get()[1]
            
            if current == goal_grid:
                # Reconstruct path
                path = []
                while current in came_from:
                    path.append(self._grid_to_world(current))
                    current = came_from[current]
                path.append(start)
                path.reverse()
                return path
            
            # Explore neighbors (8-connected)
            for dx, dy in [(-1,-1), (-1,0), (-1,1), (0,-1), (0,1), (1,-1), (1,0), (1,1)]:
                neighbor = (current[0] + dx, current[1] + dy)
                
                if not self._is_valid_cell(neighbor):
                    continue
                
                if self._is_occupied(neighbor):
                    continue
                
                tentative_g = g_score[current] + math.sqrt(dx**2 + dy**2)
                
                if neighbor not in g_score or tentative_g < g_score[neighbor]:
                    came_from[neighbor] = current
                    g_score[neighbor] = tentative_g
                    f_score[neighbor] = tentative_g + self._heuristic(neighbor, goal_grid)
                    open_set.put((f_score[neighbor], neighbor))
        
        return None
    
    def _navigate_to_goal(self): # Navigate towards goal using pure pursuit or similar controller
        if not self.current_pose or not self.current_goal:
            return
        
        # Check for obstacles
        if self._detect_obstacle_ahead():
            self.state = NavigationState.OBSTACLE_AVOIDANCE
            return
        
        # Calculate distance to goal
        dx = self.current_goal.pose.position.x - self.current_pose.pose.position.x
        dy = self.current_goal.pose.position.y - self.current_pose.pose.position.y
        distance = math.sqrt(dx**2 + dy**2)
        
        # Check if goal reached
        if distance < self.goal_tolerance:
            self.state = NavigationState.GOAL_REACHED
            return
        
        # Calculate desired heading
        desired_heading = math.atan2(dy, dx)
        
        # Get current heading from quaternion
        current_heading = self._get_yaw_from_quaternion(
            self.current_pose.pose.orientation
        )
        
        # Calculate heading error
        heading_error = self._normalize_angle(desired_heading - current_heading)
        
        # Simple proportional controller
        cmd = Twist()
        
        # Angular velocity (turn towards goal)
        cmd.angular.z = np.clip(
            2.0 * heading_error,
            -self.max_angular_speed,
            self.max_angular_speed
        )
        
        # Linear velocity (move forward if roughly aligned)
        if abs(heading_error) < math.pi / 4:
            cmd.linear.x = np.clip(
                0.5 * distance,
                0.0,
                self.max_speed
            )
        else:
            cmd.linear.x = 0.1  # Slow down while turning
        
        self.cmd_vel_pub.publish(cmd)
    
    def _avoid_obstacles(self): # Simple obstacle avoidance using potential field method
        if not self.local_obstacles:
            self.state = NavigationState.NAVIGATING
            return
        
        # Calculate repulsive force from obstacles
        repulsive_x = 0.0
        repulsive_y = 0.0
        
        for obs in self.local_obstacles:
            dist = math.sqrt(obs.x**2 + obs.y**2)
            if dist > 0.01:
                repulsive_x -= obs.x / (dist**2)
                repulsive_y -= obs.y / (dist**2)
        
        # Calculate attractive force towards goal
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
        
        # Combine forces
        total_x = attractive_x + 2.0 * repulsive_x
        total_y = attractive_y + 2.0 * repulsive_y
        
        # Calculate command
        cmd = Twist()
        desired_heading = math.atan2(total_y, total_x)
        
        current_heading = self._get_yaw_from_quaternion(
            self.current_pose.pose.orientation
        )
        heading_error = self._normalize_angle(desired_heading - current_heading)
        
        cmd.angular.z = np.clip(
            2.0 * heading_error,
            -self.max_angular_speed,
            self.max_angular_speed
        )
        cmd.linear.x = 0.2  # Slow speed during avoidance
        
        self.cmd_vel_pub.publish(cmd)
        
        # Check if obstacles cleared
        if not self._detect_obstacle_ahead():
            self.state = NavigationState.NAVIGATING
    
    def _detect_obstacle_ahead(self) -> bool: # Check if there's an obstacle directly ahead
        for obs in self.local_obstacles:
            # Check if obstacle is in front (within ±30 degrees)
            angle = math.atan2(obs.y, obs.x)
            if abs(angle) < math.pi / 6 and obs.x < self.obstacle_distance:
                return True
        return False
    
    def _create_direct_path(self): # Create direct path without map
        if not self.current_pose or not self.current_goal:
            return
        
        path = Path()
        path.header.frame_id = "map"
        path.header.stamp = self.get_clock().now().to_msg()
        
        # Start pose
        path.poses.append(self.current_pose)
        
        # Goal pose
        path.poses.append(self.current_goal)
        
        self.global_path = path
        self.global_path_pub.publish(path)
    
    def _create_path_msg(self, waypoints: List[Tuple[float, float]]) -> Path: # Convert waypoints to Path message
        path = Path()
        path.header.frame_id = "map"
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
    
    def _stop_robot(self):
        cmd = Twist()
        self.cmd_vel_pub.publish(cmd)
    
    # Utility functions
    def _world_to_grid(self, pos: Tuple[float, float]) -> Tuple[int, int]:
        x = int((pos[0] - self.map_origin[0]) / self.map_resolution)
        y = int((pos[1] - self.map_origin[1]) / self.map_resolution)
        return (x, y)
    
    def _grid_to_world(self, grid: Tuple[int, int]) -> Tuple[float, float]:
        x = grid[0] * self.map_resolution + self.map_origin[0]
        y = grid[1] * self.map_resolution + self.map_origin[1]
        return (x, y)
    
    def _is_valid_cell(self, cell: Tuple[int, int]) -> bool: # Check if cell is within map bounds
        if not self.map:
            return False
        return (0 <= cell[0] < self.map.info.width and 
                0 <= cell[1] < self.map.info.height)
    
    def _is_occupied(self, cell: Tuple[int, int]) -> bool: # Check if cell is occupied in the map
        if not self.map:
            return False
        
        idx = cell[1] * self.map.info.width + cell[0]
        if 0 <= idx < len(self.map.data):
            return self.map.data[idx] > 50  # Occupied threshold
        return True
    
    def _heuristic(self, a: Tuple[int, int], b: Tuple[int, int]) -> float: # Euclidean distance heuristic for A*
        return math.sqrt((a[0] - b[0])**2 + (a[1] - b[1])**2)
    
    def _get_yaw_from_quaternion(self, q) -> float: # Extract yaw angle from quaternion
        siny_cosp = 2 * (q.w * q.z + q.x * q.y)
        cosy_cosp = 1 - 2 * (q.y * q.y + q.z * q.z)
        return math.atan2(siny_cosp, cosy_cosp)

    def _normalize_angle(self, angle: float) -> float: # Normalize angle to [-pi, pi]
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
        node.get_logger().info("Shutting down...")
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
