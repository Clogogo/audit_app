#!/usr/bin/env bash
# ── FinanceAudit startup script ──────────────────────────────────────────────
# Starts Ollama (if needed), pulls required models, then launches the app.

set -e
RESET='\033[0m'; BOLD='\033[1m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; CYAN='\033[0;36m'

info()    { echo -e "${CYAN}[INFO]${RESET}  $*"; }
success() { echo -e "${GREEN}[OK]${RESET}    $*"; }
warn()    { echo -e "${YELLOW}[WARN]${RESET}  $*"; }
error()   { echo -e "${RED}[ERROR]${RESET} $*"; }

echo -e "\n${BOLD}╔══════════════════════════════════════╗${RESET}"
echo -e "${BOLD}║       FinanceAudit — Starting up     ║${RESET}"
echo -e "${BOLD}╚══════════════════════════════════════╝${RESET}\n"

# ── 1. Check Ollama is installed ──────────────────────────────────────────────
if ! command -v ollama &>/dev/null; then
  warn "Ollama not found. AI features will use Gemini fallback (if configured)."
  warn "Install Ollama from https://ollama.com to enable local AI."
  echo ""
else
  # ── 2. Start Ollama server if not already running ────────────────────────
  if curl -sf http://localhost:11434/api/tags &>/dev/null; then
    success "Ollama is already running"
  else
    info "Starting Ollama server..."
    ollama serve &>/dev/null &
    OLLAMA_PID=$!

    # Wait up to 10 seconds for it to come up
    for i in {1..10}; do
      if curl -sf http://localhost:11434/api/tags &>/dev/null; then
        success "Ollama server started (PID $OLLAMA_PID)"
        break
      fi
      if [ $i -eq 10 ]; then
        warn "Ollama did not start in time — AI features may be unavailable"
      fi
      sleep 1
    done
  fi

  # ── 3. Ensure required models are available ────────────────────────────────
  # Vision model for image receipts
  VISION_MODEL="${OLLAMA_VISION_MODEL:-llama3.2-vision}"
  TEXT_MODEL="${OLLAMA_TEXT_MODEL:-llama3.2:1b}"

  check_or_pull() {
    local model="$1"
    local label="$2"
    if ollama list 2>/dev/null | grep -q "^${model}"; then
      success "$label model found: $model"
    else
      info "Pulling $label model: $model (this may take a while on first run)..."
      if ollama pull "$model"; then
        success "$label model ready"
      else
        warn "Could not pull $model — AI $label features may be limited"
      fi
    fi
  }

  check_or_pull "$VISION_MODEL" "Vision (receipt OCR)"
  check_or_pull "$TEXT_MODEL"   "Text (bank statement categorisation)"
  echo ""
fi

# ── 4. Launch the application ─────────────────────────────────────────────────
info "Starting FinanceAudit (frontend + API)..."
echo ""
exec npm start
