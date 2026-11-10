"""Only verified provenance reaches the UI; citations never enter spoken text."""
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from dori_llm.llm_node import LLMNode, VectorRetriever
from dori_llm.response import parse_response, source_metadata


HIT = {'source': '/private/index/page.txt', 'score': .9, 'text': '도서관은 E8에 있습니다.',
       'book_title': 'DGIST 가이드북', 'edition': '2026', 'page_number': 15,
       'page_label': '13', 'source_url': 'https://example.org/guide.pdf'}


def test_answer_and_deduplicated_verified_sources_are_separate():
    raw = json.dumps({'answer': '도서관은 E8에 있습니다. [1] (출처: 가이드북 13쪽)\n출처: 모델이 만든 목록',
                      'source_ids': [1, 1, 0, 99, '1', True], 'url': 'https://untrusted.example'})
    answer, sources = parse_response(raw, [HIT])
    assert answer == '도서관은 E8에 있습니다.'
    assert sources == [source_metadata(HIT)]
    assert '/private' not in json.dumps(sources)
    assert 'untrusted' not in json.dumps(sources)


@pytest.mark.parametrize('raw', ['plain prose with citations', '{bad JSON', '[]',
                                     '{"answer": 1}', '{"answer": "", "source_ids": []}',
                                     '{"answer": "hello", "source_ids": "1"}'])
def test_malformed_structured_output_is_not_spoken(raw):
    with pytest.raises(ValueError):
        parse_response(raw, [HIT])


@pytest.mark.parametrize('url', ['javascript:alert(1)', 'file:///private/guide.pdf',
                                 'https://user:secret@example.org/guide', 'https://[invalid'])
def test_unsafe_urls_are_not_exposed(url):
    assert 'url' not in source_metadata({**HIT, 'source_url': url})


def test_rag_source_ids_match_context_and_do_not_leak_into_next_turn():
    node = object.__new__(LLMNode)
    node.get_logger = Mock(return_value=Mock())
    node.current_language = 'ko'
    node.use_external = True
    node.llm_client = object()
    node.conversation_history = []
    node.rag_top_k = 3
    node.kb = SimpleNamespace(search_faq=Mock(return_value=None), search_location=Mock(return_value=None))
    node.retriever = VectorRetriever(None)
    node.retriever.search = Mock(return_value=[HIT])
    node._call_llm_with_context = Mock(return_value=json.dumps({'answer': HIT['text'], 'source_ids': [1]}))
    first = node._generate_response('도서관은 어떤 곳이야?', '')
    assert first['text'] == HIT['text']
    assert first['sources'] == [source_metadata(HIT)]
    context = node._call_llm_with_context.call_args.args[1]
    assert 'Source ID: 1' in context and 'Edition: 2026' in context
    node._call_llm_with_context.return_value = json.dumps({'answer': '안녕하세요.', 'source_ids': []})
    second = node._generate_response('안녕', '')
    assert 'sources' not in second


def test_invalid_model_output_gets_safe_localized_fallback():
    node = object.__new__(LLMNode)
    node.current_language = 'ko'
    node.get_logger = Mock(return_value=Mock())
    node.use_external = True
    node.llm_client = object()
    node.rag_top_k = 3
    node.kb = SimpleNamespace(search_faq=Mock(return_value=None), search_location=Mock(return_value=None))
    node.retriever = VectorRetriever(None)
    node.retriever.search = Mock(return_value=[HIT])
    node._call_llm_with_context = Mock(return_value='도서관은 E8. 출처: 가이드북 13쪽')
    sources = []
    assert node._handle_with_rag('도서관?', '', sources) == node._localized('llm_unavailable')
    assert not sources
