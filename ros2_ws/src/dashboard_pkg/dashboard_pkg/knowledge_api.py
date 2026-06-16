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
  python3 knowledge_api.py [--port 3000] [--repo-root /path/to/dori] [--web-dir /path/to/web]
"""

import argparse
import asyncio
import base64
import hashlib
import hmac
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal

from fastapi import Depends, FastAPI, File, Header, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

try:
    from llm_pkg.paths import find_repo_root as _shared_find_repo_root
except Exception:
    _shared_find_repo_root = None

# ── Path resolution ────────────────────────────────────────────────────────────

def find_repo_root(start: Path) -> Path:
    """Walk up from start until we find the repo root.

    Root markers:
      - ros2_ws/src directory + README.md
      - OR .git + README.md
    """
    if _shared_find_repo_root is not None:
        return _shared_find_repo_root(start)

    for parent in [start, *start.parents]:
        has_readme = (parent / 'README.md').exists()
        has_ros2_src = (parent / 'ros2_ws' / 'src').is_dir()
        has_git = (parent / '.git').exists()
        if has_readme and (has_ros2_src or has_git):
            return parent
    return start  # fallback


def normalize_repo_root(candidate: Path) -> Path:
    """Normalize an explicit --repo-root path to the actual repository root."""
    resolved = candidate.expanduser().resolve()
    for parent in [resolved, *resolved.parents]:
        has_ros2_src = (parent / 'ros2_ws' / 'src').is_dir()
        has_crawler = (parent / 'tools' / 'crawler' / 'crawl_campus.py').is_file()
        if has_ros2_src and has_crawler:
            return parent
    return resolved


DEFAULT_REPO = find_repo_root(Path(__file__).resolve().parent)

parser_arg = argparse.ArgumentParser(add_help=False)
parser_arg.add_argument('--repo-root', default=str(DEFAULT_REPO))
parser_arg.add_argument('--port', type=int, default=3000)
parser_arg.add_argument('--web-dir', default='')
args, _ = parser_arg.parse_known_args()

REPO_ROOT   = normalize_repo_root(Path(args.repo_root))
ROS2_WS_ROOT = REPO_ROOT / 'ros2_ws'
PARSER_SCRIPT  = REPO_ROOT / 'tools' / 'parser' / 'parse_cafeteria_menu.py'
BUILDER_SCRIPT = REPO_ROOT / 'ros2_ws' / 'src' / 'llm_pkg' / 'llm_pkg' / 'build_index.py'
CRAWLER_SCRIPT = REPO_ROOT / 'tools' / 'crawler' / 'crawl_campus.py'
PROCESSED_DIR  = REPO_ROOT / 'data' / 'campus' / 'processed'
INDEXED_DIR    = REPO_ROOT / 'data' / 'campus' / 'indexed'
KNOWLEDGE_FILE = INDEXED_DIR / 'campus_knowledge.json'

# ── Job registry ───────────────────────────────────────────────────────────────

_jobs: dict[str, dict] = {}
# job schema:
# {
#   status: idle|running|done|error,
#   lines: [str],
#   total_chunks: int,   # parsed only from final "Total chunks  : <num>" summary line
#   total_vectors: int,  # parsed only from final "Total vectors : <num>" summary line
#   error: str,
# }

_TOTAL_CHUNKS_RE = re.compile(r'^\s*Total chunks\s*:\s*(\d+)\s*$')
_TOTAL_VECTORS_RE = re.compile(r'^\s*Total vectors\s*:\s*(\d+)\s*$')

_crawl_jobs: dict[str, dict] = {}
# job schema: { status: pending|running|done|error, lines: [str], started_at: str|None,
#               finished_at: str|None, error: str }


# ── App ────────────────────────────────────────────────────────────────────────

app = FastAPI(title='DORI Knowledge API', version='1.0.0')
logger = logging.getLogger(__name__)

_DEFAULT_ALLOWED_ORIGINS = (
    'https://dash.dgist-dori.xyz',
)


def _parse_allowed_origins(raw: str) -> list[str]:
    if not raw:
        return list(_DEFAULT_ALLOWED_ORIGINS)

    origins: list[str] = []
    for item in (part.strip() for part in raw.split(',') if part.strip()):
        normalized = item.rstrip('/')
        if normalized and normalized not in origins:
            origins.append(normalized)
    return origins or list(_DEFAULT_ALLOWED_ORIGINS)


_ALLOWED_ORIGINS = _parse_allowed_origins(os.environ.get('DORI_ALLOWED_ORIGINS', '').strip())
_ALLOWED_ORIGIN_SET = set(_ALLOWED_ORIGINS)


@app.middleware('http')
async def enforce_origin_allowlist(request: Request, call_next):
    origin = request.headers.get('origin', '').strip().rstrip('/')
    if origin and origin not in _ALLOWED_ORIGIN_SET:
        logger.warning(
            'cors_origin_blocked origin=%s path=%s method=%s client=%s',
            origin,
            request.url.path,
            request.method,
            request.client.host if request.client else '-',
        )
        return JSONResponse(status_code=403, content={'detail': 'Origin is not allowed'})
    return await call_next(request)


app.add_middleware(
    CORSMiddleware,
    allow_origins=_ALLOWED_ORIGINS,
    allow_credentials=False,
    allow_methods=['GET', 'POST', 'PUT', 'OPTIONS'],
    allow_headers=['Authorization', 'Content-Type'],
)


# ── AuthN/AuthZ ───────────────────────────────────────────────────────────────

_AUTH_TOKEN_HEADER = 'Bearer'
_JWT_SECRET = os.environ.get('DORI_API_JWT_SECRET', '').strip()
_JWT_AUDIENCE = os.environ.get('DORI_API_JWT_AUDIENCE', '').strip()
_JWT_ISSUER = os.environ.get('DORI_API_JWT_ISSUER', '').strip()
_ACCESS_ROLE_MAP_RAW = os.environ.get('DORI_API_ACCESS_TOKENS', '').strip()


@dataclass(frozen=True)
class AuthPrincipal:
    user_id: str
    roles: frozenset[str]
    auth_type: str


def _b64url_decode(value: str) -> bytes:
    padding = '=' * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def _parse_access_role_map(raw: str) -> dict[str, AuthPrincipal]:
    principals: dict[str, AuthPrincipal] = {}
    if not raw:
        return principals

    # format: token=user_id:role1|role2,token2=user2:viewer
    for item in (part.strip() for part in raw.split(',') if part.strip()):
        if '=' not in item:
            continue
        token, right = item.split('=', 1)
        if ':' in right:
            user_id, role_blob = right.split(':', 1)
        else:
            user_id, role_blob = right, 'viewer'
        roles = frozenset(r.strip().lower() for r in role_blob.split('|') if r.strip())
        principals[token.strip()] = AuthPrincipal(
            user_id=user_id.strip() or 'unknown',
            roles=roles or frozenset({'viewer'}),
            auth_type='access',
        )
    return principals


_ACCESS_ROLE_MAP = _parse_access_role_map(_ACCESS_ROLE_MAP_RAW)


def _log_auth_event(request: Request, principal: AuthPrincipal | None, required: str, status_code: int) -> None:
    logger.info(
        'auth_audit status=%s path=%s user=%s roles=%s required=%s method=%s',
        status_code,
        request.url.path,
        principal.user_id if principal else '-',
        ','.join(sorted(principal.roles)) if principal else '-',
        required,
        request.method,
    )


def _verify_jwt(token: str) -> AuthPrincipal:
    try:
        encoded_header, encoded_payload, encoded_signature = token.split('.')
    except ValueError as e:
        raise HTTPException(
            status_code=401,
            detail='Invalid token format',
            headers={'WWW-Authenticate': 'Bearer'},
        ) from e

    try:
        header = json.loads(_b64url_decode(encoded_header).decode('utf-8'))
        payload = json.loads(_b64url_decode(encoded_payload).decode('utf-8'))
    except Exception as e:
        raise HTTPException(
            status_code=401,
            detail='Invalid token payload',
            headers={'WWW-Authenticate': 'Bearer'},
        ) from e

    alg = header.get('alg', '')
    if alg != 'HS256':
        raise HTTPException(
            status_code=401,
            detail='Unsupported JWT algorithm',
            headers={'WWW-Authenticate': 'Bearer'},
        )
    if not _JWT_SECRET:
        raise HTTPException(
            status_code=401,
            detail='JWT secret is not configured',
            headers={'WWW-Authenticate': 'Bearer'},
        )

    signed_part = f'{encoded_header}.{encoded_payload}'.encode('utf-8')
    expected_sig = base64.urlsafe_b64encode(
        hmac.new(_JWT_SECRET.encode('utf-8'), signed_part, hashlib.sha256).digest()
    ).decode('utf-8').rstrip('=')
    if not hmac.compare_digest(expected_sig, encoded_signature):
        raise HTTPException(
            status_code=401,
            detail='Invalid token signature',
            headers={'WWW-Authenticate': 'Bearer'},
        )

    now_ts = int(time.time())
    exp = payload.get('exp')
    if exp is not None and int(exp) < now_ts:
        raise HTTPException(
            status_code=401,
            detail='Token expired',
            headers={'WWW-Authenticate': 'Bearer'},
        )
    nbf = payload.get('nbf')
    if nbf is not None and int(nbf) > now_ts:
        raise HTTPException(
            status_code=401,
            detail='Token not active yet',
            headers={'WWW-Authenticate': 'Bearer'},
        )
    if _JWT_AUDIENCE and payload.get('aud') != _JWT_AUDIENCE:
        raise HTTPException(
            status_code=401,
            detail='Invalid token audience',
            headers={'WWW-Authenticate': 'Bearer'},
        )
    if _JWT_ISSUER and payload.get('iss') != _JWT_ISSUER:
        raise HTTPException(
            status_code=401,
            detail='Invalid token issuer',
            headers={'WWW-Authenticate': 'Bearer'},
        )

    roles = payload.get('roles', payload.get('scope', ''))
    if isinstance(roles, str):
        role_values = frozenset(r.strip().lower() for r in roles.replace(',', ' ').split() if r.strip())
    elif isinstance(roles, list):
        role_values = frozenset(str(r).strip().lower() for r in roles if str(r).strip())
    else:
        role_values = frozenset()

    user_id = str(payload.get('sub', payload.get('user_id', 'unknown')))
    return AuthPrincipal(user_id=user_id, roles=role_values or frozenset({'viewer'}), auth_type='jwt')


def _authenticate_request(authorization: str | None, access: str | None) -> AuthPrincipal:
    if authorization and authorization.startswith(f'{_AUTH_TOKEN_HEADER} '):
        bearer = authorization[len(_AUTH_TOKEN_HEADER) + 1:].strip()
        if bearer:
            return _verify_jwt(bearer)

    if access:
        token = access.strip()
        if token in _ACCESS_ROLE_MAP:
            return _ACCESS_ROLE_MAP[token]

    raise HTTPException(
        status_code=401,
        detail='Authentication required',
        headers={'WWW-Authenticate': 'Bearer'},
    )


def _has_permission(principal: AuthPrincipal, required: Literal['view', 'control', 'admin']) -> bool:
    if 'admin' in principal.roles:
        return True
    if required == 'view':
        return bool({'viewer', 'view', 'control', 'deploy'} & principal.roles)
    if required == 'control':
        return bool({'control', 'deploy'} & principal.roles)
    return False


def require_permission(required: Literal['view', 'control', 'admin']):
    async def _dependency(
        request: Request,
        authorization: str | None = Header(default=None),
        access: str | None = Header(default=None, alias='Access'),
    ) -> AuthPrincipal:
        principal: AuthPrincipal | None = None
        try:
            principal = _authenticate_request(authorization, access)
        except HTTPException:
            _log_auth_event(request, principal=None, required=required, status_code=401)
            raise

        if not _has_permission(principal, required):
            _log_auth_event(request, principal=principal, required=required, status_code=403)
            raise HTTPException(status_code=403, detail='Forbidden')

        _log_auth_event(request, principal=principal, required=required, status_code=200)
        return principal

    return _dependency


def _resolve_web_dir() -> Path | None:
    if args.web_dir:
        candidate = Path(args.web_dir).expanduser().resolve()
        if candidate.is_dir():
            return candidate

    published = Path(__file__).resolve().parents[2] / 'web_current'
    if published.is_dir():
        return published

    fallback = Path(__file__).resolve().parents[2] / 'web'
    if fallback.is_dir():
        return fallback

    return None



# ── /api/knowledge/parse-menu ─────────────────────────────────────────────────

@app.post('/api/knowledge/parse-menu')
async def parse_menu(
    files: list[UploadFile] = File(...),
    _: AuthPrincipal = Depends(require_permission('control')),
):
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

def _run_build_index(
    job_id: str,
    incremental: bool,
    batch_size: int | None = None,
    chunk_batch_size: int | None = None,
):
    """Run build_index.py in a background thread, capture stdout line by line."""
    job = _jobs[job_id]
    job['status'] = 'running'

    cmd = [sys.executable, str(BUILDER_SCRIPT),
           '--docs', str(PROCESSED_DIR),
           '--output', str(INDEXED_DIR)]
    if incremental:
        cmd.append('--incremental')
    if batch_size is not None:
        cmd.extend(['--batch-size', str(batch_size)])
    if chunk_batch_size is not None:
        cmd.extend(['--chunk-batch-size', str(chunk_batch_size)])

    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, bufsize=1)
        total_chunks = 0
        total_vectors = 0
        for line in proc.stdout:
            line = line.rstrip()
            job['lines'].append(line)
            # Parse only final summary lines:
            #   "Total vectors : <num>"
            #   "Total chunks  : <num>"
            # Ignore progress lines like "Batch 1/10", "cumulative=...".
            chunks_match = _TOTAL_CHUNKS_RE.match(line)
            if chunks_match:
                total_chunks = int(chunks_match.group(1))
                continue

            vectors_match = _TOTAL_VECTORS_RE.match(line)
            if vectors_match:
                total_vectors = int(vectors_match.group(1))
        proc.wait()
        if proc.returncode == 0:
            job['status'] = 'done'
            job['total_chunks'] = total_chunks
            job['total_vectors'] = total_vectors
        else:
            job['status'] = 'error'
            job['error'] = f'Exit code {proc.returncode}'
    except Exception as e:
        job['status'] = 'error'
        job['error'] = str(e)


@app.post('/api/knowledge/build-index')
async def build_index(
    body: dict,
    _: AuthPrincipal = Depends(require_permission('control')),
):
    incremental = body.get('incremental', True)
    batch_size = body.get('batch_size')
    chunk_batch_size = body.get('chunk_batch_size')

    if not isinstance(incremental, bool):
        raise HTTPException(400, 'incremental must be a boolean')
    if batch_size is not None:
        if not isinstance(batch_size, int):
            raise HTTPException(400, 'batch_size must be an integer')
        if batch_size <= 0:
            raise HTTPException(400, 'batch_size must be > 0')
    if chunk_batch_size is not None:
        if not isinstance(chunk_batch_size, int):
            raise HTTPException(400, 'chunk_batch_size must be an integer')
        if chunk_batch_size <= 0:
            raise HTTPException(400, 'chunk_batch_size must be > 0')

    job_id = str(uuid.uuid4())[:8]
    _jobs[job_id] = {
        'status': 'pending',
        'lines': [],
        'total_chunks': 0,
        'total_vectors': 0,
        'error': '',
    }
    t = threading.Thread(
        target=_run_build_index,
        args=(job_id, incremental, batch_size, chunk_batch_size),
        daemon=True,
    )
    t.start()
    return {'job_id': job_id}


@app.get('/api/knowledge/build-index/status/{job_id}')
async def build_index_status(
    job_id: str,
    cursor: int = Query(0, ge=0),
    _: AuthPrincipal = Depends(require_permission('view')),
):
    """
    Build-index status contract:
      - total_chunks is sourced from build_index.py final summary line:
        "Total chunks  : <num>"
      - total_vectors is sourced from final summary line:
        "Total vectors : <num>"
      - Frontend completion text ("Done — N chunks indexed") MUST use total_chunks.
    """
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(404, 'Job not found')

    lines = job['lines']
    safe_cursor = min(cursor, len(lines))

    return {
        'status': job['status'],
        'new_lines': lines[safe_cursor:],
        'next_cursor': len(lines),
        'total_chunks': job['total_chunks'],
        'total_vectors': job['total_vectors'],
        'error': job['error'],
    }


# ── /api/knowledge/crawl-campus ───────────────────────────────────────────────

def _utc_now_iso() -> str:
    return datetime.utcnow().isoformat(timespec='seconds') + 'Z'


def _resolve_repo_internal_path(path_value: str | None, *, param_name: str) -> Path | None:
    if path_value in (None, ''):
        return None

    # Basic type and character validation before constructing a Path from untrusted input.
    if not isinstance(path_value, str):
        raise HTTPException(400, f'{param_name} must be a string path')

    # Normalize separators and trim whitespace to reduce platform-specific edge cases.
    raw_value = path_value.strip().replace('\\', '/')
    if raw_value in ('', '.', '/'):
        raise HTTPException(400, f'{param_name} must be a non-empty relative path')

    # Normalize the path string to eliminate any ".." or "." segments before constructing a Path.
    normed = os.path.normpath(raw_value)
    if normed in ('', '.', os.sep):
        raise HTTPException(400, f'{param_name} must be a non-empty relative path')

    # Reject absolute paths outright; callers must provide repo-internal relative paths.
    if os.path.isabs(normed):
        raise HTTPException(400, f'{param_name} must be a relative path inside the repo root')

    # Reject traversal segments after normalization as an extra safety check.
    # We split on '/' because we normalized backslashes above.
    parts = [p for p in normed.split('/') if p]
    if any(part in ('.', '..') for part in parts):
        raise HTTPException(400, f'{param_name} must not contain "." or ".." path segments')
    # Construct a repo-internal candidate path and resolve it, ensuring it stays under REPO_ROOT.
    repo_resolved = REPO_ROOT.resolve()
    candidate = repo_resolved / normed
    resolved = candidate.resolve()

    try:
        resolved.relative_to(repo_resolved)
    except ValueError as e:
        raise HTTPException(400, f'{param_name} must stay inside repo root: {repo_resolved}') from e

    return resolved


def _build_crawl_command(body: dict) -> list[str]:
    cmd = [sys.executable, str(CRAWLER_SCRIPT)]

    no_llm = body.get('no_llm', False)
    if not isinstance(no_llm, bool):
        raise HTTPException(400, 'no_llm must be a boolean')
    if no_llm:
        cmd.append('--no-llm')

    delay = body.get('delay', None)
    if delay is not None:
        if not isinstance(delay, (int, float)):
            raise HTTPException(400, 'delay must be a number')
        if delay < 0:
            raise HTTPException(400, 'delay must be >= 0')
        cmd.extend(['--delay', str(delay)])

    urls_path = _resolve_repo_internal_path(body.get('urls_path'), param_name='urls_path')
    if urls_path is not None:
        cmd.extend(['--urls', str(urls_path)])

    output_dir = _resolve_repo_internal_path(body.get('output_dir'), param_name='output_dir')
    if output_dir is not None:
        cmd.extend(['--output', str(output_dir)])

    return cmd


def _run_crawl_job(job_id: str, cmd: list[str]):
    job = _crawl_jobs[job_id]
    job['status'] = 'running'
    job['started_at'] = _utc_now_iso()

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            cwd=str(REPO_ROOT),
        )
        for line in proc.stdout:
            job['lines'].append(line.rstrip('\n'))
        proc.wait()
        if proc.returncode == 0:
            job['status'] = 'done'
        else:
            job['status'] = 'error'
            job['error'] = f'Exit code {proc.returncode}'
    except Exception as e:
        job['status'] = 'error'
        job['error'] = str(e)
    finally:
        job['finished_at'] = _utc_now_iso()


@app.post('/api/knowledge/crawl-campus')
async def crawl_campus(
    body: dict,
    _: AuthPrincipal = Depends(require_permission('control')),
):
    if not CRAWLER_SCRIPT.exists():
        raise HTTPException(500, f'Crawler script not found: {CRAWLER_SCRIPT}')

    allowed_keys = {'no_llm', 'delay', 'urls_path', 'output_dir'}
    unknown_keys = sorted(k for k in body.keys() if k not in allowed_keys)
    if unknown_keys:
        raise HTTPException(400, f'Unsupported parameters: {", ".join(unknown_keys)}')

    cmd = _build_crawl_command(body)

    job_id = str(uuid.uuid4())[:8]
    _crawl_jobs[job_id] = {
        'status': 'pending',
        'lines': [],
        'started_at': None,
        'finished_at': None,
        'error': '',
    }
    t = threading.Thread(target=_run_crawl_job, args=(job_id, cmd), daemon=True)
    t.start()

    return {'job_id': job_id}


@app.get('/api/knowledge/crawl-campus/status/{job_id}')
async def crawl_campus_status(
    job_id: str,
    _: AuthPrincipal = Depends(require_permission('view')),
):
    job = _crawl_jobs.get(job_id)
    if not job:
        raise HTTPException(404, 'Job not found')

    return {
        'status': job['status'],
        'new_lines': job['lines'],
        'started_at': job['started_at'],
        'finished_at': job['finished_at'],
        'error': job['error'],
    }


# ── /api/knowledge/index-info ─────────────────────────────────────────────────

@app.get('/api/knowledge/index-info')
async def index_info(_: AuthPrincipal = Depends(require_permission('view'))):
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
async def list_documents(_: AuthPrincipal = Depends(require_permission('view'))):
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
async def get_buildings(_: AuthPrincipal = Depends(require_permission('view'))):
    return _load_knowledge()


@app.put('/api/knowledge/buildings/{key}')
async def update_building(
    key: str,
    body: dict,
    _: AuthPrincipal = Depends(require_permission('control')),
):
    locations = _load_knowledge()
    if key not in locations:
        raise HTTPException(404, f'Building key not found: {key}')
    locations[key] = {**locations[key], **body}
    try:
        _save_knowledge(locations)
    except Exception as e:
        raise HTTPException(500, str(e))
    return {'ok': True, 'key': key}


# ── /api/control/actions (external-safe control path) ────────────────────────

_CONTROL_EXECUTOR = os.environ.get('DORI_CONTROL_EXECUTOR', 'dry-run').strip().lower() or 'dry-run'
_CONTROL_ACTIONS = frozenset({'move', 'stop', 'set_mode'})
_CONTROL_MODES = frozenset({'manual', 'auto', 'dock', 'idle'})
_CONTROL_RATE_LIMITS = {
    # action -> (max_requests, window_seconds)
    'move': (10, 1.0),
    'stop': (5, 1.0),
    'set_mode': (2, 1.0),
}
_control_rate_events: dict[tuple[str, str], list[float]] = {}
_control_rate_lock = threading.Lock()


def _validate_float_range(value, *, field: str, min_value: float, max_value: float) -> float:
    if not isinstance(value, (int, float)):
        raise HTTPException(400, f'{field} must be a number')
    normalized = float(value)
    if normalized < min_value or normalized > max_value:
        raise HTTPException(400, f'{field} must be in range [{min_value}, {max_value}]')
    return normalized


def _enforce_control_rate_limit(principal: AuthPrincipal, action: str) -> None:
    limit = _CONTROL_RATE_LIMITS.get(action)
    if not limit:
        return
    max_requests, window_sec = limit
    now = time.monotonic()
    key = (principal.user_id, action)

    with _control_rate_lock:
        events = _control_rate_events.setdefault(key, [])
        cutoff = now - window_sec
        events[:] = [t for t in events if t >= cutoff]
        if len(events) >= max_requests:
            raise HTTPException(
                status_code=429,
                detail=f'rate limit exceeded for action={action} '
                       f'({max_requests}/{window_sec:.1f}s)',
            )
        events.append(now)


def _execute_control_action(action: str, params: dict) -> dict:
    """
    Execute a validated control action through a constrained backend interface.

    Default mode is dry-run for safety. To enable ROS2 CLI execution:
      DORI_CONTROL_EXECUTOR=ros2_cli
    """
    if _CONTROL_EXECUTOR != 'ros2_cli':
        return {
            'executor': _CONTROL_EXECUTOR,
            'executed': False,
            'detail': 'dry-run mode: validated but not published to ROS network',
        }

    if action == 'move':
        linear_x = params['linear_x']
        linear_y = params['linear_y']
        angular_z = params['angular_z']
        payload = (
            '{linear: {x: ' + f'{linear_x:.4f}' + ', y: ' + f'{linear_y:.4f}' + ', z: 0.0}, '
            'angular: {x: 0.0, y: 0.0, z: ' + f'{angular_z:.4f}' + '}}'
        )
        cmd = [
            'ros2', 'topic', 'pub', '--once',
            '/cmd_vel', 'geometry_msgs/msg/Twist',
            payload,
        ]
    elif action == 'stop':
        cmd = [
            'ros2', 'topic', 'pub', '--once',
            '/cmd_vel', 'geometry_msgs/msg/Twist',
            '{linear: {x: 0.0, y: 0.0, z: 0.0}, angular: {x: 0.0, y: 0.0, z: 0.0}}',
        ]
    elif action == 'set_mode':
        mode = params['mode']
        cmd = [
            'ros2', 'topic', 'pub', '--once',
            '/dori/control/mode', 'std_msgs/msg/String',
            f'{{data: "{mode}"}}',
        ]
    else:
        raise HTTPException(400, f'Unsupported action: {action}')

    completed = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
    if completed.returncode != 0:
        raise HTTPException(
            status_code=502,
            detail=(
                'control action execution failed: '
                + (completed.stderr.strip() or completed.stdout.strip() or f'exit={completed.returncode}')
            ),
        )
    return {'executor': _CONTROL_EXECUTOR, 'executed': True, 'detail': 'published via ros2_cli'}


@app.post('/api/control/actions')
async def control_actions(
    body: dict,
    principal: AuthPrincipal = Depends(require_permission('control')),
):
    """
    Public-safe control API for external users.
    Only allowlisted actions are accepted, with strict validation and rate limiting.
    """
    action = body.get('action')
    params = body.get('params', {})
    if not isinstance(action, str):
        raise HTTPException(400, 'action must be a string')
    if not isinstance(params, dict):
        raise HTTPException(400, 'params must be an object')

    action = action.strip().lower()
    if action not in _CONTROL_ACTIONS:
        raise HTTPException(400, f'action must be one of: {sorted(_CONTROL_ACTIONS)}')

    validated: dict = {}
    if action == 'move':
        validated['linear_x'] = _validate_float_range(params.get('linear_x', 0.0), field='linear_x', min_value=-0.8, max_value=0.8)
        validated['linear_y'] = _validate_float_range(params.get('linear_y', 0.0), field='linear_y', min_value=-0.8, max_value=0.8)
        validated['angular_z'] = _validate_float_range(params.get('angular_z', 0.0), field='angular_z', min_value=-1.2, max_value=1.2)
    elif action == 'set_mode':
        mode = params.get('mode')
        if not isinstance(mode, str):
            raise HTTPException(400, 'mode must be a string')
        mode = mode.strip().lower()
        if mode not in _CONTROL_MODES:
            raise HTTPException(400, f'mode must be one of: {sorted(_CONTROL_MODES)}')
        validated['mode'] = mode

    _enforce_control_rate_limit(principal, action)
    exec_result = _execute_control_action(action, validated)
    return {
        'ok': True,
        'action': action,
        'validated_params': validated,
        'rate_limit': {
            'max_requests': _CONTROL_RATE_LIMITS[action][0],
            'window_sec': _CONTROL_RATE_LIMITS[action][1],
        },
        **exec_result,
    }


@app.post('/api/admin/publish')
async def admin_publish(
    body: dict,
    _: AuthPrincipal = Depends(require_permission('admin')),
):
    """
    High-risk raw publish endpoint.
    Intentionally admin-only and disabled unless explicitly enabled.
    """
    if os.environ.get('DORI_ENABLE_ADMIN_PUBLISH', '').strip().lower() not in ('1', 'true', 'yes'):
        raise HTTPException(403, 'admin publish endpoint is disabled')
    return {
        'ok': False,
        'detail': (
            'admin publish endpoint is reserved for controlled environments. '
            'Use /api/control/actions for external control flows.'
        ),
        'requested': body,
    }

# ── /api/tunnel-url ───────────────────────────────────────────────────────────
# 터널 WS URL을 반환. 프론트엔드가 외부 접속 시 폴링해서 WS URL 기본값 자동 설정.
#
# 우선순위:
#   1) 환경변수 DORI_WS_URL 이 설정되어 있으면 그 값을 사용 (고정 도메인용)
#   2) cloudflared 로그 파싱 (trycloudflare.com 임시 터널용, 후순위)

import re as _re
import os as _os

_CF_LOG_DASHBOARD = Path('/tmp/cloudflared_dashboard.log')
_CF_LOG_WS        = Path('/tmp/cloudflared_ws.log')
_CF_URL_RE        = _re.compile(r'https://[a-z0-9\-]+\.trycloudflare\.com')

# 고정 도메인 환경변수 (dashboard.launch.py 또는 systemd 에서 주입)
# 예: DORI_DASHBOARD_URL=https://dash.dgist-dori.xyz
#     DORI_WS_URL=wss://ws.dgist-dori.xyz
_FIXED_DASHBOARD_URL = _os.environ.get('DORI_DASHBOARD_URL', '').strip()
_FIXED_WS_URL        = _os.environ.get('DORI_WS_URL', '').strip()
_EXPOSE_ROSBRIDGE_TUNNEL = _os.environ.get('DORI_EXPOSE_ROSBRIDGE_TUNNEL', '').strip().lower() in ('1', 'true', 'yes')


def _parse_tunnel_url(log_path: Path) -> str | None:
    """Read a cloudflared log file and return the first trycloudflare URL found."""
    try:
        text = log_path.read_text(encoding='utf-8', errors='ignore')
        match = _CF_URL_RE.search(text)
        return match.group(0) if match else None
    except Exception:
        return None


@app.get('/api/tunnel-url')
async def get_tunnel_url():
    """
    Return Cloudflare Tunnel public URL for the dashboard and (optionally) rosbridge.

    Response:
      { "dashboard_url": str|null, "ws_url": str|null, "ready": bool, "ws_exposed": bool }

    Priority:
      1) DORI_WS_URL / DORI_DASHBOARD_URL env vars (fixed custom domain)
      2) cloudflared log parsing (trycloudflare.com quick tunnel, fallback)

    ws_url must use wss:// — Cloudflare Tunnel always terminates TLS.
    """
    # 1순위: 고정 도메인 환경변수
    if _FIXED_WS_URL and _EXPOSE_ROSBRIDGE_TUNNEL:
        return {
            'dashboard_url': _FIXED_DASHBOARD_URL or None,
            'ws_url':        _FIXED_WS_URL,
            'ready':         True,
            'ws_exposed':    True,
        }

    # 2순위: trycloudflare.com 임시 터널 로그 파싱
    dashboard_url = _parse_tunnel_url(_CF_LOG_DASHBOARD)
    ws_url = None
    if _EXPOSE_ROSBRIDGE_TUNNEL:
        ws_http_url = _parse_tunnel_url(_CF_LOG_WS)
        ws_url = ws_http_url.replace('https://', 'wss://', 1) if ws_http_url else None

    return {
        'dashboard_url': dashboard_url,
        'ws_url':        ws_url,
        'ready':         dashboard_url is not None or ws_url is not None,
        'ws_exposed':    _EXPOSE_ROSBRIDGE_TUNNEL and ws_url is not None,
    }

# ── Static file serving ────────────────────────────────────────────────────────
# MUST be registered after all /api/* routes.
# app.mount('/') is intentionally avoided — it shadows FastAPI routes.

WEB_DIR = _resolve_web_dir()

if WEB_DIR:
    from fastapi.responses import FileResponse as _FileResponse

    _STATIC_FILE_EXTENSIONS = {
        '.js', '.mjs', '.css', '.map', '.png', '.jpg', '.jpeg', '.gif', '.webp', '.svg', '.ico', '.woff', '.woff2', '.ttf', '.otf', '.eot',
    }
    _IMMUTABLE_ASSET_EXTENSIONS = {
        '.js', '.mjs', '.css', '.map', '.png', '.jpg', '.jpeg', '.gif', '.webp', '.svg', '.ico', '.woff', '.woff2', '.ttf', '.otf', '.eot',
    }

    def _is_versioned_asset(requested_path: Path) -> bool:
        if 'assets' not in requested_path.parts:
            return False

        stem_parts = [part for part in requested_path.stem.split('.') if part]
        return len(stem_parts) > 1


    def _static_cache_headers(requested_path: Path) -> dict[str, str]:
        normalized_parts = tuple(part for part in requested_path.parts if part not in ('', '.'))
        suffix = requested_path.suffix.lower()

        if normalized_parts == ('index.html',):
            return {'Cache-Control': 'no-cache, no-store, must-revalidate'}

        if _is_versioned_asset(requested_path) and suffix in _IMMUTABLE_ASSET_EXTENSIONS:
            return {'Cache-Control': 'public, max-age=31536000, immutable'}

        if suffix in {'.png', '.jpg', '.jpeg', '.gif', '.webp', '.svg', '.ico', '.woff', '.woff2', '.ttf', '.otf', '.eot'}:
            return {'Cache-Control': 'public, max-age=3600'}

        return {'Cache-Control': 'public, max-age=300'}


    @app.get('/{full_path:path}', include_in_schema=False)
    async def serve_spa(full_path: str):
        # 실제 파일이 있으면 그대로 반환 (JS, CSS, 이미지 등)
        target = WEB_DIR / full_path
        requested_path = Path(full_path)
        if target.is_file():
            return _FileResponse(str(target), headers=_static_cache_headers(requested_path))

        is_asset_request = (
            'assets' in requested_path.parts
            or requested_path.suffix.lower() in _STATIC_FILE_EXTENSIONS
        )
        if is_asset_request:
            raise HTTPException(404, 'Not Found')

        # 파일 확장자가 없는 SPA route만 index.html fallback 처리
        if not requested_path.suffix:
            index_path = Path('index.html')
            return _FileResponse(str(WEB_DIR / index_path), headers=_static_cache_headers(index_path))

        raise HTTPException(404, 'Not Found')

# ── /api/webhook + /api/deploy/* ──────────────────────────────────────────────
# GitHub Webhook receiver + async deploy pipeline
# Pipeline: git pull → npm run build (if web changed) → colcon build
#        → validate installed static tree → publish web_current symlink
# Only purge CDN/browser caches after the publish step completes.
#
# Env vars:
#   DORI_WEBHOOK_SECRET  : GitHub webhook secret (HMAC-SHA256)
#   DORI_ROS_DISTRO      : ROS distro name (default: humble)

import shlex

_WEBHOOK_SECRET = _os.environ.get('DORI_WEBHOOK_SECRET', '').encode()
_ROS_DISTRO     = _os.environ.get('DORI_ROS_DISTRO', 'humble')

# Single shared deploy job (only one deploy runs at a time)
_deploy_job: dict = {
    'status': 'idle',   # idle | running | done | error
    'steps':  [],       # list of { step, status, log }
    'error':  None,
    'missing_files': [],
    'started_at': None,
    'finished_at': None,
}
_deploy_lock = threading.Lock()


# ── Signature verification ────────────────────────────────────────────────────

def _verify_github_signature(body: bytes, sig_header: str | None) -> bool:
    """Verify X-Hub-Signature-256 against DORI_WEBHOOK_SECRET."""
    if not _WEBHOOK_SECRET:
        return True  # Dev mode: skip verification
    if not sig_header or not sig_header.startswith('sha256='):
        return False
    expected = 'sha256=' + hmac.new(_WEBHOOK_SECRET, body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, sig_header)


# ── Deploy pipeline ───────────────────────────────────────────────────────────

def _run_step(step_name: str, cmd: list[str], cwd: str, env: dict | None = None) -> tuple[bool, str]:
    """Run a shell command, stream output into the deploy job log."""
    import subprocess

    step = {'step': step_name, 'status': 'running', 'log': ''}
    _deploy_job['steps'].append(step)

    try:
        proc = subprocess.Popen(
            cmd,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            env={**_os.environ, **(env or {})},
        )
        output_lines = []
        for line in proc.stdout:
            output_lines.append(line)
            step['log'] = ''.join(output_lines)   # live update

        proc.wait()
        step['log'] = ''.join(output_lines)

        if proc.returncode != 0:
            step['status'] = 'error'
            return False, step['log']

        step['status'] = 'done'
        return True, step['log']

    except Exception as e:
        step['status'] = 'error'
        step['log'] = str(e)
        return False, str(e)


def _web_dir() -> Path | None:
    """Return the web/ directory path if it exists."""
    candidate = REPO_ROOT / 'web'
    return candidate if candidate.is_dir() else None


def _installed_dashboard_share_dir() -> Path:
    return Path(__file__).resolve().parents[2]


def _built_web_dir() -> Path:
    return _installed_dashboard_share_dir() / 'web'


def _published_web_dir() -> Path:
    return _installed_dashboard_share_dir() / 'web_current'


def _web_release_root() -> Path:
    return _installed_dashboard_share_dir() / 'web_releases'


def _extract_index_asset_paths(index_path: Path) -> list[str]:
    text = index_path.read_text(encoding='utf-8')
    matches = re.findall(r'''(?:src|href)=["']([^"']+)["']''', text)
    return [
        match.lstrip('/')
        for match in matches
        if match and not match.startswith(('http://', 'https://', '//'))
    ]


def _normalize_static_asset_path(raw: str) -> str | None:
    candidate = raw.strip()
    if not candidate:
        return None

    if candidate.startswith(('http://', 'https://', '//', 'data:')):
        return None

    normalized = candidate.split('?', 1)[0].split('#', 1)[0].lstrip('/')
    return normalized or None


def _collect_manifest_references(
    manifest: dict[str, dict],
    key: str,
    refs: list[tuple[str, str]],
    visited: set[str],
) -> None:
    if key in visited:
        return
    visited.add(key)

    entry = manifest.get(key)
    if not isinstance(entry, dict):
        return

    for field in ('file', 'src'):
        value = entry.get(field)
        if isinstance(value, str):
            normalized = _normalize_static_asset_path(value)
            if normalized:
                refs.append((f'manifest[{key}].{field}', normalized))

    for list_field in ('css', 'assets'):
        values = entry.get(list_field)
        if isinstance(values, list):
            for value in values:
                if isinstance(value, str):
                    normalized = _normalize_static_asset_path(value)
                    if normalized:
                        refs.append((f'manifest[{key}].{list_field}', normalized))

    for dep_field in ('imports', 'dynamicImports'):
        deps = entry.get(dep_field)
        if not isinstance(deps, list):
            continue
        for dep in deps:
            if not isinstance(dep, str):
                continue
            if dep in manifest:
                _collect_manifest_references(manifest, dep, refs, visited)
            else:
                normalized = _normalize_static_asset_path(dep)
                if normalized:
                    refs.append((f'manifest[{key}].{dep_field}', normalized))


def _validate_static_tree(web_dir: Path) -> tuple[list[str], int]:
    refs: list[tuple[str, str]] = []
    index_path = web_dir / 'index.html'
    if not index_path.is_file():
        return ['index.html'], 1

    manifest_path = web_dir / 'manifest.json'
    if manifest_path.is_file():
        try:
            manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
        except json.JSONDecodeError as exc:
            logger.warning('Failed to parse %s: %s. Falling back to index.html scan.', manifest_path, exc)
        else:
            if isinstance(manifest, dict):
                visited: set[str] = set()
                for key in manifest.keys():
                    _collect_manifest_references(manifest, key, refs, visited)
            else:
                logger.warning('Unexpected manifest format at %s. Falling back to index.html scan.', manifest_path)
    else:
        logger.warning('manifest.json not found under %s. Falling back to index.html scan.', web_dir)

    if not refs:
        for asset_path in _extract_index_asset_paths(index_path):
            if asset_path.startswith('api/'):
                continue
            refs.append(('index.html', asset_path))

    missing: list[str] = []
    seen_refs: set[str] = set()
    for source, asset_path in refs:
        if asset_path.startswith('api/'):
            continue
        ref_key = f'{source}|{asset_path}'
        if ref_key in seen_refs:
            continue
        seen_refs.add(ref_key)
        if not (web_dir / asset_path).is_file():
            missing.append(f'{source}: {asset_path}')

    return missing, len(seen_refs)


def _publish_built_web_tree() -> tuple[bool, str]:
    """
    Publish a fully built static tree via an atomic symlink swap.

    Flow:
      1) Validate install/share/dashboard_pkg/web is complete.
      2) Copy it into a new versioned release directory.
      3) Atomically replace web_current -> web_releases/<release>.

    Operators should purge CDN/browser caches only after this completes.
    """
    built_web_dir = _built_web_dir()
    missing, checked = _validate_static_tree(built_web_dir)
    if missing:
        preview = ', '.join(missing[:5])
        if len(missing) > 5:
            preview += f', ... (+{len(missing) - 5} more)'
        return False, (
            'Installed static tree is incomplete; refusing to publish '
            f'{built_web_dir}. Validation checked={checked}, missing={len(missing)}. '
            f'Missing: {preview}'
        )
    validation_summary = f'Validation checked={checked}, missing=0.'

    release_root = _web_release_root()
    release_root.mkdir(parents=True, exist_ok=True)

    release_name = datetime.utcnow().strftime('%Y%m%dT%H%M%S') + f'-{uuid.uuid4().hex[:8]}'
    release_dir = release_root / release_name
    tmp_release_dir = release_root / f'.{release_name}.tmp'

    if tmp_release_dir.exists():
        shutil.rmtree(tmp_release_dir)
    shutil.copytree(built_web_dir, tmp_release_dir)

    copied_missing, copied_checked = _validate_static_tree(tmp_release_dir)
    if copied_missing:
        shutil.rmtree(tmp_release_dir, ignore_errors=True)
        preview = ', '.join(copied_missing[:5])
        if len(copied_missing) > 5:
            preview += f', ... (+{len(copied_missing) - 5} more)'
        return False, (
            'Staged static tree is incomplete after copy; refusing to publish. '
            f'Validation checked={copied_checked}, missing={len(copied_missing)}. '
            f'Missing: {preview}'
        )
    copied_validation_summary = f'Validation checked={copied_checked}, missing=0.'

    tmp_release_dir.rename(release_dir)

    published_link = _published_web_dir()
    tmp_link = published_link.with_name(published_link.name + '.tmp')
    if tmp_link.exists() or tmp_link.is_symlink():
        tmp_link.unlink()
    tmp_link.symlink_to(release_dir, target_is_directory=True)
    os.replace(tmp_link, published_link)

    return True, (
        'Published dashboard static tree via atomic symlink swap. '
        f'{validation_summary} {copied_validation_summary} '
        f'Active tree: {published_link} -> {release_dir}. '
        'Cache purge/window for public exposure must happen after this step.'
    )


def _repair_publish_if_needed(*, reason: str) -> tuple[bool, bool, str, list[str]]:
    """
    Check current published tree integrity and optionally force publish.

    Returns:
      (ok, attempted, log, missing_files)
        ok: True when either integrity is healthy or forced publish succeeded.
        attempted: True when _publish_built_web_tree() was executed.
        log: detail log for deploy step output.
        missing_files: missing reference list discovered from web_current validation.
    """
    published_dir = _published_web_dir()

    if not published_dir.exists():
        log = (
            f'Repair trigger({reason}): web_current path does not exist: {published_dir}. '
            'Forcing publish from installed web tree.'
        )
        ok, publish_log = _publish_built_web_tree()
        return ok, True, f'{log}\n{publish_log}', ['web_current: missing directory/symlink']

    if published_dir.is_symlink():
        target = published_dir.resolve(strict=False)
        if not target.exists():
            log = (
                f'Repair trigger({reason}): web_current symlink target is missing: '
                f'{published_dir} -> {target}. Forcing publish.'
            )
            ok, publish_log = _publish_built_web_tree()
            return ok, True, f'{log}\n{publish_log}', [f'web_current symlink target missing: {target}']

    missing, checked = _validate_static_tree(published_dir)
    if missing:
        preview = ', '.join(missing[:5])
        if len(missing) > 5:
            preview += f', ... (+{len(missing) - 5} more)'
        log = (
            f'Repair trigger({reason}): web_current integrity check failed. '
            f'Validation checked={checked}, missing={len(missing)}. Missing: {preview}. '
            'Forcing publish from installed web tree.'
        )
        ok, publish_log = _publish_built_web_tree()
        return ok, True, f'{log}\n{publish_log}', missing

    return True, False, (
        f'Repair skipped({reason}): web_current integrity check passed. '
        f'Validation checked={checked}, missing=0.'
    ), []


def _changed_paths(pull_stdout: str) -> list[str]:
    """Parse 'git pull' stdout to extract list of changed file paths."""
    # git pull --ff-only output format:
    #   Updating abc1234..def5678
    #    path/to/file.py | 3 ++-
    lines = []
    for line in pull_stdout.splitlines():
        stripped = line.strip()
        if '|' in stripped:
            path = stripped.split('|')[0].strip()
            lines.append(path)
    return lines


def _deploy_pipeline(*, force_web_repair: bool = False):
    """Full deploy pipeline. Runs in a background thread."""
    import datetime

    _deploy_job.update({
        'status':      'running',
        'steps':       [],
        'error':       None,
        'missing_files': [],
        'started_at':  datetime.datetime.now().isoformat(),
        'finished_at': None,
    })

    repo = str(REPO_ROOT)
    ros_setup = f'/opt/ros/{_ROS_DISTRO}/setup.bash'

    # ── Step 1: git pull ──────────────────────────────────────────────────────
    ok, pull_log = _run_step(
        'git pull',
        ['git', 'pull', '--ff-only'],
        cwd=repo,
    )
    if not ok:
        _deploy_job.update({'status': 'error', 'error': 'git pull failed',
                            'finished_at': datetime.datetime.now().isoformat()})
        return

    changed = _changed_paths(pull_log)
    already_up_to_date = 'Already up to date' in pull_log

    if already_up_to_date:
        repair_step = {
            'step': 'web integrity check (already up to date)',
            'status': 'running',
            'log': 'git pull reported "Already up to date". Running web_current integrity check.',
        }
        _deploy_job['steps'].append(repair_step)
        ok, attempted, repair_log, missing_files = _repair_publish_if_needed(
            reason='already-up-to-date',
        )
        repair_step['log'] += '\n' + repair_log
        if attempted:
            repair_step['log'] += '\nRepair publish executed due to integrity failure.'
        else:
            repair_step['log'] += '\nRepair publish not required.'
        if not ok:
            repair_step['status'] = 'error'
            _deploy_job.update({
                'status': 'error',
                'error': 'dashboard static repair publish failed',
                'missing_files': missing_files,
                'finished_at': datetime.datetime.now().isoformat(),
            })
            return
        repair_step['status'] = 'done'
        _deploy_job.update({
            'status': 'done',
            'missing_files': [],
            'finished_at': datetime.datetime.now().isoformat(),
        })
        return

    # ── Step 2: npm build (only if web/ files changed) ───────────────────────
    web_changed = any(p.startswith('web/') for p in changed)
    web = _web_dir()

    if web_changed and web:
        ok, _ = _run_step('npm ci', ['npm', 'ci'], cwd=str(web))
        if not ok:
            _deploy_job.update({'status': 'error', 'error': 'npm ci failed',
                                'finished_at': datetime.datetime.now().isoformat()})
            return

        ok, _ = _run_step('npm run build', ['npm', 'run', 'build'], cwd=str(web))
        if not ok:
            _deploy_job.update({'status': 'error', 'error': 'npm run build failed',
                                'finished_at': datetime.datetime.now().isoformat()})
            return
        
    dashboard_changed = any(
        p.startswith('ros2_ws/src/dashboard_pkg/')
        for p in changed
    )

    # ── Step 3: install updated packages/assets ───────────────────────────────
    ros_changed = any(p.startswith('ros2_ws/src/') for p in changed)

    # The dashboard is actually served from install/share/dashboard_pkg/web, so
    # rebuilding only repo/web/dist is not sufficient. Rebuild dashboard_pkg
    # whenever web assets change so the installed index/assets stay in sync.
    packages_to_build = []
    if web_changed or dashboard_changed:
        packages_to_build.append('dashboard_pkg')

    if ros_changed:
        packages_to_build.extend([
            'dashboard_pkg',
            'navigation_pkg',
            'hri_pkg',
            'interaction_pkg',
            'perception_pkg',
            'stt_pkg',
            'tts_pkg',
            'llm_pkg',
            'bringup',
        ])

    packages_to_build = sorted(set(packages_to_build))

    if packages_to_build:
        _deploy_job['steps'].append({
            'step': 'select packages',
            'status': 'done',
            'log': 'Packages selected: ' + ', '.join(packages_to_build),
        })
        package_args = ' '.join(shlex.quote(pkg) for pkg in packages_to_build)
        if not ROS2_WS_ROOT.is_dir():
            _deploy_job.update({
                'status': 'error',
                'error': f'ROS2 workspace not found: {ROS2_WS_ROOT}',
                'finished_at': datetime.datetime.now().isoformat(),
            })
            return

        ok, _ = _run_step(
            'colcon build',
            [
                'bash', '-c',
                f'source {ros_setup} && colcon build --symlink-install --packages-select {package_args}'
            ],
            cwd=str(ROS2_WS_ROOT),
        )
        if not ok:
            _deploy_job.update({'status': 'error', 'error': 'colcon build failed',
                                'finished_at': datetime.datetime.now().isoformat()})
            return

    # ── Step 4: publish dashboard static tree only after install completes ───
    should_attempt_repair = force_web_repair or web_changed
    if should_attempt_repair:
        step = {
            'step': 'publish dashboard static tree',
            'status': 'running',
            'log': (
                'Validating install/share/dashboard_pkg/web, copying into a new '
                'versioned release directory, and switching web_current only '
                'after the full asset set is present. Purge caches only after '
                'this step reports done.'
            ),
        }
        _deploy_job['steps'].append(step)
        if force_web_repair and not web_changed:
            step['log'] += '\nRepair mode enabled: running integrity check and publishing only if needed.'
            ok, attempted, publish_log, missing_files = _repair_publish_if_needed(reason='manual-repair')
            step['log'] += '\n' + publish_log
            step['log'] += '\nRepair publish executed.' if attempted else '\nRepair publish skipped.'
        else:
            ok, publish_log = _publish_built_web_tree()
            missing_files = []
            step['log'] += '\nPublish mode: web changes detected; publish is mandatory.'
            step['log'] += '\n' + publish_log
            step['log'] += '\nRepair publish executed.'
        if not ok:
            step['status'] = 'error'
            _deploy_job.update({
                'status': 'error',
                'error': 'dashboard static publish failed',
                'missing_files': missing_files,
                'finished_at': datetime.datetime.now().isoformat(),
            })
            return
        step['status'] = 'done'

    requires_restart = dashboard_changed

    _deploy_job.update({
        'status': 'done',
        'missing_files': [],
        'finished_at': datetime.datetime.now().isoformat(),
    })

    if requires_restart:
        import signal
        import os

        _deploy_job['steps'].append({
            'step': 'restart knowledge api',
            'status': 'done',
            'log': 'dashboard_pkg change is detected and knowledge_api process is restarted.',
        })
        os.kill(os.getpid(), signal.SIGTERM)


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.post('/api/webhook')
async def github_webhook(request: Request):
    """Receive GitHub push webhook, trigger deploy pipeline on main branch."""
    body = await request.body()
    sig  = request.headers.get('X-Hub-Signature-256')

    if not _verify_github_signature(body, sig):
        return JSONResponse({'error': 'Invalid signature'}, status_code=403)

    event = request.headers.get('X-GitHub-Event', '')
    if event != 'push':
        return JSONResponse({'skipped': f'event={event}'})

    try:
        payload = json.loads(body)
    except Exception:
        return JSONResponse({'error': 'Invalid JSON'}, status_code=400)

    if payload.get('ref') != 'refs/heads/main':
        return JSONResponse({'skipped': f"ref={payload.get('ref')}"})

    with _deploy_lock:
        if _deploy_job['status'] == 'running':
            return JSONResponse({'skipped': 'deploy already in progress'}, status_code=409)
        thread = threading.Thread(target=_deploy_pipeline, daemon=True)
        thread.start()

    return JSONResponse({'ok': True, 'message': 'Deploy started'})


@app.get('/api/deploy/status')
async def deploy_status(_: AuthPrincipal = Depends(require_permission('view'))):
    """Poll deploy pipeline progress."""
    return JSONResponse(_deploy_job)


@app.post('/api/deploy/trigger')
async def deploy_trigger(_: AuthPrincipal = Depends(require_permission('admin'))):
    """Manually trigger the deploy pipeline (no webhook needed, dev use)."""
    with _deploy_lock:
        if _deploy_job['status'] == 'running':
            return JSONResponse({'skipped': 'deploy already in progress'}, status_code=409)
        thread = threading.Thread(target=_deploy_pipeline, daemon=True)
        thread.start()
    return JSONResponse({'ok': True, 'message': 'Deploy started'})


@app.post('/api/deploy/repair-web')
async def deploy_repair_web(_: AuthPrincipal = Depends(require_permission('admin'))):
    """Run a web integrity check and repair-publish if required."""
    with _deploy_lock:
        if _deploy_job['status'] == 'running':
            return JSONResponse({'skipped': 'deploy already in progress'}, status_code=409)
        thread = threading.Thread(
            target=_deploy_pipeline,
            kwargs={'force_web_repair': True},
            daemon=True,
        )
        thread.start()
    return JSONResponse({'ok': True, 'message': 'Repair deploy started'})

# ── Entrypoint ─────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    import uvicorn
    print(f'[DORI Knowledge API] Repo root : {REPO_ROOT}')
    print(f'[DORI Knowledge API] Parser    : {PARSER_SCRIPT}')
    print(f'[DORI Knowledge API] Builder   : {BUILDER_SCRIPT}')
    print(f'[DORI Knowledge API] Listening : http://0.0.0.0:{args.port}')
    uvicorn.run(app, host='0.0.0.0', port=args.port, log_level='warning')
