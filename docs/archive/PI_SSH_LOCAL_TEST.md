# Pi SSH Local Test

**Status:** No explicit SSH restrictions found. Testing local SSH.

---

## Test SSH Locally on Pi

**On Pi, run:**

```bash
# Test SSH to localhost
ssh unitares-anima@localhost
# Password: EISV-4E-CLDO

# If this works, SSH service is fine
# If this fails, there's an SSH config or user issue
```

---

## Check SSH Default Settings

**On Pi:**

```bash
# Check what SSH is actually using (defaults + config)
sudo sshd -T | grep -E "passwordauthentication|pubkeyauthentication|permitrootlogin|maxauthtries|maxstartups|listenaddress"
```

This shows the actual effective settings.

---

## Check Network Interface

**On Pi:**

```bash
# Check what interfaces SSH is listening on
sudo netstat -tlnp | grep :22

# Should show:
# 0.0.0.0:22 (all IPv4 interfaces)
# :::22 (all IPv6 interfaces)
```

---

## Enable Verbose Logging

**On Pi:**

```bash
# Edit SSH config
sudo nano /etc/ssh/sshd_config

# Add or uncomment:
LogLevel VERBOSE

# Save and restart
sudo systemctl restart ssh

# Watch logs in real-time
sudo journalctl -u ssh -f
```

**Then from MacBook, try:**

```bash
ssh -vvv unitares-anima@192.168.1.165
```

Watch both outputs to see exactly where it fails.

---

## Quick Test: Try Root

**On Pi, check if root login works:**

```bash
# Check root login setting
sudo grep "^PermitRootLogin" /etc/ssh/sshd_config

# If it's "yes" or "prohibit-password", try from MacBook:
ssh root@192.168.1.165
```

If root works but unitares-anima doesn't, there might be a user-specific issue.

