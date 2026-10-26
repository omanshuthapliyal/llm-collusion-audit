"""
Causal audit of LLM price collusion (new work, Apart AI Collusion Sprint, 23-25 Oct 2026).

Builds on the pre-existing starter repo ``starter/algorithmic-pricing-llms`` (Fish-style
Calvano duopoly by Peist, Romero & Sauer), which is imported unchanged. Everything in
``probe/`` is new sprint code.
"""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STARTER = ROOT / "starter" / "algorithmic-pricing-llms"
RESULTS = ROOT / "results"
LOGS = ROOT / "logs"

# Make the pre-existing starter code importable as ``src.*`` (as its own scripts do).
if str(STARTER) not in sys.path:
    sys.path.insert(0, str(STARTER))

# Zscaler on OT's network: use the combined system + Zscaler bundle for every HTTPS call.
_bundle = ROOT / ".certs" / "ca-bundle.pem"
if _bundle.exists():
    os.environ["SSL_CERT_FILE"] = str(_bundle)
