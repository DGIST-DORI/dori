#pragma once

#include <algorithm>
#include <cmath>
#include <stdexcept>
#include <string>
#include <vector>
#include <sensor_msgs/msg/camera_info.hpp>
#include <yaml-cpp/yaml.h>

namespace dori_camera {

// Read the YAML format emitted by ROS camera_calibration. Never invent intrinsics.
inline sensor_msgs::msg::CameraInfo load_calibration(const std::string &path) {
  sensor_msgs::msg::CameraInfo info;
  if (path.empty()) return info;
  const auto yaml = YAML::LoadFile(path);
  info.width = yaml["image_width"].as<unsigned>();
  info.height = yaml["image_height"].as<unsigned>();
  info.distortion_model = yaml["distortion_model"].as<std::string>();
  auto matrix = [&](const char *name, int rows, int cols, auto &out) {
    const auto node = yaml[name];
    const auto data = node["data"].as<std::vector<double>>();
    if (node["rows"].as<int>() != rows || node["cols"].as<int>() != cols ||
        data.size() != out.size() ||
        !std::all_of(data.begin(), data.end(), [](double x) { return std::isfinite(x); })) {
      throw std::runtime_error(std::string("Invalid calibration matrix: ") + name);
    }
    std::copy(data.begin(), data.end(), out.begin());
  };
  matrix("camera_matrix", 3, 3, info.k);
  matrix("rectification_matrix", 3, 3, info.r);
  matrix("projection_matrix", 3, 4, info.p);
  info.d = yaml["distortion_coefficients"]["data"].as<std::vector<double>>();
  if (yaml["distortion_coefficients"]["rows"].as<int>() != 1 ||
      yaml["distortion_coefficients"]["cols"].as<size_t>() != info.d.size()) {
    throw std::runtime_error("Invalid distortion coefficient matrix");
  }
  const auto model = info.distortion_model;
  const bool supported = (model == "equidistant" && info.d.size() == 4) ||
    (model == "plumb_bob" && info.d.size() == 5) ||
    (model == "rational_polynomial" && info.d.size() == 8);
  if (!supported || !info.width || !info.height || info.k[0] <= 0 || info.k[4] <= 0 ||
      std::abs(info.k[8] - 1.0) > 1e-9 ||
      !std::all_of(info.d.begin(), info.d.end(), [](double x) { return std::isfinite(x); })) {
    throw std::runtime_error("Invalid calibration dimensions, intrinsics or distortion model");
  }
  return info;
}

inline sensor_msgs::msg::CameraInfo frame_info(
    sensor_msgs::msg::CameraInfo info, unsigned width, unsigned height,
    const std_msgs::msg::Header &header) {
  if (info.k[0] != 0 && (info.width != width || info.height != height)) {
    throw std::runtime_error("Camera resolution differs from calibration; recalibrate at the capture resolution");
  }
  info.width = width;
  info.height = height;
  info.header = header;
  return info;
}
}  // namespace dori_camera
