import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.actions import IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration


def generate_launch_description():
    package_share = get_package_share_directory('robot_bringup')
    turtlebot3_bringup_share = get_package_share_directory('turtlebot3_bringup')

    default_tb3_params = os.path.join(package_share, 'config', 'hw_waffle_pi.yaml')

    usb_port = LaunchConfiguration('usb_port')
    tb3_param_dir = LaunchConfiguration('tb3_param_dir')
    use_sim_time = LaunchConfiguration('use_sim_time')

    return LaunchDescription([
        DeclareLaunchArgument(
            'usb_port',
            default_value='/dev/ttyACM0',
            description='Connected USB port for the OpenCR board',
        ),
        DeclareLaunchArgument(
            'tb3_param_dir',
            default_value=default_tb3_params,
            description='Full path to the TurtleBot3 hardware parameter file',
        ),
        DeclareLaunchArgument(
            'use_sim_time',
            default_value='false',
            description='Use simulation clock if true',
        ),
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(
                os.path.join(turtlebot3_bringup_share, 'launch', 'robot.launch.py')
            ),
            launch_arguments={
                'usb_port': usb_port,
                'tb3_param_dir': tb3_param_dir,
                'use_sim_time': use_sim_time,
                'namespace': '',
            }.items(),
        ),
    ])
