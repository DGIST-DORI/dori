"""Gemini SDK contract, credentials, and conversation behavior without API calls."""

import sys
import json
import threading
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock

import google
import pytest

from dori_llm.llm_node import CampusKnowledgeBase, LLMNode, VectorRetriever


@pytest.fixture
def backend(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    generate = Mock(return_value=SimpleNamespace(text=json.dumps({"answer": "도서관은 E8에 있습니다.", "source_ids": []})))
    # Deliberately expose only the new SDK surface, so start_chat cannot pass.
    client = SimpleNamespace(models=SimpleNamespace(generate_content=generate))
    sdk = ModuleType("google.genai")
    sdk.Client = Mock(return_value=client)
    monkeypatch.setitem(sys.modules, "google.genai", sdk)
    monkeypatch.setattr(google, "genai", sdk, raising=False)

    node = object.__new__(LLMNode)
    node.model_name = "gemini-3.5-flash-lite"
    node.use_external = True
    node.llm_client = None
    node.llm_type = None
    node.current_language = "ko"
    node.conversation_history = []
    node._busy = False
    node._busy_lock = threading.Lock()
    logger = Mock()
    node.get_logger = Mock(return_value=logger)
    return SimpleNamespace(node=node, sdk=sdk, generate=generate, logger=logger)


@pytest.mark.parametrize(
    "parameter,gemini,google_key,expected",
    [
        ("parameter-key", "gemini-key", "google-key", "parameter-key"),
        ("", "gemini-key", "google-key", "gemini-key"),
        ("", "gemini-key", "", "gemini-key"),
        ("", "", "google-key", "google-key"),
    ],
)
def test_gemini_credential_precedence(
    backend, monkeypatch, parameter, gemini, google_key, expected
):
    monkeypatch.setenv("GEMINI_API_KEY", gemini)
    monkeypatch.setenv("GOOGLE_API_KEY", google_key)
    backend.node._init_llm_client(parameter)
    backend.sdk.Client.assert_called_once_with(
        api_key=expected,
        http_options={"timeout": 20000, "retry_options": {"attempts": 1}},
    )
    assert backend.node.llm_type == "gemini"
    assert backend.node.use_external


def test_missing_key_disables_external_llm_with_setup_hint(backend):
    backend.node._init_llm_client("")
    assert not backend.node.use_external
    assert backend.node.llm_client is None
    backend.sdk.Client.assert_not_called()
    assert "Set GEMINI_API_KEY" in backend.logger.error.call_args.args[0]


@pytest.mark.parametrize("model", ["gemini-2.5-flash", "gemini-3.5-flash-lite", "gemini-3.8-flash"])
def test_first_question_uses_selected_model_and_rag_context(backend, model):
    node = backend.node
    node.model_name = model
    node._init_llm_client("test-key")
    node.rag_top_k = 3
    node.kb = SimpleNamespace(search_faq=Mock(return_value="도서관은 E8에 있습니다."))
    node.retriever = SimpleNamespace(
        search=Mock(return_value=[{"score": 0.9}]),
        format_context=Mock(return_value="[library]\n도서관은 평일에 운영합니다."),
    )

    result = node._generate_response("도서관은 어떤 곳이야?", "E1 로비")

    assert result == {
        "intent": "information",
        "text": "도서관은 E8에 있습니다.",
        "target": "",
    }
    backend.generate.assert_called_once()
    request = backend.generate.call_args.kwargs
    assert request["model"] == model
    assert request["contents"] == [
        {"role": "user", "parts": [{"text": "도서관은 어떤 곳이야?"}]}
    ]
    instruction = request["config"]["system_instruction"]
    assert "DGIST" in instruction
    assert "E1 로비" in instruction
    assert "[Campus DB]\n도서관은 E8에 있습니다." in instruction
    assert "[Documents]\n[library]" in instruction


def test_followup_preserves_last_three_turns_and_refreshes_context(backend):
    node = backend.node
    node._init_llm_client("test-key")
    node.current_language = "en"
    node.conversation_history = [
        {"user": f"question {i}", "assistant": f"answer {i}", "language": "en"}
        for i in range(4)
    ]
    node._call_llm_with_context("When does it open?", "Opens at 9 AM", "Library")
    request = backend.generate.call_args.kwargs
    assert [m["role"] for m in request["contents"]] == [
        "user", "model", "user", "model", "user", "model", "user"
    ]
    assert [m["parts"][0]["text"] for m in request["contents"]] == [
        "question 1", "answer 1", "question 2", "answer 2", "question 3", "answer 3",
        "When does it open?",
    ]
    assert "campus guide robot" in request["config"]["system_instruction"]
    assert "Opens at 9 AM" in request["config"]["system_instruction"]

    node._call_llm_with_context("And today?", "Closed today", "Cafeteria")
    instruction = backend.generate.call_args.kwargs["config"]["system_instruction"]
    assert "Closed today" in instruction and "Cafeteria" in instruction
    assert "Opens at 9 AM" not in instruction and "Library" not in instruction
    assert len(node.conversation_history) == 4


def test_reset_removes_gemini_history(backend):
    node = backend.node
    node._init_llm_client("test-key")
    node.conversation_history = [{"user": "previous", "assistant": "old answer"}]
    node._call_llm_with_context("follow-up", "", "")
    response = node._on_reset_history(None, SimpleNamespace())
    assert response.success
    node._call_llm_with_context("new session", "", "")
    assert backend.generate.call_args.kwargs["contents"] == [
        {"role": "user", "parts": [{"text": "new session"}]}
    ]


@pytest.mark.parametrize("text", [None, "", "  \n"])
def test_empty_response_uses_localized_fallback(backend, text):
    node = backend.node
    node._init_llm_client("test-key")
    backend.generate.return_value.text = text
    assert node._call_llm_with_context("질문", "", "") == node._localized("llm_unavailable")
    backend.logger.warn.assert_called_once()
    backend.logger.error.assert_not_called()


def test_api_error_is_logged_and_returns_fallback(backend):
    node = backend.node
    node._init_llm_client("test-key")
    node.current_language = "en"
    backend.generate.side_effect = RuntimeError("quota exhausted")
    assert node._call_llm_with_context("question", "", "") == node._localized("llm_unavailable")
    assert "quota exhausted" in backend.logger.error.call_args.args[0]


@pytest.mark.parametrize("text", [
    "안녕하세요", "안녕, 내 이름을 기억해줘", "고마워, 아까 내 이름 기억해?",
    "Hello, can you remember my name?", "Thanks, how can you help me?",
])
def test_conversation_including_greetings_and_thanks_reaches_llm(backend, text):
    node = backend.node
    node._init_llm_client("test-key")
    node.rag_top_k = 3
    node.kb = SimpleNamespace(search_faq=Mock(return_value=None), search_location=Mock(return_value=None))
    node.retriever = SimpleNamespace(search=Mock(return_value=[]), format_context=Mock(return_value=""))
    result = node._generate_response(text, "")
    assert result["text"] == "도서관은 E8에 있습니다."
    assert result["target"] == ""
    assert backend.generate.call_args.kwargs["contents"][-1]["parts"][0]["text"] == text


def test_navigation_remains_bound_to_registered_goals_without_llm(backend):
    node = backend.node
    node._init_llm_client("test-key")
    node.registered = [{"id": "lobby", "name": "로비"}]
    assert node._generate_response("로비로 데려다줘", "")["target"] == "lobby"
    assert node._generate_response("없는 건물로 데려다줘", "")["target"] == ""
    backend.generate.assert_not_called()


@pytest.mark.parametrize("text,intent", [("안녕하세요", "greeting"), ("감사합니다", "thanks")])
def test_explicit_offline_mode_preserves_local_social_responses(backend, text, intent):
    node = backend.node
    node.use_external = False
    assert node._generate_response(text, "")["text"] == node._localized(intent)
    backend.generate.assert_not_called()


def test_missing_index_is_only_attempted_once(tmp_path):
    logger = Mock()
    retriever = VectorRetriever(str(tmp_path), logger)
    retriever.index_dir = str(tmp_path / "missing")
    assert retriever.search("first") == []
    assert retriever.search("second") == []
    logger.warn.assert_called_once()


def test_missing_knowledge_does_not_invent_hours_or_coordinates():
    kb = object.__new__(CampusKnowledgeBase)
    kb._init_defaults()
    assert kb.search_location("도서관") is None
    assert kb.search_faq("운영시간") is None
