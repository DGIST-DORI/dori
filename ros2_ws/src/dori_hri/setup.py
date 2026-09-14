from setuptools import find_packages, setup
import os
from glob import glob

package_name = 'dori_hri'

setup(
    name=package_name,
    version='0.0.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        (os.path.join('share', package_name, 'models'),
            glob('models/*')),
        (os.path.join('share', package_name, 'assets', 'audio'),
            glob('assets/audio/*')),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='ofbt',
    maintainer_email='jaewon1627@gmail.com',
    description='Interaction coordinator package for DORI',
    license='TODO: License declaration',
    extras_require={
        'test': [
            'pytest',
        ],
    },
    entry_points={
        'console_scripts': [
            'hri_manager_node = dori_hri.hri_manager_node:main',
            'stt_node = dori_hri.stt_node:main',
            'tts_node = dori_hri.tts_node:main',
        ],
    },
)
