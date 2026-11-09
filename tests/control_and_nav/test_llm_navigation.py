"""Test LLM node navigation matching, follow-up, and goal resolution."""

import unittest
import json
from types import SimpleNamespace
from unittest.mock import Mock

from dori_llm.llm_node import IntentClassifier, LLMNode


class TestLLMNavigation(unittest.TestCase):
    def setUp(self):
        self.node = object.__new__(LLMNode)
        self.node.registered = [
            {"id": "5ea79f05827e", "name": "e6 gate"},
            {"id": "d922da6c5d23", "name": "stair"},
            {"id": "f47a9bc68237", "name": "start point"},
            {"id": "lobby_1", "name": "로비"},
        ]
        self.node.current_language = "ko"
        self.node.conversation_history = []
        self.node.use_external = False
        self.node.llm_client = None
        self.node.get_logger = Mock(return_value=Mock())
        self.node._handle_with_rag = Mock(return_value='캠퍼스 정보입니다.')

    def test_intent_classifier_patterns(self):
        self.assertEqual(IntentClassifier.classify("길안내"), "navigation")
        self.assertEqual(IntentClassifier.classify("길안내 해줘"), "navigation")
        self.assertEqual(IntentClassifier.classify("길안내 기능"), "navigation")
        self.assertEqual(IntentClassifier.classify("e6 gate 안내해줘"), "navigation")
        self.assertEqual(IntentClassifier.classify("로비로 가자"), "navigation")

    def test_navigation_query_without_destination_prompts_user(self):
        result = self.node._generate_response("길안내 해줘", "")
        self.assertEqual(result["intent"], "qa")
        self.assertEqual(result["target"], "")
        self.assertIn("어디로 안내해드릴까요?", result["text"])
        self.assertIn("e6 gate", result["text"])

    def test_direct_destination_in_prompt(self):
        result = self.node._generate_response("e6 gate 안내해줘", "")
        self.assertEqual(result["intent"], "navigation")
        self.assertEqual(result["target"], "5ea79f05827e")
        self.assertIn("e6 gate(으)로 안내하겠습니다", result["text"])

    def test_korean_alias_matching(self):
        result = self.node._generate_response("e6 게이트로 안내해줘", "")
        self.assertEqual(result["intent"], "navigation")
        self.assertEqual(result["target"], "5ea79f05827e")

        result2 = self.node._generate_response("계단으로 가자", "")
        self.assertEqual(result2["intent"], "navigation")
        self.assertEqual(result2["target"], "d922da6c5d23")

    def test_followup_turn_resolves_destination(self):
        # Turn 1: User says "길안내 해줘"
        res1 = self.node._generate_response("길안내 해줘", "")
        self.node.conversation_history.append({"user": "길안내 해줘", "assistant": res1["text"],
                                               "awaiting_destination": res1['awaiting_destination']})
        # Turn 2: User responds only with the destination name without navigation keywords
        res2 = self.node._generate_response("e6 gate", "")
        self.assertEqual(res2["intent"], "navigation")
        self.assertEqual(res2["target"], "5ea79f05827e")

    def test_matching_ignores_case_and_spacing_but_keeps_building_qualifiers(self):
        for text in ('E6gate 안내해줘', 'e6게이트로 안내해줘', '시작 위치로 가자'):
            with self.subTest(text=text):
                self.assertEqual(self.node._generate_response(text, '')['intent'], 'navigation')
        for text in ('e7 게이트 안내해줘', 'e60 gate 안내해줘', 'e 안내해줘', '계 안내해줘'):
            with self.subTest(text=text):
                self.assertEqual(self.node._generate_response(text, '')['target'], '')
        self.assertEqual(self.node._match_registered_goals(''), [])

    def test_multiple_destinations_are_not_resolved_arbitrarily(self):
        self.node.registered.append({'id': 'gate7', 'name': 'e7 gate'})
        for text in ('e6 게이트나 e7 gate 안내해줘', 'e6 gate 또는 계단으로 가자'):
            result = self.node._generate_response(text, '')
            self.assertEqual(result['target'], '')
            self.assertTrue(result['awaiting_destination'])

    def test_followup_information_question_never_starts_motion(self):
        self.node.conversation_history = [{'awaiting_destination': True}]
        result = self.node._generate_response('로비 운영시간은?', '')
        self.assertEqual(result['target'], '')
        self.node._handle_with_rag.assert_called_once()
        self.node.conversation_history = [{'assistant': '목적지 로비에 대한 정보입니다.'}]
        self.assertEqual(self.node._generate_response('로비', '')['target'], '')
        self.assertEqual(self.node._generate_response('목적지 로비 운영시간은?', '')['target'], '')

    def test_english_prompt_and_empty_or_invalid_registry(self):
        self.node.current_language = 'en'
        self.assertIn('Where would you like to go?', self.node._generate_response('directions', '')['text'])
        for data in ({'goals': []}, [], {'goals': None}, {'goals': [{'id': 'a'}]}, {'goals': [{'id': '', 'name': 'Lobby'}]}):
            self.node._on_locations(SimpleNamespace(data=json.dumps(data)))
            self.assertEqual(self.node.registered, [])
        self.assertIn('no registered destinations', self.node._generate_response('directions', '')['text'])

    def test_location_update_replaces_previous_map(self):
        self.node._on_locations(SimpleNamespace(data=json.dumps({'map_key': 'new', 'goals': [{'id': 'new', 'name': '새 로비'}]})))
        self.assertEqual(self.node._generate_response('e6 gate 안내해줘', '')['target'], '')
        self.assertEqual(self.node._generate_response('새 로비 안내해줘', '')['target'], 'new')


if __name__ == "__main__":
    unittest.main()
