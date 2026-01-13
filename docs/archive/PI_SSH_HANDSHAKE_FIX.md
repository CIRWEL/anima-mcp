# Pi SSH Handshake Fix

**Issue:** Connections reach Pi but fail during SSH handshake (preauth).

---

## Check SSH Config on Pi

Run on Pi:

```bash
# Check SSH server config
sudo cat /etc/ssh/sshd_config | grep -E "KexAlgorithms|Ciphers|MACs|HostKeyAlgorithms"

# Check if there are restrictive settings
sudo grep -E "^KexAlgorithms|^Ciphers|^MACs" /etc/ssh/sshd_config
```

---

## Fix: Update SSH Config

**On Pi, edit SSH config:**

```bash
sudo nano /etc/ssh/sshd_config
```

**Add or modify these lines (remove # if commented):**

```
# Allow common key exchange algorithms
KexAlgorithms +diffie-hellman-group-exchange-sha256,diffie-hellman-group14-sha256,diffie-hellman-group16-sha512,diffie-hellman-group18-sha512,ecdh-sha2-nistp256,ecdh-sha2-nistp384,ecdh-sha2-nistp521

# Allow common ciphers
Ciphers +aes128-ctr,aes192-ctr,aes256-ctr,aes128-gcm@openssh.com,aes256-gcm@openssh.com,chacha20-poly1305@openssh.com

# Allow common MACs
MACs +hmac-sha2-256,hmac-sha2-512,umac-128@openssh.com

# Ensure password auth is enabled
PasswordAuthentication yes
PubkeyAuthentication yes
```

**Save and restart:**

```bash
sudo systemctl restart ssh
sudo systemctl status ssh
```

---

## Alternative: Use Compatible SSH Options

**On MacBook, try connecting with older cipher:**

```bash
# Try with specific cipher
ssh -o KexAlgorithms=+diffie-hellman-group14-sha256 \
    -o Ciphers=+aes128-ctr \
    -o MACs=+hmac-sha2-256 \
    unitares-anima@192.168.1.165
```

---

## Quick Test: Check SSH Version Compatibility

**On Pi:**

```bash
# Check SSH server version
sshd -V
# or
/usr/sbin/sshd -V
```

**On MacBook:**

```bash
# Check SSH client version
ssh -V
```

Version mismatch might cause handshake issues.

---

## Most Likely Fix

The "Connection reset by [preauth]" suggests cipher/key exchange mismatch.

**Try this on MacBook:**

```bash
ssh -o HostKeyAlgorithms=+ssh-rsa \
    -o PubkeyAcceptedKeyTypes=+ssh-rsa \
    -o KexAlgorithms=+diffie-hellman-group14-sha256 \
    unitares-anima@192.168.1.165
```

Or update SSH config on Pi (see above) to allow more algorithms.

