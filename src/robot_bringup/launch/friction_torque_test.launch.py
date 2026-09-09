from launch_ros.parameter_descriptions import ParameterValue
from launch import LaunchDescription
from launch.substitutions import (
    PathJoinSubstitution,
    Command,
    FindExecutable,
)

from launch_ros.actions import Node
from launch_ros.substitutions import FindPackageShare


def generate_launch_description():

    # ============================================================
    # Robot description
    # ============================================================

    urdf_file = PathJoinSubstitution([
        FindPackageShare("robot_bringup"),
        "config",
        "cubemars_mit.urdf.xacro",
    ])

    controllers_file = PathJoinSubstitution([
        FindPackageShare("robot_bringup"),
        "config",
        "bldc_controllers.yaml",
    ])

    robot_description = {
        "robot_description": ParameterValue(Command([
            FindExecutable(name="xacro"),
            " ",
            urdf_file,
        ]), value_type=str)
    }

    # ============================================================
    # Torque / friction experiment launch
    #
    # 실행:
    #   ros2_control
    #   robot_state_publisher
    #   joint_state_broadcaster
    #   left effort-only controller
    #   right effort-only controller
    #
    # 실행하지 않음:
    #   left/right drive controller
    #   bldc_command_bridge_node
    #   drive controller
    #   transform controller
    #   IMU stabilization
    # ============================================================

    return LaunchDescription([

        # ========================================================
        # ros2_control
        # ========================================================

        Node(
            package="controller_manager",
            executable="ros2_control_node",
            parameters=[
                robot_description,
                controllers_file,
            ],
            output="screen",
        ),

        # ========================================================
        # Robot state publisher
        # ========================================================

        Node(
            package="robot_state_publisher",
            executable="robot_state_publisher",
            parameters=[robot_description],
            output="screen",
        ),

        # ========================================================
        # Joint states
        # ========================================================

        Node(
            package="controller_manager",
            executable="spawner",
            arguments=[
                "joint_state_broadcaster",
                "--controller-manager",
                "/controller_manager",
            ],
            output="screen",
        ),

        # ========================================================
        # LEFT effort-only controller
        # ========================================================

        Node(
            package="controller_manager",
            executable="spawner",
            arguments=[
                "left_bldc_effort_controller",
                "--controller-manager",
                "/controller_manager",
            ],
            output="screen",
        ),

        # ========================================================
        # RIGHT effort-only controller
        # ========================================================

        Node(
            package="controller_manager",
            executable="spawner",
            arguments=[
                "right_bldc_effort_controller",
                "--controller-manager",
                "/controller_manager",
            ],
            output="screen",
        ),
        
        #========================================================
        # Position controller
        #
        # 자동 angle sweep에서 위치 이동용.
        #
        # 시작할 때는 inactive로 load만 해둔다.
        # automatic_angle_breakaway_map_node가 필요할 때
        # effort controller와 switch해서 사용한다.
        # ========================================================

        Node(
            package="controller_manager",
            executable="spawner",
            arguments=[
                "bldc_position_controller",
                "--controller-manager",
                "/controller_manager",
                "--inactive",
            ],
            output="screen",
        ),
        
        Node(
            package='controller_manager',
            executable='spawner',
            arguments=[
                'left_bldc_drive_controller',
                '--controller-manager',
                '/controller_manager',
                '--inactive'
            ],
            output='screen'
        ),
        
        
        Node(
            package='controller_manager',
            executable='spawner',
            arguments=[
                'right_bldc_drive_controller',
                '--controller-manager',
                '/controller_manager',
                '--inactive'
            ],
            output='screen'
        ),
        
        
        
    ])
