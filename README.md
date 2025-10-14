# RAGFuzz: RAG-Guided AFL++ Fuzzing Framework

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![AFL++](https://img.shields.io/badge/AFL++-4.0+-red.svg)](https://github.com/AFLplusplus/AFLplusplus)

RAGFuzz is an advanced fuzzing framework that combines **AFL++** with **LLM-powered seed generation** and **adaptive mutation strategies** to improve code coverage and bug discovery in JSON parsers.

## Key Features

- **Adaptive Mutation**: EMA-based operator scheduling that learns which mutations work best
- **Curriculum Learning**: 3-phase progression (A→B→C) that starts safe and progressively adds complexity
- **LLM-Powered Seeds**: Uses GPT-4/Claude to generate diverse, edge-case JSON inputs
- **Plateau Detection**: Automatic detection of coverage stagnation with phase transitions
- **Multi-Target Support**: Pre-built harnesses for 4 popular JSON libraries

## Quick Start (15 Minutes)

```bash
# 1. Install AFL++ (5 min)
cd ~ && git clone https://github.com/AFLplusplus/AFLplusplus.git
cd AFLplusplus && make distrib -j$(nproc)
export PATH="$HOME/AFLplusplus:$PATH"

# 2. Install dependencies (2 min)
cd /path/to/ragfuzz
pip install -r requirements.txt

# 3. Verify setup (1 min)
export PYTHONPATH="$PWD"
./check_setup.sh

# 4. Run your first experiment (10 min)
./run_comparative_experiment.sh 600
```

**See [QUICK_START.md](QUICK_START.md) for detailed instructions.**

---

## Table of Contents

- [Architecture](#architecture)
- [Installation](#installation)
- [Usage](#usage)
  - [Basic Fuzzing](#basic-fuzzing)
  - [LLM-Enhanced Fuzzing](#llm-enhanced-fuzzing)
  - [Comparative Experiments](#comparative-experiments)
- [Mutation Strategies](#mutation-strategies)
- [Configuration](#configuration)
- [Results](#results)
- [Documentation](#documentation)
- [Contributing](#contributing)
- [License](#license)

---

## Architecture

RAGFuzz extends AFL++ with three key components:

### 1. Adaptive Mutator (`mutators/json_adapt.py`)

Implements a custom Python mutator for AFL++ with:
- **13 specialized JSON operators** (flip_bool, num_boundary, deep_nest, utf8_edge, etc.)
- **EMA-based scheduling** that adapts operator selection based on feedback
- **Curriculum learning** with 3 phases:
  - **Phase A** (parse rate < 50%): Safe operators only
  - **Phase B** (parse rate ≥ 50%): Add boundary testing
  - **Phase C** (parse rate ≥ 90%): Full operator set

### 2. LLM Seed Generator (`tools/rag_seedgen.py`)

Generates intelligent test seeds using LLMs:
- Extracts keys/tokens from existing corpus
- Calls OpenAI/Anthropic API to generate diverse JSON structures
- Validates generated JSONs against target harness
- Builds enhanced AFL++ dictionaries automatically

### 3. Plateau Detector (`tools/phase_ctl.py`)

Monitors fuzzing progress and triggers phase transitions:
- Detects coverage stagnation using sliding window analysis
- Forces curriculum progression when coverage plateaus
- Resets EMA weights to escape local optima

```
┌──────────────────────────────────────────────────────────┐
│                    RAGFuzz Pipeline                       │
└──────────────────────────────────────────────────────────┘
                            ↓
        ┌───────────────────────────────────┐
        │  LLM Seed Generation (Optional)   │
        │  • Extract corpus tokens          │
        │  • Generate diverse JSONs         │
        │  • Build enhanced dictionary      │
        └───────────────────────────────────┘
                            ↓
        ┌───────────────────────────────────┐
        │        AFL++ with Custom          │
        │       Adaptive Mutator            │
        │  • Phase A: Safe operators        │
        │  • Phase B: Boundary testing      │
        │  • Phase C: Complex mutations     │
        └───────────────────────────────────┘
                            ↓
        ┌───────────────────────────────────┐
        │   Plateau Detection (Optional)    │
        │  • Monitor coverage growth        │
        │  • Trigger phase transitions      │
        │  • Reset EMA on stagnation        │
        └───────────────────────────────────┘
                            ↓
        ┌───────────────────────────────────┐
        │         Results Analysis          │
        │  • Coverage comparison            │
        │  • Crash triage                   │
        │  • Performance metrics            │
        └───────────────────────────────────┘
```

---

## Installation

### Prerequisites

- **OS**: Linux (Ubuntu 22.04+ recommended) or WSL2
- **Python**: 3.11 or higher
- **Compiler**: clang with ASAN support
- **Memory**: 4GB+ RAM recommended

### System Dependencies

```bash
sudo apt-get update
sudo apt-get install -y git build-essential clang lld cmake \
    python3-pip python3-venv jq rsync pkg-config libjansson-dev
```

### AFL++ Installation

```bash
cd ~
git clone https://github.com/AFLplusplus/AFLplusplus.git
cd AFLplusplus
make distrib -j$(nproc)
export PATH="$HOME/AFLplusplus:$PATH"
echo 'export PATH="$HOME/AFLplusplus:$PATH"' >> ~/.bashrc
```

Verify installation:
```bash
which afl-fuzz
afl-fuzz -h
```

### Python Environment

Using conda (recommended):
```bash
conda create -n ragfuzz python=3.11 -y
conda activate ragfuzz
```

Or using venv:
```bash
python3 -m venv ~/.venvs/ragfuzz
source ~/.venvs/ragfuzz/bin/activate
```

### Install RAGFuzz

```bash
cd /path/to/ragfuzz
pip install -r requirements.txt
export PYTHONPATH="$PWD"
```

### Verify Setup

```bash
./check_setup.sh
```

This checks:
- System tools (Python, AFL++, git)
- Python dependencies
- Target binaries
- Corpus and seeds
- LLM configuration (if applicable)

---

## Usage

### Basic Fuzzing

Run AFL++ with the adaptive mutator (no LLM):

```bash
export PYTHONPATH="$PWD"
export AFL_PYTHON_MODULE=mutators.json_adapt

afl-fuzz -i corpus/json_seeds -o out/basic \
    -x corpus/dict/json.dict -m none -t 200 -V 600 -- \
    ./targets/json/json_asan
```

**Parameters:**
- `-i`: Input seed corpus
- `-o`: Output directory
- `-x`: Dictionary file
- `-m none`: No memory limit
- `-t 200`: 200ms timeout per execution
- `-V 600`: Run for 600 seconds (10 minutes)

### LLM-Enhanced Fuzzing

#### 1. Configure LLM

Create LLM configuration:

```bash
mkdir -p ~/.secrets ~/.config/ragfuzz
echo "sk-YOUR_OPENAI_KEY" > ~/.secrets/openai.key
chmod 600 ~/.secrets/openai.key

cat > ~/.config/ragfuzz/config.toml <<'EOF'
[llm]
provider = "openai"
model = "gpt-4o-mini"
temperature = 1.1
api_key_file = "$HOME/.secrets/openai.key"
EOF
```

**Supported providers:**
- `openai`: GPT-4, GPT-4o, GPT-3.5
- `anthropic`: Claude 3 Opus/Sonnet/Haiku
- Any OpenAI-compatible API

#### 2. Generate Seeds

```bash
python3 tools/rag_seedgen.py \
    --bin ./targets/json/json_asan \
    --config ~/.config/ragfuzz/config.toml \
    -n 50
```

This generates:
- `corpus/generated/`: 50 diverse JSON seeds
- `corpus/dict/auto.dict`: Extracted tokens

#### 3. Merge Corpus

```bash
cat corpus/dict/json.dict corpus/dict/auto.dict | sort -u > corpus/dict/combined.dict

mkdir -p corpus/seed_all
rsync -a corpus/json_seeds/ corpus/seed_all/
rsync -a corpus/generated/ corpus/seed_all/
```

#### 4. Run Enhanced Fuzzing

```bash
export PYTHONPATH="$PWD"
export AFL_PYTHON_MODULE=mutators.json_adapt

afl-fuzz -i corpus/seed_all -o out/llm_enhanced \
    -x corpus/dict/combined.dict -m none -t 200 -V 3600 -- \
    ./targets/json/json_asan
```

### Comparative Experiments

Run automated baseline vs. LLM-enhanced comparison:

```bash
export PYTHONPATH="$PWD"
./run_comparative_experiment.sh 600
```

This script:
1. Checks if LLM is configured (optional)
2. Generates LLM seeds if configured
3. Runs baseline AFL++ (no custom mutator)
4. Runs LLM-enhanced RAGFuzz (adaptive mutator)
5. Collects and compares results
6. Generates comparison report

**Output:**
```
out/comparative_YYYYMMDD_HHMMSS/
├── README.md               # Experiment summary
├── comparison.txt          # Metrics table
├── comparison.csv          # Exportable data
├── baseline/
│   └── default/
│       ├── fuzzer_stats
│       ├── queue/
│       └── crashes/
└── llm_enhanced/
    └── default/
        ├── fuzzer_stats
        ├── queue/
        └── crashes/
```

### With Plateau Detection

Run fuzzer with automatic plateau detection:

**Terminal 1** (Plateau detector):
```bash
python3 tools/phase_ctl.py --out out/experiment --window 180 --k 3
```

**Terminal 2** (Fuzzer):
```bash
export AFL_OUT_DIR=out/experiment
export PYTHONPATH="$PWD"
export AFL_PYTHON_MODULE=mutators.json_adapt

afl-fuzz -i corpus/seed_all -o out/experiment \
    -x corpus/dict/combined.dict -m none -t 200 -V 3600 -- \
    ./targets/json/json_asan
```

**Parameters:**
- `--window 180`: Observation window (180 seconds)
- `--k 3`: Minimum path delta for non-plateau

---

## Mutation Strategies

### Phase-Based Curriculum

| Phase | Parse Rate | Operators | Purpose |
|-------|-----------|-----------|---------|
| **A** | < 50% | `op_nop`, `op_flip_bool` | Generate valid JSONs |
| **B** | ≥ 50% | Phase A + `op_num_boundary` | Test edge cases |
| **C** | ≥ 90% | All 13 operators | Deep exploration |

### Available Operators

| Operator | Description | Phase |
|----------|-------------|-------|
| `op_nop` | No-op (identity) | A |
| `op_flip_bool` | Flip true/false values | A |
| `op_num_boundary` | Inject INT_MAX, -1, 0, etc. | B |
| `op_fix_basic` | Fix basic syntax errors | B |
| `op_rare_token` | Insert rare Unicode chars | C |
| `op_long_string` | Generate very long strings | C |
| `op_deep_nest` | Create deeply nested structures | C |
| `op_utf8_edge` | UTF-8 edge cases | C |
| `op_dup_keys` | Duplicate JSON keys | C |
| `op_add_field` | Add random fields | C |
| `op_delete_field` | Remove random fields | C |
| `op_splice_objects` | Merge JSON objects | C |
| `op_splice_arrays` | Merge JSON arrays | C |

### EMA Scheduler

The EMA (Exponential Moving Average) scheduler adapts operator selection:

- **λ (lambda)**: Learning rate (0.1-0.3)
  - Lower = more exploitation of proven operators
  - Higher = faster adaptation to new feedback

- **τ (tau)**: Temperature (0.5-1.0)
  - Lower = greedy selection of best operators
  - Higher = more exploration of all operators

- **ε (epsilon)**: Exploration rate (0.02-0.10)
  - Probability of random operator selection
  - Prevents premature convergence

**Tuning guide:**
```python
# Exploit good operators aggressively
scheduler = EMAScheduler(lam=0.1, tau=0.5, eps=0.02)

# Explore more operators
scheduler = EMAScheduler(lam=0.3, tau=1.0, eps=0.10)
```

---

## Configuration

### Mutator Configuration

Edit `mutators/json_adapt.py` to adjust:

```python
# Phase transition thresholds
def _allowed_ops():
    rate = _parse_ok / max(_parse_all, 1)

    if rate < 0.50:       # Phase A threshold
        return [0, 1]     # Safe operators
    elif rate < 0.90:     # Phase B threshold
        return [0, 1, 2]  # Add boundary testing
    else:
        return list(range(len(OPS)))  # Phase C: all operators
```

```python
# EMA scheduler parameters
_scheduler = EMAScheduler(
    lam=0.2,   # Learning rate
    tau=0.8,   # Temperature
    eps=0.05   # Exploration
)
```

### LLM Configuration

Edit `~/.config/ragfuzz/config.toml`:

```toml
[llm]
provider = "openai"           # or "anthropic"
model = "gpt-4o-mini"         # or "gpt-4", "claude-3-opus-20240229"
temperature = 1.1             # 0.7-1.5 (higher = more diverse)
max_tokens = 2000
api_key_file = "$HOME/.secrets/openai.key"

# Optional: Custom API endpoint
# base_url = "https://api.openai.com/v1"
```

### Plateau Detection Configuration

Edit `tools/phase_ctl.py` or use CLI flags:

```bash
python3 tools/phase_ctl.py \
    --out out/experiment \
    --window 180 \    # Observation window (seconds)
    --k 3 \           # Min path delta for non-plateau
    --check 10        # Check interval (seconds)
```

---

## Results

### Expected Performance (10-minute experiment)

| Metric | Baseline (AFL++) | LLM-Enhanced (RAGFuzz) | Improvement |
|--------|------------------|------------------------|-------------|
| **Paths Found** | 500-1,500 | 800-2,000 | +20-40% |
| **Coverage** | 30-50% | 40-60% | +5-15% |
| **Exec/sec** | 500-2,000 | 400-1,800 | -10-20% |
| **Unique Crashes** | 0-5 | 0-10 | More diverse |

### Why LLM-Enhanced Performs Better

1. **Diverse Seeds**: LLM generates edge cases that humans might miss
   - Deep nesting (100+ levels)
   - Boundary values (INT_MAX, NaN, -0)
   - Rare Unicode sequences (emoji, RTL, combining chars)

2. **Smart Mutations**: Adaptive operator selection
   - EMA scheduler learns which operators find new paths
   - Phase transitions prevent getting stuck

3. **Enhanced Dictionary**: LLM extracts domain-specific tokens
   - API-specific keys (`"user_id"`, `"access_token"`)
   - Format-specific values (`"2024-01-01T00:00:00Z"`)

### Analyzing Results

**View comparison:**
```bash
cat out/comparative_*/README.md
cat out/comparative_*/comparison.txt
```

**Compare crashes:**
```bash
ls -la out/comparative_*/baseline/default/crashes/
ls -la out/comparative_*/llm_enhanced/default/crashes/

# Triage crashes
python3 tools/triage.py ./targets/json/json_asan \
    out/comparative_*/llm_enhanced/default/crashes/
```

**Minimize corpus:**
```bash
afl-cmin -i out/llm_enhanced/default/queue \
    -o corpus/minimized -- ./targets/json/json_asan
```

**Minimize crash:**
```bash
afl-tmin -i crashes/id:000000,sig:06,* \
    -o crash_min.json -- ./targets/json/json_asan
```

---

## Documentation

- **[QUICK_START.md](QUICK_START.md)**: Get running in 15 minutes
- **[EXPERIMENT_GUIDE.md](EXPERIMENT_GUIDE.md)**: Complete experimental workflow
- **[EXPERIMENT_SETUP.md](EXPERIMENT_SETUP.md)**: Detailed setup and troubleshooting
- **[CLAUDE.md](CLAUDE.md)**: Implementation details and tuning guide

**Reading path:**
1. Start with QUICK_START.md for fast setup
2. Read EXPERIMENT_GUIDE.md for understanding the workflow
3. Consult EXPERIMENT_SETUP.md for troubleshooting
4. Review CLAUDE.md for customization

---

## Project Structure

```
ragfuzz/
├── corpus/
│   ├── json_seeds/          # Initial seed corpus (45 files)
│   ├── generated/           # LLM-generated seeds
│   ├── seed_all/            # Merged corpus
│   └── dict/
│       ├── json.dict        # Standard JSON tokens
│       ├── auto.dict        # LLM-extracted tokens
│       └── combined.dict    # Merged dictionary
│
├── mutators/
│   ├── json_adapt.py        # Main adaptive mutator
│   ├── json_ops.py          # 13 mutation operators
│   ├── sched_ema.py         # EMA scheduler
│   └── softmax_mutator.py   # Experimental alternative
│
├── tools/
│   ├── rag_seedgen.py       # LLM seed generator
│   ├── phase_ctl.py         # Plateau detector
│   ├── collect.py           # Statistics collector
│   ├── eval.py              # Visualizer
│   └── triage.py            # Crash analysis
│
├── targets/
│   └── json/
│       ├── json_asan        # Jansson harness
│       ├── jsonc_asan       # json-c harness
│       ├── yajl_asan        # YAJL harness
│       └── rapidjson_asan   # RapidJSON harness
│
├── scripts/
│   ├── run_comparative_experiment.sh  # Automated comparison
│   ├── run_3way.sh                    # 3-way comparison
│   └── check_setup.sh                 # Environment checker
│
├── out/                     # AFL++ output (gitignored)
├── requirements.txt         # Python dependencies
└── README.md               # This file
```

---

## Advanced Usage

### Multi-Target Fuzzing

Test all JSON parsers:

```bash
for target in json_asan jsonc_asan yajl_asan rapidjson_asan; do
    echo "Testing $target..."
    export PYTHONPATH="$PWD"
    export AFL_PYTHON_MODULE=mutators.json_adapt

    afl-fuzz -i corpus/seed_all -o out/${target}_experiment \
        -x corpus/dict/combined.dict -m none -t 200 -V 3600 -- \
        ./targets/json/$target
done
```

### 3-Way Comparison

Compare baseline vs. minimal mutator vs. full mutator:

```bash
export AFLBIN=$(which afl-fuzz)
export SEEDS=corpus/seed_all
export DICT=corpus/dict/combined.dict
export TGT=./targets/json/json_asan
export OUT_ROOT=out/3way_$(date +%y%m%d_%H%M%S)
export DUR=3600
export PY311_SP=$(python3 -c "import sys; print(':'.join(sys.path))")

./run_3way.sh

# Compare results
python3 compare_afl_stats.py $OUT_ROOT
```

### Continuous Fuzzing

Run overnight experiments:

```bash
# Run 8-hour experiment
nohup ./run_comparative_experiment.sh 28800 \
    > experiment_$(date +%Y%m%d).log 2>&1 &

# Monitor progress
tail -f experiment_*.log

# Check status
jobs
ps aux | grep afl-fuzz
```

### Adding Custom Operators

1. Edit `mutators/json_ops.py`:

```python
def op_my_custom_mutation(buf, add_buf, max_size, rng=None, **kw):
    """Your custom mutation logic."""
    try:
        data = json.loads(buf)
        # Modify data...
        result = json.dumps(data).encode('utf-8')
        return _clip(bytearray(result), max_size)
    except:
        return buf
```

2. Add to `OPS` list:

```python
OPS = [
    op_nop,
    op_flip_bool,
    # ... existing operators ...
    op_my_custom_mutation,  # Automatically gets next index
]
```

3. Operator is now available to scheduler!

---

## Troubleshooting

### AFL++ Not Found

```bash
# Install AFL++
cd ~ && git clone https://github.com/AFLplusplus/AFLplusplus.git
cd AFLplusplus && make distrib -j$(nproc)
export PATH="$HOME/AFLplusplus:$PATH"
```

### Python Import Errors

```bash
# Set PYTHONPATH
export PYTHONPATH="$PWD"

# Verify
python3 -c "from mutators.json_adapt import fuzz; print('OK')"
```

### Low Execution Speed

```bash
# Disable CPU frequency warnings
export AFL_SKIP_CPUFREQ=1

# Pin to cores
export AFL_NO_AFFINITY=1

# Use faster timeout
afl-fuzz ... -t 100 ...  # Down from 200ms
```

### LLM Seed Generation Fails

```bash
# Check config
cat ~/.config/ragfuzz/config.toml

# Verify API key
cat ~/.secrets/openai.key

# Test manually
python3 tools/rag_seedgen.py --bin ./targets/json/json_asan -n 5
```

**Note:** The experiment script automatically falls back to baseline seeds if LLM is unavailable.

---

## Contributing

Contributions welcome! Areas for improvement:

- [ ] Additional mutation operators
- [ ] Support for more file formats (XML, YAML, etc.)
- [ ] Better EMA scheduler tuning
- [ ] Integration with other LLM providers
- [ ] Parallel multi-core fuzzing
- [ ] Better crash deduplication

**To contribute:**
1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

---

## Citation

If you use RAGFuzz in your research, please cite:

```bibtex
@software{ragfuzz2025,
  title = {RAGFuzz: RAG-Guided AFL++ Fuzzing Framework},
  author = {RAGFuzz Contributors},
  year = {2025},
  url = {https://github.com/HyeonjongJang/ragfuzz}
}
```

---

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

---

## Acknowledgments

- **AFL++**: The best fuzzing tool out there ([AFLplusplus](https://github.com/AFLplusplus/AFLplusplus))
- **OpenAI**: For GPT-4 and API access
- **Anthropic**: For Claude and inspiring the name

---

## Support

- **Issues**: [GitHub Issues](https://github.com/HyeonjongJang/ragfuzz/issues)
- **Documentation**: See `docs/` directory
- **Email**: lezelamu@naver.com

---

**Ready to find bugs? Start here:**

```bash
./check_setup.sh
./run_comparative_experiment.sh 600
```

Happy fuzzing! 🐛🔍
