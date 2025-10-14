import time

T_IMPORT = "/tmp/afl_python_imported_min"
T_INIT   = "/tmp/afl_python_init_min"
T_TICK   = "/tmp/afl_python_tick_min"
T_DEINIT = "/tmp/afl_python_deinit_min"
T_QGET   = "/tmp/afl_python_qget_min"
T_QNEW   = "/tmp/afl_python_qnew_min"

def _bump(path, msg=""):
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"{int(time.time())} {msg}\n")
    except Exception:
        pass

# import 시점 표식
_bump(T_IMPORT, "imported")

def init(seed):
    _bump(T_INIT, f"seed={seed}")
    return True

def fuzz_count(max_size):
    # 이 함수가 있으면 AFL이 이번 라운드에서 fuzz()를 최소 이 횟수만큼 호출
    return 4

def fuzz(buf, add_buf, max_size):
    _bump(T_TICK, "fuzz")
    out = b'{"min":1}'
    return out if len(out) <= max_size else out[:max_size]

def deinit():
    _bump(T_DEINIT, "deinit")

def queue_get(filename):
    _bump(T_QGET, f"file={filename}")
    try:
        with open(filename, "rb") as f:
            return f.read()
    except Exception:
        return None

def queue_new_entry(filename_new_queue, filename_orig_queue):
    _bump(T_QNEW, f"new={filename_new_queue} orig={filename_orig_queue}")
