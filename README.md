# claude-wake

A minimal TUI tool for macOS that schedules wake-up messages to Terminal.app windows.

## What problem does it solve

Claude Code's token refreshes every 5 hours. After the 5 AM refresh, Claude sits idle until you manually type something. With claude-wake, you can pre-schedule tasks so a message is automatically delivered to a Claude Code terminal at a specific time — waking it up to keep working.

## Features

- Minimal TUI: `←` `→` to switch between add / edit / delete / quit, `Enter` to execute
- Stable target identification via tty (`/dev/ttysNNN`) instead of window title — titles change dynamically as Claude switches tasks, the tty never does
- Delivery via `pbcopy` + `cmd+v` paste, completely bypassing Chinese IME
- Background scheduler thread with hot-reload on config file changes
- ANSI-styled UI, pure Python 3 standard library, zero dependencies

## Installation

```bash
# Direct download
curl -o ~/claude-wake.py https://raw.githubusercontent.com/NeoXue-ai/claude-wake/main/claude-wake.py

# Or git clone
git clone https://github.com/NeoXue-ai/claude-wake.git
cp claude-wake/claude-wake.py ~/
chmod +x ~/claude-wake.py
```

Optional, add an alias:

```sh
echo "alias cw='python3 ~/claude-wake.py'" >> ~/.zshrc
echo "alias claude-wake='python3 ~/claude-wake.py'" >> ~/.zshrc
source ~/.zshrc
```

## Usage

```bash
cw
```

In the TUI:
- `←` / `→` to switch between add / edit / delete / quit
- `Enter` to execute the current item
- `q` to quit

Config file: `~/.claude-wake.json`, schema:

```json
[
  {
    "time": "05:00",
    "target": "/dev/ttys002",
    "message": "good morning, time to code",
    "enabled": true
  }
]
```

`target` accepts `*` for the frontmost window, or a tty path picked from `pick_target`.

## ⚠️ Important: Claude Code needs bypass permissions enabled

To deliver messages **into a Claude Code session**, Claude Code must be running in bypass-permissions mode. Otherwise it will prompt for confirmation on every external input, which defeats the purpose of scheduled wake-ups.

Edit `~/.claude/settings.json` and add:

```json
{
  "permissions": {
    "defaultMode": "bypassPermissions"
  }
}
```

## Sleep behaviour

Two things keep scheduled tasks alive across sleep:

- While `cw` is running it spawns `caffeinate -i -m` bound to its own PID, so the Mac won't fall asleep on idle.
- The scheduler matches an **interval** rather than an exact minute. If the machine was suspended anyway (lid closed, forced sleep), any task whose time fell inside the sleep window fires as soon as the machine wakes.

Closing the terminal stops both the scheduler and `caffeinate`.

## Requirements

- macOS (depends on AppleScript)
- Python 3.10+
- Terminal.app
- Grant **Accessibility** permission to Terminal.app: `System Settings → Privacy & Security → Accessibility → enable Terminal`