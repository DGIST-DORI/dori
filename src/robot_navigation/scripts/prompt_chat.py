#!/usr/bin/env python3
from __future__ import annotations

import argparse
import getpass
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path


DEFAULT_MODEL = os.getenv("OPENAI_MODEL", "gpt-5.4")



def ensure_openai_api_key() -> str:
    api_key = os.getenv("OPENAI_API_KEY")
    if api_key:
        return api_key

    try:
        api_key = getpass.getpass("OpenAI API key (hidden, not saved): ").strip()
    except (EOFError, KeyboardInterrupt) as exc:
        raise RuntimeError("OPENAI_API_KEY is not set") from exc
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set")

    os.environ["OPENAI_API_KEY"] = api_key
    return api_key


def read_system_prompt(prompt_file: Path) -> str:
    try:
        text = prompt_file.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise RuntimeError(f"Failed to read prompt file: {prompt_file}") from exc
    if not text:
        raise RuntimeError(f"Prompt file is empty: {prompt_file}")
    return text


def call_responses_api(api_key: str, model: str, system_prompt: str, user_prompt: str) -> str:
    payload = {
        "model": model,
        "instructions": system_prompt,
        "input": user_prompt,
        "max_output_tokens": 256,
        "store": False,
    }

    request = urllib.request.Request(
        "https://api.openai.com/v1/responses",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=30.0) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {detail[:400]}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"URL error: {exc}") from exc

    output = body.get("output", [])
    for item in output:
        if item.get("type") != "message":
            continue
        for content in item.get("content", []):
            if content.get("type") == "output_text":
                text = (content.get("text") or "").strip()
                if text:
                    return text

    raise RuntimeError(f"Could not extract output_text from response: {body}")


def parse_args() -> argparse.Namespace:
    root_dir = Path(__file__).resolve().parents[1]
    default_prompt_file = root_dir / "prompt.txt"

    parser = argparse.ArgumentParser(
        description="Stateless OpenAI chat using ros2_2d_slam/prompt.txt as the system prompt."
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
        help=f"OpenAI model name (default: {DEFAULT_MODEL})",
    )
    return parser.parse_args()


def print_help() -> None:
    print(
        "Commands:\n"
        "  /quit   exit\n"
        "  /paste  enter multiline input mode, finish with /send\n"
        "  /reload reload prompt.txt from disk\n"
        "  /show   print the current system prompt path\n"
        "  <text>  send one fresh user prompt\n",
        flush=True,
    )


def main() -> int:
    args = parse_args()
    prompt_file = args.prompt_file.resolve()

    try:
        api_key = ensure_openai_api_key()
        system_prompt = read_system_prompt(prompt_file)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr, flush=True)
        return 1

    print(f"Prompt file: {prompt_file}", flush=True)
    print(f"Model: {args.model}", flush=True)
    print(f"OPENAI_API_KEY set: {'yes' if bool(api_key) else 'no'}", flush=True)
    print("Mode: stateless. Each input is sent as a new request with no conversation history.", flush=True)
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
            continue
        if user_prompt == "/help":
            print_help()
            continue

        try:
            response_text = call_responses_api(
                api_key=api_key,
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
