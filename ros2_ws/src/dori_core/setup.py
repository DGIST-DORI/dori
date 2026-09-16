from setuptools import find_packages, setup

package_name = 'dori_core'

setup(
    name=package_name,
    version='0.0.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages', ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
    ],
    install_requires=['setuptools', 'psutil'],
    zip_safe=True,
    maintainer='ofbt',
    maintainer_email='jaewon1627@gmail.com',
    description='System metrics monitor node for DORI',
    license='TODO: License declaration',
    extras_require={
        'test': ['pytest'],
    },
    entry_points={
        'console_scripts': [
            'db_manager = dori_core.db_manager:main',
        ],
    },
)
