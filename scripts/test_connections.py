"""VvC v7.0 — Connection Test Script."""
import warnings
warnings.filterwarnings("ignore")
import sys
sys.path.insert(0, ".")
from pathlib import Path

print("=" * 50)
print("VvC v7.0 — Connection Test Summary")
print("=" * 50)

# 1. Config
from core.config import cfg
print(f"\n[Config]")
print(f"  Backend:    {cfg.backend}")
print(f"  Fallback:   {cfg.fallback}")

# 2. CLI paths
gemini_ok = Path(cfg.gemini_cmd).exists() if cfg.gemini_cmd else False
copilot_ok = Path(cfg.copilot_cmd).exists() if cfg.copilot_cmd else False
print(f"\n[CLI Binaries]")
print(f"  Gemini CLI:  {'FOUND' if gemini_ok else 'MISSING'}")
print(f"  Copilot CLI: {'FOUND' if copilot_ok else 'MISSING'}")

# 3. Gateway
from core.llm import _call_gateway
gw = _call_gateway("Say hello in one word")
status = f"OK ({len(gw)} chars)" if gw else "UNREACHABLE"
print(f"\n[Tier 1 — AI Gateway]")
print(f"  URL:    {cfg.gateway_url}")
print(f"  Model:  {cfg.gateway_proxy_model}")
print(f"  Status: {status}")

# 4. Gemini API
from core.llm import _call_gemini_api
api = _call_gemini_api("Say hello in one word", model="gemini-3-flash-preview")
status = f"OK ({len(api)} chars)" if api else "API ERROR"
print(f"\n[Tier 3 — Gemini REST API]")
print(f"  Vision Model: {cfg.gemini_vision_model}")
print(f"  Status: {status}")

# 5. Integrated
from core.llm import call_llm
r = call_llm("Explain gravity in one sentence.")
status = f"OK ({len(r)} chars)" if r else "FAILED"
print(f"\n[Integrated call_llm]")
print(f"  Status: {status}")

print(f"\n{'=' * 50}")
print("Note: Copilot CLI needs re-authentication (run: copilot /login)")
