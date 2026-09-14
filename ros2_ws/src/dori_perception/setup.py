import os
from glob import glob
from setuptools import find_packages, setup

package_name = 'dori_perception'

setup(
    name=package_name,
    version='0.0.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        ('share/' + package_name + '/config', [
            'config/landmark_db.json',
            'config/data.yaml',
        ]),
        (os.path.join('share', package_name, 'models'),
            glob('models/*.task')),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='ofbt',
    maintainer_email='jaewon1627@gmail.com',
    description='Perception nodes for DORI HRI pipeline',
    license='TODO: License declaration',
    extras_require={
        'test': [
            'pytest',
        ],
    },
    entry_points={
        'console_scripts': [
            'depth_camera_node = dori_perception.depth_camera_node:main',
            'person_detection_node = dori_perception.person_detection_node:main',
            'landmark_detection_node = dori_perception.landmark_detection_node:main',
            'gesture_recognition_node = dori_perception.gesture_recognition_node:main',
            'facial_expression_node = dori_perception.facial_expression_node:main',
        ],
    },
)
