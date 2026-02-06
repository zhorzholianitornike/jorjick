---
name: deploy
description: Push code to GitHub and deploy to Railway. Use when you want to deploy changes to the Jorjick production server.
disable-model-invocation: true
allowed-tools: Bash(git *), Bash(python3 *)
argument-hint: [commit_message]
---

# Deploy — Push to Railway

Push the current branch to GitHub, which triggers an auto-deploy on Railway.

## Usage

```
/deploy "your commit message"
```

If no message is provided via `$ARGUMENTS`, use a default: "Update code".

## Steps

1. `cd "/Users/toko/Documents/VC Code"` — ensure you are in the project root.
2. Run `git status` to see what files have changed or are untracked.
3. Stage only the relevant files (NEVER `git add -A` — skip `.DS_Store`, `.env`, `temp/`, `uploads/`, `cards/`, `fonts/`).
4. Commit with the message from `$ARGUMENTS` (or default). Always append:
   `Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>`
5. Push using the token URL pattern (osxkeychain does not work in Claude Code):

```bash
git remote set-url origin https://ghp_FSZgUNdz0hAfnnKbk4TO1OSL5QrZOi4H3r@github.com/zhorzholianitornike/jorjick.git
git push origin main
git remote set-url origin https://github.com/zhorzholianitornike/jorjick.git
```

6. Confirm push succeeded. Railway auto-deploys on push to main.
7. If Railway does not redeploy within a minute, push an empty commit:

```bash
git commit --allow-empty -m "Trigger Railway redeploy"
git remote set-url origin https://ghp_FSZgUNdz0hAfnnKbk4TO1OSL5QrZOi4H3r@github.com/zhorzholianitornike/jorjick.git
git push origin main
git remote set-url origin https://github.com/zhorzholianitornike/jorjick.git
```

## Notes

- Railway URL: https://web-production-a33ea.up.railway.app
- GitHub repo: https://github.com/zhorzholianitornike/jorjick
- Branch: main
- Cards and uploads are ephemeral on Railway (lost on restart)
