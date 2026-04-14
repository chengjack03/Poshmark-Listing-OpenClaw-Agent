#!/bin/bash
LOGFILE="/home/cymolt/poshmark_listings/cron.log"
INBOUND="/home/cymolt/poshmark_listings/.openclaw_state/media/inbound"

# Check if there are any image files in the inbound dir
shopt -s nullglob
images=("$INBOUND"/*.jpg "$INBOUND"/*.jpeg "$INBOUND"/*.png "$INBOUND"/*.JPG "$INBOUND"/*.JPEG "$INBOUND"/*.PNG)
shopt -u nullglob

if [ ${#images[@]} -eq 0 ]; then
    echo "[$(date)] No images in inbound -- skipping" >> "$LOGFILE"
    exit 0
fi

echo "[$(date)] Found ${#images[@]} image(s) -- starting preview..." >> "$LOGFILE"

# Load ANTHROPIC_API_KEY from auth-profiles.json
export ANTHROPIC_API_KEY=$(python3 -c "
import json
with open('/home/cymolt/poshmark_listings/.openclaw_state/agents/main/agent/auth-profiles.json') as f:
    d = json.load(f)
print(d['profiles']['anthropic:pi-automation-agency']['token'])
" 2>/dev/null)

python3 /home/cymolt/poshmark_listings/create_drafts_v7.py --preview >> "$LOGFILE" 2>&1
echo "[$(date)] Preview run complete (exit $?)" >> "$LOGFILE"
