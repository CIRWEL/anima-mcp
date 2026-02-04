#!/usr/bin/env python3
"""
Call git_pull tool on Pi via HTTP/MCP endpoint.
Use this when SSH is not available but HTTP is.

Usage:
    python3 scripts/call_git_pull_via_http.py [--stash] [--restart] [--url URL]
"""

import json
import urllib.request
import urllib.error
import sys
import argparse

def call_git_pull(url: str, stash: bool = True, restart: bool = True):
    """Call git_pull tool on Pi via HTTP."""
    
    # MCP Streamable HTTP request format
    request_data = {
        "jsonrpc": "2.0",
        "method": "tools/call",
        "params": {
            "name": "git_pull",
            "arguments": {
                "stash": stash,
                "restart": restart
            }
        },
        "id": 1
    }
    
    try:
        req = urllib.request.Request(
            url,
            data=json.dumps(request_data).encode(),
            headers={"Content-Type": "application/json"}
        )
        
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read().decode())
            
            if "error" in result:
                print(f"❌ Error: {result['error']}")
                return False
            
            if "result" in result:
                output = result["result"]
                if isinstance(output, str):
                    output = json.loads(output)
                
                if output.get("success"):
                    print("✅ Git pull successful!")
                    print(f"Latest commit: {output.get('latest_commit', 'N/A')}")
                    if restart:
                        print("🔄 Server restarting...")
                    return True
                else:
                    print(f"❌ Git pull failed: {output.get('stderr', 'Unknown error')}")
                    return False
            
            print(f"Response: {json.dumps(result, indent=2)}")
            return False
            
    except urllib.error.HTTPError as e:
        print(f"❌ HTTP Error {e.code}: {e.reason}")
        try:
            error_body = e.read().decode()
            print(f"Response: {error_body}")
        except:
            pass
        return False
    except urllib.error.URLError as e:
        print(f"❌ Connection failed: {e.reason}")
        return False
    except Exception as e:
        print(f"❌ Error: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(description="Call git_pull on Pi via HTTP")
    parser.add_argument("--url", default="http://192.168.1.165:8766/mcp/",
                       help="Pi HTTP endpoint URL")
    parser.add_argument("--stash", action="store_true", default=True,
                       help="Stash local changes before pulling")
    parser.add_argument("--no-stash", dest="stash", action="store_false",
                       help="Don't stash local changes")
    parser.add_argument("--restart", action="store_true", default=True,
                       help="Restart server after pulling")
    parser.add_argument("--no-restart", dest="restart", action="store_false",
                       help="Don't restart server")
    
    args = parser.parse_args()
    
    print(f"🔗 Calling git_pull on Pi via {args.url}")
    print(f"   Stash: {args.stash}, Restart: {args.restart}")
    print()
    
    success = call_git_pull(args.url, stash=args.stash, restart=args.restart)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
