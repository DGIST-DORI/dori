#include <chrono>
#include <cstring>
#include <functional>
#include <memory>
#include <string>

#include <cv_bridge/cv_bridge.h>
#include <opencv2/imgproc.hpp>
#include <rclcpp/rclcpp.hpp>
#include <sensor_msgs/msg/camera_info.hpp>
#include <sensor_msgs/msg/image.hpp>
#include <std_msgs/msg/float32.hpp>

#include <librealsense2/rs.hpp>

class DepthCameraNode : public rclcpp::Node {
public:
  DepthCameraNode() : Node("depth_camera_node") {
    width_ = this->declare_parameter<int>("width", 640);
    height_ = this->declare_parameter<int>("height", 480);
    fps_ = this->declare_parameter<int>("fps", 30);
    enable_depth_ = this->declare_parameter<bool>("enable_depth", true);
    enable_color_ = this->declare_parameter<bool>("enable_color", true);
    align_depth_to_color_ = this->declare_parameter<bool>("align_depth_to_color", true);
    depth_scale_publish_ = this->declare_parameter<bool>("depth_scale_publish", true);
    serial_number_ = this->declare_parameter<std::string>("serial_number", "");
    color_topic_ = this->declare_parameter<std::string>("topics.color_pub", "color/image_raw");
    depth_topic_ = this->declare_parameter<std::string>("topics.depth_pub", "depth/image_raw");
    color_info_topic_ = this->declare_parameter<std::string>("topics.color_info_pub", "color/camera_info");
    depth_info_topic_ = this->declare_parameter<std::string>("topics.depth_info_pub", "depth/camera_info");
    depth_scale_topic_ = this->declare_parameter<std::string>("topics.depth_scale_pub", "depth/scale");

    color_pub_ = this->create_publisher<sensor_msgs::msg::Image>(color_topic_, 10);
    depth_pub_ = this->create_publisher<sensor_msgs::msg::Image>(depth_topic_, 10);
    color_info_pub_ = this->create_publisher<sensor_msgs::msg::CameraInfo>(color_info_topic_, 10);
    depth_info_pub_ = this->create_publisher<sensor_msgs::msg::CameraInfo>(depth_info_topic_, 10);
    depth_scale_pub_ = this->create_publisher<std_msgs::msg::Float32>(depth_scale_topic_, 10);

    try {
      rs2::config config;
      if (!serial_number_.empty()) {
        config.enable_device(serial_number_);
      }
      if (enable_color_) {
        config.enable_stream(rs2_stream::RS2_STREAM_COLOR, width_, height_, rs2_format::RS2_FORMAT_BGR8, fps_);
      }
      if (enable_depth_) {
        config.enable_stream(rs2_stream::RS2_STREAM_DEPTH, width_, height_, rs2_format::RS2_FORMAT_Z16, fps_);
      }

      profile_ = pipeline_.start(config);

      if (align_depth_to_color_) {
        align_ = std::make_unique<rs2::align>(rs2_stream::RS2_STREAM_COLOR);
      }

      auto depth_sensor = get_depth_sensor(profile_.get_device());
      depth_scale_ = depth_sensor.get_depth_scale();
      RCLCPP_INFO(this->get_logger(), "Depth scale: %.6f m/unit", depth_scale_);

      auto period = std::chrono::duration<double>(1.0 / static_cast<double>(fps_));
      timer_ = this->create_wall_timer(
        std::chrono::duration_cast<std::chrono::milliseconds>(period),
        std::bind(&DepthCameraNode::timer_callback, this));

      RCLCPP_INFO(
        this->get_logger(),
        "Depth Camera Node started: %dx%d @ %dfps, align=%s",
        width_, height_, fps_, align_depth_to_color_ ? "true" : "false");
    } catch (const std::exception & e) {
      RCLCPP_ERROR(this->get_logger(), "Failed to start RealSense pipeline: %s", e.what());
      throw;
    }
  }

  ~DepthCameraNode() override {
    try {
      pipeline_.stop();
      RCLCPP_INFO(this->get_logger(), "RealSense pipeline stopped");
    } catch (...) {
    }
  }

private:
  static rs2::depth_sensor get_depth_sensor(const rs2::device & device) {
    for (const auto & sensor : device.query_sensors()) {
      if (sensor.is<rs2::depth_sensor>()) {
        return sensor.as<rs2::depth_sensor>();
      }
    }
    throw std::runtime_error("No depth sensor found on RealSense device");
  }

  static builtin_interfaces::msg::Time to_builtin_time(const rclcpp::Time & time) {
    builtin_interfaces::msg::Time stamp;
    const int64_t ns = time.nanoseconds();
    stamp.sec = static_cast<int32_t>(ns / 1000000000LL);
    stamp.nanosec = static_cast<uint32_t>(ns % 1000000000LL);
    return stamp;
  }

  sensor_msgs::msg::CameraInfo build_camera_info(const rs2_intrinsics & intrinsics, const builtin_interfaces::msg::Time & stamp, const std::string & frame_id) const {
    sensor_msgs::msg::CameraInfo info;
    info.header.stamp = stamp;
    info.header.frame_id = frame_id;
    info.width = static_cast<uint32_t>(intrinsics.width);
    info.height = static_cast<uint32_t>(intrinsics.height);
    info.distortion_model = "plumb_bob";

    info.d.resize(5);
    for (size_t i = 0; i < 5; ++i) {
      info.d[i] = intrinsics.coeffs[i];
    }

    const double fx = intrinsics.fx;
    const double fy = intrinsics.fy;
    const double cx = intrinsics.ppx;
    const double cy = intrinsics.ppy;

    info.k = {fx, 0.0, cx,
              0.0, fy, cy,
              0.0, 0.0, 1.0};

    info.r = {1.0, 0.0, 0.0,
              0.0, 1.0, 0.0,
              0.0, 0.0, 1.0};

    info.p = {fx, 0.0, cx, 0.0,
              0.0, fy, cy, 0.0,
              0.0, 0.0, 1.0, 0.0};

    return info;
  }

  void timer_callback() {
    rs2::frameset frames;
    try {
      frames = pipeline_.wait_for_frames(100);
    } catch (const std::exception &) {
      RCLCPP_WARN(this->get_logger(), "RealSense frame acquisition timeout");
      return;
    }

    if (align_) {
      frames = align_->process(frames);
    }

    const auto now = to_builtin_time(this->get_clock()->now());

    if (depth_scale_publish_) {
      std_msgs::msg::Float32 msg;
      msg.data = depth_scale_;
      depth_scale_pub_->publish(msg);
    }

    if (enable_color_) {
      const auto color_frame = frames.get_color_frame();
      if (color_frame) {
        const auto w = color_frame.get_width();
        const auto h = color_frame.get_height();
        const auto * color_data = reinterpret_cast<const uint8_t *>(color_frame.get_data());
        cv::Mat color_mat(h, w, CV_8UC3, const_cast<uint8_t *>(color_data), cv::Mat::AUTO_STEP);

        auto color_msg = cv_bridge::CvImage(std_msgs::msg::Header(), "bgr8", color_mat).toImageMsg();
        color_msg->header.stamp = now;
        color_msg->header.frame_id = "camera_color_optical_frame";
        color_pub_->publish(*color_msg);

        if (!color_intrinsics_cached_) {
          auto vsp = color_frame.get_profile().as<rs2::video_stream_profile>();
          color_intrinsics_ = vsp.get_intrinsics();
          color_intrinsics_cached_ = true;
        }
        color_info_pub_->publish(build_camera_info(color_intrinsics_, now, "camera_color_optical_frame"));
      }
    }

    if (enable_depth_) {
      const auto depth_frame = frames.get_depth_frame();
      if (depth_frame) {
        const auto w = depth_frame.get_width();
        const auto h = depth_frame.get_height();
        const auto * depth_data = reinterpret_cast<const uint16_t *>(depth_frame.get_data());

        cv::Mat depth_mat(h, w, CV_16UC1, const_cast<uint16_t *>(depth_data), cv::Mat::AUTO_STEP);
        auto depth_msg = cv_bridge::CvImage(std_msgs::msg::Header(), "16UC1", depth_mat).toImageMsg();
        depth_msg->header.stamp = now;
        depth_msg->header.frame_id = "camera_depth_optical_frame";
        depth_pub_->publish(*depth_msg);

        if (!depth_intrinsics_cached_) {
          auto vsp = depth_frame.get_profile().as<rs2::video_stream_profile>();
          depth_intrinsics_ = vsp.get_intrinsics();
          depth_intrinsics_cached_ = true;
        }
        depth_info_pub_->publish(build_camera_info(depth_intrinsics_, now, "camera_depth_optical_frame"));
      }
    }
  }

  int width_;
  int height_;
  int fps_;
  bool enable_depth_;
  bool enable_color_;
  bool align_depth_to_color_;
  bool depth_scale_publish_;
  std::string serial_number_;
  std::string color_topic_;
  std::string depth_topic_;
  std::string color_info_topic_;
  std::string depth_info_topic_;
  std::string depth_scale_topic_;

  rs2::pipeline pipeline_;
  rs2::pipeline_profile profile_;
  std::unique_ptr<rs2::align> align_;

  float depth_scale_ {0.001f};
  bool color_intrinsics_cached_ {false};
  bool depth_intrinsics_cached_ {false};
  rs2_intrinsics color_intrinsics_ {};
  rs2_intrinsics depth_intrinsics_ {};

  rclcpp::Publisher<sensor_msgs::msg::Image>::SharedPtr color_pub_;
  rclcpp::Publisher<sensor_msgs::msg::Image>::SharedPtr depth_pub_;
  rclcpp::Publisher<sensor_msgs::msg::CameraInfo>::SharedPtr color_info_pub_;
  rclcpp::Publisher<sensor_msgs::msg::CameraInfo>::SharedPtr depth_info_pub_;
  rclcpp::Publisher<std_msgs::msg::Float32>::SharedPtr depth_scale_pub_;
  rclcpp::TimerBase::SharedPtr timer_;
};

int main(int argc, char ** argv) {
  rclcpp::init(argc, argv);
  try {
    auto node = std::make_shared<DepthCameraNode>();
    rclcpp::spin(node);
  } catch (const std::exception & e) {
    fprintf(stderr, "Fatal error in depth_camera_node: %s\n", e.what());
  }
  rclcpp::shutdown();
  return 0;
}
