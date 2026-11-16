#include <cstdio>
#include <fstream>
#include <unistd.h>
#include <gtest/gtest.h>
#include "camera_calibration.hpp"

class Calibration : public ::testing::Test {
protected:
  std::string path;
  std::string yaml = R"(image_width: 640
image_height: 480
camera_matrix: {rows: 3, cols: 3, data: [320, 0, 320, 0, 320, 240, 0, 0, 1]}
rectification_matrix: {rows: 3, cols: 3, data: [1, 0, 0, 0, 1, 0, 0, 0, 1]}
projection_matrix: {rows: 3, cols: 4, data: [320, 0, 320, 0, 0, 320, 240, 0, 0, 0, 1, 0]}
distortion_model: equidistant
distortion_coefficients: {rows: 1, cols: 4, data: [0.01, -0.02, 0, 0]}
)";
  void SetUp() override {
    char filename[] = "/tmp/dori-calibration-XXXXXX";
    const int fd = mkstemp(filename);
    ASSERT_GE(fd, 0);
    close(fd);
    path = filename;
  }
  void TearDown() override { std::remove(path.c_str()); }
  auto load() {
    std::ofstream file(path);
    file << yaml;
    file.close();
    return dori_camera::load_calibration(path);
  }
};

TEST_F(Calibration, FisheyeYamlPreservesCalibrationAndFrameIdentity) {
  auto calibration = load();
  std_msgs::msg::Header header;
  header.frame_id = "camera_rear_optical_frame";
  header.stamp.sec = 123;
  auto info = dori_camera::frame_info(calibration, 640, 480, header);
  EXPECT_EQ(info.distortion_model, "equidistant");
  EXPECT_EQ(info.d.size(), 4u);
  EXPECT_DOUBLE_EQ(info.d[0], .01);
  EXPECT_EQ(info.header, header);
  EXPECT_DOUBLE_EQ(info.k[0], 320);
  EXPECT_THROW(dori_camera::frame_info(calibration, 1280, 720, header), std::runtime_error);
}

TEST_F(Calibration, MissingCalibrationIsExplicitlyUncalibrated) {
  auto info = dori_camera::frame_info(dori_camera::load_calibration(""), 800, 600, std_msgs::msg::Header());
  EXPECT_EQ(info.width, 800u);
  EXPECT_EQ(info.height, 600u);
  EXPECT_DOUBLE_EQ(info.k[0], 0);
  EXPECT_TRUE(info.d.empty());
  EXPECT_THROW(dori_camera::load_calibration(path + "-missing"), YAML::Exception);
}

TEST_F(Calibration, InvalidCalibrationIsNeverSilentlyAccepted) {
  yaml.replace(yaml.find("equidistant"), 11, "unknown");
  EXPECT_THROW(load(), std::runtime_error);
  yaml.replace(yaml.find("unknown"), 7, "equidistant");
  yaml.replace(yaml.find("[320"), 4, "[.nan");
  EXPECT_THROW(load(), std::runtime_error);
}
