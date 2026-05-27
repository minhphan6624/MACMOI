from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, GroupAction, IncludeLaunchDescription
from launch.launch_description_sources import AnyLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
from launch_ros.substitutions import FindPackageShare


def generate_launch_description():
    use_sim_time = LaunchConfiguration('use_sim_time')
    headless = LaunchConfiguration('headless')
    server_uri = LaunchConfiguration('server_uri')
    initial_map = LaunchConfiguration('initial_map')
    building_map_file = LaunchConfiguration('building_map_file')
    nav_graph_file = LaunchConfiguration('nav_graph_file')
    config_file = LaunchConfiguration('config_file')
    viz_config_file = LaunchConfiguration('viz_config_file')

    system_pkg = FindPackageShare('system_rmf_bringup')
    fleet_pkg = FindPackageShare('free_fleet_bringup')

    building_file = PathJoinSubstitution([system_pkg, 'maps', 'aiml-lab.building.yaml'])
    default_nav_graph_file = PathJoinSubstitution([system_pkg, 'nav_graphs', '1.yaml'])
    default_viz_config_file = PathJoinSubstitution([system_pkg, 'config', 'rmf.rviz'])
    rmf_core_launch = PathJoinSubstitution([system_pkg, 'launch', 'rmf_core.launch.xml'])
    fleet_config_file = PathJoinSubstitution(
        [fleet_pkg, 'config', 'fleet', 'aiml_lab_multi_tb3_fleet.yaml']
    )
    fleet_launch = PathJoinSubstitution([fleet_pkg, 'launch', 'aiml_lab_ff_bringup.launch.xml'])

    return LaunchDescription([
        DeclareLaunchArgument('use_sim_time', default_value='false'),
        DeclareLaunchArgument('headless', default_value='false'),
        DeclareLaunchArgument('server_uri', default_value=''),
        DeclareLaunchArgument('initial_map', default_value='LG'),
        DeclareLaunchArgument('building_map_file', default_value=building_file),
        DeclareLaunchArgument('nav_graph_file', default_value=default_nav_graph_file),
        DeclareLaunchArgument('config_file', default_value=fleet_config_file),
        DeclareLaunchArgument('viz_config_file', default_value=default_viz_config_file),

        GroupAction(
            actions=[
                IncludeLaunchDescription(
                    AnyLaunchDescriptionSource(rmf_core_launch),
                    launch_arguments={
                        'use_sim_time': use_sim_time,
                        'config_file': building_map_file,
                        'initial_map': initial_map,
                        'viz_config_file': viz_config_file,
                        'headless': headless,
                        'server_uri': server_uri,
                    }.items(),
                ),
            ]
        ),

        GroupAction(
            actions=[
                IncludeLaunchDescription(
                    AnyLaunchDescriptionSource(fleet_launch),
                    launch_arguments={
                        'use_sim_time': use_sim_time,
                        'nav_graph_file': nav_graph_file,
                        'config_file': config_file,
                        'server_uri': server_uri,
                    }.items(),
                ),
            ]
        ),
    ])
