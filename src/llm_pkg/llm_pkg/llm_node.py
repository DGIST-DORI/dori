import rclpy
from rclpy.node import Node
from std_msgs.msg import String, Bool
from geometry_msgs.msg import PoseStamped

import json
import re
from typing import Dict, List, Optional
from dataclasses import dataclass
import numpy as np


@dataclass
class Location:
    name: str
    description: str
    coordinates: tuple
    keywords: List[str]


class CampusKnowledgeBase: # knowledge base for the lightweight RAG
    def __init__(self, knowledge_file: str = None):
        self.locations: Dict[str, Location] = {}
        self.faqs: Dict[str, str] = {}
        
        if knowledge_file:
            self.load_knowledge(knowledge_file)
        else:
            self._init_default_knowledge()
    
    def _init_default_knowledge(self): # example (for testing)
        self.locations = {
            "도서관": Location(
                name="도서관",
                description="중앙도서관입니다. 24시간 운영하며 열람실과 그룹스터디룸이 있습니다.",
                coordinates=(37.5, 127.0),
                keywords=["도서관", "책", "공부", "열람실", "library"]
            ),
            "학생식당": Location(
                name="학생식당",
                description="학생식당입니다. 조식 8-9시, 중식 11:30-13:30, 석식 17:30-19:00 운영합니다.",
                coordinates=(37.51, 127.01),
                keywords=["식당", "밥", "식사", "cafeteria", "먹"]
            ),
            "공학관": Location(
                name="공학관",
                description="공과대학 건물입니다. 실험실과 강의실이 있습니다.",
                coordinates=(37.49, 126.99),
                keywords=["공학관", "공대", "engineering"]
            )
        }
        
        self.faqs = {
            "운영시간": "저는 평일 오전 9시부터 오후 6시까지 캠퍼스 투어를 제공합니다.",
            "기능": "캠퍼스 안내, 길 찾기, 건물 정보 제공 등을 할 수 있습니다.",
            "날씨": "죄송하지만 현재 날씨 정보는 제공하지 않습니다."
        }
    
    def load_knowledge(self, filepath: str): # load knowledge from json file
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
                # TODO: JSON parsing logic
        except Exception as e:
            print(f"Failed to load knowledge: {e}")
            self._init_default_knowledge()
    
    def search_location(self, query: str) -> Optional[Location]: # search location based on keywords
        query_lower = query.lower()
        
        for loc in self.locations.values():
            if loc.name in query:
                return loc
        
        best_match = None
        max_score = 0
        
        for loc in self.locations.values():
            score = sum(1 for kw in loc.keywords if kw in query_lower)
            if score > max_score:
                max_score = score
                best_match = loc
        
        return best_match if max_score > 0 else None
    
    def search_faq(self, query: str) -> Optional[str]: # search faq
        query_lower = query.lower()
        for key, answer in self.faqs.items():
            if key in query_lower:
                return answer
        return None


class IntentClassifier:    
    INTENT_PATTERNS = {
        "navigation": [
            r"(가|찾|어디|where|how to get)",
            r"(길|route|way)",
            r"(안내|guide)"
        ],
        "information": [
            r"(무엇|what|설명|explain|소개|introduce)",
            r"(어떤|which|뭐|무슨)"
        ],
        "greeting": [
            r"^(안녕|hello|hi|hey)",
        ],
        "thanks": [
            r"(고마|감사|thank)"
        ]
    }
    
    @classmethod
    def classify(cls, text: str) -> str:
        text_lower = text.lower()
        
        for intent, patterns in cls.INTENT_PATTERNS.items():
            for pattern in patterns:
                if re.search(pattern, text_lower):
                    return intent
        
        return "general"


class LLMNode(Node):
    def __init__(self):
        super().__init__('llm_node')
        
        # Parameters
        self.declare_parameter('knowledge_file', '')
        self.declare_parameter('use_external_llm', False)  # True: using API
        self.declare_parameter('model_name', 'gpt-3.5-turbo')
        
        knowledge_file = self.get_parameter('knowledge_file').value
        self.use_external_llm = self.get_parameter('use_external_llm').value
        
        # Knowledge base
        self.kb = CampusKnowledgeBase(knowledge_file if knowledge_file else None)
        
        # LLM (external API 사용 시)
        if self.use_external_llm:
            self._init_llm_client()
        
        # ROS Publishers
        self.response_pub = self.create_publisher(String, '/llm/response', 10)
        self.destination_pub = self.create_publisher(PoseStamped, '/navigation/destination', 10)
        self.speaking_pub = self.create_publisher(Bool, '/robot/speaking', 10)
        
        # ROS Subscribers
        self.stt_sub = self.create_subscription(
            String,
            '/stt/text',
            self.stt_callback,
            10
        )
        
        # State
        self.conversation_history = []
        self.current_destination = None
        
        self.get_logger().info("LLM node started")
    
    def _init_llm_client(self):
        # TODO: API client initialize
        self.get_logger().info("External LLM API initialized")
    
    def stt_callback(self, msg: String):
        user_text = msg.data
        self.get_logger().info(f"Received: {user_text}")
        
        self.speaking_pub.publish(Bool(data=True)) # publish that the robot is talking
        
        response = self.generate_response(user_text)

        self.response_pub.publish(String(data=response))
        self.get_logger().info(f"Response: {response}")
        
        self.conversation_history.append({
            "user": user_text,
            "assistant": response
        })
        
        # speaking done (if TTS is done, must be changed to False)
        # TODO: done signal from TTS node
        self.create_timer(3.0, lambda: self.speaking_pub.publish(Bool(data=False)))
    
    def generate_response(self, user_text: str) -> str:
        # Classify intent
        intent = IntentClassifier.classify(user_text)
        self.get_logger().info(f"Intent: {intent}")
        
        # handle
        if intent == "greeting":
            return self._handle_greeting()
        
        elif intent == "thanks":
            return "천만에요! 더 도움이 필요하시면 말씀해주세요."
        
        elif intent == "navigation":
            return self._handle_navigation(user_text)
        
        elif intent == "information":
            return self._handle_information(user_text)
        
        else:
            return self._handle_general(user_text)
    
    def _handle_greeting(self) -> str:
        return "안녕하세요! 저는 캠퍼스 안내 로봇입니다. 어디로 안내해드릴까요?"
    
    def _handle_navigation(self, text: str) -> str:
        location = self.kb.search_location(text)
        
        if location:
            self._set_destination(location)
            return f"{location.name}(으)로 안내하겠습니다. {location.description}"
        else:
            return "죄송합니다. 해당 장소를 찾을 수 없습니다. 다시 말씀해주시겠어요?"
    
    def _handle_information(self, text: str) -> str:
        faq_answer = self.kb.search_faq(text)
        if faq_answer:
            return faq_answer
        
        location = self.kb.search_location(text)
        if location:
            return location.description
        
        return "죄송합니다. 해당 정보를 찾을 수 없습니다."
    
    def _handle_general(self, text: str) -> str:
        if self.use_external_llm:
            return self._call_external_llm(text)
        else:
            return "죄송합니다. 이해하지 못했습니다. 다시 말씀해주시겠어요?"
    
    def _call_external_llm(self, text: str) -> str:
        """외부 LLM API 호출"""
        # TODO: call OpenAI ...
        # with conv hist and campus context
        system_prompt = """당신은 대학 캠퍼스 안내 로봇입니다. 
        친절하고 간결하게 답변하며, 캠퍼스 관련 질문에 답변합니다.
        모르는 내용은 솔직히 모른다고 말합니다."""
        
        # API 호출 로직
        return "external LLM response"
    
    def _set_destination(self, location: Location):
        pose = PoseStamped()
        pose.header.stamp = self.get_clock().now().to_msg()
        pose.header.frame_id = "map"
        pose.pose.position.x = location.coordinates[0]
        pose.pose.position.y = location.coordinates[1]
        pose.pose.position.z = 0.0
        pose.pose.orientation.w = 1.0
        
        self.destination_pub.publish(pose)
        self.current_destination = location.name
        self.get_logger().info(f"Destination set: {location.name}")


def main():
    rclpy.init()
    node = LLMNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
