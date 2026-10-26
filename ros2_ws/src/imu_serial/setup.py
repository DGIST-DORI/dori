from setuptools import find_packages, setup

package_name = 'imu_serial'

setup(
    name=package_name,
    version='0.0.0',

    packages=find_packages(
        exclude=['test']
    ),

    data_files=[
        (
            'share/ament_index/resource_index/packages',
            ['resource/' + package_name]
        ),
        (
            'share/' + package_name,
            ['package.xml']
        ),
    ],

    install_requires=[
        'setuptools',
        'pyserial>=3.5,<4'
    ],

    zip_safe=True,

    maintainer='who',
    maintainer_email='who@example.com',

    description='IMU serial communication and body stabilization nodes',

    license='Apache-2.0',

    tests_require=[
        'pytest'
    ],

    entry_points={
        'console_scripts': [
            'imu_node = imu_serial.imu_node:main',
            'body_pitch_node = imu_serial.body_pitch_node:main',
            'body_stabilizer_node = imu_serial.body_stabilizer_node:main',
            'servo3_pitch_follower_node = imu_serial.servo3_pitch_follower_node:main',
        ],
    },
)
