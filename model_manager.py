"""
model_manager.py
================
Manages the available model list for the AI twin.

This solves the "hardcoded model" problem:
- Models change, get rate-limited, or become deprecated
- The twin shouldn't break when a model name changes
- Users shouldn't need to update the code for model changes

How it works:
1. On startup, tries to fetch the latest model config from a remote source
2. If fetch fails, uses the local fallback (models_config.json)
3. Refreshes every 6 hours in the background
4. Tracks which models are temporarily failed (rate-limited)
5. Rotates to the next available model automatically

The user never sees model names. They just see "I'm thinking" and a response.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

import requests

log = logging.getLogger("model_manager")

# Paths
CONFIG_DIR = Path(__file__).parent
LOCAL_CONFIG = CONFIG_DIR / "models_config.json"
CACHE_FILE = Path.home() / "ai-twin-memory" / "models_cache.json"

# Remote config URL (can be updated without changing the code)
# This should point to a raw GitHub file that can be updated independently
REMOTE_CONFIG_URL = os.environ.get(
    "MODELS_CONFIG_URL",
    "https://raw.githubusercontent.com/TYKO-sys/ai-twin-phase1/main/models_config.json"
)

# Refresh interval (6 hours)
REFRESH_INTERVAL_SECONDS = 6 * 60 * 60


class ModelManager:
    """Manages the available model list with remote updates and local fallback."""

    def __init__(self):
        self._config = None
        self._last_refresh = 0
        self._failed_models = {}  # model_name → failure_expiry_timestamp
        self._lock = threading.Lock()
        self._refresh_thread = None

        # Load initial config
        self._load_config()

        # Start background refresh thread
        self._start_refresh_thread()

    def _load_config(self) -> dict:
        """Load the model configuration.

        Tries cached remote config first, then local fallback.
        """
        # Try cached remote config
        if CACHE_FILE.exists():
            try:
                cached = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
                if cached.get("fetched_at"):
                    self._config = cached.get("config", {})
                    self._last_refresh = cached.get("fetched_at", 0)
                    log.info(f"Loaded cached model config (from {datetime.fromtimestamp(self._last_refresh)})")
                    return self._config
            except Exception as e:
                log.warning(f"Failed to load cached config: {e}")

        # Fall back to local config
        try:
            self._config = json.loads(LOCAL_CONFIG.read_text(encoding="utf-8"))
            log.info("Loaded local fallback model config")
        except Exception as e:
            log.error(f"Failed to load local config: {e}")
            self._config = {"providers": {}, "provider_order": []}

        return self._config

    def _fetch_remote_config(self) -> bool:
        """Try to fetch the latest model config from the remote source.

        Returns True if successful, False otherwise.
        If it fails, the local config is used — this is normal and expected.
        """
        try:
            resp = requests.get(REMOTE_CONFIG_URL, timeout=15)
            if resp.status_code == 200:
                remote_config = resp.json()

                # Validate it has the expected structure
                if "providers" in remote_config and "provider_order" in remote_config:
                    # Save to cache
                    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
                    cache_data = {
                        "config": remote_config,
                        "fetched_at": time.time(),
                        "source": REMOTE_CONFIG_URL,
                    }
                    CACHE_FILE.write_text(
                        json.dumps(cache_data, indent=2),
                        encoding="utf-8"
                    )

                    self._config = remote_config
                    self._last_refresh = time.time()
                    log.info("Updated model config from remote source")
                    return True
                else:
                    log.warning("Remote config has invalid structure, keeping local")
                    return False
            elif resp.status_code == 404:
                # Repo is private or file doesn't exist — use local config
                # This is normal, not an error
                log.info("Remote config not available (404) — using local config")
                return False
            else:
                log.info(f"Remote config unavailable (HTTP {resp.status_code}) — using local")
                return False
        except Exception as e:
            log.info(f"Could not fetch remote config — using local: {e}")
            return False

    def _start_refresh_thread(self):
        """Start a background thread that refreshes the config every 6 hours."""
        def refresh_loop():
            while True:
                # Wait for the refresh interval
                time.sleep(REFRESH_INTERVAL_SECONDS)
                log.info("Refreshing model config from remote source...")
                self._fetch_remote_config()

        self._refresh_thread = threading.Thread(
            target=refresh_loop,
            daemon=True,
            name="model-refresh"
        )
        self._refresh_thread.start()

    def force_refresh(self) -> bool:
        """Force an immediate refresh from the remote source."""
        return self._fetch_remote_config()

    def get_available_models(self, provider: str = None) -> list:
        """Get the list of available models.

        Args:
            provider: Optional provider name (openrouter, deepseek, zai, gemini)
                      If None, returns models from all providers in order.

        Returns:
            List of (provider, model_name, base_url) tuples
        """
        if not self._config:
            return []

        models = []
        provider_order = self._config.get("provider_order", [])
        providers = self._config.get("providers", {})

        if provider:
            # Return models for a specific provider
            p = providers.get(provider, {})
            base_url = p.get("base_url", "")
            for model in p.get("models", []):
                if not self._is_model_failed(model):
                    models.append((provider, model, base_url))
        else:
            # Return models from all providers in order
            for p_name in provider_order:
                p = providers.get(p_name, {})
                base_url = p.get("base_url", "")
                for model in p.get("models", []):
                    if not self._is_model_failed(model):
                        models.append((p_name, model, base_url))

        return models

    def get_default_model(self, provider: str) -> Optional[str]:
        """Get the default model for a provider."""
        if not self._config:
            return None
        p = self._config.get("providers", {}).get(provider, {})
        return p.get("default_model")

    def get_provider_config(self, provider: str) -> dict:
        """Get the full config for a provider (base_url, headers, etc.)."""
        if not self._config:
            return {}
        return self._config.get("providers", {}).get(provider, {})

    def get_provider_order(self) -> list:
        """Get the order in which providers should be tried."""
        return self._config.get("provider_order", [])

    def mark_model_failed(self, model_name: str, cooldown_seconds: int = 60):
        """Mark a model as temporarily failed (rate-limited, etc.).

        The model won't be tried again until the cooldown expires.
        """
        with self._lock:
            expiry = time.time() + cooldown_seconds
            self._failed_models[model_name] = expiry
            log.info(f"Model {model_name} marked failed for {cooldown_seconds}s")

    def _is_model_failed(self, model_name: str) -> bool:
        """Check if a model is currently in failure cooldown."""
        with self._lock:
            expiry = self._failed_models.get(model_name, 0)
            if expiry > time.time():
                return True
            elif expiry > 0:
                # Cooldown expired, remove from failed list
                del self._failed_models[model_name]
            return False

    def clear_failures(self):
        """Clear all model failures (used by /fix command)."""
        with self._lock:
            self._failed_models.clear()
            log.info("All model failures cleared")

    def get_status(self) -> str:
        """Get a human-readable status (for debugging, not shown to user)."""
        models = self.get_available_models()
        failed = [m for m, exp in self._failed_models.items() if exp > time.time()]
        return (
            f"Available models: {len(models)}\n"
            f"Failed (cooling down): {len(failed)}\n"
            f"Last refresh: {datetime.fromtimestamp(self._last_refresh) if self._last_refresh else 'never'}\n"
            f"Config source: {'remote' if CACHE_FILE.exists() else 'local fallback'}"
        )


# Singleton instance
_manager = None


def get_model_manager() -> ModelManager:
    """Get the singleton ModelManager instance."""
    global _manager
    if _manager is None:
        _manager = ModelManager()
    return _manager


if __name__ == "__main__":
    # Test
    mm = ModelManager()
    print("=== Available Models ===")
    for provider, model, url in mm.get_available_models():
        print(f"  {provider}: {model} ({url})")
    print()
    print("=== Status ===")
    print(mm.get_status())
    print()
    print("=== Test failure tracking ===")
    mm.mark_model_failed("test-model", 5)
    print(f"Is 'test-model' failed? {mm._is_model_failed('test-model')}")
    time.sleep(6)
    print(f"After 6s, is 'test-model' failed? {mm._is_model_failed('test-model')}")
