#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
import os
import re
import threading
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import rclpy
from rclpy.node import Node
from std_msgs.msg import Bool, Int32, String


SYSTEM_PROMPT = """You are a destination selector for a mobile robot.

Your task is to choose exactly one destination point name from the provided list.

Rules:
- Output exactly one point name from the available list.
- Do not explain your choice.
- Do not output JSON.
- Do not invent a new name.
- If the user's request already contains an exact point name, output that exact name.
- If the request is ambiguous, choose the single best matching point name from the list.
"""

from navigation_contract import load_points_csv


def read_system_prompt(prompt_file: Path, fallback_prompt: str) -> str:
    try:
        text = prompt_file.read_text(encoding="utf-8").strip()
    except OSError:
        return fallback_prompt
    return text or fallback_prompt


def normalize_candidate(text: str) -> str:
    cleaned = text.strip()
    cleaned = cleaned.strip("`\"' \n\r\t")
    cleaned = cleaned.splitlines()[0].strip() if cleaned else ""
    return cleaned


class TextLLMNamedGoal(Node):
    def __init__(self) -> None:
        super().__init__("text_llm_named_goal")

        root_dir = Path(__file__).resolve().parents[1]
        default_points_file = str(root_dir / "config" / "points.example.csv")
        default_prompt_file = str(root_dir / "prompt.txt")

        self.declare_parameter("points_file", default_points_file)
        self.declare_parameter("prompt_file", default_prompt_file)
        self.declare_parameter("goal_topic", "/named_goal")
        self.declare_parameter("status_topic", "/named_goal_status")
        self.declare_parameter("input_mode", "topic")
        self.declare_parameter("navigation_mode_topic", "/NAVIGATION_MODE")
        self.declare_parameter("navigation_text_topic", "/NAVIGATION_TEXT")
        self.declare_parameter("navigation_status_topic", "/NAVIGATION_STATUS")
        self.declare_parameter("navigation_busy_topic", "/NAVIGATION_BUSY")
        self.declare_parameter("model", os.getenv("OPENAI_MODEL", "gpt-5.4"))
        self.declare_parameter("history_turns", 6)
        self.declare_parameter("max_output_tokens", 1024)

        self.points_file = Path(self.get_parameter("points_file").get_parameter_value().string_value)
        self.prompt_file = Path(self.get_parameter("prompt_file").get_parameter_value().string_value)
        self.goal_topic = self.get_parameter("goal_topic").get_parameter_value().string_value
        self.status_topic = self.get_parameter("status_topic").get_parameter_value().string_value
        self.input_mode = self.get_parameter("input_mode").get_parameter_value().string_value.lower()
        self.navigation_mode_topic = (
            self.get_parameter("navigation_mode_topic").get_parameter_value().string_value
        )
        self.navigation_text_topic = (
            self.get_parameter("navigation_text_topic").get_parameter_value().string_value
        )
        self.navigation_status_topic = (
            self.get_parameter("navigation_status_topic").get_parameter_value().string_value
        )
        self.navigation_busy_topic = (
            self.get_parameter("navigation_busy_topic").get_parameter_value().string_value
        )
        self.model = self.get_parameter("model").get_parameter_value().string_value
        self.history_turns = int(self.get_parameter("history_turns").value)
        self.max_output_tokens = int(self.get_parameter("max_output_tokens").value)
        if self.history_turns < 1 or self.max_output_tokens < 64:
            raise ValueError("Invalid history_turns/max_output_tokens")
        self.system_prompt = read_system_prompt(self.prompt_file, SYSTEM_PROMPT)

        if self.input_mode not in {"topic", "terminal"}:
            self.get_logger().warn(
                f"Unknown input_mode '{self.input_mode}', falling back to 'topic'"
            )
            self.input_mode = "topic"

        self.points = load_points_csv(self.points_file)
        self.goal_publisher = self.create_publisher(String, self.goal_topic, 10)
        self.status_subscription = self.create_subscription(
            String, self.status_topic, self.on_status, 10
        )
        self.history: list[tuple[str, str]] = []
        self._client = None

        self.control_status_publisher = None
        self.busy_publisher = None
        self.mode_subscription = None
        self.text_subscription = None
        self._worker_condition = threading.Condition()
        self._worker_stop = False
        self._worker_thread: threading.Thread | None = None
        self._navigation_active = False
        self._cached_text = ""
        self._session_last_text: str | None = None
        self._request_sequence = 0
        self._latest_request_sequence = 0
        self._pending_request: tuple[int, str] | None = None

        if self.input_mode == "topic":
            self.control_status_publisher = self.create_publisher(
                String, self.navigation_status_topic, 10
            )
            self.busy_publisher = self.create_publisher(Bool, self.navigation_busy_topic, 10)
            self.mode_subscription = self.create_subscription(
                Int32, self.navigation_mode_topic, self.on_navigation_mode, 10
            )
            self.text_subscription = self.create_subscription(
                String, self.navigation_text_topic, self.on_navigation_text, 10
            )
            self._worker_thread = threading.Thread(
                target=self.topic_worker,
                name="llm_destination_worker",
                daemon=True,
            )
            self._worker_thread.start()

        names = ", ".join(sorted(self.points.keys())) or "(none)"
        self.get_logger().info(f"Loaded points from {self.points_file}: {names}")
        self.get_logger().info(f"Using prompt file: {self.prompt_file}")
        if self.input_mode == "topic":
            self.get_logger().info(
                "Topic control enabled: "
                f"mode={self.navigation_mode_topic}, text={self.navigation_text_topic}, "
                f"status={self.navigation_status_topic}, busy={self.navigation_busy_topic}"
            )
            self.publish_control_status("ready:mode=0")
            self.publish_busy(False)

    def on_status(self, message: String) -> None:
        print(f"[named_goal_status] {message.data}", flush=True)

    def publish_control_status(self, text: str) -> None:
        if self.control_status_publisher is not None:
            self.control_status_publisher.publish(String(data=text))
        self.get_logger().info(f"Navigation input status: {text}")

    def publish_busy(self, busy: bool) -> None:
        if self.busy_publisher is not None:
            self.busy_publisher.publish(Bool(data=busy))

    def queue_request_locked(self, text: str) -> int:
        self._request_sequence += 1
        sequence = self._request_sequence
        self._latest_request_sequence = sequence
        self._pending_request = (sequence, text)
        self._session_last_text = text
        self.publish_control_status(f"queued:{sequence}")
        self._worker_condition.notify()
        return sequence

    def on_navigation_mode(self, message: Int32) -> None:
        mode = int(message.data)
        if mode not in {0, 1}:
            self.get_logger().warn(f"Rejected NAVIGATION_MODE={mode}; expected 0 or 1")
            self.publish_control_status(f"rejected_mode:{mode}")
            return

        sequence = None
        cached_text = ""
        with self._worker_condition:
            if mode == 0:
                if not self._navigation_active:
                    return
                self._navigation_active = False
                self._session_last_text = None
                self._pending_request = None
                self._request_sequence += 1
                self._latest_request_sequence = self._request_sequence
                self._worker_condition.notify()
            else:
                if self._navigation_active:
                    return
                self._navigation_active = True
                self._session_last_text = None
                cached_text = self._cached_text
                if cached_text:
                    sequence = self.queue_request_locked(cached_text)

        if mode == 0:
            self.publish_busy(False)
            self.publish_control_status("mode_off")
        elif sequence is None:
            self.publish_control_status("mode_on:waiting_for_text")

    def on_navigation_text(self, message: String) -> None:
        text = message.data.strip()
        if not text:
            self.publish_control_status("rejected_text:empty")
            return

        sequence = None
        duplicate = False
        active = False
        with self._worker_condition:
            self._cached_text = text
            active = self._navigation_active
            if active:
                if text == self._session_last_text:
                    duplicate = True
                else:
                    sequence = self.queue_request_locked(text)

        if not active:
            self.publish_control_status("text_cached:waiting_for_mode")
        elif duplicate:
            self.publish_control_status("ignored:duplicate_text")

    def topic_worker(self) -> None:
        while True:
            with self._worker_condition:
                self._worker_condition.wait_for(
                    lambda: self._worker_stop or self._pending_request is not None
                )
                if self._worker_stop:
                    return
                request = self._pending_request
                self._pending_request = None

            if request is None:
                continue
            sequence, user_text = request
            self.publish_busy(True)
            self.publish_control_status(f"processing:{sequence}")

            try:
                point_name, raw_text = self.resolve_point_name(user_text)
            except Exception as exc:  # Keep the ROS node alive after API/network failures.
                point_name = None
                raw_text = f"{type(exc).__name__}: {exc}"

            with self._worker_condition:
                if self._worker_stop:
                    return
                if not self._navigation_active or sequence != self._latest_request_sequence:
                    self.publish_control_status(f"discarded_stale:{sequence}")
                    self.publish_busy(False)
                    continue
                if point_name is None:
                    self._session_last_text = None
                    detail = " ".join(raw_text.split())[:240]
                    self.publish_control_status(f"error:{sequence}:{detail}")
                    self.publish_busy(False)
                    continue
                self.history.append((user_text, point_name))
                self.history = self.history[-self.history_turns:]
                self.publish_named_goal(point_name)
                self.publish_control_status(f"goal_published:{sequence}:{point_name}")
                self.publish_busy(False)

    def stop_topic_worker(self) -> None:
        if self._worker_thread is None:
            return
        with self._worker_condition:
            self._worker_stop = True
            self._pending_request = None
            self._worker_condition.notify()
        self._worker_thread.join(timeout=22.0)

    def reload_points(self) -> None:
        self.points = load_points_csv(self.points_file)
        names = ", ".join(sorted(self.points.keys())) or "(none)"
        print(f"Reloaded points: {names}", flush=True)

    def format_points_block(self) -> str:
        lines = []
        for name in sorted(self.points.keys()):
            point = self.points[name]
            lines.append(
                f"- {name}: frame={point['frame_id']}, "
                f"x={point['x']:.3f}, y={point['y']:.3f}, yaw_deg={point['yaw_deg']:.1f}"
            )
        return "\n".join(lines)

    def format_history_block(self) -> str:
        if not self.history:
            return "(none)"
        recent = self.history[-self.history_turns :]
        lines = []
        for user_text, point_name in recent:
            lines.append(f"user: {user_text}")
            lines.append(f"assistant: {point_name}")
        return "\n".join(lines)

    def ensure_client(self):
        if self._client is not None:
            return self._client
        try:
            from openai import OpenAI
        except ModuleNotFoundError:
            return None

        self._client = OpenAI(max_retries=0)
        return self._client

    def call_model_via_http(self, user_text: str) -> str:
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY is not set")

        payload = {
            "model": self.model,
            "instructions": self.system_prompt,
            "input": (
                "Available destination points:\n"
                f"{self.format_points_block()}\n\n"
                "Recent conversation:\n"
                f"{self.format_history_block()}\n\n"
                "User request:\n"
                f"{user_text}\n\n"
                "Return exactly one destination point name from the list above."
            ),
            "max_output_tokens": self.max_output_tokens,
            "store": False,
        }

        request = urllib.request.Request(
            "https://api.openai.com/v1/responses",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(request, timeout=20.0) as response:
                body = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"HTTP {exc.code}: {detail[:240]}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"URL error: {exc}") from exc

        if body.get("status") != "completed":
            raise RuntimeError("LLM response incomplete or failed")
        output = body.get("output", [])
        for item in output:
            if item.get("type") != "message":
                continue
            for content in item.get("content", []):
                if content.get("type") == "output_text":
                    text = content.get("text", "")
                    if text:
                        return text

        raise RuntimeError(f"Could not extract output_text from response: {body}")

    def call_model(self, user_text: str) -> str:
        prompt = (
            "Available destination points:\n"
            f"{self.format_points_block()}\n\n"
            "Recent conversation:\n"
            f"{self.format_history_block()}\n\n"
            "User request:\n"
            f"{user_text}\n\n"
            "Return exactly one destination point name from the list above."
        )

        client = self.ensure_client()
        if client is None:
            return self.call_model_via_http(user_text)

        if hasattr(client, "responses"):
            response = client.responses.create(
                model=self.model,
                instructions=self.system_prompt,
                input=prompt,
                max_output_tokens=self.max_output_tokens,
                store=False,
                timeout=20.0,
            )
            if getattr(response, "status", None) != "completed":
                raise RuntimeError("LLM response incomplete or failed")
            return getattr(response, "output_text", "") or ""

        response = client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": prompt},
            ],
            max_completion_tokens=self.max_output_tokens,
            timeout=20.0,
        )
        return response.choices[0].message.content or ""

    def extract_valid_point(self, raw_text: str) -> str | None:
        candidate = raw_text.strip().strip('`"\' ')
        return candidate if candidate in self.points else None

    def resolve_point_name(self, user_text: str) -> tuple[str | None, str]:
        direct = normalize_candidate(user_text)
        if direct in self.points:
            return direct, direct

        if not os.getenv("OPENAI_API_KEY"):
            return None, "OPENAI_API_KEY is not set"

        raw_text = self.call_model(user_text)
        point_name = self.extract_valid_point(raw_text)
        return point_name, raw_text

    def publish_named_goal(self, point_name: str) -> None:
        self.goal_publisher.publish(String(data=point_name))
        point = self.points[point_name]
        print(
            "Published named goal: "
            f"{point_name} "
            f"(x={point['x']:.3f}, y={point['y']:.3f}, yaw_deg={point['yaw_deg']:.1f})",
            flush=True,
        )


def print_help() -> None:
    print(
        "Commands:\n"
        "  list              show available point names\n"
        "  reload            reload points CSV\n"
        "  help              show this help\n"
        "  quit / exit       quit the program\n"
        "  <text>            natural language destination request\n"
        "  <point_name>      direct exact point name\n",
        flush=True,
    )


def main() -> None:
    rclpy.init()
    node = TextLLMNamedGoal()

    if node.input_mode == "topic":
        try:
            rclpy.spin(node)
        except KeyboardInterrupt:
            pass
        finally:
            node.stop_topic_worker()
            node.destroy_node()
            if rclpy.ok():
                rclpy.shutdown()
        return

    spin_thread = threading.Thread(target=rclpy.spin, args=(node,), daemon=True)
    spin_thread.start()

    try:
        print(f"Points file: {node.points_file}", flush=True)
        print(f"Prompt file: {node.prompt_file}", flush=True)
        print(f"Goal topic: {node.goal_topic}", flush=True)
        print(f"Model: {node.model}", flush=True)
        print(f"OPENAI_API_KEY set: {'yes' if bool(os.getenv('OPENAI_API_KEY')) else 'no'}", flush=True)
        print_help()

        while True:
            try:
                user_text = input("destination> ").strip()
            except EOFError:
                break

            if not user_text:
                continue
            if user_text in {"quit", "exit"}:
                break
            if user_text == "help":
                print_help()
                continue
            if user_text == "list":
                print(", ".join(sorted(node.points.keys())) or "(none)", flush=True)
                continue
            if user_text == "reload":
                node.reload_points()
                continue

            point_name, raw_text = node.resolve_point_name(user_text)
            if point_name is None:
                print(f"Could not resolve destination. Model/raw output: {raw_text}", flush=True)
                continue

            node.history.append((user_text, point_name))
            print(f"LLM selected point: {point_name}", flush=True)
            node.publish_named_goal(point_name)

    except KeyboardInterrupt:
        pass
    finally:
        if rclpy.ok():
            rclpy.shutdown()
        spin_thread.join(timeout=2.0)
        node.destroy_node()


if __name__ == "__main__":
    main()
