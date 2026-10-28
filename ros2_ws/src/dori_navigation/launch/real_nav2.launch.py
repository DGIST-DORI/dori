"""Real ROS 2 Humble Nav2 with explicit velocity routing and named-goal control."""
from pathlib import Path
import sys
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, ExecuteProcess, OpaqueFunction, IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.conditions import IfCondition
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def setup(context):
    root = Path(get_package_share_directory('dori_navigation'))
    sys.path.insert(0, str(root / 'scripts'))
    from navigation_contract import validate_map
    value = lambda name: LaunchConfiguration(name).perform(context)
    validate_map(value('map'))
    params = [value('params_file'), {'use_sim_time': False}]
    kinematics = str(Path(get_package_share_directory('dori_control')) / 'config/kinematics.yaml')
    specs = [('nav2_map_server','map_server'), ('nav2_amcl','amcl'),
             ('nav2_controller','controller_server'), ('nav2_planner','planner_server'),
             ('nav2_behaviors','behavior_server'),
             ('nav2_bt_navigator','bt_navigator'),
             ('nav2_velocity_smoother','velocity_smoother')]
    nodes = []
    for package, executable in specs:
        remaps=[]
        if executable in ('controller_server','behavior_server'):
            remaps=[('cmd_vel','/nav/cmd_vel_raw')]
        if executable=='velocity_smoother':
            remaps=[('cmd_vel','/nav/cmd_vel_raw'),('cmd_vel_smoothed','/nav/cmd_vel')]
        extra = [{'yaml_filename':value('map')}] if executable=='map_server' else []
        if executable=='bt_navigator':
            # Only dori_navigation may reach the Nav2 action.  RViz goals are
            # kept private so they cannot bypass DORI cancellation and safety.
            # Humble does not remap action base names; remap all five endpoints.
            # https://github.com/ros2/ros2/issues/1312
            remaps=[('goal_pose','/dori/internal/goal_pose')]
            remaps += [(f'/{action}/_action/{endpoint}', f'/dori/internal/{action}/_action/{endpoint}')
                       for action in ('navigate_to_pose','navigate_through_poses')
                       for endpoint in ('send_goal','get_result','cancel_goal','feedback','status')]
            extra=[{'default_nav_to_pose_bt_xml':str(root/'config/navigate_basic.xml'),
                    'default_nav_through_poses_bt_xml':str(root/'config/navigate_through_basic.xml')}]
        nodes.append(Node(package=package,executable=executable,name=executable,
                          parameters=params+extra,remappings=remaps,output='screen'))
    # Map publication must not wait for navigation service discovery or initial pose.
    groups={'map':['map_server'], 'localization':['amcl'],
            'navigation':[n for _,n in specs if n not in ('map_server','amcl')]}
    for group, managed in groups.items():
        nodes.append(Node(package='nav2_lifecycle_manager',executable='lifecycle_manager',
                          name='lifecycle_manager_'+group,
                          parameters=[{'use_sim_time':False,'autostart':True,'node_names':managed}],output='screen'))
    nodes.append(Node(package='tf2_ros',executable='static_transform_publisher',name='base_to_laser_tf',condition=IfCondition(LaunchConfiguration('publish_laser_tf')),
                      arguments=['--x',value('laser_x'),'--y',value('laser_y'),'--z',value('laser_z'),
                                 '--roll',value('laser_roll'),'--pitch',value('laser_pitch'),'--yaw',value('laser_yaw'),
                                 '--frame-id','base_link','--child-frame-id','laser']))
    # Web/RViz goals also pass through the single DORI action authority.
    scripts=['nav_drive_bridge.py', 'named_goal_bridge.py']
    for script in scripts:
        args=['/usr/bin/python3',str(root/'scripts'/script),'--ros-args','-p','use_sim_time:=false']
        if script=='nav_drive_bridge.py':
            args+=['--params-file',str(root/'config/motion_interpreter.yaml'),'--params-file',kinematics]
        nodes.append(ExecuteProcess(cmd=args,output='screen'))
    nodes.append(IncludeLaunchDescription(PythonLaunchDescriptionSource(str(
        Path(get_package_share_directory('dori_navigation'))/'launch/real_navigation.launch.py')),
        launch_arguments={'named_goals_file': value('named_goals_file')}.items()))
    nodes.append(Node(package='rviz2',executable='rviz2',arguments=['-d',str(root/'config/remote_monitor.rviz')],
                      parameters=[{'use_sim_time':False}],condition=IfCondition(LaunchConfiguration('rviz'))))
    return nodes


def generate_launch_description():
    root=Path(get_package_share_directory('dori_navigation'))
    args=[DeclareLaunchArgument('map'),
          DeclareLaunchArgument('named_goals_file', default_value=''),
          DeclareLaunchArgument('params_file',default_value=str(root/'config/nav2_real.yaml')),
          DeclareLaunchArgument('publish_laser_tf',default_value='false'),
          DeclareLaunchArgument('rviz',default_value='false')]
    args += [DeclareLaunchArgument('laser_'+axis,default_value='3.141592653589793' if axis=='yaw' else '0.0') for axis in ['x','y','z','roll','pitch','yaw']]
    return LaunchDescription(args+[OpaqueFunction(function=setup)])
