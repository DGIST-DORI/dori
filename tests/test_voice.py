#!/usr/bin/env python3
"""
E2E (End-to-End) Test Client for STT -> LLM -> TTS Pipeline.
BehaviorTree 통합 전, 로컬 환경에서 음성 대화 파이프라인을 검증하기 위한 임시 노드입니다.
"""

import json
import rclpy
from rclpy.node import Node
from rclpy.action import ActionClient
from std_msgs.msg import String

from dori_msgs.action import LLMQuery, Speak


class E2ETestClient(Node):
    def __init__(self):
        super().__init__('e2e_test_client')

        # 1. STT 결과 구독 (stt_node.py에서 발행)
        self.stt_sub = self.create_subscription(
            String, 
            'stt/result', 
            self.stt_callback, 
            10
        )

        # 2. LLM 및 TTS Action Client 초기화
        # (노드 실행 시 파라미터로 설정된 액션 이름에 맞게 수정하세요)
        self.llm_client = ActionClient(self, LLMQuery, 'llm/query')
        self.tts_client = ActionClient(self, Speak, 'tts/speak')

        # 상태 제어 (한 번에 하나의 대화만 처리하도록 락 역할)
        self.is_processing = False

        self.get_logger().info('======================================')
        self.get_logger().info('E2E Test Client Started!')
        self.get_logger().info('마이크에 대고 호출어와 함께 말해보세요.')
        self.get_logger().info('======================================')

    def stt_callback(self, msg: String):
        """STT 노드에서 텍스트가 들어오면 실행됩니다."""
        if self.is_processing:
            self.get_logger().warn('현재 다른 응답을 처리 중입니다. STT 입력을 무시합니다.')
            return

        try:
            data = json.loads(msg.data)
            user_text = data.get('text', '').strip()
            event = data.get('event', '')
        except json.JSONDecodeError:
            self.get_logger().error('STT 메시지 JSON 파싱 실패')
            return

        if event == 'stt_result' and user_text:
            self.get_logger().info(f'[STT 인식됨]: "{user_text}"')
            self.is_processing = True
            self.send_llm_goal(user_text)

    # --- 1단계: LLM 서버로 목표 전송 ---
    def send_llm_goal(self, text: str):
        if not self.llm_client.wait_for_server(timeout_sec=3.0):
            self.get_logger().error('LLM Action Server를 찾을 수 없습니다!')
            self.is_processing = False
            return

        self.get_logger().info('[LLM] 의도 분석 및 답변 생성 중...')
        goal_msg = LLMQuery.Goal()
        goal_msg.text = text
        goal_msg.location_context = '로비'  # 테스트용 하드코딩

        send_goal_future = self.llm_client.send_goal_async(goal_msg)
        send_goal_future.add_done_callback(self.llm_goal_response_callback)

    def llm_goal_response_callback(self, future):
        goal_handle = future.result()
        if not goal_handle.accepted:
            self.get_logger().error('LLM Action Goal이 거부되었습니다.')
            self.is_processing = False
            return

        result_future = goal_handle.get_result_async()
        result_future.add_done_callback(self.llm_result_callback)

    def llm_result_callback(self, future):
        """LLM 처리가 완료되면 TTS로 넘깁니다."""
        result = future.result().result
        
        if result.intent == 'error':
            self.get_logger().error('LLM 처리 중 에러 발생')
            self.is_processing = False
            return

        self.get_logger().info(f"[LLM 완료] 의도: {result.intent}, 목적지: {result.target_location}")
        self.get_logger().info(f"[LLM 답변]: {result.response_text}")

        # LLM이 만든 답변 텍스트를 TTS로 전송
        self.send_tts_goal(result.response_text)

    # --- 2단계: TTS 서버로 목표 전송 ---
    def send_tts_goal(self, text: str):
        if not self.tts_client.wait_for_server(timeout_sec=3.0):
            self.get_logger().error('TTS Action Server를 찾을 수 없습니다!')
            self.is_processing = False
            return

        self.get_logger().info('🔊 [TTS] 음성 합성 및 재생 시작...')
        goal_msg = Speak.Goal()
        goal_msg.text = text

        send_goal_future = self.tts_client.send_goal_async(goal_msg)
        send_goal_future.add_done_callback(self.tts_goal_response_callback)

    def tts_goal_response_callback(self, future):
        goal_handle = future.result()
        if not goal_handle.accepted:
            self.get_logger().error('TTS Action Goal이 거부되었습니다.')
            self.is_processing = False
            return

        result_future = goal_handle.get_result_async()
        result_future.add_done_callback(self.tts_result_callback)

    def tts_result_callback(self, future):
        """TTS 재생이 완전히 끝났을 때 호출됩니다."""
        # result = future.result().result (필요 시 TTS의 성공 여부 확인)
        self.get_logger().info('[TTS 재생 완료] 파이프라인 종료. 다음 입력을 대기합니다.\n')
        
        # 락 해제 (다음 대화 가능)
        self.is_processing = False


def main(args=None):
    rclpy.init(args=args)
    node = E2ETestClient()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()

if __name__ == '__main__':
    main()
