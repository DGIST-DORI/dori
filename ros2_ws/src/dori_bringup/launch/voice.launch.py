"""HRI voice actions share the same namespace as the BT and dashboard."""

import os
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.conditions import IfCondition
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    hri_share_dir = get_package_share_directory("dori_hri")
    model_dir = os.path.join(hri_share_dir, "models")
    # custom_wake_words = f"{model_dir}/doriya.onnx,{model_dir}/hey_dori.onnx"
    custom_wake_words = f"{model_dir}/hey_dori.onnx"

    defaults = dict(
        namespace="/dori",
        enable_stt="true",
        use_external_llm="false",
        knowledge_file="",
        rag_index_dir="",
        llm_model="gemini-2.5-flash",
        rag_top_k="3",
        whisper_model="small",
        whisper_device="cpu",
        wake_word=custom_wake_words,
        stt_audio_input_mode="microphone",
        tts_engine="gtts",
        tts_language="ko",
        tts_playback_mode="local_only",
        sfx_base_path="",
    )
    arg = LaunchConfiguration
    common = dict(namespace=arg("namespace"), output="screen")
    return LaunchDescription(
        [DeclareLaunchArgument(k, default_value=v) for k, v in defaults.items()]
        + [
            Node(
                package="dori_hri",
                executable="stt_node",
                name="stt_node",
                **common,
                condition=IfCondition(arg("enable_stt")),
                parameters=[
                    {
                        "wake_word": arg("wake_word"),
                        "whisper_model": arg("whisper_model"),
                        "whisper_device": arg("whisper_device"),
                        "audio_input_mode": arg("stt_audio_input_mode"),
                    }
                ],
            ),
            Node(
                package="dori_llm",
                executable="llm_node",
                name="llm_node",
                **common,
                parameters=[
                    {
                        "use_external_llm": arg("use_external_llm"),
                        "knowledge_file": arg("knowledge_file"),
                        "rag_index_dir": arg("rag_index_dir"),
                        "model_name": arg("llm_model"),
                        "rag_top_k": arg("rag_top_k"),
                        "action_name": "llm/query",
                    }
                ],
            ),
            Node(
                package="dori_hri",
                executable="tts_node",
                name="tts_node",
                **common,
                parameters=[
                    {
                        "tts_engine": arg("tts_engine"),
                        "language": arg("tts_language"),
                        "action_name": "tts/speak",
                        "playback_mode": arg("tts_playback_mode"),
                        "sfx.base_path": arg("sfx_base_path"),
                    }
                ],
            ),
        ]
    )
