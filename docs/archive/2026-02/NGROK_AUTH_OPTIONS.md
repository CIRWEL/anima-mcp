# ngrok Auth Options for MCP Access

**Created:** January 12, 2026  
**Last Updated:** January 12, 2026  
**Status:** Active

---

## Challenge

**Problem:** ngrok tunnels are public by default - anyone with the URL can access.

**Requirement:** 
- ✅ Secure access (not wide open)
- ✅ Don't deny agents (they need access)
- ✅ Don't complicate access (keep it simple)

---

## Auth Options

### Option 1: Basic Auth (Recommended for Now)

**Simple username/password** - Agents can use, but public can't.

**Setup:**
```bash
# Start tunnel with basic auth
ngrok http 8765 --basic-auth="agent:password123"
```

**For agents:**
```json
{
  "anima": {
    "type": "sse",
    "url": "https://anima.ngrok.io/sse",
    "headers": {
      "Authorization": "Basic YWdlbnQ6cGFzc3dvcmQxMjM="  // base64(agent:password123)
    }
  }
}
```

**Pros:**
- ✅ Simple to set up
- ✅ Blocks public access
- ✅ Agents can use (just add header)

**Cons:**
- ⚠️ Password in config (but agents need it anyway)
- ⚠️ Not super secure (but better than open)

---

### Option 2: IP Allowlist (Future)

**Only allow specific IPs** - More secure, but requires knowing agent IPs.

**Setup:**
```bash
# In ngrok dashboard or config
# Add allowed IPs: your Mac IP, agent IPs, etc.
```

**Pros:**
- ✅ More secure
- ✅ No passwords needed

**Cons:**
- ❌ Requires knowing all agent IPs
- ❌ Breaks if IPs change
- ❌ Complicated for mobile/dynamic IPs

---

### Option 3: OAuth (Future - Most Secure)

**OAuth flow** - Most secure, but complex.

**Setup:**
- Configure OAuth provider
- Agents authenticate once
- Tokens refresh automatically

**Pros:**
- ✅ Most secure
- ✅ Industry standard

**Cons:**
- ❌ Complex setup
- ❌ Requires OAuth provider
- ❌ More moving parts

---

### Option 4: ngrok Edge (Future - Best Balance)

**ngrok Edge** - Built-in auth, IP restrictions, OAuth support.

**Setup:**
- Use ngrok Edge (paid feature)
- Configure auth policies
- Set IP allowlists
- OAuth support

**Pros:**
- ✅ Built-in auth options
- ✅ Flexible policies
- ✅ Dashboard management

**Cons:**
- ⚠️ Paid feature (but might be worth it)

---

## Recommended: Start Simple, Add Auth Later

### Phase 1: Public Tunnel (Now)

**For initial setup:**
- ✅ Get everything working
- ✅ Verify connectivity
- ✅ Test with agents

**Risk:** Public URL, but:
- URLs are long/random (security through obscurity)
- Can rotate URLs
- Monitor ngrok dashboard for abuse

### Phase 2: Basic Auth (Soon)

**Add basic auth:**
```bash
ngrok http 8765 --basic-auth="agent:secure-password"
```

**Update agent configs** with auth header.

**Benefit:** Blocks casual access, agents still work.

### Phase 3: IP Restrictions (Later)

**Add IP allowlist** if needed:
- Your Mac IP
- Known agent IPs
- Office/home IPs

**Benefit:** More secure, still simple for agents.

---

## Implementation: Basic Auth

### Step 1: Start Tunnel with Auth

```bash
# On Pi
ngrok http 8765 --basic-auth="anima-agent:your-secure-password"
```

**Or in systemd service:**
```ini
[Service]
ExecStart=/usr/local/bin/ngrok http --basic-auth="anima-agent:your-secure-password" 8765
```

### Step 2: Generate Auth Header

```bash
# On Mac
echo -n "anima-agent:your-secure-password" | base64
# Output: YW5pbWEtYWdlbnQ6eW91ci1zZWN1cmUtcGFzc3dvcmQ=
```

### Step 3: Update Cursor Config

**Note:** Cursor MCP config might not support headers directly. Options:

**Option A: Use ngrok's request header rewrite**
```bash
# In ngrok config or dashboard
# Rewrite requests to add header server-side
```

**Option B: Use ngrok Edge (paid)**
- Built-in auth support
- No config changes needed

**Option C: Keep public for now, add auth later**
- Monitor for abuse
- Rotate URLs if needed
- Add auth when ready

---

## Current Recommendation

**For now:** 
- ✅ **Start public** - Get everything working
- ✅ **Monitor** - Watch ngrok dashboard
- ✅ **Document** - Keep auth options ready

**Soon:**
- ✅ **Add basic auth** - Simple, effective
- ✅ **Update agents** - Add auth headers

**Later:**
- ✅ **Consider ngrok Edge** - If need more security
- ✅ **IP restrictions** - If needed

---

## Security Notes

**Public ngrok URLs:**
- ✅ Long/random URLs (hard to guess)
- ✅ Can rotate URLs
- ✅ Monitor dashboard for abuse
- ⚠️ Not truly secure (anyone with URL can access)

**Basic auth:**
- ✅ Blocks casual access
- ✅ Simple for agents
- ⚠️ Password in config (but agents need it)

**Best practice:**
- ✅ Use strong passwords
- ✅ Rotate passwords periodically
- ✅ Monitor access logs
- ✅ Add IP restrictions if needed

---

## For Agents

**Current:** Public URL (no auth needed)

**With basic auth:**
- Add `Authorization` header to requests
- Header format: `Basic base64(username:password)`
- Agents can store credentials securely

**Future:** OAuth or Edge auth (more secure, still agent-friendly)

---

## Related

- **`docs/operations/QUICK_NGROK_SETUP.md`** - Setup guide
- **`docs/operations/NGROK_TUNNEL_SETUP.md`** - Detailed guide

---

**Strategy: Start public, add auth when needed, keep it simple for agents!**
