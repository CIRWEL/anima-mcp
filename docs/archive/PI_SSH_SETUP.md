# Raspberry Pi SSH Setup for Cursor

**Pi IP:** `192.168.1.165`  
**User:** `unitares-anima`  
**Password:** `EISV-4E-CLDO`

---

## Step 1: Enable SSH on Pi

If SSH isn't working, enable it on the Pi:

**Option A: Using raspi-config (if you have terminal access)**
```bash
sudo raspi-config
# Navigate to: Interface Options → SSH → Enable
```

**Option B: Using systemctl**
```bash
sudo systemctl enable ssh
sudo systemctl start ssh
```

**Option C: Create SSH file (headless setup)**
```bash
sudo touch /boot/ssh
sudo reboot
```

---

## Step 2: Test SSH from MacBook

```bash
ssh unitares-anima@192.168.1.165
# Enter password: EISV-4E-CLDO
```

If it works, you should see the Pi prompt.

---

## Step 3: Set Up Cursor Remote SSH

### Install Extension

1. Open Cursor
2. Press `Cmd+Shift+X` (Extensions)
3. Search for "Remote - SSH"
4. Install "Remote - SSH" by Microsoft

### Connect to Pi

1. Press `Cmd+Shift+P` (Command Palette)
2. Type: `Remote-SSH: Connect to Host`
3. Enter: `unitares-anima@192.168.1.165`
4. Enter password: `EISV-4E-CLDO`
5. Select platform: Linux

### Open Folder

Once connected:
1. File → Open Folder
2. Enter: `/home/unitares-anima`
3. Or: `~/`

Now you can edit files directly on the Pi!

---

## Step 4: (Optional) Set Up SSH Key (No Password)

**On MacBook:**
```bash
ssh-keygen -t ed25519 -C "cursor-pi"
# Press Enter for default location

ssh-copy-id unitares-anima@192.168.1.165
# Enter password when prompted
```

**Then test:**
```bash
ssh unitares-anima@192.168.1.165
# Should connect without password
```

---

## Quick Commands

**SSH to Pi:**
```bash
ssh unitares-anima@192.168.1.165
```

**Copy file to Pi:**
```bash
scp file.py unitares-anima@192.168.1.165:~/
```

**Copy file from Pi:**
```bash
scp unitares-anima@192.168.1.165:~/file.py ./
```

**Run command on Pi:**
```bash
ssh unitares-anima@192.168.1.165 "ls -la"
```

---

## Troubleshooting

**Connection timeout?**
- Check Pi is powered on
- Check Pi is on same network
- Check SSH is enabled: `sudo systemctl status ssh`
- Check firewall: `sudo ufw status`

**Permission denied?**
- Check username: `unitares-anima`
- Check password: `EISV-4E-CLDO`
- Check user exists: `cat /etc/passwd | grep unitares-anima`

**Can't find Pi?**
- Ping test: `ping 192.168.1.165`
- Check IP hasn't changed: `hostname -I` on Pi
- Check router's connected devices list

---

## Cursor Remote SSH Config

You can also add to `~/.ssh/config`:

```
Host pi-anima
    HostName 192.168.1.165
    User unitares-anima
    IdentityFile ~/.ssh/id_rsa
```

Then connect with: `ssh pi-anima` or use "pi-anima" in Cursor Remote SSH.

