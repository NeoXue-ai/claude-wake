# claude-wake

macOS 上的极简 TUI 工具,定时给 Terminal.app 窗口发消息。

## 它解决什么问题

Claude Code 的 token 每 5 小时刷新一次。凌晨 5 点 token 刷新后,Claude 处于待命状态,直到你下一次手动输入。用 claude-wake 你可以预设任务,在指定时间自动给 Claude Code 终端发一条消息把它叫醒,继续干活。

## 功能

- 极简 TUI:`←` `→` 切换 add / edit / delete / quit,`Enter` 执行
- 稳定定位目标终端:用 tty (`/dev/ttysNNN`) 而不是窗口标题——窗口标题会随 claude 任务动态变化,tty 不会变
- 通过 `pbcopy` + `cmd+v` 粘贴发送,完全绕过中文输入法
- 后台线程调度,改完配置文件自动热加载
- ANSI 着色 UI,纯 Python 3 标准库,零依赖

## 安装

```bash
# 直接下载
curl -o ~/claude-wake.py https://raw.githubusercontent.com/NeoXue-ai/claude-wake/main/claude-wake.py

# 或者 git clone
git clone https://github.com/NeoXue-ai/claude-wake.git
cp claude-wake/claude-wake.py ~/
chmod +x ~/claude-wake.py
```

可选,加 alias:

```sh
echo "alias cw='python3 ~/claude-wake.py'" >> ~/.zshrc
echo "alias claude-wake='python3 ~/claude-wake.py'" >> ~/.zshrc
source ~/.zshrc
```

## 用法

```bash
cw
```

进 TUI 后:
- `←` / `→` 切换 add / edit / delete / quit
- `Enter` 执行当前项
- `q` 退出

配置文件:`~/.claude-wake.json`,格式:

```json
[
  {
    "time": "05:00",
    "target": "/dev/ttys002",
    "message": "早安,该起床写代码了",
    "enabled": true
  }
]
```

`target` 用 `*` 表示当前 frontmost 窗口,或用 `pick_target` 选出来的 tty 路径。

## ⚠️ 重要:Claude Code 需要开启 bypass permissions

要让 claude-wake 把消息发到 **Claude Code 会话里**,Claude Code 必须运行在 bypass-permissions 模式——否则它对每条外部输入都弹确认,定时唤醒就没意义了。

编辑 `~/.claude/settings.json`,加入:

```json
{
  "permissions": {
    "defaultMode": "bypassPermissions"
  }
}
```

## 系统要求

- macOS(依赖 AppleScript)
- Python 3.10+
- Terminal.app
- 给 `Terminal.app` 授予 **辅助功能(Accessibility)** 权限:`系统设置 → 隐私与安全性 → 辅助功能 → 勾选 Terminal`