"""Bounded immutable Git metadata/config snapshot; never checkout source code.

All regular source files become empty, nonexecutable placeholders. Only YAML
and the fixed OWNERS/Ruby marker data are downloaded. This supplies Tronador's
existing path-existence checks without running project code under credentials.
"""
from __future__ import annotations

import base64
import hashlib
from pathlib import Path, PurePosixPath
import re


class SnapshotError(ValueError):
    pass


def _sha(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{40}", value):
        raise SnapshotError("snapshot_object_identity")
    return value


def _path(value):
    if (not isinstance(value, str) or not value or len(value) > 1024
            or value.startswith("/") or "\\" in value or "//" in value
            or any(ord(c) < 32 or ord(c) == 127 for c in value)
            or any(p in ("", ".", "..", ".git") for p in value.split("/"))):
        raise SnapshotError("snapshot_path")
    return value


def materialize_snapshot(github, source_sha: str, root: Path, *,
                         max_entries: int = 50000, max_configs: int = 256,
                         max_file_bytes: int = 2 * 1024 ** 2,
                         max_total_bytes: int = 16 * 1024 ** 2) -> dict:
    """Populate caller-owned empty ephemeral root using independent GitHub data.

    The caller verifies host/caller/ref eligibility before invoking this read-only
    API boundary. Returned hashes bind data to the frozen source commit; they do
    not replace caller/run/publisher authorization. Partial failures leave only
    nonexecutable data for the caller to remove, and never grant an artifact trust.
    """
    source_sha = _sha(source_sha)
    root = Path(root)
    if (root.is_symlink() or not root.is_dir() or any(root.iterdir())
            or root.stat().st_mode & 0o077):
        raise SnapshotError("snapshot_workspace")
    # The Go authority rejects symlinks in ancestry; use the real private path.
    if root != root.resolve():
        raise SnapshotError("snapshot_workspace")
    commit = github.repo("GET", "/git/commits/" + source_sha)
    if not isinstance(commit, dict) or commit.get("sha") != source_sha:
        raise SnapshotError("snapshot_commit")
    tree_sha = _sha(commit.get("tree", {}).get("sha"))
    tree = github.repo("GET", "/git/trees/" + tree_sha + "?recursive=1")
    if (not isinstance(tree, dict) or tree.get("sha") != tree_sha
            or tree.get("truncated") is not False or not isinstance(tree.get("tree"), list)
            or len(tree["tree"]) > max_entries):
        raise SnapshotError("snapshot_tree")
    entries = {}
    configurations = []
    for entry in tree["tree"]:
        if not isinstance(entry, dict):
            raise SnapshotError("snapshot_tree")
        path = _path(entry.get("path"))
        if path in entries:
            raise SnapshotError("snapshot_duplicate_path")
        _sha(entry.get("sha"))
        kind = entry.get("type")
        mode = entry.get("mode")
        if not ((kind == "tree" and mode == "040000")
                or (kind == "blob" and mode in ("100644", "100755"))):
            raise SnapshotError("snapshot_link_or_submodule")
        entries[path] = entry
        if kind == "blob" and (path.endswith((".yaml", ".yml"))
                               or path in ("OWNERS", ".cloudopsworks/.ruby")):
            if (not isinstance(entry.get("size"), int) or isinstance(entry["size"], bool)
                    or not 0 <= entry["size"] <= max_file_bytes):
                raise SnapshotError("snapshot_config_size")
            configurations.append(path)
    if len(configurations) > max_configs:
        raise SnapshotError("snapshot_config_count")
    for path in entries:
        for parent in PurePosixPath(path).parents:
            if str(parent) != "." and entries.get(str(parent), {}).get("type") != "tree":
                raise SnapshotError("snapshot_parent")
    # Every path and collision has been checked before writing any local file.
    for path, entry in sorted(entries.items(), key=lambda item: (len(PurePosixPath(item[0]).parts), item[0])):
        target = root / path
        if entry["type"] == "tree":
            target.mkdir(mode=0o700)
        else:
            target.touch(mode=0o600)
    hashes = {}
    total = 0
    for path in sorted(configurations):
        entry = entries[path]
        blob = github.repo("GET", "/git/blobs/" + entry["sha"], limit=max_file_bytes * 2)
        if (not isinstance(blob, dict) or blob.get("sha") != entry["sha"]
                or blob.get("encoding") != "base64" or blob.get("size") != entry["size"]
                or not isinstance(blob.get("content"), str)):
            raise SnapshotError("snapshot_blob")
        try:
            content = base64.b64decode("".join(blob["content"].splitlines()), validate=True)
        except (ValueError, UnicodeError):
            raise SnapshotError("snapshot_blob") from None
        total += len(content)
        if len(content) != entry["size"] or total > max_total_bytes:
            raise SnapshotError("snapshot_config_size")
        actual = hashlib.sha1(b"blob " + str(len(content)).encode() + b"\0" + content).hexdigest()
        if actual != entry["sha"]:
            raise SnapshotError("snapshot_blob_hash")
        (root / path).write_bytes(content)
        hashes[path] = {"gitBlob": entry["sha"], "sha256": "sha256:" + hashlib.sha256(content).hexdigest()}
    return {"sourceSha": source_sha, "treeSha": tree_sha, "configBlobs": hashes}
