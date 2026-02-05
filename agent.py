#!/usr/bin/env python3
"""
Multi-backend News-Card Agent with tool calling.

Backends
--------
    claude  — Anthropic SDK, Extended Thinking + tool_use
    kimi    — Moonshot Kimi K2 via OpenAI-compatible SDK + function calling

Tools available to the model
-----------------------------
    search_web      — DuckDuckGo text search (no API key)
    download_image  — fetch an image from a URL to a local file
    generate_card   — render a 1080×1350 news card via card_generator.py

Environment variables
---------------------
    BACKEND            claude | kimi   (default: claude)
    ANTHROPIC_API_KEY  required when backend = claude
    MOONSHOT_API_KEY   required when backend = kimi

CRITICAL — thinking-block rule (Claude backend)
-----------------------------------------------
    Extended Thinking returns [ThinkingBlock, TextBlock, ToolUseBlock, …].
    Every block must be stored EXACTLY as returned (via model_dump()).
    Filtering or re-creating them triggers a 400 on the next turn.
"""

import json
import os
import uuid
from pathlib import Path
from typing import Optional

import anthropic
from openai import OpenAI

from card_generator import CardGenerator
from search import search_web, download_image, create_placeholder

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
BACKEND = os.environ.get("BACKEND", "claude").lower()

# Claude
CLAUDE_MODEL   = "claude-sonnet-4-5-20250929"
CLAUDE_MAX_TOK = 16_000
CLAUDE_THINK   = 10_000

# Kimi K2  (OpenAI-compatible)
KIMI_MODEL     = "kimi-k2-0905-preview"
KIMI_MAX_TOK   = 8_000

MAX_TOOL_ROUNDS = 10   # safety cap — stops infinite tool loops

SYSTEM_PROMPT = (
    "You are a news-card bot. You can search the internet for news, "
    "download photos, and generate news-card images automatically.\n"
    "When the user asks you to find news or create a card, use the tools.\n"
    "Always try to find and download a relevant photo before generating the card. "
    "If no photo can be downloaded, generate the card anyway — a placeholder will be used."
)

# ---------------------------------------------------------------------------
# Tool schemas  (shared definition; adapted to Claude / OpenAI format below)
# ---------------------------------------------------------------------------
_TOOL_DEFS = [
    {
        "name": "search_web",
        "description": (
            "Search the internet for news or information using DuckDuckGo. "
            "Returns a list of results with title, snippet, and URL."
        ),
        "properties": {
            "query":       {"type": "string",  "description": "The search query"},
            "max_results": {"type": "integer", "description": "Number of results to return (1-10). Default 5."},
        },
        "required": ["query"],
    },
    {
        "name": "download_image",
        "description": (
            "Download an image from a URL and save it to a local file. "
            "Returns the local path on success or null on failure. "
            "Use this to grab a photo from a news-article page for card generation."
        ),
        "properties": {
            "url":  {"type": "string", "description": "Full URL of the image"},
            "dest": {"type": "string", "description": "Local path to save to (default: temp/downloaded.jpg)"},
        },
        "required": ["url"],
    },
    {
        "name": "generate_card",
        "description": (
            "Generate a 1080x1350 news card image and save it as JPEG. "
            "If photo_path is missing or the file does not exist, a dark placeholder background is used. "
            "Returns the path to the saved card."
        ),
        "properties": {
            "photo_path": {"type": "string", "description": "Path to the photo file. Omit or leave empty for placeholder."},
            "name":       {"type": "string", "description": "Name / headline (uppercased automatically on the card)"},
            "text":       {"type": "string", "description": "Body / description text for the card"},
        },
        "required": ["name", "text"],
    },
]


def _to_claude_tools() -> list[dict]:
    return [
        {
            "name":         d["name"],
            "description":  d["description"],
            "input_schema": {
                "type":       "object",
                "properties": d["properties"],
                "required":   d["required"],
            },
        }
        for d in _TOOL_DEFS
    ]


def _to_openai_tools() -> list[dict]:
    return [
        {
            "type": "function",
            "function": {
                "name":        d["name"],
                "description": d["description"],
                "parameters":  {
                    "type":       "object",
                    "properties": d["properties"],
                    "required":   d["required"],
                },
            },
        }
        for d in _TOOL_DEFS
    ]


# ---------------------------------------------------------------------------
# Tool executor
# ---------------------------------------------------------------------------
def _run_tool(name: str, args: dict) -> str:
    """Dispatch a tool call and return the result as a JSON string."""
    print(f"  [tool:{name}] {json.dumps(args, ensure_ascii=False)}")

    if name == "search_web":
        return json.dumps(
            search_web(args["query"], args.get("max_results", 5)),
            ensure_ascii=False,
        )

    if name == "download_image":
        path = download_image(args["url"], args.get("dest", "temp/downloaded.jpg"))
        return json.dumps({"path": path, "success": path is not None})

    if name == "generate_card":
        photo = args.get("photo_path", "")
        if not photo or not Path(photo).exists():
            photo = create_placeholder()
            print(f"  [tool:generate_card] using placeholder → {photo}")

        Path("cards").mkdir(exist_ok=True)
        safe  = args["name"].replace(" ", "_").replace("/", "_")[:40]
        out   = f"cards/{safe}_{uuid.uuid4().hex[:8]}.jpg"

        CardGenerator().generate(photo, args["name"], args["text"], out)
        print(f"  [tool:generate_card] saved → {out}")
        return json.dumps({"card_path": out, "success": True})

    return json.dumps({"error": f"unknown tool: {name}"})


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------
class Agent:
    def __init__(self, backend: str = BACKEND):
        self.backend = backend.lower()
        self.history: list[dict] = []

        if self.backend == "claude":
            self.client = anthropic.Anthropic(
                api_key=os.environ.get("ANTHROPIC_API_KEY")
            )
            self.tools = _to_claude_tools()

        elif self.backend == "kimi":
            self.client = OpenAI(
                api_key=os.environ.get("MOONSHOT_API_KEY"),
                base_url="https://api.moonshot.ai/v1",
            )
            self.tools = _to_openai_tools()
            # OpenAI-style APIs need the system message inside the messages list
            self.history.append({"role": "system", "content": SYSTEM_PROMPT})

        else:
            raise ValueError(f"Unknown backend '{backend}'. Use 'claude' or 'kimi'.")

    # ── public ─────────────────────────────────────────────────────────────
    def chat(self, user_input: str) -> str:
        """Agentic loop: user → model → tools → … → final text."""
        self.history.append({"role": "user", "content": user_input})

        for _ in range(MAX_TOOL_ROUNDS):
            text = self._turn_claude() if self.backend == "claude" else self._turn_kimi()
            if text is not None:
                return text

        return "[stopped — tool-call limit reached]"

    def reset(self) -> None:
        self.history.clear()
        if self.backend == "kimi":
            self.history.append({"role": "system", "content": SYSTEM_PROMPT})

    # ── Claude turn ────────────────────────────────────────────────────────
    def _turn_claude(self) -> Optional[str]:
        response = self.client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=CLAUDE_MAX_TOK,
            thinking={"type": "enabled", "budget_tokens": CLAUDE_THINK},
            system=SYSTEM_PROMPT,
            tools=self.tools,
            messages=self.history,
        )

        # CRITICAL: store every block unchanged (thinking + tool_use + text)
        self.history.append({
            "role":    "assistant",
            "content": [block.model_dump() for block in response.content],
        })

        tool_uses = [b for b in response.content if b.type == "tool_use"]
        if not tool_uses:
            # No tool calls → return visible text
            return "\n".join(b.text for b in response.content if b.type == "text")

        # Execute all tools, send results back in one user message
        self.history.append({
            "role": "user",
            "content": [
                {
                    "type":        "tool_result",
                    "tool_use_id": tu.id,
                    "content":     _run_tool(tu.name, tu.input),
                }
                for tu in tool_uses
            ],
        })
        return None   # loop again

    # ── Kimi / OpenAI turn ─────────────────────────────────────────────────
    def _turn_kimi(self) -> Optional[str]:
        response = self.client.chat.completions.create(
            model=KIMI_MODEL,
            max_tokens=KIMI_MAX_TOK,
            temperature=0.6,
            tools=self.tools,
            messages=self.history,
        )

        msg = response.choices[0].message

        if not msg.tool_calls:
            self.history.append({"role": "assistant", "content": msg.content})
            return msg.content or ""

        # Store assistant message with tool_calls exactly as returned
        self.history.append({
            "role":    "assistant",
            "content": msg.content,
            "tool_calls": [
                {
                    "id":   tc.id,
                    "type": "function",
                    "function": {
                        "name":      tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                }
                for tc in msg.tool_calls
            ],
        })

        # Execute each tool → individual "tool" role messages
        for tc in msg.tool_calls:
            self.history.append({
                "role":         "tool",
                "tool_call_id": tc.id,
                "content":      _run_tool(tc.function.name, json.loads(tc.function.arguments)),
            })
        return None   # loop again


# ---------------------------------------------------------------------------
# CLI loop
# ---------------------------------------------------------------------------
def main():
    agent = Agent()
    print("=" * 60)
    print(f" News-Card Agent  [backend: {agent.backend.upper()}]")
    print(" Commands:  quit — exit  |  reset — clear history")
    print(" Example:   Search for news about [topic] and make a card")
    print("=" * 60 + "\n")

    while True:
        try:
            user_input = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nBye.")
            break

        if not user_input:
            continue
        if user_input.lower() == "quit":
            print("Bye.")
            break
        if user_input.lower() == "reset":
            agent.reset()
            print("[History cleared]\n")
            continue

        try:
            reply = agent.chat(user_input)
            print(f"\nAgent: {reply}\n")
        except anthropic.BadRequestError as exc:
            print(f"\n[API 400] {exc.message}\n")
        except anthropic.APIError as exc:
            print(f"\n[API Error] {exc.message}\n")
        except Exception as exc:
            print(f"\n[Error] {exc}\n")


if __name__ == "__main__":
    main()
