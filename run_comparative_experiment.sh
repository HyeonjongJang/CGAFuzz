#!/usr/bin/env bash
# RAGFuzz Comparative Experiment Runner
# Runs AFL++ baseline vs LLM-enhanced RAGFuzz side-by-side
# Usage: ./run_comparative_experiment.sh [duration_seconds]

set -euo pipefail

BASELINE_PID=""; LLM_PID="";
# ============================================================================
# CONFIGURATION
# ============================================================================

# Experiment parameters
DURATION="${1:-600}"  # Default: 10 minutes (600 seconds)
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
OUT_ROOT="out/comparative_${TIMESTAMP}"

# Target configuration
TARGET="./targets/json/json_asan"
BASELINE_SEEDS="corpus/json_seeds"
LLM_SEEDS="corpus/seed_all"
BASELINE_DICT="corpus/dict/json.dict"
LLM_DICT="corpus/dict/combined.dict"

# CPU affinity (adjust based on your system)
CPU_BASELINE=0
CPU_LLM=1

# AFL++ options
AFL_COMMON_OPTS="-m none -t 200"
export AFL_SKIP_CPUFREQ=1
export AFL_NO_AFFINITY=1
export AFL_I_DONT_CARE_ABOUT_MISSING_CRASHES=1

# 모듈 선택 훅 (없으면 기본값 사용)
PYMOD_LLM="${AFL_PYTHON_MODULE_LLM:-mutators.json_adapt}"
# 베이스라인은 기본적으로 파이썬 변이기 없이 돌리되, 필요 시 외부에서 지정 가능
PYMOD_BASE="${AFL_PYTHON_MODULE_BASE:-}"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

log_info() {
    echo -e "${BLUE}[INFO]${NC} $*"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $*"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $*"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $*"
}

check_requirements() {
    log_info "Checking requirements..."

    # Check AFL++
    if ! command -v afl-fuzz &> /dev/null; then
        log_error "AFL++ not found in PATH"
        log_info "Please install AFL++:"
        echo "  cd ~"
        echo "  git clone https://github.com/AFLplusplus/AFLplusplus.git"
        echo "  cd AFLplusplus"
        echo "  make distrib -j\$(nproc)"
        echo "  export PATH=\"\$HOME/AFLplusplus:\$PATH\""
        exit 1
    fi

    # Check Python
    if ! command -v python3 &> /dev/null; then
        log_error "Python 3 not found"
        exit 1
    fi

    # Check target binary
    if [ ! -x "$TARGET" ]; then
        log_error "Target binary not found or not executable: $TARGET"
        exit 1
    fi

    # Check seeds
    if [ ! -d "$BASELINE_SEEDS" ]; then
        log_error "Baseline seeds not found: $BASELINE_SEEDS"
        exit 1
    fi

    log_success "All requirements met"
}

smoke_test() {
    log_info "Running smoke test on target..."
    if echo '{}' | timeout 3 "$TARGET" &>/dev/null; then
        log_success "Target smoke test passed"
    else
        log_error "Target smoke test failed"
        exit 1
    fi
}

setup_llm_seeds() {
    log_info "Setting up LLM-enhanced corpus..."

    # Check if LLM seeds already exist
    if [ -d "$LLM_SEEDS" ] && [ "$(ls -A $LLM_SEEDS 2>/dev/null | wc -l)" -gt 10 ]; then
        log_success "LLM seeds already exist ($(ls -1 $LLM_SEEDS | wc -l) files)"
        return 0
    fi

    # Check if LLM config exists
    if [ ! -f ~/.config/ragfuzz/config.toml ]; then
        log_warn "LLM config not found - will use existing seeds only"
        log_info "To enable LLM seed generation, create config:"
        echo ""
        echo "  mkdir -p ~/.secrets ~/.config/ragfuzz"
        echo "  echo 'sk-YOUR_KEY' > ~/.secrets/openai.key"
        echo "  chmod 600 ~/.secrets/openai.key"
        echo ""
        echo "  cat > ~/.config/ragfuzz/config.toml <<'EOF'"
        echo "  [llm]"
        echo "  provider = \"openai\""
        echo "  model = \"gpt-4o-mini\""
        echo "  temperature = 1.1"
        echo "  api_key_file = \"\$HOME/.secrets/openai.key\""
        echo "  EOF"
        echo ""

        # Use baseline seeds as fallback
        mkdir -p "$LLM_SEEDS"
        rsync -a "$BASELINE_SEEDS/" "$LLM_SEEDS/" 2>/dev/null || true
        return 0
    fi

    # Generate LLM seeds
    log_info "Generating LLM seeds (this may take a minute)..."
    export PYTHONPATH="$PWD"

    if python3 tools/rag_seedgen.py \
        --bin "$TARGET" \
        --config ~/.config/ragfuzz/config.toml \
        -n 50 2>&1 | tee /tmp/rag_seedgen.log; then

        # Merge seeds
        mkdir -p "$LLM_SEEDS"
        rsync -a "$BASELINE_SEEDS/" "$LLM_SEEDS/"
        rsync -a corpus/generated/ "$LLM_SEEDS/" 2>/dev/null || true

        # Merge dictionaries
        if [ -f corpus/dict/auto.dict ]; then
            cat corpus/dict/json.dict corpus/dict/auto.dict 2>/dev/null | \
                sort -u > "$LLM_DICT"
            log_success "Generated LLM seeds and merged dictionaries"
        fi
    else
        log_warn "LLM seed generation failed - using baseline seeds"
        mkdir -p "$LLM_SEEDS"
        rsync -a "$BASELINE_SEEDS/" "$LLM_SEEDS/"
    fi
}

run_baseline() {
    local outdir="$OUT_ROOT/baseline"
    mkdir -p "$outdir"

    log_info "Starting AFL++ BASELINE (no custom mutator)..."
    log_info "  Output: $outdir"
    log_info "  Seeds: $BASELINE_SEEDS ($(ls -1 $BASELINE_SEEDS | wc -l) files)"
    log_info "  Dict: $BASELINE_DICT"
    log_info "  CPU: $CPU_BASELINE"
    log_info "  Duration: ${DURATION}s"

    # 외부 timeout 제거, 내부 -V만 사용
    # 기본은 파이썬 변이기 없음; 필요 시 AFL_PYTHON_MODULE_BASE로 주입 가능
    if [ -n "$PYMOD_BASE" ]; then
      taskset -c $CPU_BASELINE \
      env AFL_PYTHON_MODULE="$PYMOD_BASE" \
      afl-fuzz \
          -i "$BASELINE_SEEDS" \
          -o "$outdir" \
          -x "$BASELINE_DICT" \
          $AFL_COMMON_OPTS \
          -V $DURATION \
          -- "$TARGET" \
          >"$outdir/afl.log" 2>&1 &
    else
      taskset -c $CPU_BASELINE \
      env -u AFL_PYTHON_MODULE \
      afl-fuzz \
          -i "$BASELINE_SEEDS" \
          -o "$outdir" \
          -x "$BASELINE_DICT" \
          $AFL_COMMON_OPTS \
          -V $DURATION \
          -- "$TARGET" \
          >"$outdir/afl.log" 2>&1 &
    fi

    BASELINE_PID=$!
    log_success "Baseline fuzzer started (PID: $BASELINE_PID, CPU: $CPU_BASELINE)"
}

run_llm_enhanced() {
    local outdir="$OUT_ROOT/llm_enhanced"
    mkdir -p "$outdir"

    log_info "Starting AFL++ + LLM-ENHANCED (adaptive mutator)..."
    log_info "  Output: $outdir"
    log_info "  Seeds: $LLM_SEEDS ($(ls -1 $LLM_SEEDS 2>/dev/null | wc -l) files)"
    log_info "  Dict: $LLM_DICT"
    log_info "  CPU: $CPU_LLM"
    log_info "  Duration: ${DURATION}s"

    # 파이썬 임베딩 안전성 보강: PYTHONMALLOC=malloc 권장
    # 외부 timeout 제거, 내부 -V만 사용
    taskset -c $CPU_LLM \
    env PYTHONPATH="$PWD" \
        PYTHONMALLOC="${PYTHONMALLOC:-malloc}" \
        AFL_PYTHON_MODULE="$PYMOD_LLM" \
        AFL_CUSTOM_MUTATOR_ONLY=1 \
        AFL_DISABLE_TRIM=1 \
    afl-fuzz \
        -i "$LLM_SEEDS" \
        -o "$outdir" \
        -x "$LLM_DICT" \
        $AFL_COMMON_OPTS \
        -V $DURATION \
        -- "$TARGET" \
        >"$outdir/afl.log" 2>&1 &

    LLM_PID=$!
    log_success "LLM-enhanced fuzzer started (PID: $LLM_PID, CPU: $CPU_LLM)"
}

monitor_progress() {
    log_info "Monitoring fuzzing progress (Ctrl+C to stop early)..."
    log_info "Experiment will run for ${DURATION} seconds (~$((DURATION/60)) minutes)"
    echo ""

    local start_time=$(date +%s)
    local last_check=0

    while kill -0 $BASELINE_PID 2>/dev/null || kill -0 $LLM_PID 2>/dev/null; do
        sleep 10

        local current_time=$(date +%s)
        local elapsed=$((current_time - start_time))

        # Show progress every 30 seconds
        if [ $((elapsed - last_check)) -ge 30 ]; then
            echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
            echo -e "${BLUE}Progress: ${elapsed}s / ${DURATION}s${NC}"

            # Show baseline stats
            if [ -f "$OUT_ROOT/baseline/default/fuzzer_stats" ]; then
                local b_paths=$(grep "paths_total" "$OUT_ROOT/baseline/default/fuzzer_stats" | awk '{print $3}')
                local b_execs=$(grep "execs_per_sec" "$OUT_ROOT/baseline/default/fuzzer_stats" | awk '{print $3}')
                echo -e "  ${GREEN}Baseline:${NC} paths=$b_paths, exec/s=$b_execs"
            fi

            # Show LLM stats
            if [ -f "$OUT_ROOT/llm_enhanced/default/fuzzer_stats" ]; then
                local l_paths=$(grep "paths_total" "$OUT_ROOT/llm_enhanced/default/fuzzer_stats" | awk '{print $3}')
                local l_execs=$(grep "execs_per_sec" "$OUT_ROOT/llm_enhanced/default/fuzzer_stats" | awk '{print $3}')
                echo -e "  ${YELLOW}LLM-Enhanced:${NC} paths=$l_paths, exec/s=$l_execs"
            fi

            last_check=$elapsed
        fi
    done

    log_success "Fuzzing completed!"
}

generate_comparison() {
    log_info "Generating comparison report..."

    # Use the existing comparison script
    if [ -f compare_afl_stats.py ]; then
        python3 compare_afl_stats.py "$OUT_ROOT" | tee "$OUT_ROOT/comparison.txt"
    else
        log_warn "compare_afl_stats.py not found, generating simple report..."

        echo "COMPARATIVE EXPERIMENT RESULTS" > "$OUT_ROOT/comparison.txt"
        echo "=============================" >> "$OUT_ROOT/comparison.txt"
        echo "" >> "$OUT_ROOT/comparison.txt"

        for variant in baseline llm_enhanced; do
            if [ -f "$OUT_ROOT/$variant/default/fuzzer_stats" ]; then
                echo "=== $variant ===" >> "$OUT_ROOT/comparison.txt"
                grep -E "(paths_total|bitmap_cvg|execs_per_sec|unique_crashes|execs_done)" \
                    "$OUT_ROOT/$variant/default/fuzzer_stats" >> "$OUT_ROOT/comparison.txt"
                echo "" >> "$OUT_ROOT/comparison.txt"
            fi
        done

        cat "$OUT_ROOT/comparison.txt"
    fi

    # Generate summary
    cat > "$OUT_ROOT/README.md" <<EOF
# RAGFuzz Comparative Experiment Results

**Timestamp:** $TIMESTAMP
**Duration:** ${DURATION} seconds (~$((DURATION/60)) minutes)
**Target:** $TARGET

## Experiment Setup

### Baseline (AFL++ only)
- **Seeds:** $BASELINE_SEEDS
- **Dictionary:** $BASELINE_DICT
- **Mutator:** AFL++ default mutators (no custom Python mutator)
- **Output:** $OUT_ROOT/baseline

### LLM-Enhanced (RAGFuzz)
- **Seeds:** $LLM_SEEDS (includes LLM-generated seeds)
- **Dictionary:** $LLM_DICT (includes LLM-extracted tokens)
- **Mutator:** Adaptive EMA-based mutator with curriculum learning
- **Output:** $OUT_ROOT/llm_enhanced

## Key Metrics

Compare the following metrics between baseline and LLM-enhanced:

1. **paths_total** - Total unique execution paths discovered
2. **bitmap_cvg** - Code coverage percentage
3. **execs_per_sec** - Fuzzing throughput
4. **unique_crashes** - Unique crashes found

## Results

See \`comparison.txt\` or \`comparison.csv\` for detailed comparison.

## Analysis

To analyze crashes:
\`\`\`bash
# List crashes
ls -la $OUT_ROOT/*/default/crashes/

# Triage crashes (requires target binary)
python3 tools/triage.py $TARGET $OUT_ROOT/baseline/default/crashes/
python3 tools/triage.py $TARGET $OUT_ROOT/llm_enhanced/default/crashes/
\`\`\`

To visualize results (if matplotlib installed):
\`\`\`bash
python3 tools/eval.py --out $OUT_ROOT/baseline --save $OUT_ROOT/baseline_stats.csv --png $OUT_ROOT/baseline.png
python3 tools/eval.py --out $OUT_ROOT/llm_enhanced --save $OUT_ROOT/llm_stats.csv --png $OUT_ROOT/llm.png
\`\`\`
EOF

    log_success "Comparison report saved to: $OUT_ROOT/README.md"
    log_success "Detailed stats saved to: $OUT_ROOT/comparison.txt"
}

cleanup() {
    log_info "Cleaning up..."

    # Kill any remaining processes
    kill $BASELINE_PID 2>/dev/null || true
    kill $LLM_PID 2>/dev/null || true

    # Wait for processes to exit
    wait $BASELINE_PID 2>/dev/null || true
    wait $LLM_PID 2>/dev/null || true

    log_info "Cleanup complete"
}

# ============================================================================
# MAIN EXECUTION
# ============================================================================

trap cleanup EXIT INT TERM

main() {
    echo ""
    echo "╔════════════════════════════════════════════════════════════════╗"
    echo "║         RAGFuzz Comparative Experiment Runner                  ║"
    echo "║  AFL++ Baseline vs LLM-Enhanced Adaptive Fuzzing               ║"
    echo "╚════════════════════════════════════════════════════════════════╝"
    echo ""

    check_requirements
    smoke_test
    setup_llm_seeds

    log_info "Starting comparative experiment..."
    log_info "Output directory: $OUT_ROOT"
    echo ""

    # Start both fuzzers
    run_baseline
    sleep 2  # Give baseline a head start
    run_llm_enhanced

    echo ""

    # Monitor until completion
    monitor_progress

    # Generate comparison
    echo ""
    generate_comparison

    echo ""
    log_success "Experiment complete! Results in: $OUT_ROOT"
    log_info "Review the comparison with: cat $OUT_ROOT/README.md"
}

main "$@"
