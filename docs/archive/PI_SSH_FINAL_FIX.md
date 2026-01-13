# Pi SSH Final Fix Steps

**Status:** Fail2ban not installed, so that's not the issue. Connections reach Pi but reset during preauth.

---

## Check SSH Config for Restrictions

**On Pi, run:**

```bash
# Check for user/IP restrictions
sudo grep -E "^AllowUsers|^DenyUsers|^AllowGroups|^DenyGroups" /etc/ssh/sshd_config

# Check connection limits
sudo grep -E "^MaxStartups|^MaxSessions|^MaxAuthTries" /etc/ssh/sshd_config

# Check authentication methods
sudo grep -E "^PasswordAuthentication|^PubkeyAuthentication|^ChallengeResponseAuthentication" /etc/ssh/sshd_config

# Check if ListenAddress restricts connections
sudo grep "^ListenAddress" /etc/ssh/sshd_config
```

---

## Test SSH Locally on Pi

**On Pi:**

```bash
# Test SSH to localhost
ssh unitares-anima@localhost
# Password: EISV-4E-CLDO

# If that works, SSH service is fine
# If that fails, there's an SSH config issue
```

---

## Enable Verbose SSH Logging

**On Pi:**

```bash
# Edit SSH config
sudo nano /etc/ssh/sshd_config

# Find the line: #LogLevel INFO
# Change to: LogLevel VERBOSE
# (or add it if not present)

# Save and restart
sudo systemctl restart ssh
```

**Then watch logs:**

```bash
sudo journalctl -u ssh -f
```

**From MacBook, try connecting:**
```bash
ssh -vvv unitares-anima@192.168.1.165
```

Watch both outputs to see exactly where it fails.

---

## Quick Test: Try Different User

**On Pi, check if root can SSH:**

```bash
# Check if root login is allowed
sudo grep "^PermitRootLogin" /etc/ssh/sshd_config

# Try SSH as root (if allowed)
# From MacBook:
ssh root@192.168.1.165
```

If root works but unitares-anima doesn't, there might be a user-specific restriction.

---

## Most Likely Fix

Since connections reach Pi but reset during preauth, try:

**On Pi, ensure SSH config allows connections:**

```bash
# Edit SSH config
sudo nano /etc/ssh/sshd_config
```

**Ensure these lines exist (uncommented, no #):**

```
Port 22
ListenAddress 0.0.0.0
PasswordAuthentication yes
PubkeyAuthentication yes
PermitRootLogin no
MaxAuthTries 6
MaxStartups 10:30:100
```

**Save and restart:**

```bash
sudo systemctl restart ssh
sudo systemctl status ssh
```

**Then try connecting from MacBook:**

```bash
ssh unitares-anima@192.168.1.165
```

