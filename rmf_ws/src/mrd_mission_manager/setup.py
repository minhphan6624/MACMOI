from setuptools import find_packages
from setuptools import setup

package_name = "mrd_mission_manager"

setup(
    name=package_name,
    version="0.0.0",
    packages=find_packages(exclude=["test"]),
    data_files=[
        ("share/ament_index/resource_index/packages", ["resource/" + package_name]),
        ("share/" + package_name, ["package.xml"]),
    ],
    install_requires=["setuptools"],
    zip_safe=True,
    maintainer="minhqphan",
    maintainer_email="quangminh6624@gmail.com",
    description="Mission manager for fixed-role multi-robot delivery missions.",
    license="Apache License 2.0",
)
