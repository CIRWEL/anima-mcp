# Pi SSH Config Check

**Status:** Connections reach Pi (`192.168.1.164` → `192.168.1.165`) but reset during preauth.

---

## Check SSH Config on Pi

Run these commands **on the Pi**:

```bash
# Check for any IP/host restrictions
sudo grep -E "^AllowUsers|^DenyUsers|^AllowGroups|^DenyGroups|^AllowHosts|^DenyHosts" /etc/ssh/sshd_config

# Check for connection limits
sudo grep -E "^MaxStartups|^MaxSessions|^MaxAuthTries" /etc/ssh/sshd_config

# Check authentication settings
sudo grep -E "^PasswordAuthentication|^PubkeyAuthentication|^ChallengeResponseAuthentication" /etc/ssh/sshd_config

# Check if there are any Match blocks that might restrict access
sudo grep -A 10 "^Match" /etc/ssh/sshd_config
```

---

## Test SSH from Pi to Itself

**On Pi:**

```bash
# Test SSH locally
ssh unitares-anima@localhost
# Password: EISV-4E-CLDO

# If that works, try with IP
ssh unitares-anima@192.168.1.165
```

If localhost works but IP doesn't, there might be a ListenAddress restriction.

---

## Check SSH Listen Address

**On Pi:**

```bash
# Check what SSH is listening on
sudo netstat -tlnp | grep :22

# Should show:
# 0.0.0.0:22 (all interfaces)
# :::22 (IPv6)

# Check SSH config
sudo grep "^ListenAddress" /etc/ssh/sshd_config
```

If `ListenAddress` is set to `127.0.0.1` or a specific IP, SSH won't accept external connections.

---

## Quick Fix: Reset SSH Config

**On Pi, backup and reset SSH config:**

```bash
# Backup current config
sudo cp /etc/ssh/sshd_config /etc/ssh/sshd_config.backup

# Generate new default config (if needed)
# Or edit to ensure these settings:
sudo nano /etc/ssh/sshd_config
```

**Ensure these lines exist (uncommented):**

```
Port 22
ListenAddress 0.0.0.0
PasswordAuthentication yes
PubkeyAuthentication yes
PermitRootLogin no
```

**Restart SSH:**

```bash
sudo systemctl restart ssh
sudo systemctl status ssh
```

---

## Check for Fail2Ban or Similar

**On Pi:**

```bash
# Check if fail2ban is blocking connections
sudo systemctl status fail2ban
sudo fail2ban-client status sshd

# If fail2ban is active and blocking, unban your IP:
sudo fail2ban-client set sshd unbanip 192.168.1.164
```

---

## Most Likely Issue

Given that:
- ✅ Connections reach Pi (seen in logs)
- ✅ Port 22 is open (`nc` connects)
- ❌ SSH handshake fails (reset during preauth)

**Most likely:** SSH config has restrictions or fail2ban is blocking.

**Try on Pi:**

```bash
# Check fail2ban
sudo fail2ban-client status

# If active, unban your IP
sudo fail2ban-client set sshd unbanip 192.168.1.164

# Then try connecting again from MacBook
```

