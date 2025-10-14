# -*- coding: utf-8 -*-
"""
Robust Python mutator for AFL++.
- Supports BOTH Python-only API (init/fuzz/post_process/queue_new_entry/new_crash/deinit)
  and afl_custom_* aliases used by afl-fuzz C bridge.
- NEVER raises; always returns bytes to afl-fuzz.
- LLM(OpenAI) is OPTIONAL via lazy import; on any failure it safely falls back
  to local operators without killing afl-fuzz.

Design notes:
- All exceptions are caught at API boundary.
- Outputs are clipped to `max_size` and returned as `bytes`.
- Simple curriculum over OPS based on JSON parse rate.
"""

from __future__ import annotations

import os
import json
import random
from typing import Optional, List

# Local modules (must not raise on import)
from .sched_ema import EMAScheduler
from .json_ops import OPS

# ── Globals ──────────────────────────────────────────────────────────────────
_RNG = random.Random()
_SCHED = EMAScheduler(n_ops=len(OPS), lam=0.2, tau=0.8, eps=0.02)
_last_op: Optional[int] = None

# parse-rate bookkeeping (best-effort only)
_parse_ok = 0
_parse_all = 0

# LLM lazy handle
_OPENAI = None
_LLM_READY = False
_LLM_MODEL = None
_LLM_TEMP = 1.0
_LLM_ENABLED = True  # can be toggled off by env if needed


def _bool_env(name: str, default: bool) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    v = v.strip().lower()
    if v in ("1", "true", "yes", "y", "on"):
        return True
    if v in ("0", "false", "no", "n", "off"):
        return False
    return default


# Allow user to disable LLM rapidly if it misbehaves
_LLM_ENABLED = _bool_env("RAGFUZZ_LLM_ENABLED", True)


# ── Helpers ──────────────────────────────────────────────────────────────────
def _clip(ba: bytearray, max_size: int) -> bytearray:
    try:
        if max_size is None:
            return ba
        if len(ba) > max_size:
            del ba[max_size:]
    except Exception:
        pass
    return ba


def _safe_json_loads(b: bytes | bytearray) -> bool:
    try:
        json.loads(b)
        return True
    except Exception:
        return False


def _allowed_ops() -> List[int]:
    """Simple curriculum: widen operator set as parse rate improves."""
    try:
        rate = (_parse_ok / _parse_all) if _parse_all > 0 else 0.0
    except Exception:
        rate = 0.0

    if rate >= 0.90:
        return list(range(len(OPS)))   # Phase C: all ops
    elif rate >= 0.50:
        return [0, 1, 2]               # Phase B: moderate set
    else:
        return [0, 1]                  # Phase A: safe core


# ── LLM (lazy import; optional) ──────────────────────────────────────────────
def _ensure_openai() -> None:
    """Lazy import openai and configure a minimal client; silently disable on failure."""
    global _OPENAI, _LLM_READY, _LLM_MODEL, _LLM_TEMP, _LLM_ENABLED
    if _OPENAI is not None or not _LLM_ENABLED:
        return
    try:
        import openai as _OPENAI  # type: ignore
        # load model/temperature from simple config if present
        _LLM_MODEL = os.getenv("RAGFUZZ_LLM_MODEL", "gpt-4o-mini")
        try:
            _LLM_TEMP = float(os.getenv("RAGFUZZ_LLM_TEMPERATURE", "1.0"))
        except Exception:
            _LLM_TEMP = 1.0
        # If API key is not present, keep disabled silently
        if not (os.getenv("OPENAI_API_KEY") or os.getenv("OPENAI_API_KEY_PATH")):
            # If project uses ~/.config/ragfuzz/config.toml ingestion, leave to higher layer.
            _LLM_ENABLED = False
            _LLM_READY = False
            return
        _LLM_READY = True
    except Exception:
        _OPENAI = None
        _LLM_ENABLED = False
        _LLM_READY = False


def _maybe_llm_mutate(data: bytes) -> Optional[bytes]:
    """
    Best-effort LLM-assisted mutation.
    MUST NEVER RAISE. Return None if not available.
    """
    try:
        if not _LLM_ENABLED:
            return None
        _ensure_openai()
        if not _LLM_READY or _OPENAI is None:
            return None

        # Minimal prompt; real projects can hydrate richer context.
        prompt = (
            "Mutate the following JSON while keeping it syntactically valid. "
            "Introduce edge-case structures (deep nesting, large numbers, "
            "rare unicode, duplicate keys) but stay within 1MB.\n\n"
            f"Input:\n{data[:2000].decode('utf-8', errors='ignore')}\n\nOutput only JSON:"
        )

        # Use responses API if available; swallow all errors.
        try:
            client = _OPENAI.OpenAI()  # type: ignore[attr-defined]
            rsp = client.responses.create(
                model=_LLM_MODEL or "gpt-4o-mini",
                temperature=float(_LLM_TEMP),
                input=prompt,
            )
            txt = rsp.output_text  # type: ignore[attr-defined]
        except Exception:
            # Try legacy chat.completions
            try:
                client = _OPENAI.OpenAI()  # type: ignore[attr-defined]
                rsp = client.chat.completions.create(
                    model=_LLM_MODEL or "gpt-4o-mini",
                    temperature=float(_LLM_TEMP),
                    messages=[{"role": "user", "content": prompt}],
                )
                txt = rsp.choices[0].message.content  # type: ignore[index]
            except Exception:
                return None

        if not isinstance(txt, str) or not txt.strip():
            return None
        out = txt.encode("utf-8", "ignore")
        # Return as-is; afl will clip afterwards
        return out
    except Exception:
        return None


# ── AFL++ "afl_custom_*" API ────────────────────────────────────────────────
def afl_custom_init(seed: int | None):
    try:
        if seed is not None:
            _RNG.seed(int(seed))
    except Exception:
        pass
    return 0  # must be int


def afl_custom_deinit():
    # nothing to cleanup; never raise
    return 0


def afl_custom_fuzz(buf, add_buf, max_size):
    global _last_op, _parse_ok, _parse_all
    try:
        # 입력을 확실히 bytearray로
        data = bytearray(buf) if not isinstance(buf, (bytearray, bytes)) else bytearray(buf)

        allowed = _allowed_ops() or [0]
        op_idx = _SCHED.pick(allowed=allowed)
        if not isinstance(op_idx, int) or not (0 <= op_idx < len(OPS)):
            op_idx = allowed[0]
        _last_op = op_idx

        # 연산 실행(절대 예외 밖으로 X)
        try:
            out = OPS[op_idx](data, add_buf, max_size, rng=_RNG)
        except Exception:
            out = data

        # 어떤 타입이든 bytearray로 수렴 → 길이 클리핑 → bytes로 고정
        if isinstance(out, (bytes, bytearray, memoryview)):
            out_ba = bytearray(out)
        else:
            out_ba = data  # 비정상 타입이면 원본으로 폴백

        if max_size is None:
            max_size = len(out_ba)
        else:
            try:
                max_size = int(max_size)
            except Exception:
                max_size = len(out_ba)

        if len(out_ba) > max_size:
            del out_ba[max_size:]

        # 파싱 통계(베스트 에포트)
        try:
            _parse_all += 1
            if _safe_json_loads(out_ba):
                _parse_ok += 1
        except Exception:
            pass

        # 최종: 반드시 bytes
        return bytes(out_ba)

    except Exception:
        # 최후 폴백: 원본 또는 최소 유효 JSON
        try:
            src = bytearray(buf) if not isinstance(buf, (bytes, bytearray)) else bytearray(buf)
            if len(src) > int(max_size):
                del src[int(max_size):]
            return bytes(src)
        except Exception:
            return b"{}"


def afl_custom_post_process(buf):
    return post_process(buf)


def afl_custom_queue_new_entry(filename, orig_filename):
    return 0


# ── Python-only AFL++ mutator API ───────────────────────────────────────────
def init(seed=None):
    try:
        return afl_custom_init(seed if isinstance(seed, int) else None)
    except Exception:
        return 0


def deinit():
    try:
        return afl_custom_deinit()
    except Exception:
        return 0


def fuzz(buf, add_buf, max_size):
    return afl_custom_fuzz(buf, add_buf, max_size)


def post_process(buf):
    try:
        # 어떤 타입이 와도 bytes로 강제
        return bytes(buf)
    except Exception:
        return b""


def queue_new_entry(filename: str, *rest) -> None:
    return None


def new_crash(filename: str, *rest) -> None:
    return None
