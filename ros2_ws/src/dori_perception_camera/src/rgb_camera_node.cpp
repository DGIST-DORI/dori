#include <chrono>
#include <cstdio>
#include <memory>
#include <string>

#include <opencv2/videoio.hpp>
#include <rclcpp/rclcpp.hpp>
#include <sensor_msgs/msg/image.hpp>
#include "camera_calibration.hpp"

class RGBCameraNode : public rclcpp::Node {
public:
  RGBCameraNode() : Node("rgb_camera_node") {
    const auto device = declare_parameter<std::string>("device", "/dev/video0");
    const int width = declare_parameter<int>("width", 640);
    const int height = declare_parameter<int>("height", 480);
    const int fps = declare_parameter<int>("fps", 15);
    const auto fourcc = declare_parameter<std::string>("pixel_format", "MJPG");
    frame_id_ = declare_parameter<std::string>("frame_id", "camera_front_optical_frame");
    calibration_ = dori_camera::load_calibration(
      declare_parameter<std::string>("calibration_file", ""));
    if (device.empty() || frame_id_.empty() || width <= 0 || height <= 0 ||
        fps <= 0 || fps > 120 || fourcc.size() != 4) {
      throw std::runtime_error("Invalid camera device, frame_id, dimensions, fps or pixel_format");
    }
    if (!capture_.open(device, cv::CAP_V4L2)) {
      throw std::runtime_error("Cannot open USB/V4L2 camera: " + device);
    }
    capture_.set(cv::CAP_PROP_FOURCC,
      cv::VideoWriter::fourcc(fourcc[0], fourcc[1], fourcc[2], fourcc[3]));
    capture_.set(cv::CAP_PROP_FRAME_WIDTH, width);
    capture_.set(cv::CAP_PROP_FRAME_HEIGHT, height);
    capture_.set(cv::CAP_PROP_FPS, fps);
    capture_.set(cv::CAP_PROP_BUFFERSIZE, 1);
    // Reliable, shallow queues retain compatibility with existing vision subscribers.
    image_pub_ = create_publisher<sensor_msgs::msg::Image>("color/image_raw", 1);
    info_pub_ = create_publisher<sensor_msgs::msg::CameraInfo>("color/camera_info", 1);
    timer_ = create_wall_timer(std::chrono::nanoseconds(1000000000LL / fps),
      [this]() { capture_frame(); });
    RCLCPP_INFO(get_logger(), "USB RGB camera %s: requested %dx%d at %d fps, %s",
      device.c_str(), width, height, fps, fourcc.c_str());
    if (calibration_.k[0] == 0) {
      RCLCPP_WARN(get_logger(), "No calibration: publishing uncalibrated CameraInfo (K=0); metric geometry unavailable");
    }
  }

private:
  void capture_frame() {
    cv::Mat frame;
    if (!capture_.read(frame) || frame.empty()) {
      // Do not stamp/publish cached frames: the readiness monitor must see the outage.
      if (++failed_frames_ >= 5) throw std::runtime_error("USB camera stopped delivering frames");
      RCLCPP_WARN(get_logger(), "USB camera frame acquisition failed");
      return;
    }
    failed_frames_ = 0;
    if (frame.type() != CV_8UC3) throw std::runtime_error("Camera must deliver decoded BGR8 frames");
    std_msgs::msg::Header header;
    header.stamp = now();  // Host receipt time; these independent cameras are not stereo synchronized.
    header.frame_id = frame_id_;
    const auto info = dori_camera::frame_info(calibration_, frame.cols, frame.rows, header);
    info_pub_->publish(info);
    if (!frame.isContinuous()) frame = frame.clone();
    sensor_msgs::msg::Image image;
    image.header = header;
    image.width = frame.cols;
    image.height = frame.rows;
    image.encoding = "bgr8";
    image.step = frame.cols * 3;
    image.data.assign(frame.data, frame.data + image.step * image.height);
    image_pub_->publish(image);
  }

  cv::VideoCapture capture_;
  sensor_msgs::msg::CameraInfo calibration_;
  std::string frame_id_;
  int failed_frames_ = 0;
  rclcpp::Publisher<sensor_msgs::msg::Image>::SharedPtr image_pub_;
  rclcpp::Publisher<sensor_msgs::msg::CameraInfo>::SharedPtr info_pub_;
  rclcpp::TimerBase::SharedPtr timer_;
};

int main(int argc, char **argv) {
  rclcpp::init(argc, argv);
  int result = 0;
  try {
    rclcpp::spin(std::make_shared<RGBCameraNode>());
  } catch (const std::exception &error) {
    std::fprintf(stderr, "rgb_camera_node: %s\n", error.what());
    result = 1;
  }
  rclcpp::shutdown();
  return result;
}
