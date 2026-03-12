from pathlib import Path
from setuptools import find_packages, setup
from glob import glob
import os

package_name = 'dashboard_pkg'
setup_dir = Path(__file__).resolve().parent
repo_root = setup_dir.parents[1]


def collect_web_data_files():
    """Collect web build artifacts from the repository-level web/dist directory."""
    web_dist_dir = repo_root / 'web' / 'dist'
    if not web_dist_dir.exists():
        return []

    collected = []
    for src_path in sorted(p for p in web_dist_dir.rglob('*') if p.is_file()):
        relative_parent = src_path.parent.relative_to(web_dist_dir)
        install_dir = Path('share') / package_name / 'web' / relative_parent
        try:
            relative_src = src_path.relative_to(setup_dir)
        except ValueError:
            relative_src = Path(os.path.relpath(src_path, setup_dir))
        collected.append((str(install_dir), [str(relative_src)]))

    return collected


setup(
    name=package_name,
    version='0.0.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        (os.path.join('share', package_name, 'launch'), glob('launch/*.py')),
    ] + collect_web_data_files(),
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
            'dori_bridge = dashboard_pkg.dori_bridge:main',
        ],
    },
)
