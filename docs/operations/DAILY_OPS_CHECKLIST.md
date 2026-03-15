# Daily Ops Checklist

**Created:** {today_full()}  
**Last Updated:** {today_full()}  
**Status:** Active

---

## Daily Quick Check (5-10 minutes)

- [ ] Confirm services are running: `sudo systemctl status anima-broker anima --no-pager`
- [ ] Confirm MCP health endpoint responds: `curl http://localhost:8766/health`
- [ ] Check recent errors: `sudo journalctl -u anima -n 50 --no-pager`
- [ ] Check broker logs for sensor stability: `sudo journalctl -u anima-broker -n 50 --no-pager`
- [ ] Verify state file updates: `ls -la /dev/shm/anima_state.json`

## After Any Deploy/Restart

- [ ] Wait 2 minutes for stabilization before retrying MCP calls
- [ ] Re-check service status and logs
- [ ] Confirm MCP endpoint in clients uses `/mcp/` (not `/sse`)
- [ ] If behavior is odd, restart both services once: `sudo systemctl restart anima-broker anima`

## Weekly Maintenance

- [ ] Check disk usage: `df -h`
- [ ] Confirm DB file exists: `ls -la ~/.anima/anima.db`
- [ ] Create local DB backup: `cp ~/.anima/anima.db ~/.anima/anima.db.backup.$(date +%Y%m%d)`
- [ ] Review env settings if needed: `~/.anima/anima.env`

## If Something Breaks

- [ ] Use `docs/operations/PI_DEPLOYMENT.md` troubleshooting section first
- [ ] Confirm SSH access via `docs/operations/PI_ACCESS.md`
- [ ] Confirm ports/endpoints via `docs/operations/DEFINITIVE_PORTS.md`
- [ ] Avoid rapid repeated restarts; restart once, then re-check logs
