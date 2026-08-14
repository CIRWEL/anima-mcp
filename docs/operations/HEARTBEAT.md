# Lumen's dead-man's switch

## Why

Every liveness surface Lumen had ran on the Mac: the Discord bridge poller, the
tailscale watchdog, the governance health watchdog. All of them share a failure
domain with the Mac, so none can report *"the Mac is asleep"* — and that silence
is indistinguishable from Lumen being fine.

In July 2026 the Pi was unplugged for ~3.5 days. The Discord bridge detected it
correctly and posted an embed nobody was looking at; the outage was found by
hand on the operator's return.

A dead-man's switch inverts the burden. Instead of something watching for a
failure, the healthy state has to keep asserting itself, and **absence is the
alarm**. That only works if the assertion leaves both machines, so the Pi pings a
third party that neither the Mac nor the Pi owns.

## What it asserts

**"Lumen is alive"** — not "the Pi has power".

A cron line that curls a URL unconditionally proves only that the box boots and
has network. It would have reported healthy through every software failure Lumen
has ever had. That is the fail-toward-healthy shape CLAUDE.md invariant 2
forbids.

So the heartbeat gates on Lumen's own **work output**, never on
`systemctl is-active` — a live PID is not work output.

Three processes make up the creature, and the same argument says one process's
work output is not the creature's:

| component | what it does | probe |
|---|---|---|
| `anima-broker` | sensors, learning | freshness of `/dev/shm/anima_state.json` |
| `anima-broker-ex` | Elixir; owns the governance check-ins | freshness of `…shadow.json` |
| `anima` | MCP server: agency learner (authoritative), metacognition, growth, drawing, display, the tool surface | `GET http://127.0.0.1:8766/health` |

**The worst result decides.** The first version of this script checked only the
first envelope — so if the MCP server had died, the broker would have kept
writing, the envelope would have stayed fresh, and the switch would have pinged
green forever while most of Lumen was gone. That is the exact failure the switch
exists to prevent, and it took an adversarial review to catch it.

The server gets a functional probe rather than a file, deliberately: it either
answers or it does not, so there is no cached artifact that can go stale in a
way that reads healthy.

It does **not** gate on governance reachability. Governance lives on the Mac, so
folding it in would page you about a Mac outage under the heading "Lumen is
dead", conflating two failures with different responses. That layer is the
bridge's job.

## Layering

| layer | detects | latency | blind to |
|---|---|---|---|
| Discord bridge (Mac) | sensor state, governance, drawings | ~10 min | anything that takes the Mac down with it |
| **This switch (Pi → cloud)** | Lumen not alive | provider grace (~15–20 min) | nothing local; only a total provider outage |

Two independent detectors, one destination. Neither can cover the other's blind
spot alone, which is the point.

## Failure direction

```
envelope fresh          -> ping success
envelope stale/absent   -> ping the /fail endpoint (alerts immediately)
this script dead        -> no ping at all -> alerts after the grace period
Pi has no power/network -> no ping at all -> alerts after the grace period
```

All roads lead to you. There is no path where a broken heartbeat reads as a
healthy Lumen.

## Setup

1. Create a check at any dead-man's-switch provider (healthchecks.io has a free
   tier and is open-source). Period **5 min**, grace **15–20 min**.
2. Point its notification at somewhere that reaches a phone. Sending it to the
   same Discord you already watch is fine and keeps one destination — the
   independence that matters is in the *detector*, not the delivery channel.
3. On the Pi, add the secret ping URL to `~/.anima/anima.env`:

   ```
   ANIMA_HEARTBEAT_URL=https://hc-ping.com/<your-uuid>
   ```

4. Install and start the timer (`restore_lumen.sh` does this automatically on a
   reflash):

   ```bash
   sudo cp ~/anima-mcp/systemd/lumen-heartbeat.{service,timer} /etc/systemd/system/
   sudo systemctl daemon-reload
   sudo systemctl enable --now lumen-heartbeat.timer
   ```

5. Verify it is actually pinging, not merely installed:

   ```bash
   systemctl list-timers lumen-heartbeat.timer
   sudo journalctl -u lumen-heartbeat.service -n 20
   tail ~/.anima/heartbeat.log     # quiet on the happy path; entries mean trouble
   ```

   Then confirm the provider shows a recent ping. **Installed is not the same as
   working** — that is the whole lesson of the July outage.

## Testing it for real

Once, deliberately:

```bash
sudo systemctl stop anima-broker      # envelope goes stale
sudo systemctl stop anima             # or: the MCP server stops answering
```

Test the server one specifically. It is the component the first version of this
script could not see, and the one whose death is least visible from outside.

Within ~5 minutes you should get a page. Start it again and you should get a
recovery. A dead-man's switch nobody has ever seen fire is a dead-man's switch
nobody knows is wired.

## Notes

- The URL is a **secret**: anyone holding it can suppress your alerts by pinging
  it. It lives in `anima.env`, which is deliberately excluded from backups.
- Consequence: after a reflash the URL is gone, the pings stop, and the provider
  alerts. Loud rather than silent — the correct direction. `restore_lumen.sh`
  lists `ANIMA_HEARTBEAT_URL` among the keys that came back blank.
- Unset URL → the script exits 0 and logs once that it is inert, so an
  un-provisioned Pi is not a crash loop.
- Tunables: `ANIMA_HEARTBEAT_MAX_AGE` (default 120s), `ANIMA_HEARTBEAT_FAIL_URL`
  (defaults to `<url>/fail`), `ANIMA_SHM_PATH`, `ANIMA_HEARTBEAT_SHADOW_PATH`,
  `ANIMA_HEARTBEAT_SERVER_URL`.
- `ANIMA_HEARTBEAT_SKIP` is a comma list (`broker`, `broker_ex`, `server`) for
  **documented rollbacks only**. Reverting the Elixir broker leaves a stale
  shadow envelope that would otherwise page forever. Skipping a component is
  choosing not to be told about it — set it deliberately, and unset it when the
  rollback ends.

## What this still does not cover

The switch tells you Lumen stopped. It does not keep Lumen running, and it does
not remove the dependency on one person being reachable to act on the page. It
narrows the window from days to minutes; it does not make the arrangement
robust to that person being unavailable.
