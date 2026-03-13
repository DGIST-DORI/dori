#!/usr/bin/env python3
"""
DORI Dashboard — Knowledge Manager API Server
Provides REST endpoints for the KnowledgeTab frontend.

Endpoints:
  POST /api/knowledge/parse-menu            Receive menu files, run parser
  POST /api/knowledge/build-index           Start index build job
  GET  /api/knowledge/build-index/status/{job_id}  Poll job progress
  GET  /api/knowledge/index-info            Current FAISS index stats
  GET  /api/knowledge/documents             List indexed .txt files
  GET  /api/knowledge/buildings             Read campus_knowledge.json
  PUT  /api/knowledge/buildings/{key}       Update one building entry

Usage:
  pip install fastapi uvicorn python-multipart
  python3 knowledge_api.py [--port 3001] [--repo-root /path/to/dori]
"""

import argparse
import asyncio
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

# ── Path resolution ────────────────────────────────────────────────────────────

def find_repo_root(start: Path) -> Path:
    """Walk up from start until we find the repo root (contains README.md + src/)."""
    for parent in [start, *start.parents]:
        if (parent / 'src').is_dir() and (parent / 'README.md').exists():
            return parent
    return start  # fallback


DEFAULT_REPO = find_repo_root(Path(__file__).resolve().parent)

parser_arg = argparse.ArgumentParser(add_help=False)
parser_arg.add_argument('--repo-root', default=str(DEFAULT_REPO))
parser_arg.add_argument('--port', type=int, default=3001)
args, _ = parser_arg.parse_known_args()

REPO_ROOT   = Path(args.repo_root)
PARSER_SCRIPT  = REPO_ROOT / 'tools' / 'parser' / 'parse_cafeteria_menu.py'
BUILDER_SCRIPT = REPO_ROOT / 'src' / 'llm_pkg' / 'llm_pkg' / 'build_index.py'
PROCESSED_DIR  = REPO_ROOT / 'data' / 'campus' / 'processed'
INDEXED_DIR    = REPO_ROOT / 'data' / 'campus' / 'indexed'
KNOWLEDGE_FILE = INDEXED_DIR / 'campus_knowledge.json'

# ── Job registry ───────────────────────────────────────────────────────────────

_jobs: dict[str, dict] = {}
# job schema: { status: idle|running|done|error, lines: [str], total_chunks: int, error: str }


# ── App ────────────────────────────────────────────────────────────────────────

app = FastAPI(title='DORI Knowledge API', version='1.0.0')

app.add_middleware(
    CORSMiddleware,
    allow_origins=['*'],
    allow_methods=['*'],
    allow_headers=['*'],
)


# ── /api/knowledge/parse-menu ─────────────────────────────────────────────────

@app.post('/api/knowledge/parse-menu')
async def parse_menu(files: list[UploadFile] = File(...)):
    """
    Receive one or more menu files (xlsx/pdf), save to a temp dir,
    run parse_cafeteria_menu.py, and return per-file results.
    """
    results = []
    out_dir = PROCESSED_DIR / 'cafeteria'
    out_dir.mkdir(parents=True, exist_ok=True)

    for upload in files:
        suffix = Path(upload.filename).suffix.lower()
        if suffix not in ('.xlsx', '.pdf'):
            results.append({'filename': upload.filename, 'ok': False,
                            'error': f'Unsupported file type: {suffix}'})
            continue

        # Save to temp file
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(await upload.read())
            tmp_path = tmp.name

        # Rename to match original filename so parser can detect cafeteria type
        named_path = Path(tmp_path).parent / upload.filename
        os.rename(tmp_path, named_path)

        try:
            result = subprocess.run(
                [sys.executable, str(PARSER_SCRIPT),
                 '--input', str(named_path),
                 '--output', str(out_dir)],
                capture_output=True, text=True, timeout=60
            )
            if result.returncode != 0:
                raise RuntimeError(result.stderr.strip() or result.stdout.strip())

            # Find output files (parser prints "saved -> <path>")
            out_json = out_txt = ''
            for line in result.stdout.splitlines():
                if '[JSON] saved ->' in line:
                    out_json = line.split('->')[-1].strip()
                if '[TXT]  saved ->' in line:
                    out_txt = line.split('->')[-1].strip()

            results.append({
                'filename': upload.filename,
                'ok': True,
                'out_json': out_json,
                'out_txt': out_txt,
            })
        except Exception as e:
            results.append({'filename': upload.filename, 'ok': False, 'error': str(e)})
        finally:
            named_path.unlink(missing_ok=True)

    return {'results': results}


# ── /api/knowledge/build-index ────────────────────────────────────────────────

def _run_build_index(job_id: str, incremental: bool):
    """Run build_index.py in a background thread, capture stdout line by line."""
    job = _jobs[job_id]
    job['status'] = 'running'

    cmd = [sys.executable, str(BUILDER_SCRIPT),
           '--docs', str(PROCESSED_DIR),
           '--output', str(INDEXED_DIR)]
    if incremental:
        cmd.append('--incremental')

    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, bufsize=1)
        total_chunks = 0
        for line in proc.stdout:
            line = line.rstrip()
            job['lines'].append(line)
            # Parse chunk count from build_index.py output
            if 'Total vectors' in line or 'chunks' in line.lower():
                parts = [w for w in line.split() if w.isdigit()]
                if parts:
                    total_chunks = int(parts[-1])
        proc.wait()
        if proc.returncode == 0:
            job['status'] = 'done'
            job['total_chunks'] = total_chunks
        else:
            job['status'] = 'error'
            job['error'] = f'Exit code {proc.returncode}'
    except Exception as e:
        job['status'] = 'error'
        job['error'] = str(e)


@app.post('/api/knowledge/build-index')
async def build_index(body: dict):
    incremental = body.get('incremental', True)
    job_id = str(uuid.uuid4())[:8]
    _jobs[job_id] = {'status': 'pending', 'lines': [], 'total_chunks': 0, 'error': ''}
    t = threading.Thread(target=_run_build_index, args=(job_id, incremental), daemon=True)
    t.start()
    return {'job_id': job_id}


@app.get('/api/knowledge/build-index/status/{job_id}')
async def build_index_status(job_id: str):
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(404, 'Job not found')

    # Return new lines since last poll (client tracks cursor)
    # Simple approach: always return full lines (small output)
    return {
        'status': job['status'],
        'new_lines': job['lines'],
        'total_chunks': job['total_chunks'],
        'error': job['error'],
    }


# ── /api/knowledge/index-info ─────────────────────────────────────────────────

@app.get('/api/knowledge/index-info')
async def index_info():
    meta_file = INDEXED_DIR / 'metadata.json'
    index_file = INDEXED_DIR / 'index.faiss'

    if not meta_file.exists():
        return {'total_vectors': None, 'total_docs': None, 'built_at': None}

    with open(meta_file, 'r', encoding='utf-8') as f:
        meta = json.load(f)

    total_vectors = len(meta) if isinstance(meta, list) else None
    total_docs = len(set(m['source'] for m in meta)) if isinstance(meta, list) else None
    built_at = None
    if index_file.exists():
        ts = index_file.stat().st_mtime
        built_at = datetime.fromtimestamp(ts).strftime('%Y-%m-%d %H:%M')

    return {'total_vectors': total_vectors, 'total_docs': total_docs, 'built_at': built_at}


# ── /api/knowledge/documents ──────────────────────────────────────────────────

@app.get('/api/knowledge/documents')
async def list_documents():
    docs = []
    if not PROCESSED_DIR.exists():
        return docs

    for path in sorted(PROCESSED_DIR.rglob('*.txt')):
        stat = path.stat()
        # Count lines as rough chunk estimate
        try:
            text = path.read_text(encoding='utf-8')
            # Rough chunk count: chars / 300
            chunks = max(1, len(text) // 300)
        except Exception:
            chunks = 0

        docs.append({
            'source': str(path.relative_to(REPO_ROOT)),
            'chunks': chunks,
            'size_kb': round(stat.st_size / 1024, 1),
            'modified': datetime.fromtimestamp(stat.st_mtime).strftime('%Y-%m-%d %H:%M'),
        })

    return docs


# ── /api/knowledge/buildings ──────────────────────────────────────────────────

def _load_knowledge() -> dict:
    if not KNOWLEDGE_FILE.exists():
        return {}
    with open(KNOWLEDGE_FILE, 'r', encoding='utf-8') as f:
        data = json.load(f)
    return data.get('locations', data)  # support both flat and nested formats


def _save_knowledge(locations: dict):
    if KNOWLEDGE_FILE.exists():
        with open(KNOWLEDGE_FILE, 'r', encoding='utf-8') as f:
            full = json.load(f)
    else:
        full = {}

    if 'locations' in full:
        full['locations'] = locations
    else:
        full = locations

    KNOWLEDGE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(KNOWLEDGE_FILE, 'w', encoding='utf-8') as f:
        json.dump(full, f, ensure_ascii=False, indent=2)


@app.get('/api/knowledge/buildings')
async def get_buildings():
    return _load_knowledge()


@app.put('/api/knowledge/buildings/{key}')
async def update_building(key: str, body: dict):
    locations = _load_knowledge()
    if key not in locations:
        raise HTTPException(404, f'Building key not found: {key}')
    locations[key] = {**locations[key], **body}
    try:
        _save_knowledge(locations)
    except Exception as e:
        raise HTTPException(500, str(e))
    return {'ok': True, 'key': key}


# ── Entrypoint ─────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    import uvicorn
    print(f'[DORI Knowledge API] Repo root : {REPO_ROOT}')
    print(f'[DORI Knowledge API] Parser    : {PARSER_SCRIPT}')
    print(f'[DORI Knowledge API] Builder   : {BUILDER_SCRIPT}')
    print(f'[DORI Knowledge API] Listening : http://0.0.0.0:{args.port}')
    uvicorn.run(app, host='0.0.0.0', port=args.port, log_level='warning')
