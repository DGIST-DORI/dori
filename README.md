# UGRP
![greetings](https://github.com/github/docs/actions/workflows/greetings.yml/badge.svg)

## Installation
### Prerequisites
* Ubuntu 22.04
* ROS2 Humble
* Python 3.10+
* Microphone and speakers

#### 1. Install ROS2 Dependencies
```
sudo apt update
sudo apt install -y portaudio19-dev python3-pyaudio ffmpeg libsndfile1 mpg123
```

#### 2. Clone Repository
```
git clone https://github.com/ofbt/ros2_ws.git
```

#### 3. Install Python Dependencies
```
cd ~/ros2_ws
pip3 install -r requirements.txt
```

#### 4. Set Porcupine API Key
```
echo 'export PORCUPINE_ACCESS_KEY="your_key_here"' >> ~/.bashrc
source ~/.bashrc
```
Get your API key from [Picovoice Console](https://console.picovoice.ai/)

#### 5. Build Packages
```
source /opt/ros/humble/setup.bash
colcon build --symlink-install
source install/setup.bash
```

## Usage
```
ros2 launch bringup robot.launch.py
```
```
ros2 launch bringup voice_interface.launch.py
```

For now, we're using `porcupine` as a temporary wake word. This will change in the future.
