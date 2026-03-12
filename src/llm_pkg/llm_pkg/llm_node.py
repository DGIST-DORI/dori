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
import os
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


# Campus Knowledge Base (structured JSON — fast exact lookup)

class CampusKnowledgeBase:
    """Lightweight structured knowledge base for campus locations and FAQs."""

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
                name = loc.get('name_ko') or loc.get('name') or loc.get('name_en') or key
                if not name:
                    continue
                desc = loc.get('description_ko') or loc.get('description', '')
                self.locations[key] = Location(
                    name=name,
                    description=desc,
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
        # Exact name match
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


# Vector RAG Retriever (semantic search over campus_documents/*.txt)

class VectorRetriever:
    """
    Wraps the FAISS index built by build_index.py.
    Loaded lazily on first query to avoid slowing down node startup.
    """

    def __init__(self, index_dir: Optional[str], logger=None):
        self.index_dir = index_dir
        self.logger    = logger
        self._retriever = None   # lazy init

    def _load(self):
        if not self.index_dir or not Path(self.index_dir).exists():
            if self.logger:
                self.logger.warn(
                    f'RAG index not found at "{self.index_dir}". '
                    'Vector search disabled. Run build_index.py first.'
                )
            return
        try:
            # Import here so missing deps only fail at search time, not import time
            try:
                from .build_index import Retriever
            except ImportError:
                # Fallback when run as a standalone script
                from build_index import Retriever
            self._retriever = Retriever(self.index_dir)
            if self.logger:
                self.logger.info(f'Vector retriever ready: {self.index_dir}')
        except Exception as e:
            if self.logger:
                self.logger.error(f'Failed to load vector index: {e}')

    def search(self, query: str, top_k: int = 3) -> List[dict]:
        """
        Return top_k relevant chunks. Falls back to [] if index unavailable.
        Each result: {score, source, text}
        """
        if self._retriever is None:
            self._load()
        if self._retriever is None:
            return []
        try:
            return self._retriever.search(query, top_k=top_k)
        except Exception as e:
            if self.logger:
                self.logger.error(f'Vector search failed: {e}')
            return []

    def format_context(self, results: List[dict]) -> str:
        """Format retrieved chunks into a compact context string for the LLM prompt."""
        if not results:
            return ''
        parts = []
        for r in results:
            src = Path(r['source']).stem  # filename without extension
            parts.append(f'[{src}]\n{r["text"]}')
        return '\n\n'.join(parts)


# Intent Classifier

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
            r'(메뉴|식단|밥|lunch|dinner|오늘|today)',
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


# LLM Node

class LLMNode(Node):
    def __init__(self):
        super().__init__('llm_node')

        # Parameters
        self.declare_parameter('knowledge_file',   '')
        self.declare_parameter('rag_index_dir',    '')   # path to build_index.py output
        self.declare_parameter('use_external_llm', False)
        self.declare_parameter('model_name',       'gemini-2.0-flash')
        self.declare_parameter('api_key',          '')
        self.declare_parameter('rag_top_k',        3)    # chunks to retrieve per query

        knowledge_file   = self.get_parameter('knowledge_file').value
        rag_index_dir    = self.get_parameter('rag_index_dir').value
        self.use_external   = self.get_parameter('use_external_llm').value
        self.model_name     = self.get_parameter('model_name').value
        api_key             = self.get_parameter('api_key').value
        self.rag_top_k      = self.get_parameter('rag_top_k').value

        # Knowledge base (structured)
        self.kb = CampusKnowledgeBase(knowledge_file or None, self.get_logger())

        # Vector retriever (semantic)
        self.retriever = VectorRetriever(rag_index_dir or None, self.get_logger())

        # External LLM client (optional)
        self.llm_client = None
        self.llm_type   = None
        if self.use_external:
            self._init_llm_client(api_key)

        # State
        self.conversation_history: list = []
        self.current_language: str = 'ko'
        self.current_location_context: str = ''

        # Subscribers / Publishers
        self.create_subscription(String, '/dori/llm/query', self._on_query, 10)
        self.response_pub    = self.create_publisher(String,      '/dori/llm/response', 10)
        self.destination_pub = self.create_publisher(PoseStamped, '/dori/nav/destination', 10)

        self.get_logger().info('LLM Node started')

    # LLM client init

    def _init_llm_client(self, api_key: str):
        try:
            if 'gemini' in self.model_name.lower():
                import google.generativeai as genai
                genai.configure(api_key=api_key or os.environ.get('GEMINI_API_KEY', ''))
                self.llm_client = genai.GenerativeModel(self.model_name)
                self.llm_type   = 'gemini'
                self.get_logger().info(f'Gemini client ready: {self.model_name}')

            elif 'claude' in self.model_name.lower():
                import anthropic
                self.llm_client = anthropic.Anthropic(api_key=api_key or None)
                self.llm_type   = 'claude'
                self.get_logger().info(f'Anthropic client ready: {self.model_name}')

            elif 'gpt' in self.model_name.lower():
                import openai
                self.llm_client = openai.OpenAI(api_key=api_key or None)
                self.llm_type   = 'openai'
                self.get_logger().info(f'OpenAI client ready: {self.model_name}')

            else:
                self.get_logger().warn(
                    f'Unknown model "{self.model_name}" — falling back to rule-based')
                self.use_external = False

        except ImportError as e:
            self.get_logger().error(f'LLM library not installed: {e}')
            self.use_external = False
        except Exception as e:
            self.get_logger().error(f'LLM client init failed: {e}')
            self.use_external = False

    # Query callback

    def _on_query(self, msg: String):
        try:
            data = json.loads(msg.data)
            user_text = data.get('user_text', '').strip()
            self.current_location_context = data.get('location_context', '')
        except (json.JSONDecodeError, AttributeError):
            user_text = msg.data.strip()

        if not user_text:
            return

        self.get_logger().info(f'Query: "{user_text}"')
        response = self._generate_response(user_text)

        out = String()
        out.data = response
        self.response_pub.publish(out)
        self.get_logger().info(f'Response: "{response}"')

        self.conversation_history.append({
            'user': user_text, 'assistant': response, 'language': self.current_language,
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

        # For information and general: run full RAG pipeline
        return self._handle_with_rag(user_text, intent)

    def _handle_navigation(self, text: str) -> str:
        location = self.kb.search_location(text)
        if location:
            self._publish_destination(location)
            if self.current_language == 'en':
                return f"I'll guide you to {location.name}. {location.description}"
            return f'{location.name}(으)로 안내하겠습니다. {location.description}'
        return self._localized('not_found')

    def _handle_with_rag(self, text: str, intent: str) -> str:
        """
        Two-stage retrieval:
          1. Structured KB  — fast, exact (JSON)
          2. Vector search  — semantic, document chunks (FAISS)
        Combine both into LLM context, fall back to rule-based if LLM unavailable.
        """
        # Stage 1: structured KB
        struct_context = ''
        faq_answer = self.kb.search_faq(text)
        if faq_answer:
            struct_context = faq_answer
        else:
            loc = self.kb.search_location(text)
            if loc:
                struct_context = f'{loc.name}: {loc.description}'

        # Stage 2: vector search
        vec_results = self.retriever.search(text, top_k=self.rag_top_k)
        vec_context = self.retriever.format_context(vec_results)

        # If no LLM, return best structured result or fallback
        if not self.use_external or not self.llm_client:
            if struct_context:
                return struct_context
            if vec_results:
                # Return the top chunk text directly (trimmed)
                return vec_results[0]['text'][:200]
            return self._localized('no_understand')

        # Build combined context for LLM
        context_parts = []
        if struct_context:
            context_parts.append(f'[Campus DB]\n{struct_context}')
        if vec_context:
            context_parts.append(f'[Documents]\n{vec_context}')
        combined_context = '\n\n'.join(context_parts)

        return self._call_llm_with_context(text, combined_context)

    # LLM call

    def _call_llm_with_context(self, user_text: str, context: str) -> str:
        system_prompt = self._build_system_prompt(context)
        messages      = self._build_messages(user_text)
        try:
            if self.llm_type == 'gemini':
                # Gemini: prepend system prompt as first user turn
                full_history = [
                    {'role': 'user',  'parts': [system_prompt + '\n\n' + messages[0]['content']]},
                ]
                for m in messages[1:]:
                    full_history.append({
                        'role': 'model' if m['role'] == 'assistant' else 'user',
                        'parts': [m['content']],
                    })
                chat = self.llm_client.start_chat(history=full_history[:-1])
                resp = chat.send_message(full_history[-1]['parts'][0])
                return resp.text.strip()

            elif self.llm_type == 'claude':
                resp = self.llm_client.messages.create(
                    model=self.model_name,
                    system=system_prompt,
                    messages=messages,
                    max_tokens=300,
                )
                return resp.content[0].text.strip()

            elif self.llm_type == 'openai':
                resp = self.llm_client.chat.completions.create(
                    model=self.model_name,
                    messages=[{'role': 'system', 'content': system_prompt}, *messages],
                    max_tokens=300,
                    temperature=0.7,
                )
                return resp.choices[0].message.content.strip()

        except Exception as e:
            self.get_logger().error(f'LLM call failed: {e}')
        return self._localized('no_understand')

    def _build_system_prompt(self, context: str) -> str:
        location_hint = (
            f' Current location: {self.current_location_context}.'
            if self.current_location_context else ''
        )
        context_block = f'\n\n--- Reference Information ---\n{context}\n---' if context else ''

        if self.current_language == 'en':
            return (
                f'You are DORI, a friendly campus guide robot at DGIST university. '
                f'Answer concisely (1-3 sentences). Use only the reference information below '
                f'if relevant; do not fabricate facts.{location_hint}{context_block}'
            )
        return (
            f'당신은 DGIST 캠퍼스 안내 로봇 도리입니다. '
            f'친절하고 간결하게 1-3문장으로 답변하세요. '
            f'아래 참고 정보를 활용하되, 없는 내용은 지어내지 마세요.{location_hint}{context_block}'
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
            'greeting':    {'ko': '안녕하세요! 저는 캠퍼스 안내 로봇 도리입니다. 어디로 안내해드릴까요?',
                            'en': "Hello! I'm DORI, the campus guide robot. Where would you like to go?"},
            'thanks':      {'ko': '천만에요! 더 도움이 필요하시면 불러주세요.',
                            'en': "You're welcome! Call me if you need more help."},
            'not_found':   {'ko': '죄송합니다. 해당 장소를 찾을 수 없습니다. 다시 말씀해주시겠어요?',
                            'en': "Sorry, I couldn't find that location. Could you say it again?"},
            'no_understand':{'ko': '죄송합니다. 이해하지 못했습니다. 다시 말씀해주시겠어요?',
                             'en': "Sorry, I didn't understand. Could you please repeat?"},
        }
        lang  = 'ko' if self.current_language == 'ko' else 'en'
        entry = responses.get(key, {})
        return entry.get(lang, entry.get('ko', ''))

    def _publish_destination(self, location: Location):
        pose = PoseStamped()
        pose.header.stamp    = self.get_clock().now().to_msg()
        pose.header.frame_id = 'map'
        pose.pose.position.x = float(location.coordinates[0])
        pose.pose.position.y = float(location.coordinates[1])
        pose.pose.position.z = 0.0
        pose.pose.orientation.w = 1.0
        self.destination_pub.publish(pose)
        self.get_logger().info(f'Navigation destination: {location.name}')


# Entry point

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
