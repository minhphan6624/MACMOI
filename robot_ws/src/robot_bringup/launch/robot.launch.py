import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.actions import GroupAction
from launch.actions import IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration


def generate_launch_description():
    package_share = get_package_share_directory('robot_bringup')
    launch_dir = os.path.join(package_share, 'launch')

    default_map = os.path.join(package_share, 'maps', 'aiml_lab.yaml')
    default_nav2_params = os.path.join(package_share, 'config', 'nav2_waffle_pi.yaml')
    default_hw_params = os.path.join(package_share, 'config', 'hw_waffle_pi.yaml')

    usb_port = LaunchConfiguration('usb_port')
    tb3_param_dir = LaunchConfiguration('tb3_param_dir')
    map_yaml_file = LaunchConfiguration('map')
    params_file = LaunchConfiguration('params_file')
    use_sim_time = LaunchConfiguration('use_sim_time')

    autostart = LaunchConfiguration('autostart')
    slam = LaunchConfiguration('slam')
    use_localization = LaunchConfiguration('use_localization')
    use_composition = LaunchConfiguration('use_composition')
    use_respawn = LaunchConfiguration('use_respawn')
    log_level = LaunchConfiguration('log_level')

    return LaunchDescription([
        DeclareLaunchArgument(
            'usb_port',
            default_value='/dev/ttyACM0',
            description='Connected USB port for the OpenCR board',
        ),
        DeclareLaunchArgument(
            'tb3_param_dir',
            default_value=default_hw_params,
            description='Full path to the TurtleBot3 hardware parameter file',
        ),
        DeclareLaunchArgument(
            'map',
            default_value=default_map,
            description='Full path to the map yaml file to load',
        ),
        DeclareLaunchArgument(
            'params_file',
            default_value=default_nav2_params,
            description='Full path to the Nav2 parameters file',
        ),
        DeclareLaunchArgument(
            'use_sim_time',
            default_value='False',
            description='Use simulation clock if True',
        ),
        DeclareLaunchArgument(
            'autostart',
            default_value='True',
            description='Automatically startup the Nav2 stack',
        ),
        DeclareLaunchArgument(
            'slam',
            default_value='False',
            description='Whether to run SLAM instead of localization',
        ),
        DeclareLaunchArgument(
            'use_localization',
            default_value='True',
            description='Whether to enable localization',
        ),
        DeclareLaunchArgument(
            'use_composition',
            default_value='True',
            description='Whether to use composed bringup',
        ),
        DeclareLaunchArgument(
            'use_respawn',
            default_value='False',
            description='Whether to respawn crashed nodes when composition is disabled',
        ),
        DeclareLaunchArgument(
            'log_level',
            default_value='info',
            description='Log level for Nav2 nodes',
        ),
        GroupAction(
            scoped=True,
            actions=[
                IncludeLaunchDescription(
                    PythonLaunchDescriptionSource(os.path.join(launch_dir, 'hardware.launch.py')),
                    launch_arguments={
                        'usb_port': usb_port,
                        'tb3_param_dir': tb3_param_dir,
                        'use_sim_time': use_sim_time,
                    }.items(),
                ),
            ],
        ),
        GroupAction(
            scoped=True,
            actions=[
                IncludeLaunchDescription(
                    PythonLaunchDescriptionSource(os.path.join(launch_dir, 'nav2.launch.py')),
                    launch_arguments={
                        'map': map_yaml_file,
                        'params_file': params_file,
                        'use_sim_time': use_sim_time,
                        'autostart': autostart,
                        'slam': slam,
                        'use_localization': use_localization,
                        'use_composition': use_composition,
                        'use_respawn': use_respawn,
                        'log_level': log_level,
                    }.items(),
                ),
            ],
        ),
    ])
