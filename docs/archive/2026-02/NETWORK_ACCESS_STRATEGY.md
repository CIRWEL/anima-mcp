# Network Access Strategy: Tailscale vs ngrok

**Created:** January 12, 2026  
**Last Updated:** January 12, 2026  
**Status:** Active

---

## Overview

**Goal:** Reliable, accessible MCP connections with fallbacks for stability.

**Options:**
1. **Tailscale** - Mesh VPN (private network)
2. **ngrok** - Public tunnels (HTTPS)
3. **Local Network** - Direct IP (same network)
4. **Hybrid** - Multiple options with fallbacks

---

## Comparison

| Feature | Tailscale | ngrok | Local Network |
|---------|----------|-------|---------------|
| **Accessibility** | ✅ Works anywhere (mesh VPN) | ✅ Works anywhere (public URL) | ❌ Same network only |
| **Security** | ✅ Private mesh (encrypted) | ✅ HTTPS (public but encrypted) | ⚠️ Local only (unencrypted) |
| **Stability** | ✅ Persistent IPs | ✅ Persistent URLs (custom domain) | ⚠️ IPs change |
| **Setup Complexity** | Medium (install on both) | Low (install on server) | None (just IP) |
| **Cost** | ✅ Free (up to 100 devices) | ⚠️ Free tier limited | ✅ Free |
| **Fallback Support** | ✅ Can combine with others | ✅ Can combine with others | ✅ Always available |
| **Debugging** | ⚠️ Limited visibility | ✅ Full dashboard | ⚠️ No visibility |
| **Firewall/NAT** | ✅ Works through NAT | ✅ Works through NAT | ❌ Requires same network |

---

## Current Setup

### Mac (UNITARES)
- ✅ **Tailscale:** Installed (status unknown)
- ✅ **ngrok:** Running (`unitares.ngrok.io` → `localhost:8765`)
- ✅ **Local:** `localhost:8765`

### Pi (anima-mcp)
- ❓ **Tailscale:** Status unknown (IP `100.124.49.85` mentioned)
- ❌ **ngrok:** Not installed
- ✅ **Local:** `192.168.1.165:8765`

---

## Recommended Strategy: Hybrid with Fallbacks

### Primary: Tailscale (Best for Private Access)

**Why Tailscale:**
- ✅ **Mesh VPN** - Works anywhere, secure
- ✅ **Persistent IPs** - `100.124.49.85` doesn't change
- ✅ **No public exposure** - Private network
- ✅ **Free** - Up to 100 devices
- ✅ **Low latency** - Direct peer connections

**Setup:**
```bash
# Mac
tailscale up

# Pi
sudo tailscale up

# Get IPs
tailscale status
```

**Config:**
```json
{
  "anima": {
    "type": "sse",
    "url": "http://100.124.49.85:8765/sse"
  }
}
```

### Secondary: ngrok (Best for Public/Debugging)

**Why ngrok:**
- ✅ **Public access** - Shareable URLs
- ✅ **Dashboard** - See all requests
- ✅ **HTTPS** - Secure public access
- ✅ **Verification** - "If tunnel works, connection works"

**Use cases:**
- External access (not on Tailscale)
- Debugging (see all traffic)
- Sharing with others
- Backup if Tailscale fails

**Setup:**
```bash
# Pi
ngrok http --url=anima.ngrok.io 8765
```

**Config:**
```json
{
  "anima": {
    "type": "sse",
    "url": "https://anima.ngrok.io/sse"
  }
}
```

### Fallback: Local Network (Always Available)

**Why Local:**
- ✅ **Fastest** - No tunnel overhead
- ✅ **Always works** - Same network
- ✅ **No dependencies** - No services needed

**Use cases:**
- Development/testing
- Same network access
- Fallback if both fail

**Config:**
```json
{
  "anima": {
    "type": "sse",
    "url": "http://192.168.1.165:8765/sse"
  }
}
```

---

## Recommended Architecture

### For MCP Connections (Cursor → Servers)

**Priority order:**
1. **Tailscale** (primary) - `http://100.124.49.85:8765/sse`
2. **ngrok** (secondary) - `https://anima.ngrok.io/sse`
3. **Local** (fallback) - `http://192.168.1.165:8765/sse`

**Implementation:** Cursor tries Tailscale first, falls back to ngrok, then local.

**Note:** Cursor doesn't support multiple URLs, so choose based on environment:
- **Development:** Local IP (fastest)
- **Remote work:** Tailscale (secure, reliable)
- **Debugging:** ngrok (visibility)

### For Pi → Mac (UNITARES)

**Priority order:**
1. **ngrok** (primary) - `https://unitares.ngrok.io/sse` ✅ Already running
2. **Tailscale** (secondary) - `http://[Mac-Tailscale-IP]:8765/sse`
3. **Local** (fallback) - `http://192.168.1.164:8765/sse` (Mac's local IP)

**Implementation:** Set `UNITARES_URL` environment variable on Pi.

---

## Best Practice: Use Both

### Why Not Replace?

**Tailscale ≠ ngrok** - They serve different purposes:

| Use Case | Best Choice |
|----------|-------------|
| **Private access** (you only) | Tailscale |
| **Public access** (shareable) | ngrok |
| **Debugging** (see traffic) | ngrok |
| **Mesh network** (multiple devices) | Tailscale |
| **HTTPS public URL** | ngrok |
| **Persistent private IP** | Tailscale |

### Recommended Setup

**For anima-mcp (Pi):**
1. ✅ **Tailscale** - Primary access (private, reliable)
2. ✅ **ngrok** - Secondary/debugging (public, visible)
3. ✅ **Local** - Development fallback

**For UNITARES (Mac):**
1. ✅ **ngrok** - Already running (public access)
2. ✅ **Tailscale** - If Mac on Tailscale (private access)
3. ✅ **Local** - `localhost:8765` (same machine)

---

## Configuration Examples

### Cursor MCP Config (Tailscale Primary)

```json
{
  "mcpServers": {
    "anima": {
      "type": "sse",
      "url": "http://100.124.49.85:8765/sse"
    },
    "unitares-governance": {
      "type": "http",
      "url": "https://unitares.ngrok.io/mcp"
    }
  }
}
```

### Cursor MCP Config (ngrok Primary)

```json
{
  "mcpServers": {
    "anima": {
      "type": "sse",
      "url": "https://anima.ngrok.io/sse"
    },
    "unitares-governance": {
      "type": "http",
      "url": "https://unitares.ngrok.io/mcp"
    }
  }
}
```

### Pi Environment (UNITARES_URL)

**Option 1: ngrok (current)**
```bash
export UNITARES_URL="https://unitares.ngrok.io/sse"
```

**Option 2: Tailscale (if Mac on Tailscale)**
```bash
export UNITARES_URL="http://[Mac-Tailscale-IP]:8765/sse"
```

**Option 3: Local (same network)**
```bash
export UNITARES_URL="http://192.168.1.164:8765/sse"
```

---

## Stability & Fallbacks

### Multi-Layer Fallback Strategy

**Layer 1: Tailscale (Primary)**
- ✅ Most reliable (mesh VPN)
- ✅ Works anywhere
- ✅ Private & secure

**Layer 2: ngrok (Secondary)**
- ✅ Public access
- ✅ Debugging visibility
- ✅ Works if Tailscale down

**Layer 3: Local Network (Fallback)**
- ✅ Always available (same network)
- ✅ Fastest (no tunnel)
- ✅ No dependencies

### Implementation

**For Cursor:** Choose one URL (can't auto-fallback), but can switch easily:
- Remote work → Tailscale
- Debugging → ngrok
- Development → Local

**For Pi → Mac:** Can implement retry logic:
```python
# Try ngrok first
unitares_urls = [
    "https://unitares.ngrok.io/sse",  # Primary
    "http://[Mac-Tailscale-IP]:8765/sse",  # Fallback
    "http://192.168.1.164:8765/sse"  # Last resort
]
```

---

## Recommendations

### For Your Use Case

**Primary:** **Tailscale** for anima-mcp
- ✅ Private, reliable mesh VPN
- ✅ Persistent IPs
- ✅ Works anywhere

**Secondary:** **ngrok** for debugging/backup
- ✅ Public access when needed
- ✅ Dashboard for debugging
- ✅ Backup if Tailscale fails

**UNITARES:** Keep **ngrok** (already working)
- ✅ Public access
- ✅ Already configured
- ✅ Add Tailscale as fallback if needed

### Setup Priority

1. **Verify Tailscale** on both Mac and Pi
2. **Set up ngrok** on Pi (for backup/debugging)
3. **Use Tailscale** as primary in Cursor config
4. **Set UNITARES_URL** to ngrok (already working)

---

## Related

- **`docs/operations/NGROK_TUNNEL_SETUP.md`** - ngrok setup guide
- **`docs/CURSOR_MCP_SETUP.md`** - Cursor MCP configuration
- **`docs/operations/PI_ACCESS.md`** - SSH access (uses port 2222)

---

**Answer: No, ngrok doesn't replace Tailscale - use both for maximum reliability and accessibility!**
