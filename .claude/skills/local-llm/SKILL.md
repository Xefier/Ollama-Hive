---
name: local-llm
description: Add, remove or list the Ollama rigs that Claude Code on this PC can delegate to (the local-llm MCP server), or unregister it. Use when the user runs /local-llm, or asks to register, add, remove or list a rig or an Ollama address, e.g. "add 192.168.1.189" or "register the rig at 192.168.1.189:11434".
---

# local-llm: manage this PC's rigs

The commands live in this repository's `client` folder and change the current Windows user's Claude Code config, so
they apply to every project on this PC.

Run it with the PowerShell tool from the repository root (the folder that holds `client\` and `ollama-hive\`):

```powershell
& .\client\local-llm.cmd <action> <address>[:port] ...
```

| What the user asked | Action |
|---|---|
| Add or register a rig | `add 192.168.1.189` (port 11434 unless they gave one) |
| Remove a rig | `remove 192.168.1.189` |
| Which rigs, or is it working | `list` |
| Remove everything | `unregister` (ask first: it removes every rig) |
| How much it has been used or saved | `stats` (add a number of days, default 14) |

With no address given for `add` or `remove`, ask for it. Several addresses can follow one action.

Then tell the user what the output says: each rig's address and whether it answers with a model loaded. A rig "not
answering now" is fine if it is on another flight sheet. The tools `local_llm_ask` and `local_llm_status` appear in
new sessions only, not in the one that ran the command.

If it fails, report the message as it is. "Claude Code (claude) was not found" or "Python 3.8 or newer was not found"
means that has to be installed first; nothing was changed.
