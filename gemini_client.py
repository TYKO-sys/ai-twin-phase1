"""
gemini_client.py
================
Minimal Gemini client using the official REST API directly.

Why not use the google-genai SDK?
  - google-genai depends on google-auth
  - google-auth depends on cryptography
  - cryptography needs Rust to build from source
  - Rust can't install on Termux/Android
  - Therefore: use plain HTTP requests. No SDK, no auth lib, no Rust.

API docs: https://ai.google.dev/api/rest/v1beta/models/generateContent

Supports:
  - Text generation
  - Image understanding (vision)
  - Audio transcription
  - System instructions
  - Safety settings (all disabled by default — user wants honest replies)
"""

from __future__ import annotations

import base64
import json
import logging
import time
from typing import Optional

import requests

log = logging.getLogger("gemini")

GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"


class GeminiClient:
    """Tiny REST client for the Gemini API."""

    # Default model — Google's newest flash model. Highest quotas typically.
    # If this gets deprecated, _ensure_model() auto-detects a working one.
    DEFAULT_MODEL = "gemini-3.7-flash"

    # Fallback models to try if the primary hits a daily quota limit (429).
    # Each Google model has its own separate daily quota, so switching models
    # can get you unblocked when one is exhausted.
    # NOTE: Only include models that actually exist on Google's API.
    # NOTE: We wait MIN_SECONDS_BETWEEN_REQUESTS between fallback attempts
    # because all models share the same per-minute rate limit on one API key.
    FALLBACK_MODELS = [
        "gemini-3.6-flash",
        "gemini-3.5-flash",
        "gemini-2.5-flash",
        "gemini-2.0-flash",
        "gemini-flash-latest",
    ]

    # Conservative rate limit for free tier. Gemini 3.x flash free tier is
    # 5 RPM (requests per minute). We enforce 1 request per 8 seconds to
    # stay well under that, even with retries.
    MIN_SECONDS_BETWEEN_REQUESTS = 8.0

    def __init__(self, api_key: str, model: str = None, timeout: int = 120):
        self.api_key = api_key
        self.model = model or self.DEFAULT_MODEL
        self.timeout = timeout
        self._model_verified = False
        self._last_request_time = 0.0
        self._tried_models: set = set()  # models we've already tried this session

    def _throttle(self) -> None:
        """Sleep if needed to stay under the rate limit."""
        now = time.time()
        elapsed = now - self._last_request_time
        if elapsed < self.MIN_SECONDS_BETWEEN_REQUESTS:
            wait = self.MIN_SECONDS_BETWEEN_REQUESTS - elapsed
            log.info(f"Rate limit: waiting {wait:.1f}s before next request")
            time.sleep(wait)
        self._last_request_time = time.time()

    def _pick_fallback_model(self) -> Optional[str]:
        """Pick a fallback model we haven't tried yet.

        Returns the first untried model from FALLBACK_MODELS, or None
        if all have been tried.
        """
        for m in self.FALLBACK_MODELS:
            if m != self.model and m not in self._tried_models:
                return m
        return None

    def _recover_model(self, err_body: str) -> Optional[str]:
        """Try to extract a working model name from a 404 error response.

        Google's deprecation 404s often include text like:
          "Please update your code to use models/gemini-3.6-flash"

        We parse that out. If parsing fails, we query the model list
        and pick the first available flash model.
        """
        import re
        # Pattern 1: "use models/<name>"
        match = re.search(r"use models?/([a-zA-Z0-9.\-_]+)", err_body)
        if match:
            candidate = match.group(1).strip()
            # Strip any trailing punctuation
            candidate = candidate.rstrip(".,;:!?")
            log.info(f"Extracted model name from error: {candidate}")
            return candidate
        # Pattern 2: "models/<name>"
        match = re.search(r"models?/([a-zA-Z0-9.\-_]+)", err_body)
        if match:
            candidate = match.group(1).strip().rstrip(".,;:!?")
            if candidate not in ("this", "the", "a", "an"):
                log.info(f"Extracted model name from error: {candidate}")
                return candidate
        # Pattern 3: query the model list and pick first flash
        try:
            url = f"{GEMINI_BASE_URL}?key={self.api_key}"
            resp = requests.get(url, timeout=30)
            if resp.status_code == 200:
                data = resp.json()
                for m in data.get("models", []):
                    name = m.get("name", "")
                    methods = m.get("supportedGenerationMethods", [])
                    if "generateContent" in methods and "flash" in name:
                        return name.replace("models/", "")
        except Exception as e:
            log.warning(f"Model list query failed during recovery: {e}")
        return None

    def _ensure_model(self) -> None:
        """If we haven't verified the model exists, list models and pick one.

        Google has deprecated several model names (gemini-2.0-flash-exp,
        gemini-1.5-flash, etc.). This guards against future deprecations by
        checking the model is actually available, and falling back to the
        first available text model if not.
        """
        if self._model_verified:
            return
        try:
            url = f"{GEMINI_BASE_URL}?key={self.api_key}"
            resp = requests.get(url, timeout=30)
            if resp.status_code == 200:
                data = resp.json()
                available = [m.get("name", "") for m in data.get("models", [])]
                # available names look like "models/gemini-2.0-flash"
                our_name = f"models/{self.model}"
                if our_name in available:
                    self._model_verified = True
                    log.info(f"Gemini model verified: {self.model}")
                    return
                # Fall back: pick the first model that supports generateContent
                for m in data.get("models", []):
                    name = m.get("name", "")
                    methods = m.get("supportedGenerationMethods", [])
                    if "generateContent" in methods and "flash" in name:
                        # Strip "models/" prefix
                        self.model = name.replace("models/", "")
                        self._model_verified = True
                        log.warning(
                            f"Configured model not found. "
                            f"Falling back to: {self.model}"
                        )
                        return
                # Last resort: just take the first one that supports generateContent
                for m in data.get("models", []):
                    name = m.get("name", "")
                    methods = m.get("supportedGenerationMethods", [])
                    if "generateContent" in methods:
                        self.model = name.replace("models/", "")
                        self._model_verified = True
                        log.warning(
                            f"Falling back to first available model: {self.model}"
                        )
                        return
            # If list failed, just try the configured model anyway
            log.warning(
                f"Could not list models (HTTP {resp.status_code}). "
                f"Trying configured model: {self.model}"
            )
            self._model_verified = True
        except Exception as e:
            log.warning(f"Model verification failed: {e}. Trying anyway.")
            self._model_verified = True

    def generate(
        self,
        prompt: str,
        system_instruction: Optional[str] = None,
        image_bytes: Optional[bytes] = None,
        audio_bytes: Optional[bytes] = None,
        audio_mime: str = "audio/ogg",
    ) -> str:
        """Call Gemini's generateContent endpoint. Returns text or error msg.

        Args:
            prompt: The text prompt / user message.
            system_instruction: Optional system prompt.
            image_bytes: Optional image bytes (JPEG/PNG) for vision.
            audio_bytes: Optional audio bytes for transcription.
            audio_mime: MIME type of audio (default: audio/ogg for Telegram).

        Returns:
            The text response from Gemini, or an error message string.
        """
        # Make sure our model name is still valid (Google deprecates these)
        self._ensure_model()

        url = f"{GEMINI_BASE_URL}/{self.model}:generateContent"

        # Build the contents array
        parts = [{"text": prompt}]
        if image_bytes:
            parts.append({
                "inline_data": {
                    "mime_type": "image/jpeg",
                    "data": base64.b64encode(image_bytes).decode("ascii"),
                }
            })
        if audio_bytes:
            parts.append({
                "inline_data": {
                    "mime_type": audio_mime,
                    "data": base64.b64encode(audio_bytes).decode("ascii"),
                }
            })

        body = {
            "contents": [{"role": "user", "parts": parts}],
            # All four safety categories set to OFF — user explicitly wants
            # honest, uncensored replies from their personal AI twin
            "safetySettings": [
                {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "OFF"},
                {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "OFF"},
                {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "OFF"},
                {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "OFF"},
            ],
            "generationConfig": {
                "temperature": 0.9,
                "topP": 0.95,
                "topK": 40,
                # 8192 is the max output for Gemini 3.x Flash models.
                # 2048 was too low and caused truncation mid-response.
                "maxOutputTokens": 8192,
            },
        }
        if system_instruction:
            body["systemInstruction"] = {
                "parts": [{"text": system_instruction}]
            }

        headers = {"Content-Type": "application/json"}
        params = {"key": self.api_key}

        # Retry up to 5 times: allows for 1 retry on current model,
        # then up to 4 fallback model attempts if we keep getting 429.
        last_err = None
        for attempt in range(5):
            try:
                # Throttle: ensure we don't exceed free-tier RPM
                self._throttle()

                resp = requests.post(
                    url,
                    headers=headers,
                    params=params,
                    data=json.dumps(body),
                    timeout=self.timeout,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    return self._extract_text(data)
                elif resp.status_code == 404:
                    # Model deprecated/not found — try to auto-recover
                    # Don't count this against our throttle (it's not a real
                    # generation call)
                    err_body = resp.text
                    log.warning(
                        f"Gemini 404 for model {self.model}. "
                        f"Attempting auto-recovery..."
                    )
                    # Mark this model as tried so we don't loop back to it
                    self._tried_models.add(self.model)

                    # First try to extract a model name from Google's error
                    new_model = self._recover_model(err_body)
                    # If that didn't work, try the next fallback model
                    if not new_model or new_model == self.model:
                        new_model = self._pick_fallback_model()

                    if new_model and new_model != self.model:
                        log.info(f"Switching to model: {new_model}")
                        self.model = new_model
                        self._model_verified = True
                        url = f"{GEMINI_BASE_URL}/{self.model}:generateContent"
                        last_err = f"Recovered to model {self.model}"
                        continue  # retry with new model
                    last_err = "Model not found, no recovery possible"
                    return (
                        f"(Model '{self.model}' not available. "
                        f"Run /status to check.)"
                    )
                elif resp.status_code == 429:
                    # Rate limited. Two scenarios:
                    # 1. Per-minute limit (5 RPM) — wait 60s and retry same model
                    # 2. Daily quota exhausted (250 RPD) — retrying same model
                    #    is useless. Try a fallback model instead.
                    #
                    # IMPORTANT: All models share the same per-minute rate limit
                    # on one API key. So when we switch to a fallback, we MUST
                    # wait before trying it, otherwise it'll 429 immediately too.
                    retry_after = resp.headers.get("Retry-After")
                    if retry_after:
                        try:
                            wait = float(retry_after)
                        except ValueError:
                            wait = 60.0
                    else:
                        wait = 60.0
                    wait = min(wait, 90.0)

                    if attempt == 0:
                        # First 429: wait and retry same model
                        log.warning(
                            f"Gemini 429 rate limited on {self.model}. "
                            f"Waiting {wait:.0f}s before retry."
                        )
                        time.sleep(wait)
                        self._last_request_time = 0.0
                        last_err = f"Rate limited (429) on {self.model}"
                    else:
                        # Second 429: probably daily quota. Try fallback model.
                        # But WAIT first — all models share the same per-minute
                        # limit on this API key.
                        self._tried_models.add(self.model)
                        fallback = self._pick_fallback_model()
                        if fallback:
                            log.warning(
                                f"Still rate limited on {self.model}. "
                                f"Waiting {wait:.0f}s before trying "
                                f"fallback: {fallback}"
                            )
                            time.sleep(wait)
                            self.model = fallback
                            self._model_verified = True
                            url = f"{GEMINI_BASE_URL}/{self.model}:generateContent"
                            self._last_request_time = time.time()
                            last_err = f"Switched to {self.model}"
                            continue
                        else:
                            log.error(
                                f"Rate limited on {self.model} and no "
                                f"fallbacks available."
                            )
                            return (
                                f"(I'm rate-limited on all available models. "
                                f"This is the per-minute limit (5 requests/min "
                                f"on free tier), not the daily quota. "
                                f"Wait 60 seconds and try again. "
                                f"Check usage at aistudio.google.com/usage)"
                            )
                elif resp.status_code >= 500:
                    # Server error — retry with backoff
                    wait = 2 ** attempt
                    log.warning(
                        f"Gemini {resp.status_code}, retrying in {wait}s"
                    )
                    time.sleep(wait)
                    last_err = f"Server error {resp.status_code}"
                else:
                    # Other client error (400, 401, 403) — don't retry
                    err_body = resp.text[:500]
                    log.error(f"Gemini {resp.status_code}: {err_body}")
                    return (
                        f"(Gemini error {resp.status_code}: {err_body})"
                    )
            except requests.exceptions.Timeout:
                last_err = "Request timed out"
                log.warning(f"Gemini timeout, attempt {attempt+1}/5")
                time.sleep(2 ** attempt)
            except requests.exceptions.ConnectionError as e:
                # Network is down (AdGuard toggling, wifi switching, etc.)
                # Wait for it to come back before retrying.
                last_err = f"Connection error: {type(e).__name__}"
                log.warning(
                    f"Gemini connection error (attempt {attempt+1}/5): {e}. "
                    f"Waiting for network..."
                )
                # Try to wait for network to return (up to 60s)
                import socket
                for _ in range(20):
                    try:
                        socket.gethostbyname("generativelanguage.googleapis.com")
                        break
                    except Exception:
                        time.sleep(3)
                time.sleep(2)
            except Exception as e:
                last_err = f"{type(e).__name__}: {e}"
                log.warning(
                    f"Gemini call failed (attempt {attempt+1}/5): {e}"
                )
                time.sleep(2 ** attempt)

        return (
            f"(I'm having trouble thinking right now. "
            f"Error: {last_err}. Try again in a minute.)"
        )

    def generate_with_tools(
        self,
        prompt: str,
        system_instruction: Optional[str] = None,
        tools_config: Optional[dict] = None,
        tool_executor: Optional[callable] = None,
        max_iterations: int = 5,
    ) -> str:
        """Generate a response with tool/function calling support.

        This implements the function calling loop:
        1. Send the prompt + tool definitions to Gemini
        2. Gemini responds with either text (done) or function calls
        3. If function calls, execute them and send results back
        4. Repeat until text response or max_iterations reached

        Args:
            prompt: The user's message / prompt
            system_instruction: The system prompt (twin's personality)
            tools_config: The tools config dict (functionDeclarations)
            tool_executor: A function(name, args) -> str that executes tools
            max_iterations: Max tool-call rounds before giving up

        Returns:
            The final text response from Gemini
        """
        if not tools_config or not tool_executor:
            # No tools — fall back to regular generate
            return self.generate(prompt, system_instruction=system_instruction)

        self._ensure_model()

        # Build the conversation history
        contents = [{"role": "user", "parts": [{"text": prompt}]}]

        url = f"{GEMINI_BASE_URL}/{self.model}:generateContent"

        for iteration in range(max_iterations):
            # Throttle before each API call
            self._throttle()

            body = {
                "contents": contents,
                "tools": [tools_config],
                "safetySettings": [
                    {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "OFF"},
                    {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "OFF"},
                    {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "OFF"},
                    {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "OFF"},
                ],
                "generationConfig": {
                    "temperature": 0.9,
                    "topP": 0.95,
                    "topK": 40,
                    "maxOutputTokens": 8192,
                },
            }
            if system_instruction:
                body["systemInstruction"] = {
                    "parts": [{"text": system_instruction}]
                }

            headers = {"Content-Type": "application/json"}
            params = {"key": self.api_key}

            try:
                resp = requests.post(
                    url,
                    headers=headers,
                    params=params,
                    data=json.dumps(body),
                    timeout=self.timeout,
                )

                if resp.status_code == 200:
                    data = resp.json()
                    candidates = data.get("candidates", [])
                    if not candidates:
                        return "(No response from Gemini.)"

                    candidate = candidates[0]
                    content = candidate.get("content", {})
                    parts = content.get("parts", [])

                    # Check for function calls
                    function_calls = [
                        p for p in parts if "functionCall" in p
                    ]

                    if function_calls:
                        # Add the model's response to history
                        contents.append(content)

                        # Execute each function call
                        for fc_part in function_calls:
                            fc = fc_part["functionCall"]
                            func_name = fc.get("name", "")
                            func_args = fc.get("args", {})

                            log.info(
                                f"Tool call: {func_name}({func_args})"
                            )

                            # Execute the tool
                            try:
                                result = tool_executor(func_name, func_args)
                            except Exception as e:
                                result = f"Error: {type(e).__name__}: {e}"

                            log.info(
                                f"Tool result ({func_name}): "
                                f"{result[:200]}..."
                            )

                            # Add function response to history
                            contents.append({
                                "role": "function",
                                "parts": [{
                                    "functionResponse": {
                                        "name": func_name,
                                        "response": {
                                            "name": func_name,
                                            "content": result,
                                        }
                                    }
                                }]
                            })

                        # Continue to next iteration — Gemini will process
                        # the tool results and either call more tools or
                        # give a final text response
                        continue

                    # No function calls — extract text and return
                    finish_reason = candidate.get("finishReason", "STOP")
                    texts = [p.get("text", "") for p in parts]
                    result = "".join(texts).strip()

                    usage = data.get("usageMetadata", {})
                    log.info(
                        f"Gemini response (with tools): {len(result)} chars, "
                        f"finishReason={finish_reason}, "
                        f"iterations={iteration+1}, "
                        f"input_tokens={usage.get('promptTokenCount', '?')}, "
                        f"output_tokens={usage.get('candidatesTokenCount', '?')}"
                    )

                    if finish_reason == "MAX_TOKENS":
                        result += (
                            "\n\n[... response truncated — I ran out of "
                            "output tokens. Ask me to continue. ...]"
                        )

                    return result

                elif resp.status_code == 404:
                    # Model deprecated — try recovery
                    err_body = resp.text
                    log.warning(f"Gemini 404 for model {self.model}")
                    self._tried_models.add(self.model)
                    new_model = self._recover_model(err_body)
                    if not new_model or new_model == self.model:
                        new_model = self._pick_fallback_model()
                    if new_model and new_model != self.model:
                        self.model = new_model
                        self._model_verified = True
                        url = f"{GEMINI_BASE_URL}/{self.model}:generateContent"
                        continue
                    return f"(Model '{self.model}' not available.)"

                elif resp.status_code == 429:
                    # Rate limited — wait and retry
                    retry_after = resp.headers.get("Retry-After", "60")
                    try:
                        wait = float(retry_after)
                    except ValueError:
                        wait = 60.0
                    wait = min(wait, 90.0)
                    log.warning(
                        f"Gemini 429 rate limited. Waiting {wait:.0f}s..."
                    )
                    time.sleep(wait)
                    self._last_request_time = 0.0
                    continue

                elif resp.status_code >= 500:
                    wait = 2 ** iteration
                    log.warning(
                        f"Gemini {resp.status_code}, retrying in {wait}s"
                    )
                    time.sleep(wait)
                    continue

                else:
                    err_body = resp.text[:500]
                    log.error(f"Gemini {resp.status_code}: {err_body}")
                    return f"(Gemini error {resp.status_code}: {err_body})"

            except requests.exceptions.Timeout:
                log.warning(f"Gemini timeout in tool loop (iteration {iteration+1})")
                time.sleep(2)
                continue
            except requests.exceptions.ConnectionError as e:
                log.warning(f"Gemini connection error: {e}. Waiting for network...")
                import socket
                for _ in range(20):
                    try:
                        socket.gethostbyname("generativelanguage.googleapis.com")
                        break
                    except Exception:
                        time.sleep(3)
                continue
            except Exception as e:
                log.error(f"Tool generation error: {e}")
                return f"(Error during tool use: {type(e).__name__}: {e})"

        # Max iterations reached — return what we have
        return (
            "(I used several tools to research this but hit my iteration "
            "limit. Here's what I found so far — ask me to continue if "
            "you need more.)"
        )

    def _extract_text(self, data: dict) -> str:
        """Pull the text out of Gemini's response JSON.

        Also detects truncation (finishReason == MAX_TOKENS) and appends
        a visible warning so the user knows the response was cut short.
        """
        try:
            candidates = data.get("candidates", [])
            if not candidates:
                # Could be a content filter
                prompt_feedback = data.get("promptFeedback", {})
                block_reason = prompt_feedback.get("blockReason")
                if block_reason:
                    log.warning(f"Response blocked: {block_reason}")
                    return f"(Response blocked: {block_reason})"
                log.warning("No candidates in response")
                return "(No response from Gemini.)"
            cand = candidates[0]
            content = cand.get("content", {})
            parts = content.get("parts", [])
            if not parts:
                finish_reason = cand.get("finishReason", "UNKNOWN")
                log.warning(f"Empty response, finishReason: {finish_reason}")
                return f"(Empty response, finish reason: {finish_reason})"
            texts = [p.get("text", "") for p in parts]
            result = "".join(texts).strip()

            # Log the finish reason and response length for diagnostics
            finish_reason = cand.get("finishReason", "UNKNOWN")
            usage = data.get("usageMetadata", {})
            log.info(
                f"Gemini response: {len(result)} chars, "
                f"finishReason={finish_reason}, "
                f"input_tokens={usage.get('promptTokenCount', '?')}, "
                f"output_tokens={usage.get('candidatesTokenCount', '?')}, "
                f"model={self.model}"
            )

            if finish_reason == "MAX_TOKENS":
                # The response was cut off mid-sentence because we hit
                # maxOutputTokens. Append a visible warning.
                log.warning(
                    f"Gemini response truncated (MAX_TOKENS). "
                    f"Length: {len(result)} chars."
                )
                result += (
                    "\n\n[... response truncated — I ran out of output "
                    "tokens. Ask me to continue and I'll pick up where "
                    "I left off. ...]"
                )
            elif finish_reason == "SAFETY":
                log.warning("Gemini response blocked by safety filter")
                result = (
                    f"(Response was blocked by Gemini's safety filter. "
                    f"This shouldn't happen with our settings.)\n\n"
                    f"Partial response was: {result}"
                )
            elif finish_reason == "RECITATION":
                # Gemini stopped because it detected it was about to
                # recite copyrighted content. This causes short, mid-sentence
                # truncation with no other explanation.
                log.warning(
                    f"Gemini response stopped (RECITATION). "
                    f"Length: {len(result)} chars."
                )
                result += (
                    "\n\n[... I stopped mid-thought because Gemini's "
                    "recitation filter triggered. Ask me to rephrase or "
                    "continue differently. ...]"
                )
            elif finish_reason == "OTHER":
                # Generic stop reason — could be various things
                log.warning(
                    f"Gemini response stopped (OTHER). "
                    f"Length: {len(result)} chars."
                )
                result += (
                    "\n\n[... response stopped unexpectedly (finish reason: "
                    "OTHER). Ask me to continue. ...]"
                )
            elif finish_reason not in ("", "STOP", "FINISH_REASON_STOP", "UNKNOWN"):
                log.warning(f"Gemini unusual finishReason: {finish_reason}")

            return result
        except Exception as e:
            log.error(f"Failed to extract Gemini text: {e}\nRaw: {data}")
            return f"(Failed to parse Gemini response: {type(e).__name__})"


if __name__ == "__main__":
    # Smoke test — requires GEMINI_API_KEY env var
    import os
    import sys
    if len(sys.argv) < 2:
        print("Usage: python gemini_client.py <api_key>")
        sys.exit(1)
    client = GeminiClient(sys.argv[1])
    print("Testing text generation...")
    reply = client.generate(
        "Say hello in one sentence.",
        system_instruction="You are a friendly AI. Be very brief.",
    )
    print(f"Reply: {reply}")
