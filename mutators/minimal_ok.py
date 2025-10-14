# mutators/minimal_ok.py — hardened minimal mutator
import os, time, random, traceback

T_IMPORT="/tmp/afl_python_imported_min"
T_INIT  ="/tmp/afl_python_init_min"
T_TICK  ="/tmp/afl_python_tick_min"
T_DEINIT="/tmp/afl_python_deinit_min"
T_ERR   ="/tmp/afl_python_min_errors"

def _bump(p,msg=""):
    try:
        with open(p,"a",encoding="utf-8") as f: f.write(f"{int(time.time())} {msg}\n")
    except: pass
def _err(msg):
    try:
        with open(T_ERR,"a",encoding="utf-8") as f: f.write(f"[{time.strftime('%F %T')}] {msg}\n")
    except: pass

_bump(T_IMPORT,f"imported:{__file__}")
_MIN=b"{}"

def _safe_bytes(b,max_size):
    try:
        if b is None or len(b)==0: b=_MIN
        if not isinstance(b,(bytes,bytearray,memoryview)): b=bytes(b)
        b=bytes(b)
    except: b=_MIN
    try:
        m=int(max_size)
        if m>0 and len(b)>m: b=b[:m]
    except: pass
    if not b:
        b=_MIN[: (max_size if isinstance(max_size,int) else len(_MIN))]
    return b

def _norm_fuzz_args(*args):
    data=_MIN; add=None; msz=1<<20
    try:
        if len(args)==2: data,msz=args
        elif len(args)==3: data,add,msz=args
        elif len(args)==4: _afl,data,add,msz=args
        elif len(args)>=1: data=args[0]; msz=args[-1]
    except Exception as e: _err(f"_norm_fuzz_args: {e}")
    try:
        data=bytes(data) if isinstance(data,(bytes,bytearray,memoryview)) else bytes(data)
    except: data=_MIN
    try:
        add=(bytes(add) if isinstance(add,(bytes,bytearray,memoryview)) else (bytes(add) if add is not None else None))
    except: add=None
    try: msz=int(msz)
    except: msz=1<<20
    return data,add,msz

def afl_custom_init(*args):
    try: seed=int(args[-1]) if args else int(time.time())
    except: seed=int(time.time())
    try: random.seed(seed ^ os.getpid() ^ int(time.time()))
    except: random.seed(os.getpid() ^ int(time.time()))
    _bump(T_INIT,f"seed={seed}")
    return True

def afl_custom_fuzz(*args):
    _bump(T_TICK,"fuzz")
    try:
        buf,add,max_size=_norm_fuzz_args(*args)
        return _safe_bytes(b'{"min":1}',max_size)
    except:
        _err("fuzz:\n"+traceback.format_exc())
        return _safe_bytes(_MIN,args[-1] if args else 1<<20)

def afl_custom_fuzz_count(max_size): return 4
def afl_custom_deinit(): _bump(T_DEINIT,"deinit")
