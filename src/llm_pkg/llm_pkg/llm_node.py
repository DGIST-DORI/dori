#!/usr/bin/env python3
"""
Intent classification + RAG-based campus knowledge retrieval + LLM response generation.

Subscribe topics:
  /dori/llm/query        (String) - JSON from HRI Manager: {user_text, location_context, ...}

Publish topics:
  /dori/llm/response     (String) - generated response text (consumed by TTS node)
  /dori/nav/destination  (PoseStamped) - navigation goal when intent is navigation
"""

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

import rclpy
from geometry_msgs.msg import PoseStamped
from rclpy.node import Node
from std_msgs.msg import String


@dataclass
class Location:
    name: str
    description: str
    coordinates: tuple
    keywords: List[str] = field(default_factory=list)


class CampusKnowledgeBase:
    """Lightweight RAG knowledge base for campus locations and FAQs."""

    def __init__(self, knowledge_file: Optional[str] = None, logger=None):
        self.locations: Dict[str, Location] = {}
        self.faqs: Dict[str, str] = {}
        self.logger = logger

        if knowledge_file and Path(knowledge_file).exists():
            self._load(knowledge_file)
        else:
            self._init_defaults()

    def _init_defaults(self):
        """Fallback knowledge used when no JSON file is provided."""
        self.locations = {
            'library': Location(
                name='도서관',
                description='중앙도서관입니다. 24시간 운영하며 열람실과 그룹스터디룸이 있습니다.',
                coordinates=(37.5, 127.0),
                keywords=['도서관', '책', '공부', '열람실', 'library'],
            ),
            'cafeteria': Location(
                name='학생식당',
                description='학생식당입니다. 조식 8-9시, 중식 11:30-13:30, 석식 17:30-19:00 운영합니다.',
                coordinates=(37.51, 127.01),
                keywords=['식당', '밥', '식사', 'cafeteria', '먹'],
            ),
            'engineering': Location(
                name='공학관',
                description='공과대학 건물입니다. 실험실과 강의실이 있습니다.',
                coordinates=(37.49, 126.99),
                keywords=['공학관', '공대', 'engineering'],
            ),
        }
        self.faqs = {
            '운영시간': '저는 평일 오전 9시부터 오후 6시까지 캠퍼스 투어를 제공합니다.',
            '기능': '캠퍼스 안내, 길 찾기, 건물 정보 제공 등을 할 수 있습니다.',
        }

    def _load(self, filepath: str):
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)

            for key, loc in data.get('locations', {}).items():
                name = loc.get('name', key)
                if not name:
                    continue
                self.locations[key] = Location(
                    name=name,
                    description=loc.get('description', ''),
                    coordinates=tuple(loc.get('coordinates', [0.0, 0.0])),
                    keywords=loc.get('keywords', []),
                )

            self.faqs = {k: v for k, v in data.get('faqs', {}).items() if k and v}

            if self.logger:
                self.logger.info(
                    f'Knowledge base loaded: {len(self.locations)} locations, '
                    f'{len(self.faqs)} FAQs'
                )
        except Exception as e:
            if self.logger:
                self.logger.error(f'Failed to load knowledge file: {e}')
            self._init_defaults()

    def search_location(self, query: str) -> Optional[Location]:
        query_lower = query.lower()

        # Exact name match first
        for loc in self.locations.values():
            if loc.name in query:
                return loc

        # Keyword scoring
        best, max_score = None, 0
        for loc in self.locations.values():
            score = sum(1 for kw in loc.keywords if kw in query_lower)
            if score > max_score:
                max_score, best = score, loc

        return best if max_score > 0 else None

    def search_faq(self, query: str) -> Optional[str]:
        query_lower = query.lower()
        for key, answer in self.faqs.items():
            if key in query_lower:
                return answer
        return None


class IntentClassifier:
    """Rule-based intent classifier using regex patterns."""

    PATTERNS = {
        'navigation': [
            r'(가|찾|어디|where|how to get|take me|guide me)',
            r'(길|route|way|direction)',
            r'(안내|guide|show)',
        ],
        'information': [
            r'(무엇|what|설명|explain|소개|introduce|tell me)',
            r'(어떤|which|뭐|무슨|what kind)',
        ],
        'greeting': [
            r'^(안녕|hello|hi|hey)',
        ],
        'thanks': [
            r'(고마|감사|thank|appreciate)',
        ],
    }

    @classmethod
    def classify(cls, text: str) -> str:
        text_lower = text.lower()
        for intent, patterns in cls.PATTERNS.items():
            for pattern in patterns:
                if re.search(pattern, text_lower):
                    return intent
        return 'general'


class LLMNode(Node):
    def __init__(self):
        super().__init__('llm_node')

        # Parameters
        self.declare_parameter('knowledge_file', '')
        self.declare_parameter('use_external_llm', False)
        self.declare_parameter('model_name', 'claude-sonnet-4-6')
        self.declare_parameter('api_key', '')
        self.declare_parameter('confidence_threshold', 0.4)

        knowledge_file      = self.get_parameter('knowledge_file').value
        self.use_external   = self.get_parameter('use_external_llm').value
        self.model_name     = self.get_parameter('model_name').value
        api_key             = self.get_parameter('api_key').value
        self.conf_threshold = self.get_parameter('confidence_threshold').value

        # Knowledge base
        self.kb = CampusKnowledgeBase(
            knowledge_file or None, self.get_logger()
        )

        # External LLM client (optional)
        self.llm_client = None
        self.llm_type   = None
        if self.use_external:
            self._init_llm_client(api_key)

        # State
        self.conversation_history: list = []
        self.current_language: str = 'ko'
        self.current_location_context: str = ''

        # Subscribers
        # Primary input: routed through HRI Manager
        self.create_subscription(
            String, '/dori/llm/query', self._on_query, 10)

        # Publishers
        self.response_pub     = self.create_publisher(String,      '/dori/llm/response', 10)
        self.destination_pub  = self.create_publisher(PoseStamped, '/dori/nav/destination', 10)

        self.get_logger().info('LLM Node started')

    # LLM client initialization
    def _init_llm_client(self, api_key: str):
        """Initialize external LLM API client based on model_name."""
        try:
            if 'gpt' in self.model_name.lower():
                import openai
                self.llm_client = openai.OpenAI(api_key=api_key or None)
                self.llm_type = 'openai'
                self.get_logger().info(f'OpenAI client ready: {self.model_name}')

            elif 'claude' in self.model_name.lower():
                import anthropic
                self.llm_client = anthropic.Anthropic(api_key=api_key or None)
                self.llm_type = 'claude'
                self.get_logger().info(f'Anthropic client ready: {self.model_name}')

            else:
                self.get_logger().warn(
                    f'Unknown model "{self.model_name}" — falling back to rule-based'
                )
                self.use_external = False

        except ImportError as e:
            self.get_logger().error(f'LLM library not found: {e}')
            self.use_external = False
        except Exception as e:
            self.get_logger().error(f'LLM client init failed: {e}')
            self.use_external = False

    # Query callback
    def _on_query(self, msg: String):
        """
        Receive query from HRI Manager.
        Expected JSON: {user_text, location_context, hri_state, timestamp}
        """
        try:
            data = json.loads(msg.data)
            user_text = data.get('user_text', '').strip()
            self.current_location_context = data.get('location_context', '')
        except (json.JSONDecodeError, AttributeError):
            user_text = msg.data.strip()

        if not user_text:
            return

        self.get_logger().info(f'Query received: "{user_text}"')

        response = self._generate_response(user_text)

        resp_msg = String()
        resp_msg.data = response
        self.response_pub.publish(resp_msg)
        self.get_logger().info(f'Response: "{response}"')

        self.conversation_history.append({
            'user':      user_text,
            'assistant': response,
            'language':  self.current_language,
        })

    # Response generation
    def _generate_response(self, user_text: str) -> str:
        intent = IntentClassifier.classify(user_text)
        self.get_logger().info(f'Intent: {intent}')

        if intent == 'greeting':
            return self._localized('greeting')
        if intent == 'thanks':
            return self._localized('thanks')
        if intent == 'navigation':
            return self._handle_navigation(user_text)
        if intent == 'information':
            return self._handle_information(user_text)

        # general: try external LLM, else fallback
        return self._handle_general(user_text)

    def _handle_navigation(self, text: str) -> str:
        location = self.kb.search_location(text)
        if location:
            self._publish_destination(location)
            if self.current_language == 'en':
                return f"I'll guide you to {location.name}. {location.description}"
            return f'{location.name}(으)로 안내하겠습니다. {location.description}'
        return self._localized('not_found')

    def _handle_information(self, text: str) -> str:
        answer = self.kb.search_faq(text)
        if answer:
            return answer
        location = self.kb.search_location(text)
        if location:
            return location.description
        return self._localized('no_info')

    def _handle_general(self, text: str) -> str:
        if self.use_external and self.llm_client:
            return self._call_external_llm(text)
        return self._localized('no_understand')

    def _call_external_llm(self, text: str) -> str:
        try:
            system_prompt = self._build_system_prompt()
            messages = self._build_messages(text)

            if self.llm_type == 'openai':
                resp = self.llm_client.chat.completions.create(
                    model=self.model_name,
                    messages=[{'role': 'system', 'content': system_prompt}, *messages],
                    temperature=0.7,
                    max_tokens=200,
                )
                return resp.choices[0].message.content.strip()

            elif self.llm_type == 'claude':
                resp = self.llm_client.messages.create(
                    model=self.model_name,
                    system=system_prompt,
                    messages=messages,
                    max_tokens=200,
                )
                return resp.content[0].text.strip()

        except Exception as e:
            self.get_logger().error(f'External LLM call failed: {e}')
        return self._localized('no_understand')

    def _build_system_prompt(self) -> str:
        locations_str = ', '.join(self.kb.locations.keys())
        location_hint = (
            f' Current location context: {self.current_location_context}.'
            if self.current_location_context else ''
        )
        if self.current_language == 'en':
            return (
                f'You are DORI, a university campus guide robot. '
                f'Be friendly and concise. Available locations: {locations_str}.'
                f'{location_hint}'
            )
        return (
            f'당신은 DORI, 대학 캠퍼스 안내 로봇입니다. '
            f'친절하고 간결하게 답변하세요. 안내 가능한 장소: {locations_str}.'
            f'{location_hint}'
        )

    def _build_messages(self, current_text: str) -> list:
        messages = []
        for conv in self.conversation_history[-3:]:
            messages.append({'role': 'user',      'content': conv['user']})
            messages.append({'role': 'assistant', 'content': conv['assistant']})
        messages.append({'role': 'user', 'content': current_text})
        return messages

    # Helpers
    def _localized(self, key: str) -> str:
        responses = {
            'greeting': {
                'ko': '안녕하세요! 저는 캠퍼스 안내 로봇 도리입니다. 어디로 안내해드릴까요?',
                'en': "Hello! I'm DORI, the campus guide robot. Where would you like to go?",
            },
            'thanks': {
                'ko': '천만에요! 더 도움이 필요하시면 불러주세요.',
                'en': "You're welcome! Call me if you need more help.",
            },
            'not_found': {
                'ko': '죄송합니다. 해당 장소를 찾을 수 없습니다. 다시 말씀해주시겠어요?',
                'en': "Sorry, I couldn't find that location. Could you say it again?",
            },
            'no_info': {
                'ko': '죄송합니다. 해당 정보를 찾을 수 없습니다.',
                'en': "Sorry, I couldn't find that information.",
            },
            'no_understand': {
                'ko': '죄송합니다. 이해하지 못했습니다. 다시 말씀해주시겠어요?',
                'en': "Sorry, I didn't understand. Could you please repeat?",
            },
        }
        lang = 'ko' if self.current_language == 'ko' else 'en'
        entry = responses.get(key, {})
        return entry.get(lang, entry.get('ko', ''))

    def _publish_destination(self, location: Location):
        pose = PoseStamped()
        pose.header.stamp    = self.get_clock().now().to_msg()
        pose.header.frame_id = 'map'
        pose.pose.position.x = location.coordinates[0]
        pose.pose.position.y = location.coordinates[1]
        pose.pose.position.z = 0.0
        pose.pose.orientation.w = 1.0
        self.destination_pub.publish(pose)
        self.get_logger().info(f'Navigation destination: {location.name}')


def main(args=None):
    rclpy.init(args=args)
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
