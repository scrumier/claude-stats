# claude-stats

Aggregate Claude token usage across **local + remote machines** in one shot.

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  All-time  $521.97  1221.7M tokens
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Sources
    local                         571.7M  $258.43
    root@vps.example.com          649.9M  $263.54

  Local detail  2026-03-04 → 2026-05-20  19 active days
  84k input  2.1M output  99% cache hit

  Models
    Opus      $106.87  381k  469 msgs
    Sonnet    $ 82.13  1.7M  1785 msgs
    Haiku     $  3.90  108k  650 msgs

  Peak 5h session
  341k tokens  $11.96  135 messages
  2026-05-15 23:58 → 00:38

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

## Requirements

- Python 3.8+
- [`ccusage`](https://github.com/ryoppippi/ccusage) available via `npx` on each machine you want to monitor

## Setup

```bash
git clone https://github.com/yourname/claude-stats
cd claude-stats
cp .env.example .env
# edit .env
python3 claude_stats.py
```

### Shell alias

```bash
alias claude-stats='python3 ~/Dev/claude-stats/claude_stats.py'
```

## Configuration (`.env`)

| Variable | Default | Description |
|---|---|---|
| `LOCAL` | `true` | Include the local machine |
| `SSH_SOURCES` | _(empty)_ | Comma-separated SSH hosts to pull from |
| `SSH_CCUSAGE` | `~/.bun/bin/bunx --bun ccusage --json 2>/dev/null` | Command run on each SSH host |
| `CLAUDE_PROJECTS` | `~/.claude/projects` | Path to Claude project files (for local detail) |
| `TIMEOUT` | `25` | SSH + subprocess timeout in seconds |

### Multiple VPS example

```env
LOCAL=true
SSH_SOURCES=root@vps1.example.com,root@vps2.example.com,user@workstation.local
```

If a source is unreachable it is skipped with a warning — the rest still display.
