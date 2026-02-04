#!/usr/bin/env python3
"""
Claude Agent with Extended Thinking — multi-turn safe.

ROOT CAUSE of the common 400 error:
    "thinking or redacted_thinking blocks in the latest assistant
     message cannot be modified."

    When Extended Thinking is enabled the API returns content blocks
    like:  [ThinkingBlock, TextBlock]
    In every subsequent turn you MUST send those blocks back
    completely unchanged.  Stripping, filtering or re-creating them
    triggers the 400.

FIX applied here:
    • The full assistant content (including thinking / redacted_thinking
      blocks) is stored exactly as returned by the SDK.
    • Only display text is extracted separately; the history is never
      touched.
"""

import os
import anthropic

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
MODEL          = "claude-sonnet-4-5-20250929"
MAX_TOKENS     = 16_000          # must be > budget_tokens
THINKING_BUDGET = 10_000         # tokens the model may use for thinking
SYSTEM_PROMPT  = "You are a helpful assistant."

client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))


# ---------------------------------------------------------------------------
# Agent class
# ---------------------------------------------------------------------------
class Agent:
    def __init__(
        self,
        model: str = MODEL,
        system: str = SYSTEM_PROMPT,
        max_tokens: int = MAX_TOKENS,
        thinking_budget: int = THINKING_BUDGET,
    ):
        self.model          = model
        self.system         = system
        self.max_tokens     = max_tokens
        self.thinking_budget = thinking_budget
        self.history: list[dict] = []   # full message history (never mutated)

    # --- public API --------------------------------------------------------
    def chat(self, user_input: str) -> str:
        """Send a user message, get back the visible text response."""
        # 1. Append the new user turn
        self.history.append({"role": "user", "content": user_input})

        # 2. Call the API — pass the FULL history as-is
        response = client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            thinking={
                "type": "enabled",
                "budget_tokens": self.thinking_budget,
            },
            system=self.system,
            messages=self.history,          # ← includes prior thinking blocks
        )

        # 3. Store the assistant reply EXACTLY as returned.
        #    model_dump() serialises ThinkingBlock / RedactedThinkingBlock /
        #    TextBlock into the plain dicts the API expects on the next call.
        #    Do NOT filter, modify or skip any block here.
        self.history.append({
            "role": "assistant",
            "content": [block.model_dump() for block in response.content],
        })

        # 4. Extract only the visible text for the caller
        return self._extract_text(response.content)

    def reset(self) -> None:
        """Clear conversation history."""
        self.history.clear()

    # --- helpers -----------------------------------------------------------
    @staticmethod
    def _extract_text(content_blocks) -> str:
        """Return concatenated text from TextBlock(s) only."""
        return "\n".join(
            block.text for block in content_blocks if block.type == "text"
        )


# ---------------------------------------------------------------------------
# CLI loop
# ---------------------------------------------------------------------------
def main():
    agent = Agent()
    print("=" * 60)
    print(" Claude Agent (Extended Thinking)")
    print(" Commands: 'quit' — exit | 'reset' — clear history")
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
            # Surface the raw API error so it is easy to debug
            print(f"\n[API 400 Error] {exc.message}\n")
        except anthropic.APIError as exc:
            print(f"\n[API Error] {exc.message}\n")
        except Exception as exc:
            print(f"\n[Error] {exc}\n")


if __name__ == "__main__":
    main()
