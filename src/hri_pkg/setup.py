import os
from glob import glob
from setuptools import find_packages, setup

package_name = 'hri_pkg'

setup(
    name=package_name,
    version='0.0.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        (os.path.join('share', package_name, 'launch'),
            glob('launch/*.launch.py')),
        ('share/' + package_name + '/config', [
            'config/landmark_db.json',
            'config/data.yaml',
        ]),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='ofbt',
    maintainer_email='jaewon1627@gmail.com',
    description='TODO: Package description',
    license='TODO: License declaration',
    extras_require={
        'test': [
            'pytest',
        ],
    },
    entry_points={
        'console_scripts': [
            'camera_node = hri_pkg.camera_node:main',
            'depth_camera_node = hri_pkg.depth_camera_node:main',
            'person_detection_node = hri_pkg.person_detection_node:main',
            'landmark_detection_node = hri_pkg.landmark_detection_node:main',
            'gesture_recognition_node = hri_pkg.gesture_recognition_node:main',
            'facial_expression_node = hri_pkg.facial_expression_node:main',
            'hri_manager_node = hri_pkg.hri_manager_node:main',
        ],
    },
)
