# mutators/json_adapt_safe.py
# Diagnostic + LLM buffer + JSON-safe mutator (hardened to always return bytes within max_size)

import json, random, string, os, time, glob, traceback

# ========= DEBUG HOOKS =========
DBG_BASE = "/tmp"

def _mark(path, line):
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass

def _tick(name):
    _mark(os.path.join(DBG_BASE, f"afl_python_{name}"), str(int(time.time())))

def _bump(path):
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"{int(time.time())}\n")
    except Exception:
        pass

# import 표식 (모듈 로드 확인용)
_mark("/tmp/afl_python_imported", f"imported:{__file__}:{int(time.time())}")

def _truthy(x):
    return str(x).lower() in {"1", "true", "yes", "on"}

# ========= CONFIG =========
_MIN = b"{}"
NUM_EDGES = [0, 1, -1, 2, -2, 2147483647, -2147483648, 4294967295, -4294967296, 1e308, -1e308]

LLM_BUF_DIR = os.environ.get("LLM_BUF_DIR", "/tmp/llm_buf")
LLM_FORCE   = _truthy(os.environ.get("LLM_FORCE"))
try:
    LLM_PROB = float(os.environ.get("LLM_PROB", "0.3"))
    if not (0.0 <= LLM_PROB <= 1.0):
        LLM_PROB = 0.3
except Exception:
    LLM_PROB = 0.3
AFL_CUSTOM_MUTATOR_ONLY = _truthy(os.environ.get("AFL_CUSTOM_MUTATOR_ONLY"))

# counters
DBG_ENV_FILE = "/tmp/afl_python_dbg"
TICK_FILE   = "/tmp/afl_python_tick"
LLM_AVAIL   = "/tmp/afl_python_llm_available"
LLM_USED    = "/tmp/llm_mut_calls"              # 기존 지표와 호환
LLM_SKIP    = "/tmp/afl_python_llm_skipped"
LLM_ERR     = "/tmp/afl_python_llm_errors"
NONLLM_USED = "/tmp/afl_python_non_llm"

def _log_env(stage):
    try:
        with open(DBG_ENV_FILE, "a", encoding="utf-8") as f:
            f.write(f"[{time.strftime('%F %T')}] {stage} pid={os.getpid()}\n")
            f.write(f"  LLM_BUF_DIR={LLM_BUF_DIR}\n")
            f.write(f"  LLM_FORCE={LLM_FORCE} LLM_PROB={LLM_PROB}\n")
            f.write(f"  AFL_CUSTOM_MUTATOR_ONLY={AFL_CUSTOM_MUTATOR_ONLY}\n")
            for k in ("AFL_PYTHON_MODULE", "AFL_DISABLE_TRIM"):
                f.write(f"  {k}={os.environ.get(k)}\n")
    except Exception:
        pass

# 모듈 임포트 시 환경 기록
_log_env("module-import")

# ========= SAFE BYTES =========
def _to_bytes(obj) -> bytes:
    """Best-effort convert to bytes; on failure return _MIN."""
    try:
        if obj is None:
            return _MIN
        if isinstance(obj, bytes):
            return obj
        if isinstance(obj, (bytearray, memoryview)):
            return bytes(obj)
        # common str path
        if isinstance(obj, str):
            return obj.encode("utf-8", "ignore") or _MIN
        # last resort
        return bytes(obj)
    except Exception:
        return _MIN

def _safe_bytes(b, max_size: int) -> bytes:
    """Clamp to max_size, ensure non-empty bytes."""
    b = _to_bytes(b)
    try:
        ms = int(max_size)
        if ms <= 0:
            ms = 1
    except Exception:
        ms = 1 << 20
    if len(b) > ms:
        # try JSON recompact first; otherwise truncate
        try:
            s = b.decode("utf-8", "ignore")
            j = json.loads(s)
            b2 = json.dumps(j, separators=(",", ":")).encode("utf-8", "ignore")
            b = b2 if len(b2) <= ms else b2[:ms]
        except Exception:
            b = b[:ms]
    if not b:
        b = _MIN[:ms]
    # ensure bytes (not bytearray)
    return bytes(b)

# ========= JSON MUTATORS =========
def _rand_key(n=8):
    alpha = string.ascii_lowercase + string.digits
    return "".join(random.choice(alpha) for _ in range(n))

def _mutate_number(x):
    if not isinstance(x, (int, float)):
        return random.choice(NUM_EDGES)
    if random.random() < 0.6:
        return random.choice(NUM_EDGES)
    if isinstance(x, int):
        return x + random.randint(-5, 5)
    else:
        return x + random.uniform(-5, 5)

def _mutate_string(s):
    if not isinstance(s, str):
        s = str(s)
    ops = [
        lambda t: t * random.randint(2, 6),
        lambda t: t[:max(0, len(t) - random.randint(1, max(1, len(t)//3)))],
        lambda t: t + "".join(random.choice(string.printable) for _ in range(random.randint(1, 12))),
        lambda t: t.swapcase(),
    ]
    return random.choice(ops)(s)

def _wrap_array(v):
    if isinstance(v, list) and v and random.random() < 0.5:
        return (v[0] if v else v)
    return [v]

def _ensure_depth(v, max_depth=6, cur=0):
    if cur >= max_depth:
        return None
    if isinstance(v, dict):
        out = {}
        for i, (k, val) in enumerate(list(v.items())):
            if i >= 16:
                break
            out[str(k)] = _ensure_depth(val, max_depth, cur+1)
        return out
    if isinstance(v, list):
        out = []
        for i, val in enumerate(v):
            if i >= 16:
                break
            out.append(_ensure_depth(val, max_depth, cur+1))
        return out
    return v

def _mutate_json(val):
    ops = []
    if isinstance(val, dict):
        def add_key(v):
            k = _rand_key()
            v[k] = random.choice([None, True, False, _rand_key(), random.randint(-100, 100), [], {}])
            return v
        def del_key(v):
            if v:
                k = random.choice(list(v.keys()))
                del v[k]
            return v
        def tweak_value(v):
            if not v:
                return v
            k = random.choice(list(v.keys()))
            v[k] = _mutate_json(v.get(k))
            return v
        ops += [add_key, del_key, tweak_value]

    if isinstance(val, list):
        def append_item(v):
            v.append(random.choice([None, True, False, _rand_key(), random.randint(-100,100), [], {}]))
            return v
        def pop_item(v):
            if v:
                v.pop(random.randrange(len(v)))
            return v
        def dup_item(v):
            if v:
                v.insert(random.randrange(len(v)), random.choice(v))
            return v
        ops += [append_item, pop_item, dup_item]

    def scalar_flip(v):
        if isinstance(v, bool):
            return not v
        if v is None:
            return random.choice([True, False, 0, 1, "null"])
        if isinstance(v, (int, float)):
            return _mutate_number(v)
        if isinstance(v, str):
            return _mutate_string(v)
        return v

    def type_hop(v):
        choices = [None, True, False, _rand_key(), random.randint(-100,100), [], {}]
        return random.choice(choices)

    def array_wrap(v):
        return _wrap_array(v)

    ops += [scalar_flip, type_hop, array_wrap]
    try:
        op = random.choice(ops)
        out = op(val)
    except Exception:
        out = val
    return out

def _json_roundtrip(obj, max_size):
    obj = _ensure_depth(obj)
    s = json.dumps(obj, separators=(",", ":"))
    b = s.encode("utf-8", "ignore")
    return _safe_bytes(b, max_size)

# ========= LLM BUFFER =========
def pop_llm_candidate(max_len):
    """Pick & consume one llm_*.json from buffer directory."""
    try:
        files = glob.glob(os.path.join(LLM_BUF_DIR, "llm_*.json"))
        if not files:
            return None
        f = random.choice(files)
        with open(f, "rb") as fp:
            b = fp.read()
        # consume (pop)
        try:
            os.remove(f)
        except Exception:
            pass
        if len(b) > int(max_len):
            _bump(LLM_ERR)
            return None
        return _safe_bytes(b, max_len)
    except Exception:
        _bump(LLM_ERR)
        return None

# ========= AFL API (flexible signatures) =========

def afl_custom_init(*args):
    """
    Accepts:
      - (seed)
      - (afl, seed)
    """
    _tick("tick")
    _log_env("afl_custom_init")
    try:
        seed = int(args[-1])
    except Exception:
        seed = int(time.time())

    try:
        random.seed(seed ^ os.getpid() ^ int(time.time()))
    except Exception:
        random.seed(os.getpid() ^ int(time.time()))
    return True

def _normalize_fuzz_args(*args):
    """
    Normalize AFL++ python wrapper variants to: (buf: bytes, add_buf: bytes|None, max_size: int)
      - (data, max_size)
      - (data, add_buf, max_size)
      - (afl, data, add_buf, max_size)
    """
    if len(args) == 2:
        data, max_size = args
        add_buf = None
    elif len(args) == 3:
        data, add_buf, max_size = args
    elif len(args) == 4:
        _afl, data, add_buf, max_size = args
    else:
        data = args[0] if args else _MIN
        add_buf = None
        max_size = args[-1] if args else (1 << 20)

    data_b = _to_bytes(data) or _MIN
    try:
        max_sz = int(max_size)
        if max_sz <= 0:
            max_sz = 1
    except Exception:
        max_sz = 1 << 20

    add_b = None
    if add_buf is not None:
        ab = _to_bytes(add_buf)
        add_b = ab if ab else None

    return data_b, add_b, max_sz

def afl_custom_fuzz(*args):
    """
    Flexible entry: normalize args then perform LLM/LOCAL mutation.
    Always returns bytes within max_size (never None/bytearray only).
    """
    _tick("tick")         # 호출 마커
    _bump(TICK_FILE)      # 카운터
    buf, add_buf, max_size = _normalize_fuzz_args(*args)

    try:
        # LLM 후보 관측
        has_candidates = bool(glob.glob(os.path.join(LLM_BUF_DIR, "llm_*.json")))
        if has_candidates:
            _bump(LLM_AVAIL)

        # LLM 사용 여부
        use_llm = False
        if has_candidates:
            if LLM_FORCE or AFL_CUSTOM_MUTATOR_ONLY:
                use_llm = True
            else:
                use_llm = (random.random() < LLM_PROB)

        if use_llm:
            llm = pop_llm_candidate(max_size)
            if llm:
                _bump(LLM_USED)
                return _safe_bytes(llm, max_size)
            else:
                _bump(LLM_SKIP)

        # ---- 로컬 변이 (non-LLM) ----
        keep_valid = (random.random() < 0.7)

        base = buf if buf and len(buf) > 0 else _MIN
        if keep_valid:
            try:
                val = json.loads(base.decode("utf-8", "ignore"))
            except Exception:
                val = {}
            for _ in range(random.randint(1, 4)):
                val = _mutate_json(val)
            _bump(NONLLM_USED)
            return _json_roundtrip(val, max_size)

        out = bytearray(base)
        for _ in range(random.randint(1, 3)):
            choice = random.random()
            if choice < 0.34 and len(out) > 0:
                i = random.randrange(len(out))
                del out[i]
            elif choice < 0.67 and len(out) < max(8, max_size):
                i = random.randrange(len(out)+1)
                out[i:i] = bytes([random.randrange(256)])
            else:
                if len(out) > 0:
                    i = random.randrange(len(out))
                    out[i] = random.randrange(256)
        _bump(NONLLM_USED)
        return _safe_bytes(bytes(out), max_size)

    except Exception:
        _bump(LLM_ERR)
        return _MIN[:max_size]

def afl_custom_deinit(*_args):
    pass

# ========= Back-compat aliases (일부 빌드에서 구형 이름을 찾을 수 있음) =========

# queue_get이 없으면 파일 내용을 그대로 읽어 반환하는 기본 구현
def _default_queue_get(filename):
    try:
        with open(filename, "rb") as f:
            b = f.read()
        # 파일 버퍼도 방어
        return _safe_bytes(b, 1 << 20)
    except Exception:
        return None

# queue_new_entry는 선택적이므로 no-op 기본 구현
def _default_queue_new_entry(filename_new_queue, filename_orig_queue):
    return None

# alias
init = afl_custom_init
fuzz = afl_custom_fuzz

def fuzz_count(max_size):
    # 최소 호출 횟수 보장(너무 크게는 금지)
    try:
        m = int(max_size)
        _ = m  # just to use
    except Exception:
        pass
    return 4

# opt aliases
try:
    afl_custom_queue_get  # type: ignore[name-defined]
except NameError:
    afl_custom_queue_get = None

try:
    afl_custom_queue_new_entry  # type: ignore[name-defined]
except NameError:
    afl_custom_queue_new_entry = None

queue_get = afl_custom_queue_get if afl_custom_queue_get else _default_queue_get
queue_new_entry = afl_custom_queue_new_entry if afl_custom_queue_new_entry else _default_queue_new_entry
deinit = afl_custom_deinit

# 디버그: 노출된 API를 파일로 남김
try:
    with open("/tmp/afl_python_api_min", "w", encoding="utf-8") as _f:
        _f.write(f"{int(time.time())} has init={bool('init' in globals())}\n")
        _f.write(f"{int(time.time())} has fuzz_count={bool('fuzz_count' in globals())}\n")
        _f.write(f"{int(time.time())} has fuzz={bool('fuzz' in globals())}\n")
        _f.write(f"{int(time.time())} has queue_get={bool('queue_get' in globals())}\n")
        _f.write(f"{int(time.time())} has queue_new_entry={bool('queue_new_entry' in globals())}\n")
        _f.write(f"{int(time.time())} has deinit={bool('deinit' in globals())}\n")
except Exception:
    pass
