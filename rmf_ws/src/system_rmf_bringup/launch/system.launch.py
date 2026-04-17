from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.launch_description_sources import AnyLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
from launch_ros.substitutions import FindPackageShare


def generate_launch_description():
    use_sim_time = LaunchConfiguration('use_sim_time')
    headless = LaunchConfiguration('headless')
    server_uri = LaunchConfiguration('server_uri')

    system_pkg = FindPackageShare('system_rmf_bringup')
    fleet_pkg = FindPackageShare('free_fleet_bringup')

    building_file = PathJoinSubstitution([ system_pkg, 'maps', 'aiml-lab.building.yaml'])
    nav_graph_file = PathJoinSubstitution([system_pkg, 'nav_graphs', 'graph_0.yaml'])
    rmf_core_launch = PathJoinSubstitution([system_pkg, 'launch', 'rmf_core.launch.xml'])
    
    fleet_launch = PathJoinSubstitution([fleet_pkg, 'launch', 'aiml_lab_ff_bringup.launch.xml'])

    return LaunchDescription([
        DeclareLaunchArgument('use_sim_time',default_value='false'),
        DeclareLaunchArgument('headless',default_value='false'),
        DeclareLaunchArgument('server_uri',default_value=''),

        IncludeLaunchDescription(
            AnyLaunchDescriptionSource(rmf_core_launch),
            launch_arguments={
                'use_sim_time': use_sim_time,
                'config_file': building_file,
                'initial_map': 'LG',
                'headless': headless,
            }.items()
        ),

        IncludeLaunchDescription(
            AnyLaunchDescriptionSource(fleet_launch),
            launch_arguments={
                'use_sim_time': use_sim_time,
                'nav_graph_file': nav_graph_file,
                'server_uri': server_uri,
            }.items()
        ),
    ])
