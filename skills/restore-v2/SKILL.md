---
name: restore-v2
description: Restore the project to the archived V2_IMGGENERATOR state. Use ONLY when you explicitly want to roll back all code to the last known-good V2 version.
disable-model-invocation: true
allowed-tools: Bash(git *), Bash(cp *)
---

# Restore V2_IMGGENERATOR

Roll back the entire project to the V2_IMGGENERATOR archive.

## Two methods — pick one:

### Method A: Git checkout (fastest)

```bash
cd "/Users/toko/Documents/VC Code"
git checkout V2_IMGGENERATOR -- .
```

This restores all tracked files to the tagged commit `427d917` without changing the branch. You can then commit if you want to make this the new HEAD.

### Method B: File backup restore (if git tag is lost)

The V2 files are backed up at:
`/Users/toko/.claude/projects/-Users-toko-Documents-VC-Code/memory/V2_IMGGENERATOR/`

Copy each file back:
```bash
BACKUP="/Users/toko/.claude/projects/-Users-toko-Documents-VC-Code/memory/V2_IMGGENERATOR"
DEST="/Users/toko/Documents/VC Code"
cp "$BACKUP/web_app.py"        "$DEST/web_app.py"
cp "$BACKUP/card_generator.py" "$DEST/card_generator.py"
cp "$BACKUP/facebook.py"       "$DEST/facebook.py"
cp "$BACKUP/telegram_bot.py"   "$DEST/telegram_bot.py"
cp "$BACKUP/agent.py"          "$DEST/agent.py"
cp "$BACKUP/setup_fonts.py"    "$DEST/setup_fonts.py"
cp "$BACKUP/requirements.txt"  "$DEST/requirements.txt"
cp "$BACKUP/Procfile"          "$DEST/Procfile"
cp "$BACKUP/.gitignore"        "$DEST/.gitignore"
```

## After restore

1. Verify files with `git diff` to confirm the rollback.
2. If you want to deploy the restored version, use `/deploy "Restore to V2_IMGGENERATOR"`.

## What V2 contains

- card_generator.py: 1080×1350 cards with blue overlay, red dot, 54px name (uppercase), 30px text (uppercase)
- web_app.py: Full Georgian dashboard + FB upload + Telegram bot + Georgian notifications with Tbilisi time
- facebook.py: Graph API photo upload
- All other project files at commit 427d917
