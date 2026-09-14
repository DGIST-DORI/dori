import os
from glob import glob
from setuptools import find_packages, setup

package_name = 'dori_hri_expression'

setup(
    name=package_name,
    version='0.0.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        (os.path.join('share', package_name, 'config'), glob('config/*')),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='ofbt',
    maintainer_email='jaewon1627@gmail.com',
    description='HRI expression publishing package for DORI',
    license='TODO: License declaration',
    extras_require={
        'test': [
            'pytest',
        ],
    },
    entry_points={
        'console_scripts': [
            'emotion_publisher_node = dori_hri_expression.emotion_publisher_node:main',
        ],
    },
)
