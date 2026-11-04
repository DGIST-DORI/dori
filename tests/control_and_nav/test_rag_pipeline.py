"""RAG ingestion, freshness and atomic replacement using real FAISS, no API/model download."""
import importlib.util
import json
from pathlib import Path
import re
from types import SimpleNamespace
from unittest.mock import Mock
import zipfile

import numpy as np
import pytest

from dori_llm import build_index as index
from dori_llm.corpus import available, read_document, write_document
from dori_llm.index_store import active_directory, read_manifest

ROOT = Path(__file__).resolve().parents[2]


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


crawler = module('rag_crawler', 'tools/crawler/crawl_campus.py')
parser = module('rag_parser', 'tools/parser/parse_cafeteria_menu.py')


class Tokenizer:
    def __call__(self, text, add_special_tokens=True, return_offsets_mapping=False, **kwargs):
        spans = [m.span() for m in re.finditer(r'\S+', text)]
        result = {'input_ids': list(range(len(spans) + (2 if add_special_tokens else 0)))}
        if return_offsets_mapping:
            result['offset_mapping'] = spans
        return result

    def num_special_tokens_to_add(self, pair):
        return 2


class Model:
    tokenizer = Tokenizer()
    max_seq_length = 64

    def __init__(self):
        self.calls = []

    def get_sentence_embedding_dimension(self):
        return 3

    def encode(self, texts, **kwargs):
        self.calls.extend(texts)
        values = np.array([[1 + ('library' in t), 1 + ('cafeteria' in t), 1.] for t in texts], dtype='float32')
        return values / np.linalg.norm(values, axis=1, keepdims=True)


@pytest.fixture
def corpus(tmp_path):
    docs, output = tmp_path / 'docs', tmp_path / 'index'
    docs.mkdir()
    def write(name, text='library study room', **metadata):
        path = docs / name
        write_document(path, text, dict(kind='web', title=name,
                       source_url='https://www.dgist.ac.kr/' + name,
                       fetched_at='2026-11-01T00:00:00+00:00',
                       valid_until='2099-01-01T00:00:00+00:00', **metadata))
        return path
    return SimpleNamespace(docs=docs, output=output, write=write, model=Model())


def test_source_comments_urls_and_categories(tmp_path):
    urls = tmp_path / 'urls.txt'
    urls.write_text('https://www.dgist.ac.kr/kor/ # 한국어\nhttps://other.example/kor/ # English\n')
    entries = crawler.load_extra_urls(urls)
    assert len(entries) == 2
    assert all(e[1] == 'misc' for e in entries)
    assert entries[0][2] != entries[1][2]
    urls.write_text('https://example.org/ ../escape bad\n')
    with pytest.raises(ValueError, match='category'):
        crawler.load_extra_urls(urls)


@pytest.mark.parametrize('url', ['file:///etc/passwd', 'https://u:p@example.com/', 'missing-host'])
def test_invalid_source_urls_are_rejected(url):
    with pytest.raises(ValueError):
        crawler.canonical_url(url)


def test_extraction_keeps_table_rows_and_single_characters():
    html = '<nav>Noise</nav><main><h1>시설</h1><p>' + '도서관 시설 안내입니다. ' * 10
    html += '</p><table><tr><td>층</td><td>1</td><td>열람실</td></tr></table></main>'
    text = crawler.extract_text(html, '')
    assert '층 | 1 | 열람실' in text and 'Noise' not in text


def test_table_rowspans_preserve_floor_on_every_row():
    soup = crawler.BeautifulSoup('<table><tr><td rowspan="2">1층</td><td>수영장</td></tr><tr><td>헬스장</td></tr></table>', 'html.parser')
    assert crawler.table_text(soup.table) == '1층 | 수영장\n1층 | 헬스장'


def test_dgist_content_container_excludes_navigation():
    html = '<div>NOISE</div><div id="contens">' + '원문 내용 ' * 30 + '<div class="content-info">담당자</div></div>'
    text = crawler.extract_text(html, '')
    assert 'NOISE' not in text and '담당자' not in text


def test_history_extraction_preserves_year_and_event_date():
    html = '<main><ul class="history-list"><li class="year">2026<ul><li class="day-txt"><em>02.23.</em>첫 개강 ' + '대학교 행사 안내 ' * 10 + '</li></ul></li></ul></main>'
    text = crawler.extract_text(html, '')
    assert '## 2026' in text and '02.23. 첫 개강' in text


@pytest.mark.parametrize('html', ['<main>404 Page not found</main>', '<main>메뉴</main>'])
def test_soft_errors_never_become_documents(html):
    with pytest.raises(ValueError):
        crawler.extract_text(html, '')


def test_ingestion_uses_full_source_not_generated_facts_and_removes_old_fallback(tmp_path):
    raw = dict(doc_id='sample', url='https://www.dgist.ac.kr/page',
               final_url='https://www.dgist.ac.kr/page', fetched_at='2026-11-01T00:00:00+00:00',
               valid_until='2099-01-01T00:00:00+00:00', raw_text='원문입니다. ' * 1000 + '마지막 사실', html='<main>source</main>')
    old = tmp_path / 'processed/intro/sample_raw.txt'
    old.parent.mkdir(parents=True)
    old.write_text('stale fallback')
    crawler.save_raw(raw, tmp_path)
    metadata, text = crawler.save_refined({'summary_ko': 'UNVERIFIED FACT'}, raw, 'intro', '제목', 'Title', tmp_path)
    assert '마지막 사실' in Path(text).read_text()
    assert 'UNVERIFIED FACT' not in Path(text).read_text()
    assert json.loads(Path(metadata).read_text())['derived']['indexed'] is False
    assert not old.exists()
    assert read_document(Path(text), tmp_path / 'processed')['source_url'] == raw['url']


def test_failed_crawl_has_nonzero_status_and_keeps_previous_document(tmp_path, monkeypatch):
    target = tmp_path / 'processed/intro/dgist_history.txt'
    target.parent.mkdir(parents=True)
    target.write_text('last good source')
    monkeypatch.setattr(crawler, 'fetch_page', lambda *a, **k: (None, 'network unavailable'))
    assert crawler.main(['--output', str(tmp_path), '--delay', '0', '--no-llm']) == 1
    assert target.read_text() == 'last good source'
    report = json.loads(next((tmp_path / 'reports').glob('*.json')).read_text())
    assert report['summary']['failure_count'] == 5


def test_invalid_metadata_blocks_build_without_replacing_active(corpus):
    path = corpus.write('a.txt')
    builder = index.IndexBuilder(corpus.output, corpus.model)
    assert builder.build(corpus.docs)
    before = active_directory(corpus.output)
    path.write_text('changed without source record')
    assert not builder.build(corpus.docs, incremental=True)
    assert active_directory(corpus.output) == before


def test_incremental_reuses_vectors_and_removes_deleted_sources(corpus):
    corpus.write('a.txt')
    other = corpus.write('b.txt', 'cafeteria lunch')
    builder = index.IndexBuilder(corpus.output, corpus.model)
    assert builder.build(corpus.docs)
    corpus.model.calls.clear()
    assert builder.build(corpus.docs, incremental=True)
    assert not corpus.model.calls
    other.unlink()
    assert builder.build(corpus.docs, incremental=True)
    manifest = read_manifest(active_directory(corpus.output))
    assert manifest['removed_sources'] == ['b.txt']
    assert manifest['total_docs'] == 1
    assert all(m['source_key'] == 'a.txt' for m in builder._meta)
    (corpus.docs / 'a.txt').unlink()
    assert builder.build(corpus.docs, incremental=True)
    assert builder._index.ntotal == 0


def test_changed_text_is_reembedded_once(corpus):
    corpus.write('a.txt')
    builder = index.IndexBuilder(corpus.output, corpus.model)
    assert builder.build(corpus.docs)
    corpus.model.calls.clear()
    corpus.write('a.txt', 'cafeteria changed')
    assert builder.build(corpus.docs, incremental=True)
    assert len(corpus.model.calls) == 1
    assert 'changed' in builder._meta[0]['text']


def test_subset_root_or_model_change_requires_full_rebuild(corpus, monkeypatch):
    corpus.write('folder/a.txt')
    builder = index.IndexBuilder(corpus.output, corpus.model)
    assert builder.build(corpus.docs)
    before = active_directory(corpus.output)
    assert not builder.build(corpus.docs / 'folder', incremental=True)
    monkeypatch.setattr(index, 'SIGNATURE', {**index.SIGNATURE, 'revision': 'different'})
    assert not builder.build(corpus.docs, incremental=True)
    assert active_directory(corpus.output) == before


def test_corruption_is_detected_before_faiss_load(corpus):
    corpus.write('a.txt')
    assert index.IndexBuilder(corpus.output, corpus.model).build(corpus.docs)
    (active_directory(corpus.output) / 'metadata.json').write_text('[]')
    with pytest.raises(ValueError, match='checksum'):
        index.Retriever(corpus.output, corpus.model)


def test_failed_embedding_preserves_active_generation(corpus, monkeypatch):
    corpus.write('a.txt')
    builder = index.IndexBuilder(corpus.output, corpus.model)
    assert builder.build(corpus.docs)
    before = active_directory(corpus.output)
    corpus.write('b.txt')
    monkeypatch.setattr(builder, '_embed', Mock(side_effect=RuntimeError('embedding failed')))
    assert not builder.build(corpus.docs, incremental=True)
    assert active_directory(corpus.output) == before


def test_concurrent_document_change_aborts_before_commit(corpus, monkeypatch):
    corpus.write('a.txt')
    builder = index.IndexBuilder(corpus.output, corpus.model)
    assert builder.build(corpus.docs)
    before = active_directory(corpus.output)
    corpus.write('b.txt')
    embed = builder._embed
    def change(texts, batch_size):
        corpus.write('a.txt', 'modified during embedding')
        return embed(texts, batch_size)
    monkeypatch.setattr(builder, '_embed', change)
    assert not builder.build(corpus.docs, incremental=True)
    assert active_directory(corpus.output) == before


def test_generation_write_failure_keeps_old_index_readable(corpus, monkeypatch):
    corpus.write('a.txt')
    builder = index.IndexBuilder(corpus.output, corpus.model)
    assert builder.build(corpus.docs)
    before = active_directory(corpus.output)
    write = index.atomic_write
    def fail(path, text):
        if Path(path).name == 'metadata.json':
            raise OSError('disk full')
        write(path, text)
    monkeypatch.setattr(index, 'atomic_write', fail)
    assert not builder.build(corpus.docs)
    assert active_directory(corpus.output) == before
    assert index.Retriever(corpus.output, corpus.model).search('library')


def test_build_lock_rejects_second_writer(corpus):
    corpus.write('a.txt')
    with index.build_lock(corpus.output):
        assert not index.IndexBuilder(corpus.output, corpus.model).build(corpus.docs)
    assert not (corpus.output / 'CURRENT').exists()


def test_evaluation_failure_and_stage_only_never_activate(corpus, tmp_path):
    corpus.write('a.txt')
    builder = index.IndexBuilder(corpus.output, corpus.model)
    assert builder.build(corpus.docs)
    before = active_directory(corpus.output)
    evaluation = tmp_path / 'eval.json'
    evaluation.write_text(json.dumps([{'query': 'library', 'source_key': 'missing.txt'}]))
    assert not builder.build(corpus.docs, evaluation=evaluation)
    assert active_directory(corpus.output) == before
    assert builder.build(corpus.docs, publish=False)
    assert active_directory(corpus.output) == before
    assert (corpus.output / 'generations' / builder.generation).is_dir()
    staged = builder.generation
    index.activate_generation(corpus.output, staged)
    assert active_directory(corpus.output).name == staged
    index.activate_generation(corpus.output, before.name)
    assert active_directory(corpus.output) == before


def test_expired_and_future_sources_are_not_returned(corpus):
    corpus.write('a.txt')
    path = corpus.write('old.txt')
    record = json.loads(path.with_suffix('.json').read_text())
    record['valid_until'] = '2000-01-01T00:00:00+00:00'
    write_document(path, path.read_text(), record)
    assert index.IndexBuilder(corpus.output, corpus.model).build(corpus.docs)
    retriever = index.Retriever(corpus.output, corpus.model)
    assert all(h['source_key'] != 'old.txt' for h in retriever.search('library'))
    # A source can expire after startup without rebuilding/restarting retrieval.
    retriever._meta[0]['valid_until'] = '2000-01-01T00:00:00+00:00'
    assert retriever.search('library') == []
    assert not available({'valid_from': '2099-01-01T00:00:00+00:00'})


def test_token_chunks_cover_end_of_long_document_without_truncation():
    model = Model()
    text = ' '.join(f'단어{i}' for i in range(400))
    chunks = list(index.token_chunks(text, model, '문서 제목'))
    assert all(len(model.tokenizer(c)['input_ids']) <= model.max_seq_length for c in chunks)
    assert '단어399' in chunks[-1]
    assert all(f'단어{i}' in '\n'.join(chunks) for i in range(400))


def test_chunks_do_not_mix_separate_sections():
    chunks = list(index.token_chunks('주소 333\n## 지하철\n진천역 1번 출구', Model(), '찾아오는 길'))
    assert len(chunks) == 2
    assert '주소 333' in chunks[0] and '진천역' not in chunks[0]
    assert '지하철' in chunks[1] and '진천역' in chunks[1]


def test_exact_korean_entity_evidence_refines_dense_ranking():
    import faiss
    vectors = faiss.IndexFlatIP(3)
    vectors.add(np.array([[.95, np.sqrt(1 - .95**2), 0], [.6, .8, 0]], dtype='float32'))
    model = SimpleNamespace(encode=lambda *a, **k: np.array([[1, 0, 0]], dtype='float32'))
    metadata = [{'text': '일반 대학원 소개', 'source': 'generic'},
                {'text': '기술경영전문대학원 개강 2026년 2월', 'source': 'specific'}]
    hits = index.search_index(vectors, metadata, model, '기술경영전문대학원 개강')
    assert hits[0]['source'] == 'specific'


@pytest.mark.parametrize('text', ['11/5', '11월 5일'])
def test_menu_dates_without_year_are_rejected(text):
    with pytest.raises(ValueError, match='ambiguous'):
        parser.parse_date_from_value(text)
    assert parser.parse_date_from_value(text, 2025) == '2025-11-05'
    assert parser.parse_date_from_value('2026.11.5') == '2026-11-05'


def test_xlsx_default_namespace_inline_text_and_numeric_dates(tmp_path):
    path = tmp_path / 'test.xlsx'
    with zipfile.ZipFile(path, 'w') as z:
        z.writestr('xl/worksheets/sheet1.xml', '''<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData><row r="7"><c r="D7"><v>46000</v></c><c r="E7" t="inlineStr"><is><t>2026.11.3</t></is></c></row></sheetData></worksheet>''')
    with zipfile.ZipFile(path) as z:
        assert parser._load_shared_strings(z) == []
        rows = parser._parse_sheet_rows(z, 'xl/worksheets/sheet1.xml', [])
    assert rows['7'] == {'D': '46000', 'E': '2026.11.3'}
    assert re.fullmatch(r'\d{4}-\d{2}-\d{2}', parser.parse_date_from_value(rows['7']['D']))


def test_parser_failure_does_not_report_success(tmp_path):
    path = tmp_path / 'unknown.xlsx'
    path.write_bytes(b'invalid')
    assert parser.main(['--input', str(path), '--output', str(tmp_path / 'out')]) == 1


def test_running_llm_reloads_generation_and_keeps_last_good_on_failure(corpus, monkeypatch):
    from dori_llm.llm_node import VectorRetriever
    corpus.write('a.txt')
    builder = index.IndexBuilder(corpus.output, corpus.model)
    assert builder.build(corpus.docs)
    real = index.Retriever
    factory = Mock(side_effect=lambda path, **kwargs: real(path, corpus.model))
    monkeypatch.setattr(index, 'Retriever', factory)
    reader = VectorRetriever(str(corpus.output), Mock())
    assert reader.search('library')
    assert builder.build(corpus.docs)
    assert reader.search('library')
    assert factory.call_count == 2
    (corpus.output / 'CURRENT').write_text('missing-generation')
    assert reader.search('library')  # Previously verified, unexpired snapshot.
    assert reader.search('library')
    assert factory.call_count == 3
