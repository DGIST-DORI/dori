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

            'yaw_angle_node = imu_serial.yaw_angle_node:main',

            'yaw_damping_node = imu_serial.yaw_damping_node:main',
            
            'breakaway_test_node = imu_serial.breakaway_test_node:main',
            
            'dynamic_friction_test_node = imu_serial.dynamic_friction_test_node:main',
            
            'dynamic_friction_velocity_test_node = imu_serial.dynamic_friction_velocity_test_node:main',
            
            'dynamic_friction_torque_sweep_node = imu_serial.dynamic_friction_torque_sweep_node:main',
            
            'single_wheel_torque_test_node = imu_serial.single_wheel_torque_test_node:main',
            
            'pure_torque_sweep_node = imu_serial.pure_torque_sweep_node:main',
            
            'angle_breakaway_test_node = imu_serial.angle_breakaway_test_node:main',
            
            'automatic_angle_breakaway_map_node = imu_serial.automatic_angle_breakaway_map_node:main',
            
            'servo3_pitch_follower_node = imu_serial.servo3_pitch_follower_node:main',
        ],
    },
)
