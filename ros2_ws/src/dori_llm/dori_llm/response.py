"""Separate spoken answers from verified retrieval provenance."""
import json
import re
from urllib.parse import urlsplit


def source_metadata(hit):
    """Expose document metadata, never server file paths or model-written URLs."""
    source = {'title': str(hit.get('book_title') or hit.get('title') or '참고 문서')}
    for key in ('edition', 'page_number', 'page_label'):
        if hit.get(key) is not None:
            source[key] = hit[key]
    url = hit.get('source_url')
    if isinstance(url, str):
        try:
            parsed = urlsplit(url)
            if parsed.scheme in ('https', 'http') and parsed.hostname and not parsed.username:
                source['url'] = url
        except ValueError:
            pass
    return source


def parse_response(raw, hits):
    """Fail closed on malformed output instead of speaking JSON or a bibliography.

    IDs refer only to this turn's retrieved chunks. The model selects evidence;
    titles, editions, pages and URLs are always copied from retrieval metadata.
    """
    raw = re.sub(r'^```(?:json)?\s*|\s*```$', '', raw.strip())
    data = json.loads(raw)
    if not isinstance(data, dict) or not isinstance(data.get('answer'), str):
        raise ValueError('Missing spoken answer')
    ids = data.get('source_ids', [])
    if not isinstance(ids, list):
        raise ValueError('Invalid source IDs')
    answer = data['answer'].strip()
    # Defense against familiar citation formatting leaking into the answer field.
    answer = re.split(r'(?:^|\n)\s*(?:#{1,6}\s*)?(?:출처|참고\s*자료|Sources?|References?)\s*[:：]', answer, maxsplit=1, flags=re.I)[0]
    answer = re.sub(r'[\[(](?:출처|참고\s*자료|Sources?|References?)\s*[:：][^\]\)\n]*[\])]', '', answer, flags=re.I)
    answer = re.sub(r'\[\d+(?:\s*[,\-]\s*\d+)*\]', '', answer).strip()
    if not answer:
        raise ValueError('Empty spoken answer')
    sources = []
    for index in ids:
        if type(index) is int and 1 <= index <= len(hits):
            source = source_metadata(hits[index - 1])
            if source not in sources:
                sources.append(source)
    return answer, sources
