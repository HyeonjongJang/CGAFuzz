#!/usr/bin/env bash
# RAGFuzz Setup Verification Script
# Checks if all requirements are met for running experiments

set -euo pipefail

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

ERRORS=0
WARNINGS=0

check_pass() {
    echo -e "  ${GREEN}✓${NC} $1"
}

check_fail() {
    echo -e "  ${RED}✗${NC} $1"
    ((ERRORS++))
}

check_warn() {
    echo -e "  ${YELLOW}⚠${NC} $1"
    ((WARNINGS++))
}

echo ""
echo "╔════════════════════════════════════════════════════════════════╗"
echo "║           RAGFuzz Setup Verification                           ║"
echo "╚════════════════════════════════════════════════════════════════╝"
echo ""

# ============================================================================
# 1. System Tools
# ============================================================================
echo -e "${BLUE}[1/7] Checking system tools...${NC}"

if command -v python3 &> /dev/null; then
    PYVER=$(python3 --version | awk '{print $2}')
    check_pass "Python 3 found: $PYVER"
else
    check_fail "Python 3 not found"
fi

if command -v pip &> /dev/null || command -v pip3 &> /dev/null; then
    check_pass "pip found"
else
    check_fail "pip not found"
fi

if command -v git &> /dev/null; then
    check_pass "git found"
else
    check_warn "git not found (optional)"
fi

# ============================================================================
# 2. AFL++
# ============================================================================
echo ""
echo -e "${BLUE}[2/7] Checking AFL++...${NC}"

if command -v afl-fuzz &> /dev/null; then
    AFL_VER=$(afl-fuzz -h 2>&1 | head -1 || echo "unknown")
    check_pass "afl-fuzz found: $AFL_VER"

    # Check for Python support
    if afl-fuzz -h 2>&1 | grep -q -i python; then
        check_pass "AFL++ Python support detected"
    else
        check_warn "AFL++ Python support not detected"
    fi
else
    check_fail "afl-fuzz not found in PATH"
    echo ""
    echo "  Install AFL++:"
    echo "    cd ~"
    echo "    git clone https://github.com/AFLplusplus/AFLplusplus.git"
    echo "    cd AFLplusplus && make distrib -j\$(nproc)"
    echo "    export PATH=\"\$HOME/AFLplusplus:\$PATH\""
fi

if command -v afl-cmin &> /dev/null; then
    check_pass "afl-cmin found"
else
    check_warn "afl-cmin not found"
fi

# ============================================================================
# 3. Python Dependencies
# ============================================================================
echo ""
echo -e "${BLUE}[3/7] Checking Python dependencies...${NC}"

# Check if in virtual environment
if [ -n "${VIRTUAL_ENV:-}" ]; then
    check_pass "Virtual environment active: $VIRTUAL_ENV"
elif [ -n "${CONDA_DEFAULT_ENV:-}" ]; then
    check_pass "Conda environment active: $CONDA_DEFAULT_ENV"
else
    check_warn "No virtual environment detected (recommended)"
fi

# Check Python packages
if python3 -c "import openai" 2>/dev/null; then
    OPENAI_VER=$(python3 -c "import openai; print(openai.__version__)" 2>/dev/null || echo "unknown")
    check_pass "openai package found: $OPENAI_VER"
else
    check_warn "openai package not found (needed for LLM seed generation)"
fi

if python3 -c "import tomli" 2>/dev/null || python3 -c "import tomllib" 2>/dev/null; then
    check_pass "TOML parser found"
else
    check_warn "tomli/tomllib not found (needed for LLM config)"
fi

if python3 -c "import tomlkit" 2>/dev/null; then
    check_pass "tomlkit found"
else
    check_warn "tomlkit not found (optional)"
fi

# ============================================================================
# 4. RAGFuzz Components
# ============================================================================
echo ""
echo -e "${BLUE}[4/7] Checking RAGFuzz components...${NC}"

# Check PYTHONPATH
if [ -n "${PYTHONPATH:-}" ] && echo "$PYTHONPATH" | grep -q "$PWD"; then
    check_pass "PYTHONPATH includes current directory"
else
    check_warn "PYTHONPATH not set (run: export PYTHONPATH=\"\$PWD\")"
fi

# Check mutators
if [ -f "mutators/json_adapt.py" ]; then
    check_pass "Main mutator found: mutators/json_adapt.py"

    # Try importing
    if PYTHONPATH="$PWD" python3 -c "from mutators.json_adapt import fuzz" 2>/dev/null; then
        check_pass "Mutator import successful"
    else
        check_fail "Mutator import failed"
    fi
else
    check_fail "Main mutator not found: mutators/json_adapt.py"
fi

if [ -f "mutators/json_ops.py" ]; then
    check_pass "Operators found: mutators/json_ops.py"
else
    check_fail "Operators not found: mutators/json_ops.py"
fi

if [ -f "tools/rag_seedgen.py" ]; then
    check_pass "LLM seed generator found"
else
    check_warn "LLM seed generator not found: tools/rag_seedgen.py"
fi

# ============================================================================
# 5. Target Binaries
# ============================================================================
echo ""
echo -e "${BLUE}[5/7] Checking target binaries...${NC}"

if [ -x "targets/json/json_asan" ]; then
    check_pass "Target binary found: targets/json/json_asan"

    # Test execution
    if echo '{}' | timeout 3 ./targets/json/json_asan &>/dev/null; then
        check_pass "Target binary executes correctly"
    else
        check_fail "Target binary execution failed"
    fi
else
    check_fail "Target binary not found or not executable: targets/json/json_asan"
fi

# Check other targets
for target in jsonc_asan yajl_asan rapidjson_asan; do
    if [ -x "targets/json/$target" ]; then
        check_pass "Additional target found: $target"
    fi
done

# ============================================================================
# 6. Corpus and Seeds
# ============================================================================
echo ""
echo -e "${BLUE}[6/7] Checking corpus and seeds...${NC}"

if [ -d "corpus/json_seeds" ]; then
    SEED_COUNT=$(ls -1 corpus/json_seeds/*.json 2>/dev/null | wc -l || echo 0)
    if [ "$SEED_COUNT" -gt 0 ]; then
        check_pass "Baseline seeds found: $SEED_COUNT files"
    else
        check_fail "No baseline seeds found in corpus/json_seeds/"
    fi
else
    check_fail "Baseline seeds directory not found: corpus/json_seeds/"
fi

if [ -d "corpus/seed_all" ]; then
    SEED_ALL_COUNT=$(ls -1 corpus/seed_all/*.json 2>/dev/null | wc -l || echo 0)
    check_pass "Merged seeds directory exists: $SEED_ALL_COUNT files"
else
    check_warn "Merged seeds directory not found: corpus/seed_all/"
fi

if [ -f "corpus/dict/json.dict" ]; then
    DICT_LINES=$(wc -l < corpus/dict/json.dict)
    check_pass "Baseline dictionary found: $DICT_LINES entries"
else
    check_fail "Baseline dictionary not found: corpus/dict/json.dict"
fi

if [ -f "corpus/dict/combined.dict" ]; then
    COMBINED_LINES=$(wc -l < corpus/dict/combined.dict)
    check_pass "Combined dictionary found: $COMBINED_LINES entries"
else
    check_warn "Combined dictionary not found (will be generated)"
fi

# ============================================================================
# 7. LLM Configuration (Optional)
# ============================================================================
echo ""
echo -e "${BLUE}[7/7] Checking LLM configuration (optional)...${NC}"

if [ -f ~/.config/ragfuzz/config.toml ]; then
    check_pass "LLM config file found"

    # Check API key
    if grep -q "api_key_file" ~/.config/ragfuzz/config.toml; then
        KEY_FILE=$(grep "api_key_file" ~/.config/ragfuzz/config.toml | cut -d'"' -f2)
        KEY_FILE="${KEY_FILE/#\~/$HOME}"

        if [ -f "$KEY_FILE" ]; then
            check_pass "API key file exists: $KEY_FILE"
        else
            check_warn "API key file not found: $KEY_FILE"
        fi
    else
        check_warn "api_key_file not specified in config"
    fi
else
    check_warn "LLM config not found: ~/.config/ragfuzz/config.toml"
    echo ""
    echo "  To enable LLM seed generation:"
    echo "    mkdir -p ~/.secrets ~/.config/ragfuzz"
    echo "    echo 'sk-YOUR_KEY' > ~/.secrets/openai.key"
    echo "    chmod 600 ~/.secrets/openai.key"
    echo ""
    echo "    cat > ~/.config/ragfuzz/config.toml <<'EOF'"
    echo "    [llm]"
    echo "    provider = \"openai\""
    echo "    model = \"gpt-4o-mini\""
    echo "    temperature = 1.1"
    echo "    api_key_file = \"\$HOME/.secrets/openai.key\""
    echo "    EOF"
fi

# ============================================================================
# Summary
# ============================================================================
echo ""
echo "╔════════════════════════════════════════════════════════════════╗"
echo "║                      Verification Summary                      ║"
echo "╚════════════════════════════════════════════════════════════════╝"
echo ""

if [ $ERRORS -eq 0 ] && [ $WARNINGS -eq 0 ]; then
    echo -e "${GREEN}✓ All checks passed!${NC}"
    echo ""
    echo "You're ready to run experiments:"
    echo "  ./run_comparative_experiment.sh 600"
    exit 0
elif [ $ERRORS -eq 0 ]; then
    echo -e "${YELLOW}⚠ Setup complete with $WARNINGS warning(s)${NC}"
    echo ""
    echo "You can run basic experiments, but some features may be unavailable."
    echo "Review warnings above for optional improvements."
    echo ""
    echo "To run experiments:"
    echo "  ./run_comparative_experiment.sh 600"
    exit 0
else
    echo -e "${RED}✗ Setup incomplete: $ERRORS error(s), $WARNINGS warning(s)${NC}"
    echo ""
    echo "Please fix the errors above before running experiments."
    echo "See EXPERIMENT_SETUP.md for detailed setup instructions."
    exit 1
fi
