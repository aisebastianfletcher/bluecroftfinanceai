"""
OpenAI diagnostics helper.

Provides a safe, non-leaking diagnostic that checks:
 - whether an OpenAI key is available via Streamlit secrets or env
 - whether the key can list models (lightweight, safe check)
 - optionally performs a tiny test chat completion to verify model access

This module intentionally avoids printing or returning the API key.
"""
from typing import Any, Dict, Optional
import os
import json
import requests

DEFAULT_TIMEOUT = 8.0
MODELS_ENDPOINT = "https://api.openai.com/v1/models"
CHAT_ENDPOINT = "https://api.openai.com/v1/chat/completions"


def _get_key_from_streamlit_or_env() -> Optional[str]:
    # Prefer Streamlit secrets if available (won't crash if Streamlit isn't present)
    try:
        import streamlit as st  # type: ignore
        key = st.secrets.get("OPENAI_API_KEY") or st.secrets.get("OPENAI_KEY")
        if key:
            return key
    except Exception:
        pass
    # Fallback to environment variables
    return os.environ.get("OPENAI_API_KEY") or os.environ.get("OPENAI_KEY")


def _safe_json_snippet(obj: Any, max_len: int = 300) -> str:
    try:
        s = json.dumps(obj)
        if len(s) <= max_len:
            return s
        return s[:max_len] + "...(truncated)"
    except Exception:
        return "<unserializable>"


def diagnose(openai_model: Optional[str] = None, run_chat_test: bool = False) -> Dict[str, Any]:
    """
    Run OpenAI diagnostics.

    Args:
      openai_model: optional model id to test a chat completion with if run_chat_test=True.
      run_chat_test: whether to attempt a tiny chat completion (may use tokens).

    Returns:
      dict with keys:
        key_present: bool
        models_check: { http_status, ok, message, models_preview }
        chat_test: { attempted, http_status, ok, message, assistant_snippet }  # only if run_chat_test
    """
    result: Dict[str, Any] = {"key_present": False, "models_check": None, "chat_test": None}
    key = _get_key_from_streamlit_or_env()
    result["key_present"] = bool(key)

    if not key:
        result["models_check"] = {
            "http_status": None,
            "ok": False,
            "message": "No OpenAI key found in Streamlit secrets or environment variables.",
        }
        if run_chat_test:
            result["chat_test"] = {
                "attempted": False,
                "ok": False,
                "message": "Chat test not attempted because no key available.",
            }
        return result

    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}

    # 1) Lightweight models list check
    try:
        resp = requests.get(MODELS_ENDPOINT, headers=headers, timeout=DEFAULT_TIMEOUT)
        status = resp.status_code
        ok = resp.status_code == 200
        models_preview = None
        message = ""
        if ok:
            try:
                payload = resp.json()
                models = payload.get("data", []) if isinstance(payload, dict) else []
                # show up to 20 model ids (no sensitive data)
                models_preview = [m.get("id") for m in models[:20]]
                message = f"Listed {len(models)} models (preview up to 20)."
            except Exception as e:
                message = f"Listed models but failed to parse JSON: {_safe_json_snippet(str(e))}"
        else:
            # Try to surface an actionable message without leaking details
            try:
                payload = resp.json()
                # Common OpenAI error shape: {'error': {'message': '...', 'type': '...'}}
                err = payload.get("error") if isinstance(payload, dict) else payload
                message = _safe_json_snippet(err)
            except Exception:
                message = f"HTTP {status} returned from models endpoint."
        result["models_check"] = {
            "http_status": status,
            "ok": ok,
            "message": message,
            "models_preview": models_preview,
        }
    except requests.RequestException as e:
        result["models_check"] = {
            "http_status": None,
            "ok": False,
            "message": f"Network error when contacting OpenAI models endpoint: {_safe_json_snippet(str(e))}",
            "models_preview": None,
        }

    # 2) Optional tiny chat completion to validate model access (costs tokens)
    if run_chat_test:
        # Choose a safe default model if none provided (user may override)
        model_to_use = openai_model or os.environ.get("OPENAI_MODEL") or "gpt-4"
        payload = {
            "model": model_to_use,
            "messages": [{"role": "user", "content": "Say 'diagnostic ok' in one short sentence."}],
            "max_tokens": 8,
            "temperature": 0.0,
        }
        chat_result = {"attempted": True, "http_status": None, "ok": False, "message": "", "assistant_snippet": None}
        try:
            resp = requests.post(CHAT_ENDPOINT, headers=headers, json=payload, timeout=DEFAULT_TIMEOUT)
            chat_result["http_status"] = resp.status_code
            if resp.status_code == 200:
                try:
                    body = resp.json()
                    # Locate assistant content safely
                    choices = body.get("choices") or []
                    if choices and isinstance(choices, list):
                        msg = choices[0].get("message") or {}
                        assistant_text = (msg.get("content") or "").strip()
                        chat_result["assistant_snippet"] = assistant_text[:200]
                        chat_result["ok"] = True
                        chat_result["message"] = "Chat completion succeeded."
                    else:
                        chat_result["message"] = "Chat API returned 200 but no choices were present."
                except Exception as e:
                    chat_result["message"] = f"Chat API returned 200 but parsing failed: {_safe_json_snippet(str(e))}"
            else:
                # parse error body for friendly guidance (don't leak key)
                try:
                    err = resp.json()
                    chat_result["message"] = _safe_json_snippet(err)
                except Exception:
                    chat_result["message"] = f"Chat endpoint returned HTTP {resp.status_code}"
        except requests.RequestException as e:
            chat_result["message"] = f"Network error when contacting chat endpoint: {_safe_json_snippet(str(e))}"
        result["chat_test"] = chat_result

    return result
