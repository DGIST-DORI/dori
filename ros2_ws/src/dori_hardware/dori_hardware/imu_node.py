#!/usr/bin/env python3

import math
import threading

import serial

import rclpy
from rclpy.node import Node

from sensor_msgs.msg import Imu
from sensor_msgs.msg import MagneticField


class ImuSerialNode(Node):

    def __init__(self):

        super().__init__('imu_serial_node')

        # ============================================================
        # Parameters
        # ============================================================

        self.declare_parameter(
            'port',
            '/dev/serial/by-id/usb-Arduino_Nano_33_BLE_B9CD51D670B512DB-if00'
        )

        self.declare_parameter(
            'baudrate',
            230400
        )

        self.declare_parameter(
            'frame_id',
            'imu_link'
        )

        self.port = (
            self.get_parameter('port')
            .get_parameter_value()
            .string_value
        )

        self.baudrate = (
            self.get_parameter('baudrate')
            .get_parameter_value()
            .integer_value
        )

        self.frame_id = (
            self.get_parameter('frame_id')
            .get_parameter_value()
            .string_value
        )

        # ============================================================
        # Publishers
        # ============================================================

        self.imu_pub = self.create_publisher(
            Imu,
            '/imu/data_raw',
            10
        )

        self.mag_pub = self.create_publisher(
            MagneticField,
            '/imu/mag',
            10
        )

        # ============================================================
        # Serial
        # ============================================================

        self.ser = serial.Serial(
            port=self.port,
            baudrate=self.baudrate,
            timeout=0.1
        )

        self.ser.reset_input_buffer()

        self.get_logger().info(
            f'Opened serial port: {self.port}'
        )

        self.get_logger().info(
            'Publishing /imu/data_raw'
        )

        self.get_logger().info(
            'Publishing /imu/mag'
        )

        # ============================================================
        # Serial thread
        # ============================================================

        self.running = True

        self.serial_thread = threading.Thread(
            target=self.serial_loop,
            daemon=True
        )

        self.serial_thread.start()


    # ================================================================
    # Serial loop
    # ================================================================

    def serial_loop(self):

        while self.running:

            try:

                raw_line = self.ser.readline()

            except serial.SerialException:

                break

            if not raw_line:
                continue

            line = raw_line.decode(
                'utf-8',
                errors='ignore'
            ).strip()

            if not line:
                continue

            # Arduino debug lines
            if line.startswith('#'):
                continue

            values = line.split(',')

            # 9-axis CSV
            if len(values) != 9:
                continue

            try:

                ax_g = float(values[0])
                ay_g = float(values[1])
                az_g = float(values[2])

                gx_dps = float(values[3])
                gy_dps = float(values[4])
                gz_dps = float(values[5])

                mx_uT = float(values[6])
                my_uT = float(values[7])
                mz_uT = float(values[8])

            except ValueError:

                continue

            self.publish_data(
                ax_g,
                ay_g,
                az_g,
                gx_dps,
                gy_dps,
                gz_dps,
                mx_uT,
                my_uT,
                mz_uT
            )


    # ================================================================
    # Publish
    # ================================================================

    def publish_data(
        self,
        ax_g,
        ay_g,
        az_g,
        gx_dps,
        gy_dps,
        gz_dps,
        mx_uT,
        my_uT,
        mz_uT
    ):

        now = self.get_clock().now().to_msg()

        # ============================================================
        # IMU
        # ============================================================

        imu_msg = Imu()

        imu_msg.header.stamp = now
        imu_msg.header.frame_id = self.frame_id

        # g -> m/s²
        G = 9.80665

        imu_msg.linear_acceleration.x = ax_g * G
        imu_msg.linear_acceleration.y = ay_g * G
        imu_msg.linear_acceleration.z = az_g * G

        # deg/s -> rad/s
        imu_msg.angular_velocity.x = math.radians(gx_dps)
        imu_msg.angular_velocity.y = math.radians(gy_dps)
        imu_msg.angular_velocity.z = math.radians(gz_dps)

        # orientation은 아직 계산 안 함
        imu_msg.orientation.x = 0.0
        imu_msg.orientation.y = 0.0
        imu_msg.orientation.z = 0.0
        imu_msg.orientation.w = 1.0

        imu_msg.orientation_covariance[0] = -1.0

        self.imu_pub.publish(
            imu_msg
        )

        # ============================================================
        # Magnetometer
        #
        # sensor_msgs/MagneticField 단위 = Tesla
        #
        # μT -> T
        # ============================================================

        mag_msg = MagneticField()

        mag_msg.header.stamp = now
        mag_msg.header.frame_id = self.frame_id

        mag_msg.magnetic_field.x = mx_uT * 1e-6
        mag_msg.magnetic_field.y = my_uT * 1e-6
        mag_msg.magnetic_field.z = mz_uT * 1e-6

        self.mag_pub.publish(
            mag_msg
        )


    # ================================================================
    # Shutdown
    # ================================================================

    def destroy_node(self):

        self.running = False

        # The read has a 0.1 s timeout. Wait for it to finish before
        # closing the descriptor; closing during readline races with os.read.
        if hasattr(self, 'serial_thread'):
            if self.serial_thread.is_alive():
                self.serial_thread.join()

        if hasattr(self, 'ser'):
            if self.ser.is_open:
                self.ser.close()

        super().destroy_node()


def main(args=None):

    rclpy.init(args=args)

    node = ImuSerialNode()

    try:

        rclpy.spin(node)

    except KeyboardInterrupt:

        pass

    finally:

        node.destroy_node()

        rclpy.shutdown()


if __name__ == '__main__':

    main()
