# RAGFuzz Comparative Experiment Setup Guide

This guide will help you set up and run comparative experiments between AFL++ baseline and LLM-enhanced RAGFuzz.

## 📋 Table of Contents

1. [Prerequisites](#prerequisites)
2. [Environment Setup](#environment-setup)
3. [Running Experiments](#running-experiments)
4. [Analyzing Results](#analyzing-results)
5. [Troubleshooting](#troubleshooting)

---

## 🔧 Prerequisites

### System Requirements

- **OS:** Ubuntu 22.04 / WSL2 (recommended)
- **CPU:** Multi-core (at least 2 cores for parallel experiments)
- **RAM:** 4GB+ recommended
- **Python:** 3.8+ (3.11+ recommended)

### Required Tools

```bash
# Update system packages
sudo apt-get update
sudo apt-get install -y git build-essential clang lld cmake \
    python3-pip python3-venv jq rsync pkg-config
```

---

## 🚀 Environment Setup

### Step 1: Install AFL++

AFL++ is **required** but currently not installed. Follow these steps:

```bash
# Clone AFL++
cd ~
git clone https://github.com/AFLplusplus/AFLplusplus.git
cd AFLplusplus

# Build AFL++ with Python support
make distrib -j$(nproc)

# Add to PATH (permanent)
echo 'export PATH="$HOME/AFLplusplus:$PATH"' >> ~/.bashrc
source ~/.bashrc

# Verify installation
which afl-fuzz
afl-fuzz -h
```

**Important:** Ensure AFL++ is built with Python 3.12 support (matches your current Python version).

### Step 2: Set Up Python Environment

```bash
cd ~/ragfuzz/ragfuzz-main

# Option A: Using venv (recommended)
python3 -m venv ~/.venvs/ragfuzz
source ~/.venvs/ragfuzz/bin/activate

# Option B: Using conda
conda create -n ragfuzz python=3.12 -y
conda activate ragfuzz

# Install Python dependencies
pip install -r requirements.txt
```

### Step 3: Configure LLM (Optional but Recommended)

To enable LLM-enhanced seed generation:

```bash
# Create directories
mkdir -p ~/.secrets ~/.config/ragfuzz

# Add your OpenAI API key
echo "sk-YOUR_ACTUAL_KEY_HERE" > ~/.secrets/openai.key
chmod 600 ~/.secrets/openai.key

# Create configuration file
cat > ~/.config/ragfuzz/config.toml <<'EOF'
[llm]
provider = "openai"
model = "gpt-4o-mini"
temperature = 1.1
api_key_file = "$HOME/.secrets/openai.key"
EOF
```

**Note:** Replace `sk-YOUR_ACTUAL_KEY_HERE` with your actual OpenAI API key.

If you don't have an OpenAI key, the experiment will still run but without LLM-generated seeds.

### Step 4: Verify Setup

```bash
# Set PYTHONPATH
export PYTHONPATH="$PWD"

# Test Python mutator import
python3 -c "from mutators.json_adapt import fuzz; print('Mutator OK')"

# Test target binary
echo '{}' | ./targets/json/json_asan && echo "Target OK"

# Quick 10-second smoke test
export AFL_PYTHON_MODULE=mutators.json_adapt
timeout 10 afl-fuzz -i corpus/json_seeds -o out/smoke_test \
    -x corpus/dict/json.dict -m none -t 200 -- ./targets/json/json_asan
```

---

## 🧪 Running Experiments

### Quick Start (10 minutes)

```bash
cd ~/ragfuzz/ragfuzz-main

# Run comparative experiment for 10 minutes (600 seconds)
./run_comparative_experiment.sh 600
```

### Recommended Durations

- **Quick test:** 600 seconds (10 minutes)
- **Standard:** 3600 seconds (1 hour)
- **Thorough:** 21600 seconds (6 hours)
- **Research-grade:** 86400 seconds (24 hours)

### What the Experiment Does

The script automatically:

1. ✅ **Checks prerequisites** (AFL++, Python, target binary)
2. ✅ **Generates LLM seeds** (if configured) or uses baseline seeds
3. ✅ **Runs two parallel fuzzers:**
   - **Baseline:** Pure AFL++ (no custom mutator)
   - **LLM-Enhanced:** AFL++ + adaptive mutator + LLM seeds
4. ✅ **Monitors progress** in real-time
5. ✅ **Generates comparison report** with statistics

### Manual Experiment Setup

If you prefer manual control:

#### Terminal 1: Baseline (AFL++ only)
```bash
export PYTHONPATH="$PWD"
export AFL_SKIP_CPUFREQ=1

# Pure AFL++ baseline
unset AFL_PYTHON_MODULE
afl-fuzz -i corpus/json_seeds -o out/manual_baseline \
    -x corpus/dict/json.dict -m none -t 200 -V 600 -- \
    ./targets/json/json_asan
```

#### Terminal 2: LLM-Enhanced
```bash
export PYTHONPATH="$PWD"
export AFL_PYTHON_MODULE=mutators.json_adapt
export AFL_SKIP_CPUFREQ=1

# LLM-enhanced fuzzing
afl-fuzz -i corpus/seed_all -o out/manual_llm \
    -x corpus/dict/combined.dict -m none -t 200 -V 600 -- \
    ./targets/json/json_asan
```

---

## 📊 Analyzing Results

### View Comparison Report

```bash
# After experiment completes
cd ~/ragfuzz/ragfuzz-main

# View results
cat out/comparative_*/README.md
cat out/comparative_*/comparison.txt
```

### Key Metrics to Compare

| Metric | Description | Higher is Better? |
|--------|-------------|-------------------|
| `paths_total` | Unique execution paths discovered | ✅ Yes |
| `bitmap_cvg` | Code coverage percentage | ✅ Yes |
| `execs_per_sec` | Fuzzing throughput | ✅ Yes |
| `unique_crashes` | Unique crashes found | Depends on goal |
| `execs_done` | Total executions performed | Neutral |

### Generate Visualizations (Optional)

If you installed matplotlib:

```bash
pip install matplotlib

# Generate graphs
python3 tools/eval.py --out out/comparative_*/baseline \
    --save out/baseline_stats.csv --png out/baseline.png

python3 tools/eval.py --out out/comparative_*/llm_enhanced \
    --save out/llm_stats.csv --png out/llm.png
```

### Triage Crashes

```bash
# Compare crash directories
ls -la out/comparative_*/baseline/default/crashes/
ls -la out/comparative_*/llm_enhanced/default/crashes/

# Deduplicate and cluster crashes
python3 tools/triage.py ./targets/json/json_asan \
    out/comparative_*/baseline/default/crashes/

python3 tools/triage.py ./targets/json/json_asan \
    out/comparative_*/llm_enhanced/default/crashes/
```

### Use Existing Comparison Script

```bash
# Compare 3-way experiments (if using run_3way.sh)
python3 compare_afl_stats.py out/3way_*/
```

---

## 🔍 Troubleshooting

### Issue: AFL++ not found

**Error:** `afl-fuzz: command not found`

**Solution:**
```bash
# Check if AFL++ is installed
ls ~/AFLplusplus/afl-fuzz

# Add to PATH
export PATH="$HOME/AFLplusplus:$PATH"

# Make permanent
echo 'export PATH="$HOME/AFLplusplus:$PATH"' >> ~/.bashrc
source ~/.bashrc
```

### Issue: Python mutator import fails

**Error:** `ModuleNotFoundError: No module named 'mutators'`

**Solution:**
```bash
# Always set PYTHONPATH before running
export PYTHONPATH="$PWD"

# Verify it's set
echo $PYTHONPATH

# Test import
python3 -c "from mutators.json_adapt import fuzz"
```

### Issue: AFL++ Python version mismatch

**Error:** `Python version mismatch between AFL++ and mutator`

**Solution:**
```bash
# Rebuild AFL++ with current Python version
cd ~/AFLplusplus
make clean
make distrib -j$(nproc)

# Verify Python version matches
python3 --version
afl-fuzz -h | grep -i python
```

### Issue: LLM seed generation fails

**Error:** `openai.AuthenticationError` or connection errors

**Solution:**
```bash
# Check API key
cat ~/.secrets/openai.key

# Verify config
cat ~/.config/ragfuzz/config.toml

# Test API manually
python3 -c "
from openai import OpenAI
import pathlib
key = pathlib.Path('~/.secrets/openai.key').expanduser().read_text().strip()
client = OpenAI(api_key=key)
print('API key valid:', key[:10] + '...')
"

# Run without LLM (fallback)
# The experiment script will automatically use baseline seeds if LLM fails
```

### Issue: Target binary crashes immediately

**Error:** Target exits with signal 11 (SEGFAULT)

**Solution:**
```bash
# Test target manually
echo '{}' | ./targets/json/json_asan
echo $?  # Should return 0

# Check ASAN is working
echo 'invalid' | ./targets/json/json_asan

# Rebuild target if needed
cd targets/json
clang -O2 -g -fsanitize=address -fno-omit-frame-pointer \
    -o json_asan harness.c $(pkg-config --cflags --libs jansson)
```

### Issue: Low execution speed

**Problem:** `execs_per_sec` is very low (<100)

**Solutions:**
```bash
# 1. Disable CPU frequency scaling warnings
export AFL_SKIP_CPUFREQ=1

# 2. Use faster timeout
afl-fuzz ... -t 100 ...  # Reduce from 200ms to 100ms

# 3. Pin to specific CPU cores
taskset -c 0 afl-fuzz ...

# 4. Check if running in VM (slower performance expected)
```

---

## 📈 Expected Results

### Typical Outcomes

**Baseline (AFL++ only):**
- Paths: 500-2000 (depends on duration)
- Coverage: 30-50%
- Exec/sec: 500-2000

**LLM-Enhanced (RAGFuzz):**
- Paths: 800-3000 (20-50% more than baseline)
- Coverage: 40-60% (5-15% higher than baseline)
- Exec/sec: 400-1800 (slightly slower due to custom mutator)

**Note:** Results vary based on:
- Experiment duration
- Target complexity
- LLM seed quality
- System performance

---

## 🎯 Next Steps

### After Running Experiments

1. **Compare metrics** - Which approach found more paths/crashes?
2. **Analyze coverage** - Did LLM seeds cover new code areas?
3. **Examine crashes** - Are LLM-discovered crashes unique?
4. **Tune parameters** - Adjust EMA scheduler, curriculum thresholds
5. **Scale up** - Run longer experiments (6-24 hours)

### Advanced Experiments

```bash
# 3-way comparison (baseline vs mini vs full)
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

### Different Targets

Test against different JSON parsers:

```bash
# json-c
./run_comparative_experiment.sh 600 ./targets/json/jsonc_asan

# YAJL
./run_comparative_experiment.sh 600 ./targets/json/yajl_asan

# RapidJSON
./run_comparative_experiment.sh 600 ./targets/json/rapidjson_asan
```

---

## 📚 Additional Resources

- **AFL++ Docs:** https://github.com/AFLplusplus/AFLplusplus/blob/stable/docs/
- **CLAUDE.md:** Project-specific implementation details
- **README.md:** Korean fuzzing execution guide

---

## ✅ Checklist

Before running experiments, ensure:

- [ ] AFL++ installed and in PATH
- [ ] Python 3.8+ with dependencies installed
- [ ] PYTHONPATH exported (`export PYTHONPATH="$PWD"`)
- [ ] Target binary tested (`echo '{}' | ./targets/json/json_asan`)
- [ ] Seeds exist (`ls corpus/json_seeds/`)
- [ ] (Optional) LLM config created (`~/.config/ragfuzz/config.toml`)
- [ ] Experiment script executable (`chmod +x run_comparative_experiment.sh`)

---

**Ready to run?**

```bash
./run_comparative_experiment.sh 600
```

Good luck with your experiments! 🚀
