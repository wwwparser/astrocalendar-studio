"""Нумерованные неизменяемые копии экспортированных выпусков."""
import datetime as dt
import hashlib
import json
from pathlib import Path


def archive_calendar(path: Path) -> dict:
    path = Path(path)
    content = path.read_bytes()
    digest = hashlib.sha256(content).hexdigest()
    folder = path.parent / "revisions" / path.stem
    folder.mkdir(parents=True, exist_ok=True)
    manifest = folder / "history.json"
    history = json.loads(manifest.read_text(encoding="utf-8")) if manifest.exists() else []
    if history and history[-1]["sha256"] == digest:
        return history[-1]
    version = len(history) + 1
    name = f"{path.stem}_v{version:03d}{path.suffix}"
    destination = folder / name
    destination.write_bytes(content)
    record = {"version": version, "file": name, "sha256": digest,
              "updated_at": dt.datetime.now(dt.timezone.utc).isoformat()}
    history.append(record)
    temporary = manifest.with_suffix(".tmp")
    temporary.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(manifest)
    return record
