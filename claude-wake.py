#!/usr/bin/env python3
"""
claude-wake - TUI for scheduling wake-up messages to Terminal.app windows.

Usage:
  python3 ~/claude-wake.py
  alias cw='python3 ~/claude-wake.py'
"""

import json
import os
import select
import subprocess
import sys
import termios
import threading
import time
import tty
from datetime import datetime
from pathlib import Path

CONFIG_PATH = Path.home() / ".claude-wake.json"

# ANSI
RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
REVERSE = "\033[7m"
CLR_BRIGHT_BLACK = "\033[90m"
CLR_BRIGHT_RED = "\033[91m"
CLEAR = "\033[2J\033[H"

MENU_ITEMS = ["add", "edit", "delete", "quit"]


def c(color, text):
    return f"{color}{text}{RESET}"


# ─── event log (thread-safe) ──────────────────────────────────────
_event_log = []
_log_lock = threading.Lock()


def log_event(msg):
    with _log_lock:
        ts = datetime.now().strftime("%H:%M:%S")
        _event_log.append((ts, msg))
        if len(_event_log) > 50:
            _event_log.pop(0)


def recent_events(n=3):
    with _log_lock:
        return list(_event_log[-n:])


# ─── storage ──────────────────────────────────────────────────────
def load_tasks():
    if CONFIG_PATH.exists():
        try:
            return json.loads(CONFIG_PATH.read_text())
        except json.JSONDecodeError:
            log_event("配置文件损坏,已忽略")
    return []


def save_tasks(tasks):
    CONFIG_PATH.write_text(json.dumps(tasks, indent=2, ensure_ascii=False))


# ─── AppleScript helpers ──────────────────────────────────────────
def list_terminal_windows():
    script = '''
tell application "Terminal"
    set out to ""
    repeat with w in windows
        try
            set ttyPath to tty of w
        on error
            set ttyPath to ""
        end try
        set out to out & ttyPath & "|" & (name of w as string) & "\\n"
    end repeat
    return out
end tell
'''
    try:
        r = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, text=True, check=True,
        )
        rows = []
        for line in r.stdout.strip().split("\n"):
            if "|" in line:
                tty, title = line.split("|", 1)
                rows.append((tty.strip(), title.strip()))
        return rows
    except Exception as e:
        return [("ERR", str(e))]


def send_to_terminal(target, message):
    subprocess.run(["pbcopy"], input=message.encode("utf-8"), check=True)
    if target == "*":
        activate_script = 'tell application "Terminal" to activate'
    elif target.startswith("/dev/ttys") or target.startswith("ttys"):
        activate_script = f'''
tell application "Terminal"
    activate
    try
        set targetWin to first window whose tty is "{target}"
        set frontmost of targetWin to true
        set selected of targetWin to true
    on error
        return "NO_MATCH"
    end try
end tell
'''
    else:
        safe_title = target.replace("\\", "\\\\").replace('"', '\\"')
        activate_script = f'''
tell application "Terminal"
    activate
    try
        set targetWin to first window whose name contains "{safe_title}"
        set frontmost of targetWin to true
        set selected of targetWin to true
    on error
        return "NO_MATCH"
    end try
end tell
'''
    full_script = f'''
{activate_script}
delay 0.3
tell application "System Events"
    keystroke "v" using {{command down}}
    key code 36
end tell
'''
    r = subprocess.run(["osascript", "-e", full_script], capture_output=True, text=True)
    if "NO_MATCH" in r.stdout:
        raise RuntimeError(f"没找到 target='{target}' 的终端窗口")


# ─── scheduler (background thread) ───────────────────────────────
def scheduler_loop(tasks):
    sent_today = {}
    last_mtime = CONFIG_PATH.stat().st_mtime if CONFIG_PATH.exists() else 0
    last_check = datetime.now()
    while True:
        try:
            if CONFIG_PATH.exists():
                current_mtime = CONFIG_PATH.stat().st_mtime
                if current_mtime != last_mtime:
                    tasks = load_tasks()
                    last_mtime = current_mtime
                    sent_today = {}
                    log_event(f"config reloaded ({len(tasks)} tasks)")

            now = datetime.now()
            gap = (now - last_check).total_seconds()
            if gap > 120:
                log_event(f"检测到休眠/挂起 {int(gap//60)} 分钟,补检查错过的任务")

            day = now.strftime("%Y-%m-%d")
            for i, task in enumerate(tasks):
                if not task.get("enabled", True) or sent_today.get(i) == day:
                    continue
                try:
                    h, m = map(int, task["time"].split(":"))
                except (ValueError, KeyError):
                    continue
                sched = now.replace(hour=h, minute=m, second=0, microsecond=0)
                # 休眠期间错过的也算命中:上次检查点 < 计划时间 <= 现在
                if not (last_check <= sched <= now):
                    continue
                log_event(f"触发 #{i+1} → {task.get('target','*')}: {task['message'][:30]}")
                try:
                    send_to_terminal(task.get("target", "*"), task["message"])
                    sent_today[i] = day
                    log_event(f"  发送成功")
                except Exception as e:
                    log_event(f"  失败: {e}")

            last_check = now
        except Exception as e:
            log_event(f"调度异常: {e}")
        time.sleep(20)


def next_trigger(tasks):
    now_min = datetime.now().hour * 60 + datetime.now().minute
    candidates = []
    for t in tasks:
        if not t.get("enabled", True):
            continue
        try:
            h, m = map(int, t["time"].split(":"))
            delta = h * 60 + m - now_min
            if delta <= 0:
                delta += 24 * 60
            candidates.append((delta, t["time"]))
        except (ValueError, KeyError):
            continue
    if not candidates:
        return None
    candidates.sort()
    return candidates[0]


# ─── raw key input + arrow-key picker ────────────────────────────
def read_key():
    """Read a single key in raw mode. Returns key name string or char."""
    fd = sys.stdin.fileno()
    if not os.isatty(fd):
        try:
            line = sys.stdin.readline().rstrip("\n")
        except (EOFError, OSError):
            return None
        return line if line else "ENTER"

    old = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        ch = os.read(fd, 1).decode("utf-8", errors="replace")
        if ch == "\x1b":
            r, _, _ = select.select([sys.stdin], [], [], 0.05)
            if r:
                ch2 = os.read(fd, 1).decode("utf-8", errors="replace")
                if ch2 == "[":
                    r2, _, _ = select.select([sys.stdin], [], [], 0.05)
                    if r2:
                        ch3 = os.read(fd, 1).decode("utf-8", errors="replace")
                        return {"A": "UP", "B": "DOWN", "C": "RIGHT", "D": "LEFT"}.get(ch3, "ESC")
            return "ESC"
        if ch in ("\r", "\n"):
            return "ENTER"
        if ch == "\x03":
            raise KeyboardInterrupt
        return ch
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


def pick_from_list(items, title="Select", preselect=0):
    """Arrow-key picker. Returns selected index or None."""
    if not items:
        return None
    selected = max(0, min(preselect, len(items) - 1))
    while True:
        sys.stdout.write(CLEAR)
        print()
        print(f"  {title}")
        print()
        for i, item in enumerate(items):
            marker = "›" if i == selected else " "
            print(f"  {marker} {item}")
        print()
        print(f"  {c(DIM, '↑↓ navigate · enter select · q/esc cancel')}")
        sys.stdout.flush()

        key = read_key()
        if key == "UP":
            selected = (selected - 1) % len(items)
        elif key == "DOWN":
            selected = (selected + 1) % len(items)
        elif key == "ENTER":
            return selected
        elif key in ("q", "Q", "ESC"):
            return None


# ─── pickers ──────────────────────────────────────────────────────
def pick_target(preselect="*"):
    """Arrow-key picker for target window. Returns tty path or '*' for frontmost."""
    windows = list_terminal_windows()
    items = ["* (frontmost)"]
    targets = ["*"]
    for tty, title in windows:
        if tty == "ERR" or not tty:
            continue
        items.append(f"{title}  {c(DIM, tty)}")
        targets.append(tty)
    if len(items) == 1:
        return "*"
    if preselect == "*":
        pre = 0
    else:
        pre = targets.index(preselect) if preselect in targets else 0
    selected = pick_from_list(items, title="Pick target window", preselect=pre)
    if selected is None:
        return None
    return targets[selected]


def pick_task(tasks, title="Pick task"):
    """Arrow-key picker for tasks. Returns 0-based index or None."""
    if not tasks:
        return None
    items = []
    for t in tasks:
        msg = t["message"]
        if len(msg) > 35:
            msg = msg[:32] + "..."
        state = "●" if t.get("enabled", True) else "○"
        target = t.get("target", "*")
        items.append(f"{t['time']}  {state}  {target[:18]:<18}  {msg}")
    selected = pick_from_list(items, title=title, preselect=0)
    if selected is None:
        return None
    return selected


# ─── text prompts ────────────────────────────────────────────────
def prompt(label, default=""):
    suffix = f" {c(DIM, '[' + default + ']')}" if default else ""
    val = input(f"  {c(CLR_BRIGHT_RED, '›')} {label}{suffix}: ").strip()
    return val or default


def confirm(label, default="no"):
    suffix = f" {c(DIM, '[' + default + ']')}"
    val = input(f"  {c(CLR_BRIGHT_RED, '›')} {label}{suffix}: ").strip().lower()
    if not val:
        val = default.lower()
    return val in ("y", "yes")


# ─── actions ──────────────────────────────────────────────────────
def action_add(tasks):
    print()
    print("  Add task")
    t = prompt("Time HH:MM", "05:00")
    try:
        datetime.strptime(t, "%H:%M")
    except ValueError:
        return f"时间格式不对: {t}"

    target = pick_target()
    if target is None:
        return "已取消"

    msg = prompt("Message")
    if not msg:
        return "消息不能为空"

    tasks.append({"time": t, "target": target, "message": msg, "enabled": True})
    save_tasks(tasks)
    return f"已添加 #{len(tasks)}: {t} → {target}"


def action_edit(tasks):
    if not tasks:
        return "暂无任务"

    idx = pick_task(tasks, title="Pick task to edit")
    if idx is None:
        return "已取消"

    t = tasks[idx]
    print()
    print(f"  Edit #{idx+1}")
    print(f"  current: {t['time']} → {t.get('target','*')} → {t['message']}")

    new_time = prompt("Time", t["time"]) or t["time"]
    try:
        datetime.strptime(new_time, "%H:%M")
    except ValueError:
        return "时间格式不对"

    new_target = pick_target(preselect=t.get("target", "*"))
    if new_target is None:
        return "已取消"

    new_msg = prompt("Message", t["message"]) or t["message"]

    tasks[idx] = {
        "time": new_time,
        "target": new_target,
        "message": new_msg,
        "enabled": t.get("enabled", True),
    }
    save_tasks(tasks)
    return f"任务 #{idx+1} 已更新"


def action_delete(tasks):
    if not tasks:
        return "暂无任务"

    idx = pick_task(tasks, title="Pick task to delete")
    if idx is None:
        return "已取消"

    t = tasks[idx]
    if not confirm(f"Delete '{t['time']} → {t['message'][:30]}'?", "no"):
        return "已取消"

    tasks.pop(idx)
    save_tasks(tasks)
    return f"已删除 #{idx+1}"


# ─── render ───────────────────────────────────────────────────────
def render(tasks, selected=0):
    sys.stdout.write(CLEAR)
    now_str = datetime.now().strftime("%H:%M:%S")
    active_count = sum(1 for t in tasks if t.get("enabled", True))

    print()
    print(f"  {c(BOLD, '☾ CLAUDE WAKE')}")
    print()
    print(f"  {now_str}  scheduler ●  tasks {len(tasks)} ({active_count} on)")
    print()

    if not tasks:
        print("  no tasks.")
    else:
        for i, t in enumerate(tasks):
            enabled = t.get("enabled", True)
            state = "on " if enabled else "off"
            target = t.get("target", "*")
            msg = t["message"]
            if len(msg) > 42:
                msg = msg[:39] + "..."
            print(f"  {i+1:<3} {t['time']:<6} {target:<14} {state:<5} {msg}")

        nt = next_trigger(tasks)
        if nt:
            delta, hhmm = nt
            if delta < 60:
                nt_str = f"in {delta}m"
            else:
                h, m = divmod(delta, 60)
                nt_str = f"in {h}h {m}m"
            print()
            print(f"  next  {hhmm}  ({nt_str})")

    print()
    max_len = max(len(name) for name in MENU_ITEMS)
    parts = []
    for i, name in enumerate(MENU_ITEMS):
        cell = name.ljust(max_len)
        if i == selected:
            cell = c(REVERSE, cell)
        parts.append(cell)
    print(f"  {'    '.join(parts)}")
    print(f"  {c(DIM, '← → navigate · enter select · q quit')}")

    print()
    events = recent_events(3)
    if not events:
        print(f"  {c(DIM, '(no events yet)')}")
    else:
        for ts, msg in events:
            print(f"  {c(DIM, ts)}  {msg}")
    print()


# ─── keep the Mac awake while running ────────────────────────────
def keep_awake():
    """Prevent idle sleep for as long as this process lives."""
    try:
        subprocess.Popen(
            ["caffeinate", "-i", "-m", "-w", str(os.getpid())],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return True
    except Exception as e:
        log_event(f"caffeinate 启动失败: {e}")
        return False


# ─── main ─────────────────────────────────────────────────────────
def main():
    tasks = load_tasks()
    awake = keep_awake()
    log_event("scheduler started" + ("  (caffeinate on)" if awake else ""))
    threading.Thread(target=scheduler_loop, args=(tasks,), daemon=True).start()

    def run(name):
        if name == "add":
            return action_add(tasks)
        if name == "edit":
            return action_edit(tasks)
        if name == "delete":
            return action_delete(tasks)
        return None

    selected = 0
    try:
        while True:
            render(tasks, selected)
            key = read_key()
            if key == "LEFT":
                selected = (selected - 1) % len(MENU_ITEMS)
            elif key == "RIGHT":
                selected = (selected + 1) % len(MENU_ITEMS)
            elif key == "ENTER":
                name = MENU_ITEMS[selected]
                if name == "quit":
                    print(f"\n  {c(CLR_BRIGHT_RED, 'Bye.')} "
                          f"{c(DIM, '关掉终端,调度就停了。')}\n")
                    break
                result = run(name)
                if result:
                    log_event(result)
            elif key in ("q", "Q"):
                print(f"\n  {c(CLR_BRIGHT_RED, 'Bye.')} "
                      f"{c(DIM, '关掉终端,调度就停了。')}\n")
                break
            elif key is None:
                print(f"\n  {c(CLR_BRIGHT_RED, 'No stdin.')} "
                      f"{c(DIM, '需要交互式终端。')}\n")
                break
    except KeyboardInterrupt:
        print(f"\n  {c(CLR_BRIGHT_RED, 'Interrupted.')}\n")
    finally:
        sys.stdout.write(RESET)


if __name__ == "__main__":
    main()