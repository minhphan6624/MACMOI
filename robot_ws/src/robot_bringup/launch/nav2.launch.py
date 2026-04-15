import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.actions import IncludeLaunchDescription
from launch.actions import OpaqueFunction
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration


def _launch_setup(context, package_share, nav2_bringup_share):
    robot_id = LaunchConfiguration('robot_id').perform(context)
    params_file = LaunchConfiguration('params_file').perform(context)

    robot_param_files = {
        'tb3_1': os.path.join(package_share, 'config', 'nav2_waffle_pi_tb3_1.yaml'),
        'tb3_2': os.path.join(package_share, 'config', 'nav2_waffle_pi_tb3_2.yaml'),
    }
    default_params_file = robot_param_files.get(
        robot_id,
        os.path.join(package_share, 'config', 'nav2_waffle_pi_tb3_1.yaml'),
    )
    resolved_params_file = params_file or default_params_file

    map_yaml_file = LaunchConfiguration('map')
    use_sim_time = LaunchConfiguration('use_sim_time')
    autostart = LaunchConfiguration('autostart')
    slam = LaunchConfiguration('slam')
    use_localization = LaunchConfiguration('use_localization')
    use_composition = LaunchConfiguration('use_composition')
    use_respawn = LaunchConfiguration('use_respawn')
    log_level = LaunchConfiguration('log_level')

    return [
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(
                os.path.join(nav2_bringup_share, 'launch', 'bringup_launch.py')
            ),
            launch_arguments={
                'namespace': '',
                'use_namespace': 'False',
                'map': map_yaml_file,
                'params_file': resolved_params_file,
                'use_sim_time': use_sim_time,
                'autostart': autostart,
                'slam': slam,
                'use_localization': use_localization,
                'use_composition': use_composition,
                'use_respawn': use_respawn,
                'log_level': log_level,
            }.items(),
        ),
    ]


def generate_launch_description():
    package_share = get_package_share_directory('robot_bringup')
    nav2_bringup_share = get_package_share_directory('nav2_bringup')

    default_map = os.path.join(package_share, 'maps', 'aiml_lab.yaml')

    robot_id = LaunchConfiguration('robot_id')

    return LaunchDescription([
        DeclareLaunchArgument(
            'robot_id',
            default_value='tb3_1',
            description='Robot identifier used to select the default Nav2 parameter file',
        ),
        DeclareLaunchArgument(
            'map',
            default_value=default_map,
            description='Full path to the map yaml file to load',
        ),
        DeclareLaunchArgument(
            'params_file',
            default_value='',
            description='Optional full path to the Nav2 parameters file. Leave empty to select from robot_id',
        ),
        DeclareLaunchArgument(
            'use_sim_time',
            default_value='False',
            description='Use simulation clock if true',
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
        OpaqueFunction(
            function=lambda context: _launch_setup(
                context,
                package_share,
                nav2_bringup_share,
            )
        ),
    ])
