# Anima Pi Access

## Quick SSH
```bash
ssh pi-anima
```

## Details
- **Host**: 192.168.1.165
- **Port**: 2222
- **User**: unitares-anima
- **Key**: ~/.ssh/id_ed25519_pi

## Rsync (sync code to Pi)
```bash
rsync -avz --exclude='.venv' --exclude='*.db' --exclude='*.log' --exclude='__pycache__' \
  -e "ssh -p 2222 -i ~/.ssh/id_ed25519_pi" \
  /Users/cirwel/projects/anima-mcp/ \
  unitares-anima@192.168.1.165:/home/unitares-anima/anima-mcp/
```

## Restart Anima
```bash
ssh pi-anima "pkill -f 'anima --sse'; cd ~/anima-mcp && source .venv/bin/activate && ANIMA_ID='49e14444-b59e-48f1-83b8-b36a988c9975' nohup anima --sse --host 0.0.0.0 --port 8765 > anima.log 2>&1 &"
```

## Check Logs
```bash
ssh pi-anima "tail -50 ~/anima-mcp/anima.log"
```

## Check Status
```bash
ssh pi-anima "ps aux | grep anima | grep -v grep"
```
