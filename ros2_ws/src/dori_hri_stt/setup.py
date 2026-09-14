from setuptools import find_packages, setup
import os
from glob import glob

package_name = 'dori_hri_stt'

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
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='ofbt',
    maintainer_email='ofbt@todo.todo',
    description='HRI speech input package for DORI',
    license='TODO: License declaration',
    extras_require={
        'test': [
            'pytest',
        ],
    },
    entry_points={
        'console_scripts': [
            'stt_node = dori_hri_stt.stt_node:main',
        ],
    },
)
