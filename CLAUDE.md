# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

RAGFuzz is a RAG-guided AFL++ fuzzing framework for JSON parsers. It combines:
- **Adaptive mutation** with EMA-based operator scheduling
- **Curriculum learning** (3-phase progression: A→B→C)
- **LLM-powered seed generation** for intelligent corpus expansion
- **Plateau detection** for phase transitions

## Core Architecture

### Mutation Pipeline (mutators/)

The fuzzing uses a **3-phase curriculum** based on JSON parse rate:

- **Phase A** (rate < 0.50): Safe core operators `[op_nop, op_flip_bool]`
- **Phase B** (rate ≥ 0.50): Add boundary testing `[..., op_num_boundary]`
- **Phase C** (rate ≥ 0.90): All operators including complex transformations

**Key components:**
- `mutators/json_adapt.py` - Main AFL++ mutator with curriculum logic
  - Exposes both `afl_custom_*` (C API parity) and `init/fuzz` (Python API)
  - Updates parse stats (`_parse_ok/_parse_all`) to drive phase transitions
  - Uses EMA scheduler to adaptively select operators
- `mutators/json_ops.py` - Operator implementations (13 total)
  - Base: `op_nop`, `op_flip_bool`, `op_num_boundary`
  - Extended: `op_fix_basic`, `op_rare_token`, `op_long_string`, `op_deep_nest`, `op_utf8_edge`, `op_dup_keys`, `op_add_field`, `op_delete_field`, `op_splice_objects`, `op_splice_arrays`
  - All operators accept `(buf, add_buf, max_size, rng=None)` signature
- `mutators/sched_ema.py` - EMAScheduler for operator selection
  - Parameters: `lam` (learning rate), `tau` (temperature), `eps` (exploration)
  - `pick(allowed)` - Softmax sampling with ε-greedy exploration
  - `reward_update(op, d_cov, uniq_crash, new_path)` - Update operator scores

### LLM Integration (tools/)

- `tools/rag_seedgen.py` - Generate JSON seeds using LLM
  - Extracts keys from existing corpus/queue files
  - Calls OpenAI-compatible API (supports both Responses and ChatCompletion APIs)
  - Validates generated JSONs against target harness
  - Outputs seeds to `corpus/generated/` and keys to `corpus/dict/auto.dict`
  - Config: `~/.config/ragfuzz/config.toml` (TOML format with `[llm]` section)

- `tools/phase_ctl.py` - Plateau detection sidecar
  - Monitors `fuzzer_stats` for path growth stagnation
  - Writes `phase_ctl.json` with `{"plateau": true/false}`
  - Mutator can read this to trigger B→C transition or EMA reset

### Targets

Pre-built binaries in `targets/json/`:
- `json_asan` - Jansson library harness (default)
- `jsonc_asan` - json-c library
- `yajl_asan` - YAJL library
- `rapidjson_asan` - RapidJSON library

All harnesses read JSON from stdin, parse it, and exit cleanly (return 0 even on parse failures for path diversity).

## Common Commands

### Environment Setup

```bash
# Required: Set PYTHONPATH for mutator imports
export PYTHONPATH="$PWD"

# Python environment (choose one)
conda create -n ragfuzz python=3.11 -y && conda activate ragfuzz
# OR
python3 -m venv ~/.venvs/ragfuzz && source ~/.venvs/ragfuzz/bin/activate

# Install dependencies
pip install "openai>=1.40.0" tomli tomlkit
```

### Build Target (if needed)

```bash
cd targets/json
clang -O2 -g -fsanitize=address -fno-omit-frame-pointer \
  -o json_asan harness.c $(pkg-config --cflags --libs jansson)
```

### Quick Smoke Test

```bash
# Test mutator import
python -c "from mutators.json_adapt import fuzz; print(fuzz(b'{}', b'', 1024))"

# 10-second fuzzing run
export AFL_PYTHON_MODULE=mutators.json_adapt
afl-fuzz -i corpus/json_seeds -o out/smoke \
  -x corpus/dict/json.dict -m none -t 200 -V 10 -- \
  ./targets/json/json_asan
```

### LLM Seed Generation

```bash
# Setup config (one-time)
mkdir -p ~/.secrets ~/.config/ragfuzz
echo "sk-YOUR_KEY" > ~/.secrets/openai.key
chmod 600 ~/.secrets/openai.key

cat > ~/.config/ragfuzz/config.toml <<EOF
[llm]
provider = "openai"
model = "gpt-4o-mini"
temperature = 1.1
api_key_file = "$HOME/.secrets/openai.key"
EOF

# Generate seeds
python3 tools/rag_seedgen.py \
  --bin ./targets/json/json_asan \
  --config ~/.config/ragfuzz/config.toml \
  -n 50

# Merge dictionaries
cat corpus/dict/json.dict corpus/dict/auto.dict | sort -u > corpus/dict/combined.dict

# Merge seeds
mkdir -p corpus/seed_all
rsync -a corpus/json_seeds/ corpus/seed_all/
rsync -a corpus/generated/ corpus/seed_all/
```

### Run Fuzzing Campaign

**Baseline (no custom mutator):**
```bash
unset AFL_PYTHON_MODULE
afl-fuzz -i corpus/json_seeds -o out/baseline \
  -x corpus/dict/json.dict -m none -t 200 -V 600 -- \
  ./targets/json/json_asan
```

**With adaptive mutator:**
```bash
export PYTHONPATH="$PWD"
export AFL_PYTHON_MODULE=mutators.json_adapt
afl-fuzz -i corpus/seed_all -o out/adaptive \
  -x corpus/dict/combined.dict -m none -t 200 -V 600 -- \
  ./targets/json/json_asan
```

**3-way comparison (baseline vs mini vs full):**
```bash
# Set environment variables
export AFLBIN=$(which afl-fuzz)
export SEEDS=corpus/seed_all
export DICT=corpus/dict/combined.dict
export TGT=./targets/json/json_asan
export OUT_ROOT=out/3way_$(date +%y%m%d_%H%M%S)
export DUR=600  # seconds
export PY311_SP=$(python3 -c "import sys; print(':'.join(sys.path))")

./run_3way.sh
```

### With Plateau Sidecar

Terminal 1 (plateau detector):
```bash
python3 tools/phase_ctl.py --out out/run --window 180 --k 3
```

Terminal 2 (fuzzer):
```bash
export AFL_OUT_DIR=out/run
export PYTHONPATH="$PWD"
export AFL_PYTHON_MODULE=mutators.json_adapt
afl-fuzz -i corpus/seed_all -o out/run \
  -x corpus/dict/combined.dict -m none -t 200 -V 600 -- \
  ./targets/json/json_asan
```

### Collect Statistics

```bash
python3 tools/collect.py out/baseline stats_baseline.csv
python3 tools/collect.py out/adaptive stats_adaptive.csv
```

Key metrics: `edges_found`, `paths_total`, `execs_per_sec`, `unique_crashes`

### Corpus Minimization & Triage

```bash
# Minimize corpus
afl-cmin -i out/adaptive/default/queue -o corpus/minimized -- \
  ./targets/json/json_asan

# Minimize individual crash
afl-tmin -i out/adaptive/default/crashes/id:000000,* \
  -o crash_min.json -- ./targets/json/json_asan
```

## Tuning Guide

### EMA Scheduler (`mutators/sched_ema.py`)
- `lam` (0.1-0.3): Learning rate. Lower = more exploitation
- `tau` (0.5-1.0): Temperature. Higher = more exploration
- `eps` (0.02-0.10): ε-greedy exploration

### Phase Transitions (`mutators/json_adapt.py`)
- A→B threshold: Default 0.50, increase to 0.70 for stricter parsers
- B→C threshold: Default 0.90, decrease to 0.85 for faster progression
- Modify `_allowed_ops()` to adjust phase operator sets

### Plateau Detection (`tools/phase_ctl.py`)
- `--window 180`: Observation window (seconds). Increase for slow targets
- `--k 3`: Minimum path delta for non-plateau. Decrease for sensitivity

### LLM Generation (`tools/rag_seedgen.py`)
- `-n 100-200`: Generate more seeds for better initial coverage
- `temperature 1.1-1.5`: Higher for more diverse/creative outputs
- Monitor `corpus/dict/auto.dict` growth for dictionary effectiveness

## Adding New Operators

1. Add function to `mutators/json_ops.py`:
```python
def op_my_mutation(buf, add_buf, max_size, rng=None, **kw):
    # Mutation logic here
    return _clip(bytearray(modified), max_size)
```

2. Append to `OPS` list:
```python
OPS.append(op_my_mutation)
```

3. Operators are automatically available to scheduler (index-based)

4. To add to specific phase, modify `_allowed_ops()` in `json_adapt.py`:
```python
def _allowed_ops():
    # ...
    if rate >= 0.90:
        return list(range(len(OPS)))  # Phase C: includes new operator
```

## File Structure Notes

- `out/` - AFL++ output directory (excluded from Windows checkout due to colon in filenames)
- `corpus/json_seeds/` - Initial seed corpus
- `corpus/generated/` - LLM-generated seeds
- `corpus/dict/` - AFL++ dictionaries (tokens)
- `corpus/seed_all/` - Merged corpus for production runs
- `mutators/softmax_mutator.py` - Experimental alternative mutator (not used by default)
- `scripts/` - Helper scripts for analysis
- `triage/` - Post-fuzzing crash analysis tools

## Important Implementation Details

### Mutator Exception Handling
All mutator functions are wrapped in try-except to never kill afl-fuzz:
- `afl_custom_fuzz()` returns `b"{}"` as last resort fallback
- Individual operators return unmodified `buf` on exception
- Parse stats updates are best-effort (wrapped in try-except)

### Phase Control Integration
The mutator checks for optional `phase_ctl.json`:
- Read by `_allowed_ops()` to force phase transitions
- Enables external control without modifying mutator code
- Falls back to parse-rate-based curriculum if file absent

### Operator Indexing
Operators are indexed positionally in `OPS` list:
- Phase A uses indices [0,1]
- Phase B uses indices [0,1,2]
- Phase C uses all indices
- **Never remove/reorder existing operators** - only append to preserve indices
