# New travel laptop setup — MacBook Air

**Goal:** identical access to the production system, set up in ~30 min so you can work remote from anywhere.

The Mac mini at home stays your production server (scrapers, scheduled jobs run there). The laptop is your **remote control + on-the-go workstation**.

---

## What this laptop SHOULD do

✅ Read/write `~/dealmatcher` (synced via iCloud Drive from Mac mini)
✅ Run scoring + analysis scripts on demand
✅ Connect to Salesforce, SendGrid, Twilio dashboards via browser
✅ Talk to Claude (Cowork desktop app)
✅ Fire/check/troubleshoot launchd jobs running ON THE MAC MINI via SSH

## What this laptop SHOULD NOT do

❌ Run launchd scheduled jobs (those stay on the Mac mini at home — single source of truth)
❌ Hold a separate copy of `~/Library/LaunchAgents` plists (would create double-fires)

---

## Setup checklist (30 min, do at home before trip)

### Phase 1 — System basics (5 min)

- [ ] Sign in to iCloud with same Apple ID as Mac mini
- [ ] System Settings → iCloud Drive → ON
- [ ] Wait for iCloud sync to complete (`~/Library/Mobile Documents/com~apple~CloudDocs` populates)
- [ ] System Settings → Privacy & Security → Full Disk Access → add Terminal

### Phase 2 — Python + dependencies (10 min)

- [ ] Install python.org Python 3.14: https://www.python.org/downloads/
- [ ] Verify: `python3 --version` should print 3.14.x
- [ ] Install dependencies:
  ```
  pip3 install --break-system-packages simple-salesforce msal requests pillow openpyxl pandas
  ```

### Phase 3 — Sync the project folder (5 min)

The `~/dealmatcher` folder needs to be reachable from the laptop. Two options:

**Option A — iCloud Drive sync (recommended):**
- [ ] On Mac mini: move `~/dealmatcher` into iCloud Drive
  ```
  mv ~/dealmatcher ~/Library/Mobile\ Documents/com~apple~CloudDocs/dealmatcher
  ln -s ~/Library/Mobile\ Documents/com~apple~CloudDocs/dealmatcher ~/dealmatcher
  ```
- [ ] On laptop: same `ln -s` to create the `~/dealmatcher` symlink to iCloud version
- [ ] Verify: `ls ~/dealmatcher/parser.py` works on laptop

**Option B — Git (alternative):**
- [ ] On Mac mini: `cd ~/dealmatcher && git init && git add . && git commit -m "initial"`
- [ ] Push to private GitHub repo (or use git-store for portability)
- [ ] On laptop: `git clone <repo> ~/dealmatcher`

### Phase 4 — Cowork (Claude) desktop app (5 min)

- [ ] Install Cowork: https://claude.ai/desktop
- [ ] Sign in with same Anthropic account as Mac mini
- [ ] Connect the same Salesforce, Twilio, SendGrid MCPs (or skip if not needed remotely)
- [ ] Verify: open Cowork → ask "list files in ~/dealmatcher" → should see your scripts

### Phase 5 — SSH to the Mac mini (10 min)

For when you need to fire `launchctl start ...` on the Mac mini from anywhere:

**On Mac mini:**
- [ ] System Settings → General → Sharing → Remote Login → ON
- [ ] Note the Mac mini's local IP and external IP (from your router or whatismyip.com)
- [ ] If trip will use varying networks, configure dynamic DNS (e.g., DuckDNS, no-ip)

**On laptop:**
- [ ] Generate SSH key: `ssh-keygen -t ed25519`
- [ ] Copy public key to Mac mini:
  ```
  ssh-copy-id christopherjohnson@<mac-mini-ip>
  ```
- [ ] Test: `ssh christopherjohnson@<mac-mini-ip> 'ls ~/dealmatcher'`
- [ ] If working: add an alias to `~/.zshrc`:
  ```
  alias mini='ssh christopherjohnson@<mac-mini-ip>'
  alias mini-status='ssh christopherjohnson@<mac-mini-ip> "cd ~/dealmatcher && python3 tools/morning_preflight.py"'
  alias mini-fire-email='ssh christopherjohnson@<mac-mini-ip> "launchctl start com.johnsonbuys.emailcampaign"'
  alias mini-fire-sms='ssh christopherjohnson@<mac-mini-ip> "launchctl start com.johnsonbuys.smscampaign"'
  alias mini-fire-chf='ssh christopherjohnson@<mac-mini-ip> "launchctl start com.cheaphomes.dealmatcher"'
  ```
- [ ] Reload: `source ~/.zshrc`
- [ ] Now from anywhere: `mini-status` runs preflight on the Mac mini

### Phase 6 — Mobile workflow (5 min)

- [ ] iPhone → enable Personal Hotspot
- [ ] On laptop: connect to hotspot once to remember the network
- [ ] Test: open Salesforce mobile dashboards on phone (also work on laptop browser)
- [ ] Install Salesforce mobile app on phone if not already

---

## Verify on laptop before trip

Run all these on the laptop. Each should succeed:

```
ls ~/dealmatcher/parser.py                              # iCloud sync confirmed
python3 -c "from simple_salesforce import Salesforce"   # deps installed
python3 ~/dealmatcher/tools/morning_preflight.py        # connects to SF
mini-status                                              # SSH alias works
```

If all 4 work, the laptop is ready.

---

## What to bring on trip

- MacBook Air + MagSafe charger
- iPhone + Lightning cable (for hotspot tethering)
- Paper notebook (for when you don't want to type)
- This SOP doc (printed)
- Emergency contacts list (printed)

That's it. The Mac mini at home runs everything autonomously. Your phone receives all alerts. The laptop is for occasional deeper work + Salesforce browsing.

---

## In case of TOTAL system failure on the road

If the Mac mini itself has gone offline (power loss, network outage, etc.):

1. Salesforce + your manual phone calls keep the business running. The campaign automation pauses, but inbound deals are still tracked.
2. SSH back into the Mac mini once it's reachable: `mini`
3. Run `mini-status` to see what's broken
4. Worst case: you can work straight from Salesforce mobile + phone calls until you're home
