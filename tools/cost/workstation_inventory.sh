#!/usr/bin/env bash
# READ-ONLY inventory ON the Workstation (G/H of Kostenreductie 4.1). Run in the Workstation terminal.
# Prints facts only; changes nothing; never prints file contents, tokens or keys. Output: ~/ws-inventory-<UTC>.txt
set -uo pipefail
OUT="$HOME/ws-inventory-$(date -u +%Y%m%dT%H%M%SZ).txt"
{
echo "## Disk";               df -h /home
echo "## Top-level /home";    du -sh /home/* /home/.[!.]* 2>/dev/null | sort -h | tail -20
echo "## Root-only dirs (needs sudo; reports size and entry count only)"
for d in /home/lost+found /home/.docker_data; do
  if sudo -n true 2>/dev/null; then echo "$d: $(sudo du -sh "$d" 2>/dev/null | cut -f1), entries=$(sudo find "$d" -mindepth 1 -maxdepth 1 2>/dev/null | wc -l)";
  else echo "$d: SUDO NOT AVAILABLE NON-INTERACTIVELY - run: sudo du -sh $d && sudo ls -la $d | head"; fi
done
echo "## Docker";             docker image ls --format '{{.Repository}}:{{.Tag}} {{.Size}}' 2>/dev/null | head -30; docker volume ls 2>/dev/null
echo "## Git worktrees: dirty files / unpushed commits / stash (since the 13-10 backup)"
for g in $(find "$HOME" -maxdepth 3 -name .git \( -type d -o -type f \) 2>/dev/null); do
  w=$(dirname "$g")
  dirty=$(git -C "$w" status --porcelain 2>/dev/null | wc -l)
  unpushed=$(git -C "$w" log --oneline --branches --not --remotes 2>/dev/null | wc -l)
  stash=$(git -C "$w" stash list 2>/dev/null | wc -l)
  newest=$(find "$w" -path "$w/node_modules" -prune -o -path "$w/web/node_modules" -prune -o -type f -newermt 2026-10-13 -print 2>/dev/null | grep -v '/\.git/' | wc -l)
  echo "$w | branch=$(git -C "$w" rev-parse --abbrev-ref HEAD 2>/dev/null) dirty=$dirty unpushed=$unpushed stash=$stash files_changed_since_13_10=$newest"
done
echo "## Deploy evidence (command names only, no arguments with secrets)"
cat "$HOME/.bash_history" "$HOME/.zsh_history" 2>/dev/null | grep -oE "gcloud (run (deploy|services update(-traffic)?)|builds submit)|docker (build|push)" | sort | uniq -c
ls -la "$HOME/.config/gcloud/configurations" 2>/dev/null | tail -n +2
gcloud config list --format='value(core.account,core.project)' 2>/dev/null
echo "## Files outside git that are newer than 13-10 (names only, max 200)"
find "$HOME" -xdev -type f -newermt 2026-10-13 2>/dev/null | grep -vE '/(node_modules|\.git|\.cache|\.npm|\.venv[^/]*)/' | head -200
} > "$OUT" 2>&1
echo "Written: $OUT"
