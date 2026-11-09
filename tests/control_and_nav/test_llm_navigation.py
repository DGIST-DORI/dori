"""Test LLM node navigation matching, follow-up, and goal resolution."""

import unittest
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
        self.node.conversation_history.append({"user": "길안내 해줘", "assistant": res1["text"], "language": "ko"})
        
        # Turn 2: User responds only with the destination name without navigation keywords
        res2 = self.node._generate_response("e6 gate", "")
        self.assertEqual(res2["intent"], "navigation")
        self.assertEqual(res2["target"], "5ea79f05827e")


if __name__ == "__main__":
    unittest.main()
