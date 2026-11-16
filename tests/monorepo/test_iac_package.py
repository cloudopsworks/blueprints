"""Local byte/protocol proof only; never an Azure deployment test."""
import base64
import datetime as dt
import hashlib
import hmac
from pathlib import Path
import sys
import tempfile
import unittest
from urllib.parse import parse_qs, urlencode, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "cd/monorepo/runtime"))
from iac_package import PackageError, private_blob_uri, stage_zip


class PackageTests(unittest.TestCase):
    def setUp(self):
        self.now = dt.datetime(2026, 11, 13, tzinfo=dt.timezone.utc)
        self.fields = dict(sv="2023-11-03", spr="https", sp="r", sr="c",
                           se="2026-11-13T01:00:00Z",
                           sig=base64.b64encode(b"s" * 32).decode())
        self.digest = "a" * 64

    def uri(self, **changes):
        fields = dict(self.fields, **changes)
        return private_blob_uri("fixtureaccount", "packages", "components/api",
                                self.digest, "released-package.zip", urlencode(fields), now=self.now)

    def test_fixed_destination_and_secret_is_only_query(self):
        url = urlsplit(self.uri())
        self.assertEqual(url.hostname, "fixtureaccount.blob.core.windows.net")
        self.assertEqual(url.path, f"/packages/components/api/{self.digest}/released-package.zip")
        self.assertEqual(parse_qs(url.query)["sp"], ["r"])
        self.assertNotIn(self.fields["sig"], url.path)

    def test_token_scope_lifetime_and_safe_errors(self):
        for changes in ({"sp": "rw"}, {"sr": "s"}, {"spr": "https,http"},
                        {"se": "2026-11-12T23:59:00Z"}, {"st": "2026-11-14T00:00:00Z"},
                        {"sig": "SENTINEL_SECRET"}, {"si": "unverified-policy"},
                        {"ss": "b", "srt": "sco"}, {"rscd": "attachment"},
                        {"ske": "2026-11-12T23:59:00Z"}):
            with self.subTest(changes=list(changes)):
                with self.assertRaises(PackageError) as caught:
                    self.uri(**changes)
                self.assertRegex(str(caught.exception), r"^package_[a-z_]+$")
                self.assertNotIn("SENTINEL", str(caught.exception))
        with self.assertRaises(PackageError):
            private_blob_uri("fixtureaccount", "packages", "api", self.digest,
                             "released-package.zip", urlencode(self.fields) + "&sp=r", now=self.now)

    def test_destination_cannot_be_a_pr_url_or_escape(self):
        for account, container, prefix in [("evil.test/path", "packages", "api"),
                                            ("fixtureaccount", "packages", "../api"),
                                            ("fixtureaccount", "packages", "api?sig=x"),
                                            ("fixtureaccount", "packages", "/api")]:
            with self.assertRaises(PackageError):
                private_blob_uri(account, container, prefix, self.digest,
                                 "released-package.zip", urlencode(self.fields), now=self.now)

    def test_container_sas_read_protocol_exact_path_and_bytes(self):
        # Deterministic service-SAS verifier models the documented HTTPS GET
        # contract, not ARM/Functions execution. Signature binds account/container.
        key = b"fixture-only-signing-key"
        content = b"fixture private package"
        self.digest = hashlib.sha256(content).hexdigest()
        def string_to_sign(fields, canonical):
            return "\n".join([fields["sp"], fields.get("st", ""), fields["se"], canonical,
                              "", fields.get("sip", ""), fields["spr"], fields["sv"],
                              fields["sr"], "", "", "", "", "", "", ""])
        canonical = "/blob/fixtureaccount/packages"
        self.fields["sig"] = base64.b64encode(hmac.new(
            key, string_to_sign(self.fields, canonical).encode(), hashlib.sha256).digest()).decode()
        uri = self.uri()
        parsed = urlsplit(uri)
        fields = {k: v[0] for k, v in parse_qs(parsed.query).items()}
        supplied = base64.b64decode(fields["sig"])
        self.assertTrue(hmac.compare_digest(supplied, hmac.new(
            key, string_to_sign(fields, canonical).encode(), hashlib.sha256).digest()))
        self.assertEqual(fields["sp"], "r")
        self.assertEqual(hashlib.sha256(content).hexdigest(), self.digest)
        wrong = "/blob/fixtureaccount/foreign-container"
        self.assertFalse(hmac.compare_digest(supplied, hmac.new(
            key, string_to_sign(fields, wrong).encode(), hashlib.sha256).digest()))

    def test_changed_bytes_at_same_transport_path_change_provider_path(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "transport.zip"
            paths = []
            for content in (b"first", b"second"):
                source.write_bytes(content)
                digest = hashlib.sha256(content).hexdigest()
                path = stage_zip(source, root, digest)
                paths.append(path)
                self.assertEqual(path.read_bytes(), content)
                self.assertEqual(path.parent.name, digest)
            self.assertNotEqual(*paths)
            with self.assertRaises(PackageError):
                stage_zip(source, root, "0" * 64)
            with self.assertRaises(PackageError):
                stage_zip(source, root, hashlib.sha256(b"second").hexdigest(), limit=2)
            link = root / "link.zip"
            link.symlink_to(source)
            with self.assertRaises(PackageError):
                stage_zip(link, root, hashlib.sha256(b"second").hexdigest())
            self.assertFalse(any(root.glob("*/tmp*")))


if __name__ == "__main__":
    unittest.main()
