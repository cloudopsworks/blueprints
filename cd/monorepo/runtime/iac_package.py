"""Data-only preparation for IaC-owned Azure package publication.

This module never uploads a blob, deploys a workload, or acquires credentials.
The caller must supply a verified artifact and protected landing-zone settings.
Signed URIs are ephemeral sensitive provider inputs, never lifecycle records.
"""
from __future__ import annotations

import base64
import datetime as dt
import hashlib
import os
from pathlib import Path
import re
import stat
import tempfile
from urllib.parse import parse_qsl, urlencode


class PackageError(ValueError):
    """Only fixed codes: exceptions are safe to categorize without secret text."""


def _date(value: str) -> dt.datetime:
    try:
        result = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        if result.tzinfo is None:
            raise ValueError()
        return result.astimezone(dt.timezone.utc)
    except (ValueError, TypeError):
        raise PackageError("package_sas_time") from None


def private_blob_uri(account: str, container: str, prefix: str, digest: str,
                     basename: str, sas: str, *, now: dt.datetime | None = None,
                     minimum_lifetime: int = 600) -> str:
    """Construct an Azure public-cloud blob URI; never accept an arbitrary URL.

    A container/blob service SAS may grant read only. An account SAS, stored
    access policy, response override, duplicate/unknown parameter, insecure
    transport or unusable lifetime is rejected. Azure still verifies the
    signature against the exact generated account/container/object on GET.
    """
    if (not isinstance(account, str) or not re.fullmatch(r"[a-z0-9]{3,24}", account)
            or not isinstance(container, str)
            or not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{1,61})[a-z0-9]", container)
            or "--" in container):
        raise PackageError("package_destination")
    if (not isinstance(prefix, str) or len(prefix) > 512
            or not prefix or any(not re.fullmatch(r"[a-zA-Z0-9_-]+", p)
                                 for p in prefix.strip("/").split("/"))
            or prefix.startswith("/") or "//" in prefix):
        raise PackageError("package_destination")
    if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise PackageError("package_digest")
    if basename not in ("main.zip", "released-package.zip"):
        raise PackageError("package_basename")
    if (not isinstance(sas, str) or not 1 <= len(sas) <= 8192
            or "#" in sas or any(ord(c) < 32 for c in sas)):
        raise PackageError("package_sas")
    try:
        pairs = parse_qsl(sas.removeprefix("?"), keep_blank_values=True,
                          strict_parsing=True, max_num_fields=24)
    except ValueError:
        raise PackageError("package_sas") from None
    values = dict(pairs)
    allowed = {"sv", "spr", "st", "se", "sr", "sp", "sig", "sip",
               "skoid", "sktid", "skt", "ske", "sks", "skv", "saoid", "suoid", "scid"}
    if (len(values) != len(pairs) or set(values) - allowed
            or any(not v for v in values.values())
            or values.get("sp") != "r" or values.get("sr") not in ("b", "c")
            or values.get("spr") != "https"
            or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", values.get("sv", ""))):
        raise PackageError("package_sas_scope")
    try:
        if len(base64.b64decode(values.get("sig", ""), validate=True)) != 32:
            raise ValueError()
    except ValueError:
        raise PackageError("package_sas_signature") from None
    current = now or dt.datetime.now(dt.timezone.utc)
    if current.tzinfo is None or not 60 <= minimum_lifetime <= 3600:
        raise PackageError("package_sas_time")
    if _date(values.get("se", "")) <= current + dt.timedelta(seconds=minimum_lifetime):
        raise PackageError("package_sas_expired")
    if "st" in values and _date(values["st"]) > current:
        raise PackageError("package_sas_not_yet_valid")
    # Delegation validity cannot expire before the requested access expiry.
    delegation = {"skoid", "sktid", "skt", "ske", "sks", "skv"}
    if delegation & values.keys():
        if not delegation <= values.keys() or values["sks"] != "b":
            raise PackageError("package_sas_scope")
        if _date(values["skt"]) > current or _date(values["ske"]) < _date(values["se"]):
            raise PackageError("package_sas_time")
    object_name = f"{prefix.rstrip('/')}/{digest}/{basename}"
    return f"https://{account}.blob.core.windows.net/{container}/{object_name}?{urlencode(pairs)}"


def stage_zip(source: Path, root: Path, digest: str, *, limit: int = 1024 ** 3) -> Path:
    """Copy verified bytes into a digest-addressed provider-visible local path.

    A new package at the same transport filename changes zip_deploy_file's
    value. Hash mismatch/oversize/link inputs fail before a usable file exists.
    The caller owns and removes the protected ephemeral root after execution.
    """
    if not re.fullmatch(r"[0-9a-f]{64}", digest) or limit <= 0:
        raise PackageError("package_digest")
    root = Path(root)
    if root.is_symlink() or not root.is_dir():
        raise PackageError("package_workspace")
    directory = root / digest
    directory.mkdir(mode=0o700, exist_ok=True)
    if directory.is_symlink() or not directory.is_dir():
        raise PackageError("package_workspace")
    target = directory / "main.zip"
    descriptor = None
    temporary = None
    try:
        descriptor = os.open(source, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise PackageError("package_source")
        h = hashlib.sha256()
        total = 0
        with os.fdopen(descriptor, "rb") as src:
            descriptor = None
            with tempfile.NamedTemporaryFile(dir=directory, delete=False) as dst:
                temporary = Path(dst.name)
                while block := src.read(1024 * 1024):
                    total += len(block)
                    if total > limit:
                        raise PackageError("package_size")
                    h.update(block)
                    dst.write(block)
        if h.hexdigest() != digest:
            raise PackageError("package_digest")
        os.replace(temporary, target)
        temporary = None
        return target
    except OSError:
        raise PackageError("package_source") from None
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if temporary is not None:
            temporary.unlink(missing_ok=True)
