"""
multi_provider.py
=================
Multi-provider LLM client that rotates through all available AI providers.

This solves the rate-limiting problem by trying multiple providers in order:
1. OpenRouter (if OPENROUTER_API_KEY set)
2. DeepSeek (if DEEPSEEK_API_KEY set)
3. Z.ai (if ZAI_API_KEY set)
4. Gemini (if GEMINI_API_KEY set)

If one provider is rate-limited or down, it automatically tries the next.

All providers use the OpenAI-compatible API format, so they share the
same calling logic. Only Gemini uses its own format (via gemini_client.py).

Free providers to sign up for:
- DeepSeek: https://chat.deepseek.com/ → settings → API keys
  (generous free tier, ~$0.14/M tokens after free credit)
- Z.ai: https://chat.z.ai/ → settings → API key
  (GLM-4 series, free tier)
- Gemini: https://aistudio.google.com/apikey
  (250 req/day free)
- OpenRouter: https://openrouter.ai/keys
  ($5 free credit, 300+ models)
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Optional, Callable

import requests

log = logging.getLogger("multi_provider")

# Import model manager for dynamic model configuration
try:
    from model_manager import get_model_manager
    _mm = get_model_manager()
except Exception as e:
    log.warning(f"Could not import model_manager: {e}")
    _mm = None


class OpenAICompatibleClient:
    """Generic client for any OpenAI-compatible API.

    Works with: DeepSeek, Z.ai, OpenRouter, and any other provider
    that uses the OpenAI chat completions format.
    """

    def __init__(self, api_key: str, base_url: str, model: str,
                 provider_name: str = "", timeout: int = 120):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.provider_name = provider_name or base_url
        self.timeout = timeout
        self._last_request_time = 0.0
        self._consecutive_failures = 0
        self._cooldown_until = 0.0  # timestamp when we can try again

    def _throttle(self, min_seconds: float = 1.0):
        now = time.time()
        elapsed = now - self._last_request_time
        if elapsed < min_seconds:
            time.sleep(min_seconds - elapsed)
        self._last_request_time = time.time()

    def is_available(self) -> bool:
        """Check if this provider is available (not in cooldown)."""
        return time.time() >= self._cooldown_until

    def _mark_failed(self, cooldown_seconds: float = 60.0):
        """Mark this provider as failed, put it in cooldown."""
        self._consecutive_failures += 1
        self._cooldown_until = time.time() + cooldown_seconds
        log.warning(
            f"{self.provider_name} failed ({self._consecutive_failures}x), "
            f"cooling down for {cooldown_seconds:.0f}s"
        )

    def _mark_success(self):
        """Reset failure counter on success."""
        if self._consecutive_failures > 0:
            log.info(f"{self.provider_name} recovered")
        self._consecutive_failures = 0
        self._cooldown_until = 0.0

    def generate(self, prompt: str, system_instruction: str = None,
                 image_bytes: bytes = None) -> Optional[str]:
        """Generate a response. Returns text or None on failure."""
        if not self.is_available():
            return None

        self._throttle()

        messages = []
        if system_instruction:
            messages.append({"role": "system", "content": system_instruction})

        if image_bytes:
            import base64
            b64 = base64.b64encode(image_bytes).decode("ascii")
            messages.append({
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {
                        "url": f"data:image/jpeg;base64,{b64}"
                    }}
                ]
            })
        else:
            messages.append({"role": "user", "content": prompt})

        body = {
            "model": self.model,
            "messages": messages,
            "max_tokens": 8192,
            "temperature": 0.9,
        }

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        # OpenRouter-specific headers (recommended by their docs)
        if "openrouter" in self.base_url:
            headers["HTTP-Referer"] = "https://github.com"
            headers["X-Title"] = "AI Twin"

        try:
            resp = requests.post(
                f"{self.base_url}/chat/completions",
                headers=headers,
                json=body,
                timeout=self.timeout,
            )

            if resp.status_code == 200:
                data = resp.json()
                content = data.get("choices", [{}])[0] \
                    .get("message", {}) \
                    .get("content", "") or ""
                self._mark_success()
                return content.strip()

            elif resp.status_code == 429:
                log.warning(f"{self.provider_name} rate limited (429)")
                self._mark_failed(cooldown_seconds=60)
                # Also mark in model_manager
                if _mm:
                    _mm.mark_model_failed(self.model, 60)
                return None

            elif resp.status_code >= 500:
                log.warning(f"{self.provider_name} server error {resp.status_code}")
                self._mark_failed(cooldown_seconds=30)
                if _mm:
                    _mm.mark_model_failed(self.model, 30)
                return None

            else:
                err_body = resp.text[:500] if resp.text else "(empty response)"
                log.error(f"{self.provider_name} error {resp.status_code}: {err_body}")
                self._mark_failed(cooldown_seconds=30)
                if _mm:
                    _mm.mark_model_failed(self.model, 30)
                return None

        except requests.exceptions.Timeout:
            log.warning(f"{self.provider_name} timeout")
            self._mark_failed(cooldown_seconds=30)
            return None
        except Exception as e:
            log.error(f"{self.provider_name} failed: {e}")
            self._mark_failed(cooldown_seconds=30)
            return None

    def generate_with_tools(self, prompt: str, system_instruction: str = None,
                            tools_config: dict = None,
                            tool_executor: Callable = None,
                            max_iterations: int = 5) -> Optional[str]:
        """Generate with tool calling support. Returns text or None."""
        if not self.is_available():
            return None

        # Convert Gemini tool format to OpenAI format
        openai_tools = []
        if tools_config:
            for fd in tools_config.get("functionDeclarations", []):
                openai_tools.append({
                    "type": "function",
                    "function": {
                        "name": fd.get("name", ""),
                        "description": fd.get("description", ""),
                        "parameters": fd.get("parameters", {"type": "object", "properties": {}}),
                    }
                })

        messages = []
        if system_instruction:
            messages.append({"role": "system", "content": system_instruction})
        messages.append({"role": "user", "content": prompt})

        # Track which files we've already read (prevents infinite loops)
        read_files = set()

        for iteration in range(max_iterations):
            self._throttle()

            body = {
                "model": self.model,
                "messages": messages,
                "max_tokens": 8192,
                "temperature": 0.9,
            }
            if openai_tools:
                body["tools"] = openai_tools
                body["tool_choice"] = "auto"

            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            }

            # OpenRouter-specific headers (recommended by their docs)
            if "openrouter" in self.base_url:
                headers["HTTP-Referer"] = "https://github.com"
                headers["X-Title"] = "AI Twin"

            try:
                resp = requests.post(
                    f"{self.base_url}/chat/completions",
                    headers=headers,
                    json=body,
                    timeout=self.timeout,
                )

                if resp.status_code == 429:
                    log.warning(f"{self.provider_name} rate limited in tool loop")
                    self._mark_failed(60)
                    return None
                elif resp.status_code >= 500:
                    log.warning(f"{self.provider_name} server error in tool loop")
                    self._mark_failed(30)
                    return None
                elif resp.status_code != 200:
                    log.error(f"{self.provider_name} error {resp.status_code}")
                    self._mark_failed(30)
                    return None

                data = resp.json()
                choice = data.get("choices", [{}])[0]
                message = choice.get("message", {})
                tool_calls = message.get("tool_calls", [])

                if tool_calls:
                    messages.append(message)
                    for tc in tool_calls:
                        func = tc.get("function", {})
                        func_name = func.get("name", "")
                        func_args_str = func.get("arguments", "{}")

                        try:
                            func_args = json.loads(func_args_str)
                        except json.JSONDecodeError:
                            func_args = {}

                        # Prevent infinite read_file loops
                        if func_name == "read_file":
                            fname = func_args.get("filename", "")
                            if fname in read_files:
                                log.warning(
                                    f"Prevented duplicate read_file({fname}) "
                                    f"— breaking loop"
                                )
                                # Force the model to respond with text
                                messages.append({
                                    "role": "tool",
                                    "tool_call_id": tc.get("id", ""),
                                    "content": f"You already read {fname}. "
                                               f"Use the content you already have. "
                                               f"Do not read it again.",
                                })
                                continue
                            read_files.add(fname)

                        log.info(f"{self.provider_name} tool call: {func_name}({func_args})")

                        try:
                            result = tool_executor(func_name, func_args)
                        except Exception as e:
                            result = f"Error: {type(e).__name__}: {e}"

                        messages.append({
                            "role": "tool",
                            "tool_call_id": tc.get("id", ""),
                            "content": result,
                        })
                    continue

                # No tool calls — return text
                content = message.get("content", "") or ""
                self._mark_success()
                return content.strip()

            except Exception as e:
                log.error(f"{self.provider_name} tool loop error: {e}")
                self._mark_failed(30)
                return None

        return "(I used several tools but hit my iteration limit.)"


class MultiProviderClient:
    """Routes requests through multiple LLM providers with automatic failover."""

    def __init__(self):
        self.providers = []  # List of (name, client) tuples in priority order

        # Get all available API keys
        groq_key = os.environ.get("GROQ_API_KEY", "").strip()
        openrouter_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
        freellmapi_key = os.environ.get("FREELLMAPI_API_KEY", "").strip()
        mistral_key = os.environ.get("MISTRAL_API_KEY", "").strip()
        cerebras_key = os.environ.get("CEREBRAS_API_KEY", "").strip()
        zai_key = os.environ.get("ZAI_API_KEY", "").strip()
        gemini_key = os.environ.get("GEMINI_API_KEY", "").strip()

        # Get provider order from model_manager (or fallback to default)
        if _mm:
            provider_order = _mm.get_provider_order()
        else:
            provider_order = ["freellmapi", "groq", "openrouter", "mistral", "cerebras", "zai", "gemini"]

        # Map provider names to their API keys
        key_map = {
            "groq": groq_key,
            "openrouter": openrouter_key,
            "freellmapi": freellmapi_key or "free",  # FreeLLMAPI is free, no key needed — use "free" as placeholder
            "mistral": mistral_key,
            "cerebras": cerebras_key,
            "zai": zai_key,
            "gemini": gemini_key,
        }

        # Build provider specs using model_manager for models and URLs
        provider_specs = []

        for p_name in provider_order:
            p_key = key_map.get(p_name, "")
            if not p_key:
                continue

            if p_name == "gemini":
                # Gemini uses its own client, added separately below
                continue

            p_config = _mm.get_provider_config(p_name) if _mm else {}

            # Use known defaults if model_manager doesn't have the config
            defaults = {
                "groq": ("https://api.groq.com/openai/v1", "llama-3.3-70b-versatile"),
                "openrouter": ("https://openrouter.ai/api/v1", "openrouter/free"),
                "freellmapi": ("https://freellmapi.tashfeenahmed.repl.co/v1", "auto"),
                "mistral": ("https://api.mistral.ai/v1", "open-mixtral-8x7b"),
                "cerebras": ("https://api.cerebras.ai/v1", "gemma-4-31b"),
                "zai": ("https://api.z.ai/api/paas/v4", "glm-4.6"),
            }

            default_url, default_model = defaults.get(p_name, ("", ""))
            base_url = p_config.get("base_url", default_url)
            model = p_config.get("default_model", default_model)

            if base_url and model:
                provider_specs.append((p_name, p_key, base_url, model))

        # Create OpenAI-compatible clients
        for name, key, url, model in provider_specs:
            client = OpenAICompatibleClient(
                api_key=key,
                base_url=url,
                model=model,
                provider_name=name,
            )
            self.providers.append((name, client))

        # Add Gemini as last resort (different API format)
        if gemini_key:
            try:
                from gemini_client import GeminiClient
                gemini = GeminiClient(api_key=gemini_key)
                self.providers.append(("gemini", gemini))
            except Exception as e:
                log.error(f"Failed to init Gemini: {e}")

        names = [name for name, _ in self.providers]
        log.info(f"Multi-provider initialized: {', '.join(names)}")

        # Track the last successful provider (sticky)
        self._last_good_provider = None

    @property
    def model(self):
        """Return the model of the preferred/last-good provider."""
        if self._last_good_provider:
            for name, client in self.providers:
                if name == self._last_good_provider:
                    return getattr(client, "model", "unknown")
        if self.providers:
            return getattr(self.providers[0][1], "model", "unknown")
        return "none"

    def generate(self, prompt: str, system_instruction: str = None,
                 image_bytes: bytes = None) -> str:
        """Try providers in order until one succeeds. Failover on any error."""
        # Try last good provider first (sticky)
        order = list(self.providers)
        if self._last_good_provider:
            # Move last good to front
            order.sort(key=lambda x: 0 if x[0] == self._last_good_provider else 1)

        last_error = None
        for name, client in order:
            # Skip providers in cooldown
            if hasattr(client, "is_available") and not client.is_available():
                continue

            try:
                result = client.generate(
                    prompt=prompt,
                    system_instruction=system_instruction,
                    image_bytes=image_bytes,
                )
            except Exception as e:
                last_error = e
                log.warning(
                    f"Provider {name} raised in generate: "
                    f"{type(e).__name__}: {e}. Failing over to next provider."
                )
                if hasattr(client, "mark_failed"):
                    try:
                        client.mark_failed()
                    except Exception:
                        pass
                continue

            if result and not result.startswith("("):
                self._last_good_provider = name
                log.info(f"Provider {name} succeeded for generate ({len(result)} chars)")
                return result
            elif result:
                log.warning(
                    f"Provider {name} returned error in generate: {result[:100]}. "
                    f"Failing over to next provider."
                )
                if hasattr(client, "mark_failed"):
                    try:
                        client.mark_failed()
                    except Exception:
                        pass
            else:
                log.warning(f"Provider {name} returned None in generate. Failing over to next provider.")

        if last_error:
            log.error(f"All providers failed in generate. Last error: {last_error}")
        return "(All AI providers are unavailable. Check your API keys and try again in a minute.)"

    def generate_with_tools(self, prompt: str, system_instruction: str = None,
                            tools_config: dict = None,
                            tool_executor: Callable = None,
                            max_iterations: int = 5) -> str:
        """Try providers in order with tool support. Failover on any error.

        If a provider rate-limits or raises mid-loop, we retry the next
        provider from scratch. The user's message and the twin's
        understanding (system + knowledge base + today's messages) live in
        the prompt itself, so they survive the failover. Tool-call history
        from earlier iterations is lost — accepted trade-off vs. failing.
        """
        order = list(self.providers)
        if self._last_good_provider:
            order.sort(key=lambda x: 0 if x[0] == self._last_good_provider else 1)

        last_error = None
        for name, client in order:
            # Skip providers in cooldown
            if hasattr(client, "is_available") and not client.is_available():
                continue

            # Check if client supports tools
            if not hasattr(client, "generate_with_tools"):
                # Gemini client has different interface — skip for tool calls
                continue

            try:
                result = client.generate_with_tools(
                    prompt=prompt,
                    system_instruction=system_instruction,
                    tools_config=tools_config,
                    tool_executor=tool_executor,
                    max_iterations=max_iterations,
                )
            except Exception as e:
                last_error = e
                log.warning(
                    f"Provider {name} raised in generate_with_tools: "
                    f"{type(e).__name__}: {e}. Failing over to next provider."
                )
                if hasattr(client, "mark_failed"):
                    try:
                        client.mark_failed()
                    except Exception:
                        pass
                continue

            if result and not result.startswith("("):
                self._last_good_provider = name
                log.info(f"Provider {name} succeeded for generate_with_tools ({len(result)} chars)")
                return result
            elif result:
                log.warning(
                    f"Provider {name} returned error in tool loop: {result[:100]}. "
                    f"Failing over to next provider."
                )
                if hasattr(client, "mark_failed"):
                    try:
                        client.mark_failed()
                    except Exception:
                        pass
            else:
                log.warning(f"Provider {name} returned None in tool loop. Failing over to next provider.")

        if last_error:
            log.error(f"All providers failed in generate_with_tools. Last error: {last_error}")
        return "(All AI providers are unavailable. Check your API keys and try again in a minute.)"
