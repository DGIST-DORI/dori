#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


DEFAULT_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:3b")
DEFAULT_BASE_URL = (
    os.getenv("OLLAMA_BASE_URL")
    or os.getenv("OLLAMA_HOST")
    or "http://127.0.0.1:11434"
).rstrip("/")


def read_system_prompt(prompt_file: Path) -> str:
    try:
        text = prompt_file.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise RuntimeError(f"Failed to read prompt file: {prompt_file}") from exc
    if not text:
        raise RuntimeError(f"Prompt file is empty: {prompt_file}")
    return text


def http_json(method: str, url: str, payload: dict[str, Any] | None = None, timeout: float = 30.0) -> dict[str, Any]:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method=method,
    )

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {detail[:400]}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"URL error: {exc}") from exc

    try:
        return json.loads(body)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Invalid JSON response from {url}: {body[:400]}") from exc


def list_local_models(base_url: str) -> list[str]:
    body = http_json("GET", f"{base_url}/api/tags", timeout=10.0)
    models = body.get("models", [])
    names: list[str] = []
    for model in models:
        name = model.get("name")
        if isinstance(name, str) and name:
            names.append(name)
    return names


def call_ollama_chat(base_url: str, model: str, system_prompt: str, user_prompt: str) -> str:
    body = http_json(
        "POST",
        f"{base_url}/api/chat",
        payload={
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "stream": False,
        },
    )

    message = body.get("message", {})
    content = message.get("content")
    if isinstance(content, str) and content.strip():
        return content.strip()

    raise RuntimeError(f"Could not extract assistant content from response: {body}")


def parse_args() -> argparse.Namespace:
    root_dir = Path(__file__).resolve().parents[1]
    default_prompt_file = root_dir / "prompt.txt"

    parser = argparse.ArgumentParser(
        description="Stateless Ollama chat using ros2_2d_slam/prompt.txt as the system prompt."
    )
    parser.add_argument(
        "--prompt-file",
        type=Path,
        default=default_prompt_file,
        help=f"Path to the system prompt file (default: {default_prompt_file})",
    )
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help=f"Ollama model name (default: {DEFAULT_MODEL})",
    )
    parser.add_argument(
        "--base-url",
        default=DEFAULT_BASE_URL,
        help=f"Ollama base URL (default: {DEFAULT_BASE_URL})",
    )
    return parser.parse_args()


def print_help() -> None:
    print(
        "Commands:\n"
        "  /quit   exit\n"
        "  /paste  enter multiline input mode, finish with /send\n"
        "  /reload reload prompt.txt from disk\n"
        "  /show   print the current system prompt path and Ollama endpoint\n"
        "  <text>  send one fresh user prompt\n",
        flush=True,
    )


def print_model_warning(base_url: str, model: str) -> None:
    try:
        names = list_local_models(base_url)
    except RuntimeError as exc:
        print(f"Warning: could not query Ollama models: {exc}", flush=True)
        return

    if model not in names:
        print(
            f"Warning: model '{model}' is not installed in Ollama. "
            f"Run `ollama pull {model}` or pass `--model <installed-model>`.",
            flush=True,
        )


def main() -> int:
    args = parse_args()
    prompt_file = args.prompt_file.resolve()
    base_url = args.base_url.rstrip("/")

    try:
        system_prompt = read_system_prompt(prompt_file)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr, flush=True)
        return 1

    print(f"Prompt file: {prompt_file}", flush=True)
    print(f"Ollama base URL: {base_url}", flush=True)
    print(f"Model: {args.model}", flush=True)
    print("Mode: stateless. Each input is sent as a new request with no conversation history.", flush=True)
    print_model_warning(base_url, args.model)
    print_help()

    while True:
        try:
            user_prompt = input("user> ").strip()
        except EOFError:
            print("", flush=True)
            break
        except KeyboardInterrupt:
            print("", flush=True)
            break

        if not user_prompt:
            continue
        if user_prompt in {"/quit", "/exit"}:
            break
        if user_prompt == "/paste":
            print("Paste mode. End with /send on its own line.", flush=True)
            lines: list[str] = []
            while True:
                try:
                    line = input("... ")
                except EOFError:
                    print("", flush=True)
                    break
                except KeyboardInterrupt:
                    print("", flush=True)
                    lines = []
                    break
                if line.strip() == "/send":
                    break
                lines.append(line)
            user_prompt = "\n".join(lines).strip()
            if not user_prompt:
                continue
        if user_prompt == "/reload":
            try:
                system_prompt = read_system_prompt(prompt_file)
            except RuntimeError as exc:
                print(str(exc), flush=True)
                continue
            print(f"Reloaded system prompt from {prompt_file}", flush=True)
            continue
        if user_prompt == "/show":
            print(f"Prompt file: {prompt_file}", flush=True)
            print(f"Ollama base URL: {base_url}", flush=True)
            print(f"Model: {args.model}", flush=True)
            continue
        if user_prompt == "/help":
            print_help()
            continue

        try:
            response_text = call_ollama_chat(
                base_url=base_url,
                model=args.model,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
            )
        except RuntimeError as exc:
            print(f"Request failed: {exc}", flush=True)
            continue

        print(response_text, flush=True)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
