"""Atomic artifact batches and recording provenance, using only the standard library."""

import json
import tempfile
from pathlib import Path

from check_update import replace_paths


def write_outputs(output_dir: Path, outputs: dict[str, bytes]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".stage-", dir=output_dir) as tmp:
        staged = []
        for name, data in outputs.items():
            path = Path(tmp) / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            staged.append((path, output_dir / name))
        replace_paths(staged)


def json_bytes(value) -> bytes:
    return (json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")


def source_identity(path: Path) -> dict:
    stat = path.stat()
    return {"path": str(path.resolve()), "size": stat.st_size, "mtime_ns": stat.st_mtime_ns}


def validate_source(path: Path, output_dir: Path) -> None:
    provenance = output_dir / "source.json"
    if provenance.exists() and json.loads(
        provenance.read_text(encoding="utf-8")
    ) != source_identity(path):
        raise ValueError(
            "Output directory belongs to a different or changed recording; choose a new output directory"
        )
