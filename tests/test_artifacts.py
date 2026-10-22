"""Artifact transactions and recording identity."""

import pytest
from conftest import import_script

artifacts = import_script("diagnostics.py")


def test_replaced_recording_cannot_reuse_outputs(tmp_path):
    video = tmp_path / "meeting.mp4"
    video.write_bytes(b"original")
    out = tmp_path / "out"
    artifacts.write_outputs(
        out, {"source.json": artifacts.json_bytes(artifacts.source_identity(video))}
    )
    artifacts.validate_source(video, out)
    video.write_bytes(b"changed recording")
    with pytest.raises(ValueError, match="different or changed"):
        artifacts.validate_source(video, out)
