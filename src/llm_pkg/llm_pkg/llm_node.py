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
    def __init__(self, knowledge_file: str = None, logger=None):
        self.locations: Dict[str, Location] = {}
        self.faqs: Dict[str, str] = {}
        self.logger = logger
        
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
                
                # JSON parsing logic
                if 'locations' in data:
                    for key, loc_data in data['locations'].items():
                        if not key or not key.strip():
                            continue

                        name = loc_data.get('name', key)
                        if not name or not name.strip():
                            continue
                        
                        self.locations[key] = Location(
                            name=loc_data.get('name', key),
                            description=loc_data.get('description', ''),
                            coordinates=tuple(loc_data.get('coordinates', [0.0, 0.0])),
                            keywords=loc_data.get('keywords', [])
                        )
            
                if 'faqs' in data:
                    self.faqs = {k: v for k, v in data['faqs'].items() if k and v}
                
                if self.logger:
                    self.logger.info(f"Loaded {len(self.locations)} locations and {len(self.faqs)} FAQs")
        
        except FileNotFoundError:
            if self.logger:
                self.logger.error(f"Knowledge file not found: {filepath}")
            self._init_default_knowledge()
        except json.JSONDecodeError as e:
            if self.logger:
                self.logger.error(f"JSON decode error: {e}")
            self._init_default_knowledge()
        except Exception as e:
            if self.logger:
                self.logger.error(f"Failed to load knowledge: {e}")
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
            r"(가|찾|어디|where|how to get|take me|guide me)",
            r"(길|route|way|direction)",
            r"(안내|guide|show)"
        ],
        "information": [
            r"(무엇|what|설명|explain|소개|introduce|tell me)",
            r"(어떤|which|뭐|무슨|what kind)"
        ],
        "greeting": [
            r"^(안녕|hello|hi|hey|greetings)",
        ],
        "thanks": [
            r"(고마|감사|thank|appreciate)"
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
        self.declare_parameter('confidence_threshold', 0.4)
        self.declare_parameter('api_key', '')
        
        knowledge_file = self.get_parameter('knowledge_file').value
        self.use_external_llm = self.get_parameter('use_external_llm').value
        self.model_name = self.get_parameter('model_name').value
        self.confidence_threshold = self.get_parameter('confidence_threshold').value
        api_key = self.get_parameter('api_key').value
        
        # Knowledge base
        self.kb = CampusKnowledgeBase(knowledge_file if knowledge_file else None, self.get_logger())
        
        # LLM (external API client)
        self.llm_client = None
        if self.use_external_llm:
            self._init_llm_client(api_key)
        
        # ROS Publishers
        self.response_pub = self.create_publisher(String, '/llm/response', 10)
        self.destination_pub = self.create_publisher(PoseStamped, '/navigation/destination', 10)
        self.speaking_pub = self.create_publisher(Bool, '/dori/speaking', 10)
        
        # ROS Subscribers
        self.stt_sub = self.create_subscription(
            String,
            '/stt/text',
            self.stt_callback,
            10
        )

        self.tts_done_sub = self.create_subscription(
            Bool,
            '/tts/done',
            self.tts_done_callback,
            10
        )
        
        # State
        self.conversation_history = []
        self.current_destination = None
        self.current_language = "ko"
        self.is_speaking = False
        
        self.get_logger().info("LLM node started")
    
    def _init_llm_client(self):
        try:
            if 'gpt' in self.model_name.lower(): # OpenAI API
                import openai
                self.llm_client = openai.OpenAI(api_key=api_key or None)
                self.llm_type = 'openai'
                self.get_logger().info(f"OpenAI API initialized with model: {self.model_name}")
                
            elif 'claude' in self.model_name.lower(): # Anthropic Claude API
                import anthropic
                self.llm_client = anthropic.Anthropic(api_key=api_key or None)
                self.llm_type = 'claude'
                self.get_logger().info(f"Claude API initialized with model: {self.model_name}")
                
            else:
                self.get_logger().warn(f"Unknown model: {self.model_name}, falling back to rule-based")
                self.use_external_llm = False
                
        except ImportError as e:
            self.get_logger().error(f"Failed to import LLM library: {e}")
            self.use_external_llm = False
        except Exception as e:
            self.get_logger().error(f"Failed to initialize LLM client: {e}")
            self.use_external_llm = False
    
    def stt_callback(self, msg: String):
        try:
            data = json.loads(msg.data)
            user_text = data.get("text", "")
            confidence = data.get("confidence", 0.0)
            language = data.get("language", "unknown")

            self.current_language = language
            
            self.get_logger().info(f"Received [{language}] (conf: {confidence:.2f}): {user_text}")
            
            if confidence < self.confidence_threshold:
                self.get_logger().warn("Low confidence ({confidence:.2f}), ignoring...")
                return
            
        except json.JSONDecodeError:
            user_text = msg.data
            self.get_logger().info(f"Received: {user_text}")
        
        if not user_text or not user_text.strip():
            return
        
        self.is_speaking = True
        self.speaking_pub.publish(Bool(data=True)) # publish that the robot is talking
        
        response = self.generate_response(user_text)

        self.response_pub.publish(String(data=response))
        self.get_logger().info(f"Response: {response}")
        
        self.conversation_history.append({
            "user": user_text,
            "assistant": response,
            "language": self.current_language
        })
        
        # speaking done (if TTS is done, must be changed to False)
        # TODO: done signal from TTS node

    def tts_done_callback(self, msg: Bool):
        if msg.data:
            self.is_speaking = False
            self.speaking_pub.publish(Bool(data=False))
            self.get_logger().info("TTS done, robot is silent now.")
    
    def generate_response(self, user_text: str) -> str:
        # Classify intent
        intent = IntentClassifier.classify(user_text)
        self.get_logger().info(f"Intent: {intent}")
        
        # handle
        if intent == "greeting":
            return self._get_localized_response("greeting")
        
        elif intent == "thanks":
            return self._get_localized_response("thanks")
        
        elif intent == "navigation":
            return self._handle_navigation(user_text)
        
        elif intent == "information":
            return self._handle_information(user_text)
        
        else:
            return self._handle_general(user_text)
    
    def _get_localized_response(self, key: str) -> str:
        """언어별 응답"""
        responses = {
            "greeting": {
                "ko": "안녕하세요! 저는 캠퍼스 안내 로봇입니다. 어디로 안내해드릴까요?",
                "en": "Hello! I'm the campus guide robot. Where would you like to go?"
            },
            "thanks": {
                "ko": "천만에요! 더 도움이 필요하시면 말씀해주세요.",
                "en": "You're welcome! Let me know if you need more help."
            },
            "not_found": {
                "ko": "죄송합니다. 해당 장소를 찾을 수 없습니다. 다시 말씀해주시겠어요?",
                "en": "Sorry, I couldn't find that location. Could you say it again?"
            },
            "no_info": {
                "ko": "죄송합니다. 해당 정보를 찾을 수 없습니다.",
                "en": "Sorry, I couldn't find that information."
            },
            "no_understand": {
                "ko": "죄송합니다. 이해하지 못했습니다. 다시 말씀해주시겠어요?",
                "en": "Sorry, I didn't understand. Could you please repeat?"
            }
        }
        
        lang = "ko" if self.current_language == "ko" else "en"
        return responses.get(key, {}).get(lang, responses[key]["ko"])
    
    def _handle_navigation(self, text: str) -> str:
        location = self.kb.search_location(text)
        
        if location:
            self._set_destination(location)
            
            if self.current_language == "en":
                return f"I'll guide you to {location.name}. {location.description}"
            else:
                return f"{location.name}(으)로 안내하겠습니다. {location.description}"
        else:
            return self._get_localized_response("not_found")
    
    def _handle_information(self, text: str) -> str:
        faq_answer = self.kb.search_faq(text)
        if faq_answer:
            return faq_answer
        
        location = self.kb.search_location(text)
        if location:
            return location.description
        
        return self._get_localized_response("no_info")
    
    def _handle_general(self, text: str) -> str:
        if self.use_external_llm:
            return self._call_external_llm(text)
        else:
            return self._get_localized_response("no_understand")
    
    def _call_external_llm(self, text: str) -> str:
        try:
            system_prompt = self._build_system_prompt()
            
            messages = self._build_message_history(text)
            
            if self.llm_type == 'openai':
                response = self.llm_client.chat.completions.create(
                    model=self.model_name,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        *messages
                    ],
                    temperature=0.7,
                    max_tokens=200
                )
                return response.choices[0].message.content.strip()
                
            elif self.llm_type == 'claude':
                response = self.llm_client.messages.create(
                    model=self.model_name,
                    system=system_prompt,
                    messages=messages,
                    max_tokens=200,
                    temperature=0.7
                )
                return response.content[0].text.strip()
            
        except Exception as e:
            self.get_logger().error(f"LLM API call failed: {e}")
            return self._get_localized_response("no_understand")
    
    def _build_system_prompt(self) -> str:
        locations_str = ", ".join(self.kb.locations.keys())
        
        if self.current_language == "en":
            return f"""You are a university campus guide robot. 
            Be friendly, concise, and helpful.
            Available locations: {locations_str}
            Answer questions about campus locations, facilities, and services.
            If you don't know something, honestly say so."""
        else:
            return f"""당신은 대학 캠퍼스 안내 로봇입니다. 
            친절하고 간결하게 답변하며, 캠퍼스 관련 질문에 답변합니다.
            이용 가능한 장소: {locations_str}
            캠퍼스 위치, 시설, 서비스에 대한 질문에 답변하세요.
            모르는 내용은 솔직히 모른다고 말합니다."""
    
    def _build_message_history(self, current_text: str) -> list:
        messages = []
        
        # recent three conversations
        for conv in self.conversation_history[-3:]:
            messages.append({"role": "user", "content": conv["user"]})
            messages.append({"role": "assistant", "content": conv["assistant"]})
        
        messages.append({"role": "user", "content": current_text})
        
        return messages

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
