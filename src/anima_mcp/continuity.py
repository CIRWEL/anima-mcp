"""Continuity Kernel - export, verify, import, and status of Lumen's identity.

Five layers from most essential to most ephemeral: SOUL (DB identity),
AUTOBIOGRAPHY (DB events/history), SELF_KNOWLEDGE (models, preferences,
genesis), RELATIONSHIPS (messages, knowledge), EXPRESSION (canvas, brightness).
"""

import enum, hashlib, io, json, shutil, sqlite3, sys, tarfile, tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional


class KernelLayer(enum.Enum):
    SOUL = "soul"
    AUTOBIOGRAPHY = "autobiography"
    SELF_KNOWLEDGE = "self_knowledge"
    RELATIONSHIPS = "relationships"
    EXPRESSION = "expression"

_LAYER_FILES: Dict[KernelLayer, List[str]] = {
    KernelLayer.SOUL: [], KernelLayer.AUTOBIOGRAPHY: [],
    KernelLayer.SELF_KNOWLEDGE: [
        "self_model.json", "preferences.json", "trajectory_genesis.json",
        "last_schema.json", "metacognition_baselines.json", "patterns.json",
        "anima_history.json", "day_summaries.json",
    ],
    KernelLayer.RELATIONSHIPS: ["messages.json", "knowledge.json"],
    KernelLayer.EXPRESSION: ["canvas.json", "display_brightness.json"],
}
_DB_LAYERS = {KernelLayer.SOUL, KernelLayer.AUTOBIOGRAPHY}
ALL_LAYERS = set(KernelLayer)


# ── Dataclasses ──────────────────────────────────────────────────────

@dataclass
class KernelManifest:
    version: int; creature_id: str; born_at: str; exported_at: str
    layers: List[str]; checksums: Dict[str, str]
    total_alive_seconds: float; total_awakenings: int
    observation_count: int; genesis_present: bool

@dataclass
class VerificationResult:
    valid: bool; layers_present: List[str]; layers_missing: List[str]
    corrupted_files: List[str]; manifest: Optional[KernelManifest]

@dataclass
class ImportResult:
    success: bool; files_restored: List[str]
    files_backed_up: List[str]; warnings: List[str]

@dataclass
class KernelStatus:
    creature_id: Optional[str]; born_at: Optional[str]
    layers_present: List[str]; genesis_present: bool
    last_heartbeat: Optional[str]; alive_seconds: float
    observation_count: int; file_sizes: Dict[str, int]
    missing_critical: List[str]


# ── Helpers ──────────────────────────────────────────────────────────

def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()

def _read_identity(db_path: Path) -> dict:
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute("SELECT * FROM identity LIMIT 1").fetchone()
        return dict(row) if row else {}
    finally:
        conn.close()

def _count_rows(db_path: Path, table: str) -> int:
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    except sqlite3.OperationalError:
        return 0
    finally:
        conn.close()

def _collect_files(layers: set, state_dir: Path, db_path: Path) -> Dict[str, Path]:
    files = {}
    if layers & _DB_LAYERS:
        files["anima.db"] = db_path
    for layer in layers:
        for name in _LAYER_FILES.get(layer, []):
            p = state_dir / name
            if p.exists():
                files[name] = p
    return files


# ── Public API ───────────────────────────────────────────────────────

def export_kernel(db_path, state_dir, output_path, layers=None) -> KernelManifest:
    """Export kernel layers into a .tar.gz archive."""
    db_path, state_dir, output_path = Path(db_path), Path(state_dir), Path(output_path)
    chosen = set(layers) if layers else ALL_LAYERS

    identity = _read_identity(db_path) if db_path.exists() else {}
    files = _collect_files(chosen, state_dir, db_path)
    checksums = {name: _sha256(path) for name, path in files.items()}

    manifest = KernelManifest(
        version=1,
        creature_id=identity.get("creature_id", "unknown"),
        born_at=identity.get("born_at", "unknown"),
        exported_at=datetime.now().isoformat(),
        layers=sorted(l.value for l in chosen),
        checksums=checksums,
        total_alive_seconds=identity.get("total_alive_seconds", 0.0),
        total_awakenings=identity.get("total_awakenings", 0),
        observation_count=_count_rows(db_path, "state_history") if db_path.exists() else 0,
        genesis_present=(state_dir / "trajectory_genesis.json").exists(),
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(output_path, "w:gz") as tar:
        blob = json.dumps(manifest.__dict__, indent=2).encode()
        info = tarfile.TarInfo(name="kernel/manifest.json")
        info.size = len(blob)
        tar.addfile(info, io.BytesIO(blob))
        for name, path in files.items():
            tar.add(str(path), arcname=f"kernel/{name}")
    return manifest


def verify_kernel(archive_path) -> VerificationResult:
    """Verify archive integrity against its manifest."""
    archive_path = Path(archive_path)
    try:
        with tarfile.open(archive_path, "r:gz") as tar:
            mf = tar.extractfile("kernel/manifest.json")
            if not mf:
                return VerificationResult(False, [], [], ["manifest.json missing"], None)
            manifest = KernelManifest(**json.loads(mf.read()))
            corrupted = []
            with tempfile.TemporaryDirectory() as tmpdir:
                tar.extractall(tmpdir, filter="data")
                kdir = Path(tmpdir) / "kernel"
                for name, expected in manifest.checksums.items():
                    fp = kdir / name
                    if not fp.exists():
                        corrupted.append(f"{name} (missing)")
                    elif _sha256(fp) != expected:
                        corrupted.append(f"{name} (checksum mismatch)")
    except Exception as e:
        return VerificationResult(False, [], [], [str(e)], None)

    all_vals = {l.value for l in KernelLayer}
    return VerificationResult(
        valid=not corrupted,
        layers_present=list(manifest.layers),
        layers_missing=sorted(all_vals - set(manifest.layers)),
        corrupted_files=corrupted, manifest=manifest,
    )


def import_kernel(archive_path, target_db_path, target_state_dir, layers=None) -> ImportResult:
    """Import kernel from archive, backing up existing files first."""
    archive_path = Path(archive_path)
    target_db_path, target_state_dir = Path(target_db_path), Path(target_state_dir)

    vr = verify_kernel(archive_path)
    if not vr.valid:
        return ImportResult(False, [], [], [f"Verification failed: {vr.corrupted_files}"])

    chosen_vals = {l.value for l in (set(layers) if layers else ALL_LAYERS)}
    effective = chosen_vals & set(vr.layers_present)
    warnings, backed_up, restored = [], [], []

    backup_dir = target_state_dir / ".pre_import_backup"
    backup_dir.mkdir(parents=True, exist_ok=True)

    with tarfile.open(archive_path, "r:gz") as tar:
        with tempfile.TemporaryDirectory() as tmpdir:
            tar.extractall(tmpdir, filter="data")
            kdir = Path(tmpdir) / "kernel"

            # Restore DB if soul or autobiography requested
            if effective & {l.value for l in _DB_LAYERS}:
                src_db = kdir / "anima.db"
                if src_db.exists():
                    if target_db_path.exists():
                        shutil.copy2(target_db_path, backup_dir / "anima.db")
                        backed_up.append("anima.db")
                    target_db_path.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src_db, target_db_path)
                    restored.append("anima.db")
                else:
                    warnings.append("anima.db requested but not in archive")

            # Restore JSON files
            for layer in KernelLayer:
                if layer.value not in effective:
                    continue
                for name in _LAYER_FILES.get(layer, []):
                    src = kdir / name
                    if not src.exists():
                        continue
                    dst = target_state_dir / name
                    if dst.exists():
                        shutil.copy2(dst, backup_dir / name)
                        backed_up.append(name)
                    target_state_dir.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src, dst)
                    restored.append(name)

    return ImportResult(success=True, files_restored=restored,
                        files_backed_up=backed_up, warnings=warnings)


def get_kernel_status(db_path, state_dir) -> KernelStatus:
    """Quick health check of the current kernel on disk."""
    db_path, state_dir = Path(db_path), Path(state_dir)
    identity = _read_identity(db_path) if db_path.exists() else {}
    obs = _count_rows(db_path, "state_history") if db_path.exists() else 0

    present, missing, sizes = [], [], {}
    if db_path.exists():
        present.extend([KernelLayer.SOUL.value, KernelLayer.AUTOBIOGRAPHY.value])
        sizes["anima.db"] = db_path.stat().st_size
    else:
        missing.append("anima.db")

    for layer in (KernelLayer.SELF_KNOWLEDGE, KernelLayer.RELATIONSHIPS, KernelLayer.EXPRESSION):
        found = False
        for name in _LAYER_FILES[layer]:
            p = state_dir / name
            if p.exists():
                found = True
                sizes[name] = p.stat().st_size
        if found:
            present.append(layer.value)

    return KernelStatus(
        creature_id=identity.get("creature_id"),
        born_at=identity.get("born_at"),
        layers_present=present, genesis_present=(state_dir / "trajectory_genesis.json").exists(),
        last_heartbeat=identity.get("last_heartbeat_at"),
        alive_seconds=identity.get("total_alive_seconds", 0.0),
        observation_count=obs, file_sizes=sizes, missing_critical=missing,
    )


# ── CLI ──────────────────────────────────────────────────────────────

def _cli():
    import argparse
    _db = str(Path.home() / ".anima" / "anima.db")
    _dir = str(Path.home() / ".anima")
    _lv = [l.value for l in KernelLayer]
    p = argparse.ArgumentParser(prog="continuity", description="Lumen continuity kernel")
    sub = p.add_subparsers(dest="cmd")

    e = sub.add_parser("export"); e.add_argument("output")
    e.add_argument("--db", default=_db); e.add_argument("--dir", default=_dir)
    e.add_argument("--layers", nargs="+", choices=_lv)

    v = sub.add_parser("verify"); v.add_argument("archive")

    i = sub.add_parser("import"); i.add_argument("archive")
    i.add_argument("--db", default=_db); i.add_argument("--dir", default=_dir)
    i.add_argument("--layers", nargs="+", choices=_lv)

    s = sub.add_parser("status")
    s.add_argument("--db", default=_db); s.add_argument("--dir", default=_dir)

    a = p.parse_args()
    if a.cmd == "export":
        ly = [KernelLayer(x) for x in a.layers] if a.layers else None
        print(json.dumps(export_kernel(a.db, a.dir, a.output, ly).__dict__, indent=2))
    elif a.cmd == "verify":
        r = verify_kernel(a.archive)
        print(json.dumps({"valid": r.valid, "layers_present": r.layers_present,
              "layers_missing": r.layers_missing, "corrupted_files": r.corrupted_files}, indent=2))
        sys.exit(0 if r.valid else 1)
    elif a.cmd == "import":
        ly = [KernelLayer(x) for x in a.layers] if a.layers else None
        r = import_kernel(a.archive, a.db, a.dir, ly)
        print(json.dumps({"success": r.success, "files_restored": r.files_restored,
              "files_backed_up": r.files_backed_up, "warnings": r.warnings}, indent=2))
        sys.exit(0 if r.success else 1)
    elif a.cmd == "status":
        print(json.dumps(get_kernel_status(a.db, a.dir).__dict__, indent=2))
    else:
        p.print_help()

if __name__ == "__main__":
    _cli()
