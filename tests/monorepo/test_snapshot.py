import base64
import copy
import hashlib
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "cd/monorepo/runtime"))
from snapshot import materialize_snapshot, SnapshotError


class API:
    def __init__(self):
        self.commit_sha = "a" * 40
        self.tree_sha = "b" * 40
        self.requests = []
        self.blobs = {}
        self.entries = []
        for path, mode, content in [(".cloudopsworks", "040000", None),
                                     (".cloudopsworks/cloudopsworks-ci.yaml", "100644", b"schemaVersion: 2\n"),
                                     ("components", "040000", None),
                                     ("components/api", "040000", None),
                                     ("components/api/app.py", "100755", b"raise RuntimeError('NEVER DOWNLOAD OR EXECUTE')\n"),
                                     ("OWNERS", "100644", b"admins: []\n")]:
            sha = "c" * 40 if content is None else hashlib.sha1(b"blob " + str(len(content)).encode() + b"\0" + content).hexdigest()
            entry = {"path": path, "mode": mode, "sha": sha, "type": "tree" if content is None else "blob"}
            if content is not None:
                entry["size"] = len(content)
                self.blobs[sha] = {"sha": sha, "encoding": "base64", "size": len(content), "content": base64.b64encode(content).decode()}
            self.entries.append(entry)
        self.tree = {"sha": self.tree_sha, "truncated": False, "tree": self.entries}

    def repo(self, method, suffix, **kwargs):
        self.requests.append((method, suffix))
        if suffix == "/git/commits/" + self.commit_sha:
            return {"sha": self.commit_sha, "tree": {"sha": self.tree_sha}}
        if suffix == "/git/trees/" + self.tree_sha + "?recursive=1":
            return self.tree
        if suffix.startswith("/git/blobs/"):
            return self.blobs[suffix.rsplit("/", 1)[1]]
        raise AssertionError("unexpected API request")


class SnapshotTests(unittest.TestCase):
    def test_exact_config_bytes_and_metadata_only_source(self):
        api = API()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            result = materialize_snapshot(api, api.commit_sha, root)
            self.assertEqual((root / ".cloudopsworks/cloudopsworks-ci.yaml").read_bytes(), b"schemaVersion: 2\n")
            self.assertEqual((root / "components/api/app.py").read_bytes(), b"")
            self.assertEqual((root / "components/api/app.py").stat().st_mode & 0o111, 0)
            self.assertEqual(result["sourceSha"], api.commit_sha)
            self.assertNotIn("components/api/app.py", result["configBlobs"])
            source_blob = next(e["sha"] for e in api.entries if e["path"].endswith("app.py"))
            self.assertNotIn(("GET", "/git/blobs/" + source_blob), api.requests)
            self.assertTrue(all(method == "GET" for method, _ in api.requests))

    def reject(self, api, **bounds):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(SnapshotError) as caught:
                materialize_snapshot(api, api.commit_sha, Path(directory).resolve(), **bounds)
            self.assertRegex(str(caught.exception), "^snapshot_[a-z_]+$")

    def test_truncated_duplicate_traversal_link_and_submodule_rejected(self):
        api = API(); api.tree["truncated"] = True; self.reject(api)
        api = API(); api.entries.append(copy.deepcopy(api.entries[0])); self.reject(api)
        for path, mode, kind in [("../escape", "100644", "blob"), ("bad\\path", "100644", "blob"),
                                  ("link", "120000", "blob"), ("module", "160000", "commit")]:
            api = API(); api.entries.append({"path": path, "mode": mode, "type": kind, "sha": "d" * 40}); self.reject(api)
        api = API(); api.entries[:] = [e for e in api.entries if e["path"] != "components"]; self.reject(api)

    def test_wrong_blob_bytes_and_bounds_rejected(self):
        api = API(); blob = next(iter(api.blobs.values())); blob["content"] = base64.b64encode(b"FORGED CONFIG!!!!\n").decode(); self.reject(api)
        api = API(); self.reject(api, max_entries=1)
        api = API(); self.reject(api, max_configs=1)
        api = API(); self.reject(api, max_total_bytes=1)
        api = API(); self.reject(api, max_file_bytes=1)
        api = API(); api.tree["sha"] = "e" * 40; self.reject(api)


if __name__ == "__main__":
    unittest.main()
