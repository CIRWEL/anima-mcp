# Pi SSH Fail2Ban Fix

**Check fail2ban status on Pi:**

```bash
sudo fail2ban-client status
```

**Expected output:**
- If fail2ban is **not installed**: `command not found` or `No such file`
- If fail2ban is **installed but not running**: Shows status but no jails
- If fail2ban is **active**: Shows list of jails (like `sshd`)

---

## If Fail2Ban is Active

**Check SSH jail:**

```bash
sudo fail2ban-client status sshd
```

**Look for your IP (`192.168.1.164`) in the "Banned IP list"**

**If your IP is banned, unban it:**

```bash
sudo fail2ban-client set sshd unbanip 192.168.1.164
```

**Then try connecting from MacBook:**

```bash
ssh unitares-anima@192.168.1.165
```

---

## If Fail2Ban is Not Installed/Running

Then the issue is likely SSH config. Check:

```bash
# Check SSH config for restrictions
sudo grep -E "^AllowUsers|^DenyUsers|^MaxAuthTries|^MaxStartups" /etc/ssh/sshd_config

# Check if there are Match blocks
sudo grep -A 10 "^Match" /etc/ssh/sshd_config
```

---

## Alternative: Check SSH Verbose Logs

**On Pi, enable verbose SSH logging:**

```bash
# Edit SSH config
sudo nano /etc/ssh/sshd_config

# Add or uncomment:
LogLevel VERBOSE

# Restart SSH
sudo systemctl restart ssh
```

**Then watch logs while connecting:**

```bash
sudo journalctl -u ssh -f
```

**From MacBook, try connecting:**
```bash
ssh -vvv unitares-anima@192.168.1.165
```

Watch both outputs to see where it fails.

