#!/usr/bin/env python3
import os, time, json, glob, argparse, random, pathlib, traceback, re
from datetime import datetime
from openai import OpenAI   # pip install openai>=1.44

SYSTEM = (
    "You are a fuzzer assistant. Mutate JSON while preserving syntactic validity. "
    "Return ONLY one JSON object/array without code fences or commentary. Max ~16KB."
)

USER_TMPL = """Given this JSON sample, produce ONE meaningfully different JSON that is still valid and likely to explore new branches.
Rules:
- Output MUST be a single JSON object or array.
- No explanations, no backticks, no code fences, no extra text.
- You may insert/delete/alter keys/values; try edgy numbers, nested arrays/objects, unusual unicode.
- Keep it under ~16KB.

Sample:
{sample}
"""

# --- robust extractors -------------------------------------------------
_CODEFENCE_RX = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.S)

def _try_parse_json(txt: str):
    """1) direct parse, 2) code fence, 3) strip leading/trailing, 4) brace-scan"""
    # (1) straight
    try:
        return json.loads(txt)
    except Exception:
        pass

    # (2) code fence block
    m = _CODEFENCE_RX.search(txt)
    if m:
        inner = m.group(1).strip()
        try:
            return json.loads(inner)
        except Exception:
            pass

    # (3) trim leading noise up to first '{' or '[' and last '}'/']'
    start = None
    for i, ch in enumerate(txt):
        if ch in "{[":
            start = i
            break
    if start is not None:
        cand = txt[start:]
        # try cut at last possible closing brace/bracket
        for end in range(len(cand), 0, -1):
            frag = cand[:end].strip()
            if frag and frag[-1] in "}]":
                try:
                    return json.loads(frag)
                except Exception:
                    continue

    # (4) give up
    raise ValueError("no-parse")

def load_seeds(seed_dir):
    paths = sorted(p for p in glob.glob(os.path.join(seed_dir, "*")) if os.path.isfile(p))
    data = []
    for p in paths:
        try:
            b = pathlib.Path(p).read_bytes()
            s = b.decode("utf-8", "ignore")
            json.loads(s)  # only valid JSON seeds
            data.append(s)
        except Exception:
            pass
    return data

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True, help="seed corpus dir (only valid JSON considered)")
    ap.add_argument("--out", required=True, help="buffer dir (e.g., /tmp/llm_buf)")
    ap.add_argument("--rate", type=int, default=30, help="targets per minute")
    ap.add_argument("--model", default="gpt-4o-mini")
    ap.add_argument("--max-bytes", type=int, default=16*1024)
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--dry", action="store_true", help="emit trivial JSON without LLM for plumbing test")
    args = ap.parse_args()

    out_dir = pathlib.Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    bad_dir = out_dir / "_bad"
    bad_dir.mkdir(parents=True, exist_ok=True)

    seeds = load_seeds(args.src)
    if not seeds:
        raise SystemExit(f"No valid JSON seeds in --src: {args.src}")

    interval = 60.0 / max(args.rate, 1)

    if args.dry:
        print(f"[producer][DRY] writing trivial JSONs into {out_dir}")
        i = 0
        while True:
            obj = {"dry": True, "i": i, "rand": random.randint(-1_000_000, 1_000_000)}
            blob = json.dumps(obj, separators=(",", ":")).encode()
            tmp = out_dir / f".llm_tmp_{i}.partial"
            dst = out_dir / f"llm_{datetime.utcnow().strftime('%Y%m%dT%H%M%S%fZ')}.json"
            tmp.write_bytes(blob)
            tmp.replace(dst)
            i += 1
            time.sleep(interval)

    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        raise SystemExit("OPENAI_API_KEY not set")

    client = OpenAI(api_key=api_key)
    print(f"[producer] loaded {len(seeds)} seeds; writing to {out_dir}; model={args.model}; rate={args.rate}/min")

    n = 0
    while True:
        sample = random.choice(seeds)
        prompt = USER_TMPL.format(sample=sample)
        try:
            resp = client.chat.completions.create(
                model=args.model,
                messages=[{"role": "system", "content": SYSTEM},
                          {"role": "user", "content": prompt}],
                temperature=0.9,
                max_tokens=2000,
            )
            raw = (resp.choices[0].message.content or "").strip()

            # robust parse
            try:
                obj = _try_parse_json(raw)
            except Exception:
                # save raw for debugging
                (bad_dir / f"bad_{datetime.utcnow().strftime('%Y%m%dT%H%M%S%fZ')}.txt").write_text(raw, encoding="utf-8", errors="ignore")
                if args.verbose:
                    print("[producer][WARN] could not parse JSON; saved raw to _bad/")
                time.sleep(interval)
                continue

            blob = json.dumps(obj, separators=(",", ":")).encode("utf-8")
            if len(blob) > args.max_bytes:
                if args.verbose:
                    print(f"[producer][WARN] oversized {len(blob)} > {args.max_bytes}, skipping")
                time.sleep(interval)
                continue

            tmp = out_dir / f".llm_tmp_{n}.partial"
            dst = out_dir / f"llm_{datetime.utcnow().strftime('%Y%m%dT%H%M%S%fZ')}.json"
            tmp.write_bytes(blob)
            tmp.replace(dst)
            n += 1
            if args.verbose and n % 10 == 0:
                print(f"[producer] wrote {n} files")
            time.sleep(interval)

        except KeyboardInterrupt:
            print("\n[producer] interrupted, exiting.")
            break
        except Exception as e:
            print("[producer][ERR]:", e)
            if args.verbose:
                traceback.print_exc()
            time.sleep(1.0)

if __name__ == "__main__":
    main()
