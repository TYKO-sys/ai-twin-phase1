"""
openrouter_client.py
====================
OpenRouter LLM client — OpenAI-compatible API that routes to 100+ models.

Why OpenRouter instead of direct Gemini?
  - Single API key, access to models from Google, Anthropic, Meta, Mistral, etc.
  - If one provider is down, OpenRouter can route to another
  - Built-in rate limit management across providers
  - Free models available (Llama 3.3 70B, Mistral, Deepseek)
  - OpenAI-compatible API (industry standard, simple)

This client has the same interface as GeminiClient:
  - generate(prompt, system_instruction, image_bytes, audio_bytes) -> str
  - generate_with_tools(prompt, system_instruction, tools_config, tool_executor) -> str

Model cycling: if the primary model fails, it tries fallback models.
This is the "model cycler" the user asked about.

Cost: OpenRouter gives $5 free credit on signup. After that:
  - Free models (Llama 3.3 70B): $0
  - Cheap models (Deepseek): ~$0.20/M tokens
  - Premium models (Claude Sonnet): ~$3/M tokens
"""

from __future__ import annotations

import base64
import json
import logging
import time
from typing import Optional, Callable

import requests

log = logging.getLogger("openrouter")

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1/chat/completions"


class OpenRouterClient:
    """OpenRouter LLM client with model cycling and tool support."""

    # Primary model — free, supports tools, good quality
    # These are the ACTUAL model names from OpenRouter's API as of 2026-08-30
    DEFAULT_MODEL = "z-ai/glm-5.2:free"

    # Fallback models — all free, all support tool calling
    # Verified from https://openrouter.ai/api/v1/models
    FALLBACK_MODELS = [
        "google/gemma-4-31b-it:free",           # Google's open model
        "nvidia/nemotron-3.5-lightning:free",    # 1M context
        "minimax/minimax-m3:free",               # 1M context
        "thinkingmachines/inkling-small:free",   # 1M context
        "openrouter/free",                       # OpenRouter's own free model
    ]

    # Rate limiting: OpenRouter is more generous than Gemini
    MIN_SECONDS_BETWEEN_REQUESTS = 2.0

    def __init__(self, api_key: str, model: str = None,
                 timeout: int = 120,
                 site_url: str = "https://github.com",
                 site_name: str = "AI Twin"):
        self.api_key = api_key
        self.model = model or self.DEFAULT_MODEL
        self.timeout = timeout
        self._last_request_time = 0.0
        self._tried_models: set = set()
        self._available_models: list = []  # cached from /models endpoint
        self._models_checked = False

        # OpenRouter recommends setting these headers for ranking
        self.headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": site_url,
            "X-Title": site_name,
        }

    def _fetch_available_models(self) -> list:
        """Fetch the list of available models from OpenRouter.

        Returns a list of model IDs. Used to find working free models
        if our configured ones are outdated.
        """
        if self._models_checked:
            return self._available_models

        try:
            resp = requests.get(
                "https://openrouter.ai/api/v1/models",
                headers={"Authorization": f"Bearer {self.api_key}"},
                timeout=30,
            )
            if resp.status_code == 200:
                data = resp.json()
                models = data.get("data", [])
                self._available_models = [m.get("id", "") for m in models]
                self._models_checked = True
                log.info(
                    f"OpenRouter: found {len(self._available_models)} "
                    f"available models"
                )
                return self._available_models
        except Exception as e:
            log.warning(f"Could not fetch OpenRouter model list: {e}")

        return []

    def _find_working_free_model(self) -> Optional[str]:
        """Find a free model that actually exists on OpenRouter.

        Tries our configured list first, then searches the full model list
        for any free model that supports tool calling.
        """
        available = self._fetch_available_models()

        if not available:
            # Can't verify — just return the first fallback
            return self.FALLBACK_MODELS[0] if self.FALLBACK_MODELS else None

        # First, check if any of our configured models are available
        all_models = [self.model] + self.FALLBACK_MODELS
        for m in all_models:
            if m in available and m not in self._tried_models:
                return m

        # None of ours work — search for any free model that supports tools
        free_models_with_tools = [
            "z-ai/glm-5.2:free",
            "google/gemma-4-31b-it:free",
            "nvidia/nemotron-3.5-lightning:free",
            "minimax/minimax-m3:free",
            "thinkingmachines/inkling-small:free",
            "openrouter/free",
            "google/gemma-4-26b-a4b-it:free",
            "nvidia/nemotron-3-ultra-550b-a55b:free",
            "minimax/minimax-m2.7:free",
            "nvidia/nemotron-3-super-120b-a12b:free",
            "thinkingmachines/inkling:free",
            "cohere/north-mini-code:free",
            "inclusionai/ling-3.0-flash-fin:free",
            "poolside/laguna-s-2.1:free",
            "poolside/laguna-xs-2.1:free",
            "liquid/lfm-2.5-2.6b:free",
            "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free",
            "dots-studio/dots-3-note-preview:free",
        ]
        for m in free_models_with_tools:
            if m in available and m not in self._tried_models:
                log.info(f"Found working free model: {m}")
                return m

        # Last resort: any free model at all
        for m in available:
            if ":free" in m and m not in self._tried_models:
                log.info(f"Using any free model: {m}")
                return m

        return None

    def _throttle(self) -> None:
        """Rate limit: wait if we made a request too recently."""
        now = time.time()
        elapsed = now - self._last_request_time
        if elapsed < self.MIN_SECONDS_BETWEEN_REQUESTS:
            wait = self.MIN_SECONDS_BETWEEN_REQUESTS - elapsed
            time.sleep(wait)
        self._last_request_time = time.time()

    def _pick_fallback_model(self) -> Optional[str]:
        """Pick the next untried fallback model.

        First tries our configured fallback list, then queries OpenRouter
        for any available free model if our list is exhausted or outdated.
        """
        # Try our configured fallbacks first
        for m in self.FALLBACK_MODELS:
            if m != self.model and m not in self._tried_models:
                return m

        # Our list is exhausted — search OpenRouter for any working free model
        return self._find_working_free_model()

    def generate(
        self,
        prompt: str,
        system_instruction: Optional[str] = None,
        image_bytes: Optional[bytes] = None,
        audio_bytes: Optional[bytes] = None,
        audio_mime: str = "audio/ogg",
    ) -> str:
        """Generate a response (no tools). Same interface as GeminiClient.

        For images, uses OpenAI vision format (image_url with base64 data).
        Audio is not directly supported by most OpenRouter models, so we
        fall back to text-only if audio is provided.
        """
        # Build messages in OpenAI format
        messages = []

        if system_instruction:
            messages.append({"role": "system", "content": system_instruction})

        # User message — handle text + image
        if image_bytes:
            # Vision format (OpenAI-compatible)
            b64_image = base64.b64encode(image_bytes).decode("ascii")
            messages.append({
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{b64_image}"
                        }
                    }
                ]
            })
        else:
            messages.append({"role": "user", "content": prompt})

        return self._call_api(messages, tools=None, max_retries=5)

    def generate_with_tools(
        self,
        prompt: str,
        system_instruction: Optional[str] = None,
        tools_config: Optional[dict] = None,
        tool_executor: Optional[Callable] = None,
        max_iterations: int = 5,
    ) -> str:
        """Generate with tool/function calling support.

        tools_config should be in Gemini format (functionDeclarations).
        We convert to OpenAI format internally.
        """
        if not tools_config or not tool_executor:
            return self.generate(prompt, system_instruction=system_instruction)

        # Convert Gemini tool format to OpenAI format
        openai_tools = self._convert_tools_to_openai(tools_config)

        # Build initial messages
        messages = []
        if system_instruction:
            messages.append({"role": "system", "content": system_instruction})
        messages.append({"role": "user", "content": prompt})

        # Tool calling loop
        for iteration in range(max_iterations):
            response_data = self._call_api_raw(
                messages, tools=openai_tools, max_retries=10
            )

            if response_data is None:
                return "(I'm having trouble reaching the AI service right now.)"

            choice = response_data.get("choices", [{}])[0]
            message = choice.get("message", {})
            finish_reason = choice.get("finish_reason", "stop")

            # Check for tool calls
            tool_calls = message.get("tool_calls", [])

            if tool_calls:
                # Add assistant message to history
                messages.append(message)

                # Execute each tool call
                for tc in tool_calls:
                    func = tc.get("function", {})
                    func_name = func.get("name", "")
                    func_args_str = func.get("arguments", "{}")

                    try:
                        func_args = json.loads(func_args_str)
                    except json.JSONDecodeError:
                        func_args = {}

                    log.info(f"Tool call: {func_name}({func_args})")

                    try:
                        result = tool_executor(func_name, func_args)
                    except Exception as e:
                        result = f"Error: {type(e).__name__}: {e}"

                    log.info(f"Tool result ({func_name}): {result[:200]}...")

                    # Add tool result to messages
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.get("id", ""),
                        "content": result,
                    })

                # Continue to next iteration — model will process tool results
                continue

            # No tool calls — extract text and return
            content = message.get("content", "") or ""
            result = content.strip()

            usage = response_data.get("usage", {})
            log.info(
                f"OpenRouter response: {len(result)} chars, "
                f"finish={finish_reason}, "
                f"iterations={iteration+1}, "
                f"model={response_data.get('model', self.model)}, "
                f"tokens={usage.get('total_tokens', '?')}"
            )

            if finish_reason == "length":
                result += (
                    "\n\n[... response truncated — I ran out of output "
                    "tokens. Ask me to continue. ...]"
                )

            return result

        return (
            "(I used several tools to research this but hit my iteration "
            "limit. Here's what I found so far — ask me to continue if "
            "you need more.)"
        )

    def _convert_tools_to_openai(self, gemini_tools: dict) -> list:
        """Convert Gemini tool format to OpenAI format.

        Gemini: {"functionDeclarations": [{"name": ..., "description": ..., "parameters": {...}}]}
        OpenAI: [{"type": "function", "function": {"name": ..., "description": ..., "parameters": {...}}}]
        """
        openai_tools = []
        for fd in gemini_tools.get("functionDeclarations", []):
            openai_tools.append({
                "type": "function",
                "function": {
                    "name": fd.get("name", ""),
                    "description": fd.get("description", ""),
                    "parameters": fd.get("parameters", {"type": "object", "properties": {}}),
                }
            })
        return openai_tools

    def _call_api_raw(
        self,
        messages: list,
        tools: Optional[list] = None,
        max_retries: int = 10,
    ) -> Optional[dict]:
        """Call OpenRouter API and return raw JSON response.

        Returns None if all retries fail.
        Increased max_retries to 10 to allow trying all fallback models.
        """
        body = {
            "model": self.model,
            "messages": messages,
            "max_tokens": 8192,
            "temperature": 0.9,
        }

        if tools:
            body["tools"] = tools
            body["tool_choice"] = "auto"

        last_err = None
        for attempt in range(max_retries):
            self._throttle()

            try:
                resp = requests.post(
                    OPENROUTER_BASE_URL,
                    headers=self.headers,
                    json=body,
                    timeout=self.timeout,
                )

                if resp.status_code == 200:
                    return resp.json()

                elif resp.status_code == 429:
                    # Rate limited — free models share a 20/min limit PER IP
                    # On a phone, your IP is shared with thousands of other
                    # users on your carrier. So 429s happen even if you
                    # haven't made any requests yourself.
                    #
                    # Strategy: try a different free model (different pool),
                    # only wait if we've exhausted all models.
                    retry_after = resp.headers.get("Retry-After", "60")
                    try:
                        wait = float(retry_after)
                    except ValueError:
                        wait = 60.0
                    wait = min(wait, 90.0)

                    log.warning(
                        f"OpenRouter 429 rate limited on {self.model}. "
                        f"This is likely shared-IP rate limiting, not your usage."
                    )

                    # Try switching to a different free model first
                    # (different models may have different rate limit pools)
                    self._tried_models.add(self.model)
                    fallback = self._pick_fallback_model()
                    if fallback:
                        log.info(f"Switching to different model: {fallback}")
                        self.model = fallback
                        body["model"] = self.model
                        self._last_request_time = 0.0  # skip throttle
                        continue

                    # All models exhausted — wait the full period and retry
                    log.warning(
                        f"All models rate limited. Waiting {wait:.0f}s "
                        f"before retrying..."
                    )
                    time.sleep(wait)
                    self._last_request_time = 0.0
                    # Reset tried models so we can try them again after waiting
                    self._tried_models.clear()
                    last_err = "Rate limited (429)"

                elif resp.status_code == 402:
                    # Payment required — switch to a free model
                    log.warning(
                        f"OpenRouter 402 (payment required) for {self.model}. "
                        f"Trying free fallback model..."
                    )
                    self._tried_models.add(self.model)
                    fallback = self._pick_fallback_model()
                    if fallback:
                        self.model = fallback
                        body["model"] = self.model
                        log.info(f"Switched to: {self.model}")
                        continue
                    return None

                elif resp.status_code == 404:
                    # Model not found — try fallback immediately
                    log.warning(
                        f"OpenRouter 404: model {self.model} not found. "
                        f"Trying fallback..."
                    )
                    self._tried_models.add(self.model)
                    fallback = self._pick_fallback_model()
                    if fallback:
                        self.model = fallback
                        body["model"] = self.model
                        self._last_request_time = 0.0
                        log.info(f"Switched to: {self.model}")
                        continue
                    return None

                elif resp.status_code >= 500:
                    # Server error — try fallback model
                    wait = min(2 ** attempt, 16)
                    log.warning(
                        f"OpenRouter {resp.status_code}, retrying in {wait}s"
                    )
                    time.sleep(wait)

                    if attempt >= 1:
                        self._tried_models.add(self.model)
                        fallback = self._pick_fallback_model()
                        if fallback:
                            log.warning(
                                f"Switching from {self.model} to {fallback}"
                            )
                            self.model = fallback
                            body["model"] = self.model
                            self._last_request_time = 0.0
                    last_err = f"Server error {resp.status_code}"

                else:
                    # Other error — log and try fallback
                    err_body = resp.text[:500]
                    log.error(
                        f"OpenRouter {resp.status_code}: {err_body}"
                    )

                    # Try fallback model
                    self._tried_models.add(self.model)
                    fallback = self._pick_fallback_model()
                    if fallback:
                        log.warning(
                            f"Error on {self.model}. Trying {fallback}..."
                        )
                        self.model = fallback
                        body["model"] = self.model
                        self._last_request_time = 0.0
                        continue
                    return None

            except requests.exceptions.Timeout:
                last_err = "Request timed out"
                log.warning(f"OpenRouter timeout (attempt {attempt+1})")
                time.sleep(2)

            except requests.exceptions.ConnectionError as e:
                last_err = f"Connection error: {type(e).__name__}"
                log.warning(f"OpenRouter connection error: {e}")
                # Wait for network
                import socket
                for _ in range(20):
                    try:
                        socket.gethostbyname("openrouter.ai")
                        break
                    except Exception:
                        time.sleep(3)

            except Exception as e:
                last_err = f"{type(e).__name__}: {e}"
                log.error(f"OpenRouter call failed: {e}")
                time.sleep(2)

        log.error(f"OpenRouter failed after {max_retries} attempts: {last_err}")
        return None

    def _call_api(
        self,
        messages: list,
        tools: Optional[list] = None,
        max_retries: int = 5,
    ) -> str:
        """Call API and return text response (or error message)."""
        data = self._call_api_raw(messages, tools, max_retries)
        if data is None:
            return (
                "(I'm having trouble reaching the AI service right now. "
                "This is usually temporary — try again in a minute.)"
            )

        try:
            choice = data.get("choices", [{}])[0]
            message = choice.get("message", {})
            content = message.get("content", "") or ""
            return content.strip()
        except Exception as e:
            log.error(f"Failed to parse OpenRouter response: {e}")
            return f"(Failed to parse response: {type(e).__name__})"


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python openrouter_client.py <api_key>")
        sys.exit(1)

    client = OpenRouterClient(sys.argv[1])
    print(f"Testing with model: {client.model}")
    print()

    # Test basic generation
    print("=== Basic generation test ===")
    result = client.generate(
        "Say hello in one sentence.",
        system_instruction="You are a friendly AI. Be very brief."
    )
    print(f"Response: {result}")
    print()

    # Test with tools
    print("=== Tool calling test ===")
    from tools import GEMINI_TOOLS_CONFIG, execute_tool
    result = client.generate_with_tools(
        "What is 25 * 17?",
        system_instruction="You are a helpful assistant. Use tools when appropriate.",
        tools_config=GEMINI_TOOLS_CONFIG,
        tool_executor=execute_tool,
    )
    print(f"Response: {result}")
