#!/usr/bin/env python3
"""claude-stats — aggregate Claude token usage across local + remote machines"""

import glob, json, os, subprocess
from collections import defaultdict
from datetime import datetime
from pathlib import Path


# ── Config ────────────────────────────────────────────────────────────────────

def _load_env():
    env = Path(__file__).parent / ".env"
    if not env.exists():
        return
    for line in env.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

_load_env()

PROJECTS    = Path(os.environ.get("CLAUDE_PROJECTS", "~/.claude/projects")).expanduser()
SSH_SOURCES = [s.strip() for s in os.environ.get("SSH_SOURCES", "").split(",") if s.strip()]
USE_LOCAL   = os.environ.get("LOCAL", "true").lower() not in ("false", "0", "no")
SSH_CCUSAGE = os.environ.get("SSH_CCUSAGE", "~/.bun/bin/bunx --bun ccusage --json 2>/dev/null")
TIMEOUT     = int(os.environ.get("TIMEOUT", "25"))


# ── Colors ────────────────────────────────────────────────────────────────────

R = "\033[0m"; B = "\033[1m"; DIM = "\033[2m"
P = "\033[38;5;141m"; G = "\033[38;5;84m"
Y = "\033[38;5;221m"; C = "\033[38;5;117m"; M = "\033[38;5;213m"

def col(text, color): return f"{color}{text}{R}"

def fmt_tokens(n):
    if n >= 1e9: return f"{n/1e9:.2f}B"
    if n >= 1e6: return f"{n/1e6:.1f}M"
    return f"{n/1e3:.0f}k"


# ── Sources ───────────────────────────────────────────────────────────────────

def _parse_ccusage(stdout):
    try:
        return json.loads(stdout).get("totals") or {}
    except Exception:
        return None

def fetch_local():
    try:
        r = subprocess.run(["npx", "ccusage", "--json"],
                           capture_output=True, text=True, timeout=TIMEOUT)
        return _parse_ccusage(r.stdout)
    except Exception:
        return None

def fetch_ssh(host):
    try:
        r = subprocess.run(
            ["ssh", "-o", "ConnectTimeout=8", "-o", "StrictHostKeyChecking=no",
             host, SSH_CCUSAGE],
            capture_output=True, text=True, timeout=TIMEOUT,
        )
        return _parse_ccusage(r.stdout)
    except Exception:
        return None

def gather_sources():
    """Returns {label: totals_dict_or_None} for every configured source."""
    sources = {}
    if USE_LOCAL:
        sources["local"] = fetch_local()
    for host in SSH_SOURCES:
        sources[host] = fetch_ssh(host)
    return sources


# ── Local JSONL parsing ───────────────────────────────────────────────────────

PRICING = {
    "opus":   (15.0, 75.0,  1.50,  18.75),
    "sonnet": ( 3.0, 15.0,  0.30,   3.75),
    "haiku":  ( 0.8,  4.0,  0.08,   1.00),
}

def _pricing(model):
    for key, p in PRICING.items():
        if key in model.lower(): return p
    return PRICING["sonnet"]

def parse_local_jsonl():
    msgs = []
    for path in glob.glob(str(PROJECTS / "**" / "*.jsonl"), recursive=True):
        try:
            with open(path) as fh:
                for raw in fh:
                    d = json.loads(raw.strip())
                    if d.get("type") != "assistant": continue
                    u     = d.get("message", {}).get("usage")
                    model = d.get("message", {}).get("model", "")
                    ts    = d.get("timestamp", "")
                    if not u or not ts: continue
                    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                    i, o, cr, cw = _pricing(model)
                    cost = (
                        u.get("input_tokens",             0) * i  +
                        u.get("output_tokens",            0) * o  +
                        u.get("cache_read_input_tokens",  0) * cr +
                        u.get("cache_creation_input_tokens", 0) * cw
                    ) / 1e6
                    msgs.append({
                        "dt":    dt,
                        "model": model,
                        "sid":   d.get("sessionId", ""),
                        "inp":   u.get("input_tokens",            0),
                        "out":   u.get("output_tokens",           0),
                        "cr":    u.get("cache_read_input_tokens", 0),
                        "cost":  cost,
                    })
        except Exception:
            continue
    return sorted(msgs, key=lambda m: m["dt"])


# ── Analytics ─────────────────────────────────────────────────────────────────

def peak_window(msgs, window_seconds=18_000):
    """Find the single densest rolling window across all sessions."""
    if not msgs: return {}
    by_sid = defaultdict(list)
    for m in msgs:
        by_sid[m["sid"]].append(m)
    best = {"tok": 0}
    for ms in by_sid.values():
        ms = sorted(ms, key=lambda m: m["dt"])
        for i, anchor in enumerate(ms):
            t0  = anchor["dt"].timestamp()
            win = [m for m in ms[i:] if m["dt"].timestamp() - t0 <= window_seconds]
            tok = sum(m["inp"] + m["out"] for m in win)
            if tok > best["tok"]:
                best = {
                    "tok":   tok,
                    "cost":  sum(m["cost"] for m in win),
                    "msgs":  len(win),
                    "start": win[0]["dt"],
                    "end":   win[-1]["dt"],
                }
    return best

def by_model(msgs):
    acc = defaultdict(lambda: {"tok": 0, "cost": 0.0, "msgs": 0})
    for m in msgs:
        label = next((k.capitalize() for k in PRICING if k in m["model"].lower()), "Sonnet")
        acc[label]["tok"]  += m["inp"] + m["out"]
        acc[label]["cost"] += m["cost"]
        acc[label]["msgs"] += 1
    return dict(acc)


# ── Display ───────────────────────────────────────────────────────────────────

def print_sources(sources):
    if len(sources) <= 1:
        return
    print(f"  {col('Sources', Y)}")
    for label, v in sources.items():
        if v is None:
            print(f"    {label:<28}  {col('unavailable', DIM)}")
        else:
            tok  = fmt_tokens(v.get("totalTokens", 0))
            cost = f"${v.get('totalCost', 0):.2f}"
            print(f"    {label:<28}  {col(tok, DIM)}  {col(cost, P)}")
    print()

def print_local_detail(msgs):
    if not msgs: return
    first = msgs[0]["dt"].strftime("%Y-%m-%d")
    last  = msgs[-1]["dt"].strftime("%Y-%m-%d")
    days  = len({m["dt"].strftime("%Y-%m-%d") for m in msgs})
    total = sum(m["inp"] + m["out"] + m["cr"] for m in msgs)
    cache = sum(m["cr"] for m in msgs) / max(total, 1) * 100
    inp   = fmt_tokens(sum(m["inp"] for m in msgs))
    out   = fmt_tokens(sum(m["out"] for m in msgs))
    print(f"  {col('Local detail', Y)}  {col(f'{first} → {last}', DIM)}  {col(f'{days} active days', DIM)}")
    print(f"  {col(inp, C)} input  {col(out, M)} output  {col(f'{cache:.0f}% cache hit', DIM)}\n")

def print_models(models):
    if not models: return
    print(f"  {col('Models', Y)}")
    for label, s in sorted(models.items(), key=lambda x: -x[1]["cost"]):
        if not s["msgs"]: continue
        cost_str = f"${s['cost']:6.2f}"
        tok_str  = fmt_tokens(s["tok"])
        msg_str  = str(s["msgs"]) + " msgs"
        print(f"    {label:<8}  {col(cost_str, P)}  {col(tok_str, DIM)}  {col(msg_str, DIM)}")
    print()

def print_peak(bw):
    if not bw.get("tok"): return
    start    = bw["start"].strftime("%Y-%m-%d %H:%M")
    end      = bw["end"].strftime("%H:%M")
    cost_str = f"${bw['cost']:.2f}"
    msg_str  = str(bw["msgs"]) + " messages"
    print(f"  {col('Peak 5h session', Y)}")
    print(f"  {col(fmt_tokens(bw['tok']), G)} tokens  {col(cost_str, P)}  {col(msg_str, DIM)}")
    print(f"  {col(f'{start} → {end}', DIM)}\n")


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    print(f"\n{col('fetching...', DIM)}", end="\r", flush=True)

    sources = gather_sources()
    msgs    = parse_local_jsonl() if USE_LOCAL else []
    bw      = peak_window(msgs)
    models  = by_model(msgs)

    print(" " * 30, end="\r")

    total_cost = sum((v or {}).get("totalCost",   0) for v in sources.values())
    total_tok  = sum((v or {}).get("totalTokens", 0) for v in sources.values())
    failed     = [name for name, v in sources.items() if v is None]

    print(f"\n{col('━'*48, P)}")
    print(f"  {col('All-time', DIM)}  {col(f'${total_cost:.2f}', B+G)}  {col(fmt_tokens(total_tok)+' tokens', DIM)}")
    for name in failed:
        print(f"  {col(f'⚠  {name} unreachable', Y)}")
    print(f"{col('━'*48, P)}\n")

    print_sources(sources)
    print_local_detail(msgs)
    print_models(models)
    print_peak(bw)

    print(f"{col('━'*48, P)}\n")


if __name__ == "__main__":
    main()
