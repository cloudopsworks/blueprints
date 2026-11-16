"""Strict, dependency-free consumer of the monorepo v1 wire protocol.

The schema is an extracted copy of Tronador's versioned contract, not a YAML
configuration resolver. Shape validation never establishes GitHub/cloud trust;
privileged callers must additionally supply independently obtained link proofs.
"""
from __future__ import annotations

import argparse
import copy
import datetime as dt
import gzip
import hashlib
import io
import json
import math
import os
import shutil
from pathlib import Path, PurePosixPath
import re
import tarfile
from typing import Any
from urllib.parse import unquote, urlsplit
import zipfile

from executor import ExecutionError, Runner

MAX_DOCUMENT_BYTES = 4 * 1024 * 1024
MAX_ARCHIVE_BYTES = 1024 * 1024 * 1024
MAX_ARCHIVE_ENTRIES = 10000
API_VERSION = "cloudopsworks.io/v1"
SCHEMA_PATH = Path(__file__).with_name("schema") / "monorepo-v1.schema.json"
KUBERNETES = {"aws.eks", "gcp.gke", "azure.aks"}
STATIC = {"aws.s3-static", "gcp.storage-static", "azure.blob-static"}
API_TARGETS = {"aws.apigateway-rest", "gcp.apigateway", "azure.apim"}
FUNCTIONS = {"aws.lambda", "gcp.functions-gen2", "azure.functions"}
WEB = {"aws.beanstalk", "gcp.cloudrun", "gcp.appengine", "azure.containerapps", "azure.appservice"}
SCHEMA: dict[str, Any] | None = None


class ContractError(ValueError):
    """A bounded machine-readable validation failure without raw input values."""

    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


def fail(code: str, message: str) -> None:
    raise ContractError(code, message)


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_bytes(value)).hexdigest()


def payload_digest(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            fail("duplicate-key", "duplicate JSON object key")
        result[key] = value
    return result


def _constant(_: str) -> None:
    fail("non-finite-number", "non-finite JSON number")


def load_record(source: bytes | str | Path) -> dict[str, Any]:
    """Load untrusted JSON; strings contain JSON, Paths identify local files."""
    if isinstance(source, Path):
        if source.is_symlink() or not source.is_file() or source.stat().st_size > MAX_DOCUMENT_BYTES:
            fail("document-size", "record must be a regular bounded JSON file")
        data = source.read_bytes()
    elif isinstance(source, str):
        data = source.encode("utf-8", errors="strict")
    else:
        data = source
    if len(data) > MAX_DOCUMENT_BYTES:
        fail("document-size", "record exceeds 4 MiB")
    try:
        value = json.loads(data.decode("utf-8", errors="strict"), object_pairs_hook=_pairs, parse_constant=_constant)
    except (UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise ContractError("invalid-json", "record is not bounded UTF-8 JSON") from exc
    if not isinstance(value, dict):
        fail("invalid-record", "wire record must be an object")
    return value


def schema() -> dict[str, Any]:
    global SCHEMA
    if SCHEMA is None:
        SCHEMA = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    return SCHEMA


def _check(value: Any, rule: dict[str, Any], path: str, depth: int = 0, *, document: dict[str, Any] | None = None) -> None:
    """Evaluate the closed schema's finite keyword subset (no external refs)."""
    document = schema() if document is None else document
    if depth > 64:
        fail("document-depth", "wire record is too deeply nested")
    if "$ref" in rule:
        ref = rule["$ref"]
        if not ref.startswith("#/$defs/") or ref[8:] not in document.get("$defs", {}):
            fail("schema-invalid", "unsupported schema reference")
        _check(value, document["$defs"][ref[8:]], path, depth + 1, document=document)
    for union in ("oneOf", "anyOf"):
        if union in rule:
            matches = 0
            for option in rule[union]:
                try:
                    _check(value, option, path, depth + 1, document=document)
                    matches += 1
                except ContractError:
                    pass
            if matches == 0 or (union == "oneOf" and matches != 1):
                fail("schema-union", f"{path}: unsupported or ambiguous wire variant")
    if "const" in rule and (type(value) is not type(rule["const"]) or value != rule["const"]):
        fail("schema-const", f"{path}: incorrect fixed protocol value")
    if "enum" in rule and not any(type(value) is type(item) and value == item for item in rule["enum"]):
        fail("schema-enum", f"{path}: unsupported enumeration value")
    kind = rule.get("type")
    matches = {"object": isinstance(value, dict), "array": isinstance(value, list), "string": isinstance(value, str),
               "integer": type(value) is int, "number": type(value) in (int, float), "boolean": type(value) is bool,
               "null": value is None}
    kinds = kind if isinstance(kind, list) else [kind]
    if kind and not any(matches.get(item, False) for item in kinds):
        fail("schema-type", f"{path}: incorrect JSON type")
    if isinstance(value, dict):
        properties = rule.get("properties", {})
        if any(key not in value for key in rule.get("required", [])):
            fail("schema-required", f"{path}: missing required field")
        additional = rule.get("additionalProperties", True)
        if additional is False and any(key not in properties for key in value):
            fail("schema-unknown", f"{path}: unknown field")
        for key, item in value.items():
            sub = properties.get(key, additional if isinstance(additional, dict) else None)
            if sub:
                _check(item, sub, f"{path}.{key}", depth + 1, document=document)
        for bound, op in (("minProperties", lambda x, y: x < y), ("maxProperties", lambda x, y: x > y)):
            if bound in rule and op(len(value), rule[bound]):
                fail("schema-size", f"{path}: object size outside bounds")
    if isinstance(value, list):
        if rule.get("uniqueItems") and len({canonical_bytes(item) for item in value}) != len(value):
            fail("schema-unique", f"{path}: duplicate array member")
        for bound, op in (("minItems", lambda x, y: x < y), ("maxItems", lambda x, y: x > y)):
            if bound in rule and op(len(value), rule[bound]):
                fail("schema-size", f"{path}: array size outside bounds")
        if "items" in rule:
            for i, item in enumerate(value):
                _check(item, rule["items"], f"{path}[{i}]", depth + 1, document=document)
    if isinstance(value, str):
        if ("minLength" in rule and len(value) < rule["minLength"]) or ("maxLength" in rule and len(value) > rule["maxLength"]):
            fail("schema-size", f"{path}: string size outside bounds")
        if "pattern" in rule and re.search(rule["pattern"], value) is None:
            fail("schema-pattern", f"{path}: malformed protocol string")
        if rule.get("format") == "date-time":
            try:
                stamp = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
                if stamp.tzinfo is None:
                    raise ValueError("timezone required")
            except ValueError as exc:
                raise ContractError("schema-date", f"{path}: timestamp must include a timezone") from exc
    if type(value) in (int, float):
        if not math.isfinite(value) or ("minimum" in rule and value < rule["minimum"]) or ("maximum" in rule and value > rule["maximum"]):
            fail("schema-range", f"{path}: number outside bounds")


def safe_path(value: str, *, root: bool = False, output: bool = False) -> str:
    if not value or "\\" in value or re.search(r"[\x00-\x1f\x7f]", value) or value.startswith(("/", "~")):
        fail("unsafe-path", "path must be bounded and repository relative")
    parts = value.split("/")
    if value == "." and root:
        return value
    if any(part in ("", ".", "..") for part in parts) or re.match(r"^[A-Za-z]:", value):
        fail("unsafe-path", "path contains ambiguous or escaping segments")
    if any(part.casefold() == ".git" for part in parts) or (not output and parts[:2] == [".cloudopsworks", "out"]):
        fail("unsafe-path", "path names reserved metadata/output")
    return value


def rooted_path(root: Path, relative: str, *, must_exist: bool = True, output: bool = False) -> Path:
    safe_path(relative, root=True, output=output)
    root = root.resolve(strict=True)
    candidate = root
    for part in PurePosixPath(relative).parts:
        candidate = candidate / part
        if candidate.is_symlink():
            fail("unsafe-path", "symlink path is not allowed")
    try:
        candidate.resolve(strict=must_exist).relative_to(root)
    except (ValueError, OSError) as exc:
        raise ContractError("unsafe-path", "path escapes its trusted root or is missing") from exc
    return candidate


def _unique(values: list[Any], message: str) -> None:
    if len({canonical_bytes(item) for item in values}) != len(values):
        fail("duplicate-id", message)


def _relative_http_path(value: str) -> None:
    decoded = unquote(value)
    if not value.startswith("/") or value.startswith("//") or any(x in decoded for x in ("..", "\\", "?", "#")) or re.search(r"[\x00-\x20\x7f]", decoded):
        fail("unsafe-probe-path", "probe path must remain on the verified origin")
    if re.search(r"%(?:2f|5c|00|2e)", value, re.I):
        fail("unsafe-probe-path", "encoded probe separators are not permitted")


def _artifact(artifact: dict[str, Any], *, published: bool = False, repository: dict[str, str] | None = None) -> None:
    allowed = {"container": {"oci"}, "archive": {"zip", "tar.gz"}, "static": {"zip", "tar.gz"},
               "function": {"zip", "tar.gz", "oci"}, "openapi": {"openapi-json", "openapi-yaml"}}
    if artifact["format"] not in allowed[artifact["kind"]]:
        fail("artifact-format", "artifact kind and payload format disagree")
    location = artifact["location"]
    if location["kind"] == "local":
        safe_path(location["path"], output=True)
        if published:
            fail("unpublished-artifact", "complete release cannot contain a local artifact")
    elif location["kind"] == "actions-artifact":
        safe_path(location["path"], output=True)
        expected_prefix = "components-" + location["runId"] + "-" + location["runAttempt"] + "-"
        if not location["artifactName"].startswith(expected_prefix):
            fail("actions-artifact-name", "Actions artifact name disagrees with run identity")
        if repository and location["repositoryId"] != repository["id"]:
            fail("repository-mismatch", "Actions artifact belongs to another repository")
    elif location["kind"] == "oci":
        reference = location["reference"]
        if artifact["format"] != "oci" or not reference.endswith("@" + artifact["digest"]):
            fail("artifact-digest", "OCI reference must name the recorded immutable descriptor digest")
        if re.search(r"[\s\x00-\x1f]", reference) or "://" in reference or reference.startswith(("/", "-")):
            fail("artifact-location", "unsafe OCI registry reference")
    else:
        safe_path(location["name"])
        if "/" in location["name"] or location["tag"].startswith("-"):
            fail("artifact-location", "release asset identity is not a simple immutable name")
        if repository and location["repositoryId"] != repository["id"]:
            fail("repository-mismatch", "artifact belongs to another repository")


def _package(package: dict[str, Any]) -> None:
    kind = package["kind"]
    if kind == "container":
        safe_path(package["dockerfile"])
        safe_path(package["context"], root=True)
    elif kind == "archive":
        if not package["include"]:
            fail("package-empty", "archive requires explicit include paths")
        for item in package["include"]:
            safe_path(item, root=True)
    elif kind == "static":
        safe_path(package["directory"], root=True)
        safe_path(package["index"])
    elif kind == "function":
        safe_path(package["source"], root=True)
        if not package["mode"].startswith(package["provider"] + "-"):
            fail("function-provider", "function package mode and provider disagree")
    else:
        safe_path(package["file"])


def _readiness(target: dict[str, Any], workload: dict[str, Any] | None = None) -> None:
    readiness = target["readiness"]
    if readiness["intervalSeconds"] > readiness["deadlineSeconds"]:
        fail("readiness-timeout", "readiness interval exceeds its deadline")
    probe = readiness["probe"]
    kind = target["kind"]
    expected = {"lambda-invoke"} if kind == "aws.lambda" else {"static-http"} if kind in STATIC else {"http"}
    if kind == "gcp.functions-gen2" and target["trigger"]["kind"] == "eventarc":
        expected = {"gcp-eventarc"}
    if kind == "azure.functions":
        expected = {"http", "azure-function-admin"}
    if probe["kind"] not in expected:
        fail("readiness-mode", "probe mode is incompatible with the native target")
    if probe["kind"] in ("http", "static-http"):
        if probe["path"] is not None:
            _relative_http_path(probe["path"])
        elif workload is not None and workload["kind"] != "http":
            fail("readiness-path", "non-HTTP workloads require an explicit HTTP probe path")
    if probe["kind"] == "http":
        if probe["method"] == "GET" and probe["requestBody"]:
            fail("readiness-body", "GET probes require an empty request body")
        auth = probe["auth"]["kind"]
        if auth == "gcp-id-token" and target["provider"] != "gcp":
            fail("readiness-auth", "GCP audience tokens require a GCP target")
        if kind in KUBERNETES and auth != "none":
            fail("readiness-auth", "loopback Kubernetes health probe must be credential free")
        if kind == "aws.beanstalk" and (auth != "none" or probe["method"] != "GET" or probe["requestBody"]):
            fail("readiness-auth", "native Beanstalk HTTP permits only credential-free health GET")


def validate_appengine_configuration(config: dict[str, Any]) -> None:
    """Intrinsic semantics for sole-Go-generated closed app.yaml data."""
    _check(config, schema()["$defs"]["AppEngineConfiguration"], "$.appConfig")
    environment, runtime = config["environment"], config["runtime"]
    scaling = config["scaling"] or {}
    for key in ("entrypoint", "instanceClass"):
        value = config[key]
        if value is not None and (not value.strip() or re.search(r"[\x00-\x1f\x7f]", value)):
            fail("appengine-config-string", "App Engine generated string is invalid")
    if environment == "standard":
        if not config["entrypoint"] or not config["entrypoint"].strip():
            fail("appengine-config-entrypoint", "standard App Engine requires explicit entrypoint")
        if config["runtimeConfig"] is not None or not re.fullmatch(r"(nodejs|python|java|go|ruby|php)[0-9]+", runtime):
            fail("appengine-config-standard-runtime", "standard App Engine runtime configuration disagrees")
    else:
        if config["instanceClass"] is not None or scaling.get("kind") == "basic":
            fail("appengine-config-flex-mode", "flexible App Engine uses incompatible standard fields")
        if runtime == "custom":
            if config["runtimeConfig"] is not None:
                fail("appengine-config-custom-runtime", "custom App Engine cannot use native runtime configuration")
        elif runtime not in ("nodejs", "python", "java", "go", "ruby", "php", "aspnetcore") or config["runtimeConfig"] is None:
            fail("appengine-config-flex-runtime", "native flexible App Engine requires explicit runtime configuration")
        if scaling.get("kind") == "automatic" and (scaling["targetCpuUtilization"] is None or scaling["targetThroughputUtilization"] is not None):
            fail("appengine-config-flex-scaling", "flexible automatic scaling requires CPU policy only")
    for value in (config["runtimeConfig"] or {}).values():
        if not value.strip() or re.search(r"[\x00-\x1f\x7f]", value):
            fail("appengine-config-runtime", "runtime configuration string is invalid")
    durations = {}
    from decimal import Decimal
    for key in ("idleTimeout", "minPendingLatency", "maxPendingLatency"):
        if scaling.get(key) is not None:
            duration = Decimal(scaling[key][:-1])
            if duration <= 0 or duration > 86400:
                fail("appengine-config-duration", "App Engine scaling duration is outside bounds")
            durations[key] = duration
    for lower, upper in (("minPendingLatency", "maxPendingLatency"),):
        if lower in durations and upper in durations and durations[lower] > durations[upper]:
            fail("appengine-config-scaling-range", "App Engine scaling range is reversed")
    for lower, upper in (("minInstances", "maxInstances"), ("minIdleInstances", "maxIdleInstances")):
        if scaling.get(lower) is not None and scaling.get(upper) is not None and scaling[lower] > scaling[upper]:
            fail("appengine-config-scaling-range", "App Engine instance range is reversed")
    for key in ("targetCpuUtilization", "targetThroughputUtilization"):
        if scaling.get(key) is not None and scaling[key] <= 0:
            fail("appengine-config-scaling-range", "App Engine utilization must be positive")


def _target(target: dict[str, Any]) -> None:
    for key, value in target.items():
        if key not in ("readiness",) and isinstance(value, str) and re.search(r"[\x00-\x1f\x7f]", value):
            fail("unsafe-resource", "resource data contains control characters")
    if target.get("prefix") is not None:
        safe_path(target["prefix"])
    if target.get("appConfig") is not None:
        safe_path(target["appConfig"])
    if target["kind"] == "gcp.appengine" and target.get("appConfigResolved") is not None:
        config = target["appConfigResolved"]
        validate_appengine_configuration(config)
        if (config["service"] != target["service"] or target.get("runtime") not in (None, "", config["runtime"])
                or target.get("appEnvironment") not in (None, "", config["environment"])
                or target.get("iac", {}).get("entrypoint") not in (None, "", config["entrypoint"])):
            fail("appengine-config-conflict", "App Engine generated configuration differs from target")
    for value in (target.get("iac", {}).get("sourcePrefix"), target.get("iac", {}).get("packageStorage", {}).get("prefix")):
        if value:
            safe_path(value.rstrip("/"))
    if target['kind']=='aws.apigateway-rest' and not target.get('restApiId'):
        if target.get('ownership')!='managed' or not target.get('apiName') or not target.get('apiVersion'):
            fail('api-identity', 'fresh managed REST API requires explicit name and version; existing APIs require exact ID')
    _readiness(target)


def _binding(package: dict[str, Any], workload: dict[str, Any], target: dict[str, Any]) -> None:
    kind = target["kind"]
    if workload["kind"] == "http":
        _relative_http_path(workload["healthPath"])
    expected = "static" if kind in STATIC else "api" if kind in API_TARGETS else "function" if kind in FUNCTIONS else "http"
    if workload["kind"] != expected:
        fail("workload-target", "normal workload is incompatible with target family")
    pk = package["kind"]
    if kind in KUBERNETES | {"gcp.cloudrun", "azure.containerapps"} and pk != "container":
        fail("package-target", "target requires an immutable container package")
    if kind in STATIC and pk != "static" or kind in API_TARGETS and pk != "openapi":
        fail("package-target", "target and package kinds disagree")
    if kind in FUNCTIONS:
        if pk != "function" or package["provider"] != target["provider"]:
            fail("package-target", "native function target requires its provider handler package")
        required_mode = {"aws.lambda": "aws-" + ("image" if target.get("packageMode") == "image" else "zip"),
                         "gcp.functions-gen2": "gcp-gen2", "azure.functions": "azure-" + target.get("packageMode", "zip")}[kind]
        if package["mode"] != required_mode:
            fail("package-mode", "function target package mode does not match")
    if kind == "gcp.appengine" and target.get("appConfigResolved") is not None:
        config = target["appConfigResolved"]
        if (pk == "container" and (config["runtime"] != "custom" or config["environment"] != "flexible")
                or pk == "archive" and config["runtime"] == "custom"):
            fail("appengine-config-package-mode", "App Engine configuration and package modes disagree")
    if kind == "azure.appservice" and (target["packageMode"] == "container") != (pk == "container"):
        fail("package-mode", "App Service package mode does not match")
    _readiness(target, workload)


def _preview_projection(component: dict[str, Any]) -> None:
    projection = component["preview"]
    package = component["package"]
    if projection["mode"] == "artifact-only":
        if package["kind"] != "openapi":
            fail("preview-projection", "only OpenAPI is artifact-only in previews")
        return
    _relative_http_path(projection["healthPath"])
    source = projection["source"]
    if source == "main" and package["kind"] != "container" or source == "static" and package["kind"] != "static" or source == "function" and package["kind"] != "function":
        fail("preview-projection", "preview projection does not match the normal package")
    if package["kind"] == "function" and source != "function":
        fail("function-preview-handler-required", "function previews require an invocation-tested handler projection")
    if source in ("dockerfile", "function"):
        safe_path(projection["dockerfile"])
        safe_path(projection["context"], root=True)
    if source == "function":
        _relative_http_path(projection["invokePath"])
        if not projection["invokeTest"]["requestBody"]:
            fail("preview-handler", "function preview requires a real invocation assertion")


def _component(component: dict[str, Any]) -> None:
    safe_path(component["path"], root=True)
    language = component["language"]
    profile = component["buildProfile"]
    profiles = {"dotnet": {"dotnet"}, "go": {"go"}, "java": {"maven", "gradle"}, "node": {"npm", "pnpm", "yarn"},
                "python": {"python"}, "rust": {"cargo"}, "ruby": {"bundler", "rails"}}
    if profile not in profiles[language] or (component["framework"] == "rails") != (profile == "rails"):
        fail("build-profile", "language, framework and build profile disagree")
    _unique(component["dependsOn"], "duplicate dependency")
    _unique(component["targetIds"], "duplicate target binding")
    _package(component["package"])
    _preview_projection(component)
    if component["package"]["kind"] == "function":
        if component["framework"] == "rails" or language == "rust" and component["package"]["provider"] == "gcp":
            fail("function-runtime", "unsupported native function runtime")
    _merge_toolchains([component])


def _merge_toolchains(components: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[tuple[str, str], dict[str, Any]] = {}
    for component in components:
        for tool in component["toolchains"]:
            expected_distribution = 'temurin' if tool['tool'] == 'java' else 'default'
            if tool['distribution'] != expected_distribution:
                fail('toolchain-distribution', 'tool distribution is not supported by the fixed installer')
            _unique(tool["components"], "duplicate toolchain component")
            if component["id"] not in tool["components"]:
                fail("toolchain-owner", "toolchain requirement omits its owner")
            key = (tool["tool"], tool["distribution"])
            if key in merged and merged[key]["version"] != tool["version"]:
                fail("toolchain-version-conflict", "dependency closure requests incompatible exact tool versions")
            entry = merged.setdefault(key, {**tool, "components": []})
            entry["components"] = sorted(set(entry["components"]) | set(tool["components"]))
    return [merged[key] for key in sorted(merged)]


def _validate_plan(plan: dict[str, Any]) -> None:
    components = plan["components"]
    _unique([c["id"] for c in components], "duplicate component ID")
    _unique([t["id"] for t in plan["targets"]], "duplicate target ID")
    by_id = {c["id"]: c for c in components}
    targets = {t["id"]: t for t in plan["targets"]}
    if sum(len(c["targetIds"]) for c in components) > 256:
        fail("request-limit", "target-component request count exceeds 256")
    paths: list[str] = []
    for component in components:
        _component(component)
        path = component["path"]
        if path == "." and (len(components) != 1 or component["language"] != "ruby"):
            fail("component-root", "root component is reserved for standalone Ruby")
        if path != "." and any(path.casefold() == p.casefold() or path.casefold().startswith(p.casefold() + "/") or p.casefold().startswith(path.casefold() + "/") for p in paths):
            fail("component-overlap", "component source paths overlap")
        paths.append(path)
        if any(d not in by_id for d in component["dependsOn"]):
            fail("dependency-missing", "unknown dependency")
        for target_id in component["targetIds"]:
            if target_id not in targets:
                fail("target-missing", "unknown target binding")
            _binding(component["package"], component["workload"], targets[target_id])
    for target in targets.values():
        _target(target)
    closure_cache: dict[str, set[str]] = {}
    visiting: set[str] = set()
    visited: set[str] = set()
    def closure(owner: str) -> set[str]:
        if owner in closure_cache:
            return closure_cache[owner]
        if owner in visiting:
            fail("dependency-cycle", "component dependencies contain a cycle")
        visiting.add(owner)
        result = {owner}
        for dependency in by_id[owner]["dependsOn"]:
            result |= closure(dependency)
        visiting.remove(owner)
        visited.add(owner)
        closure_cache[owner] = result
        return result
    for owner in by_id:
        if owner not in visited:
            closure(owner)
    selected = [s["componentId"] for s in plan["buildSelection"]]
    rows = plan["matrix"]["include"]
    _unique(selected, "duplicate build selection")
    _unique([r["componentId"] for r in rows], "duplicate matrix row")
    if selected != [r["componentId"] for r in rows] or plan["buildNoop"] != (not selected):
        fail("selection-mismatch", "matrix, selection and no-op flag disagree")
    for row in rows:
        owner = row["componentId"]
        if owner not in by_id:
            fail("component-missing", "matrix references an unknown component")
        order = row["closure"]
        _unique(order, "duplicate closure component")
        if not order or order[-1] != owner or set(order) != closure(owner):
            fail("closure-incomplete", "dependency closure is incomplete or owner is not last")
        seen: set[str] = set()
        for ident in order:
            if not set(by_id[ident]["dependsOn"]) <= seen:
                fail("closure-order", "dependency closure is not topological")
            seen.add(ident)
        expected = _merge_toolchains([by_id[c] for c in order])
        if sorted(row["toolchains"], key=lambda t: (t["tool"], t["distribution"])) != expected:
            fail("toolchain-closure", "matrix toolchains do not match the complete dependency closure")
    _unique(plan["removedComponents"], "duplicate removed component")
    if set(plan["removedComponents"]) & set(by_id):
        fail("component-removed", "active component also marked removed")
    policy = plan["previewPolicy"]
    if policy["enabled"] != bool(policy["targets"]):
        fail("preview-policy", "preview enablement and target list disagree")
    _unique([p["targetId"] for p in policy["targets"]], "duplicate preview target")
    for item in policy["targets"]:
        if item["targetId"] not in targets or targets[item["targetId"]]["kind"] not in KUBERNETES:
            fail("preview-target", "previews require a configured Kubernetes target")
    validate_resource_ownership([{ "componentId": c["id"], "target": targets[t]} for c in components for t in c["targetIds"]])


def claims_overlap(first: str, second: str) -> bool:
    if first == second:
        return True
    def typed(value):
        if value.startswith('prefix:'):
            return 'prefix', value[7:]
        if value.startswith('object:'):
            return 'object', value[7:]
        return 'resource', value
    a, left = typed(first)
    b, right = typed(second)
    if a == 'prefix' and b in ('prefix','object') and right.startswith(left):
        return True
    if b == 'prefix' and a in ('prefix','object') and left.startswith(right):
        return True
    return False


def validate_resource_ownership(bindings: list[dict[str, Any]], identities: dict[str, str] | None = None) -> None:
    """Reject known collisions; trusted provider resolution adds canonical aliases."""
    claims: list[tuple[str, str | None]] = []
    for binding in bindings:
        target = binding["target"]
        kind = target["kind"]
        identity = binding.get("providerIdentity") or (identities or {}).get(target["authRef"])
        account = identity or target.get("project") or target.get("subscriptionId") or "unresolved:" + target["authRef"]
        parent = f"{target['provider']}:{str(account).casefold()}:{target.get('region', '')}:"
        prefix = None
        if kind in KUBERNETES:
            claim = parent + "cluster:" + target["cluster"] + ":namespace:" + target["namespace"] + ":release:" + binding["componentId"]
        elif kind in STATIC:
            claim = parent + "storage:" + target.get("bucket", target.get("account", "")) + ":" + target.get("container", "")
            prefix = target["prefix"].strip("/")
        elif kind == "aws.lambda":
            claim = parent + "lambda:" + target["functionName"].split(":function:")[-1].split(":")[0]
        elif kind == "aws.beanstalk":
            claim = parent + "beanstalk:" + target["environmentName"]
        elif kind == "aws.apigateway-rest":
            identity=target.get('restApiId')
            if not identity:
                if target.get('ownership')!='managed' or not target.get('apiName') or not target.get('apiVersion'):
                    fail('api-identity', 'REST API ownership has no exact existing ID or explicit fresh managed selector')
                identity='new-name:'+target['apiName']
            claim = parent + "rest-api:" + identity
        elif kind == "gcp.appengine":
            claim = f"gcp:{str(account).casefold()}:appengine:" + target["service"]
        elif kind == "gcp.apigateway":
            claim = parent + "gateway:" + target["gateway"]
        elif kind.startswith("gcp."):
            claim = parent + kind + ":" + target.get("service", target.get("functionName", ""))
        elif kind == "azure.apim":
            claim = parent + target["resourceGroup"].casefold() + ":apim:" + target["serviceName"] + ":" + target["apiId"]
        elif kind in ('azure.appservice','azure.functions'):
            claim = parent + target['resourceGroup'].casefold() + ':site:' + target['appName'].casefold()
            slot=target.get('slot','production').casefold()
            prefix='' if slot in ('','production') else 'slots/'+slot
        else:
            claim = parent + target["resourceGroup"].casefold() + ":app:" + target["appName"].casefold()
        for old, old_prefix in claims:
            overlap = prefix in (None, "") or old_prefix in (None, "") or prefix == old_prefix or prefix.startswith(old_prefix + "/") or old_prefix.startswith(prefix + "/")
            if claim == old and overlap:
                fail("resource-ownership", "multiple component bindings claim one mutable cloud resource")
        claims.append((claim, prefix))
        for extra in binding.get("resourceClaims", []):
            if any(claims_overlap(extra, old) for old, _ in claims):
                fail("resource-ownership", "resolved cloud resource aliases collide")
            claims.append((extra, None))


def validate_shape(record: dict[str, Any]) -> dict[str, Any]:
    """Validate only the frozen finite schema, without proving semantic trust."""
    _check(record, schema(), "$")
    return record


def validate_record(record: dict[str, Any]) -> dict[str, Any]:
    validate_shape(record)
    kind = record["kind"]
    for owner in [record, *record.get("components", [])]:
        for key in ("mainArtifact", "previewArtifact", "artifact"):
            artifact = owner.get(key)
            location = artifact.get("location", {}) if artifact else {}
            if location.get("kind") == "actions-artifact":
                expected = "components-" + location["runId"] + "-" + location["runAttempt"] + "-" + owner.get("componentId", "")
                if location["artifactName"] != expected:
                    fail("actions-artifact-owner", "Actions artifact component identity disagrees")
    if kind == "BuildPlan":
        _validate_plan(record)
    elif kind == "ComponentResult":
        success = record["status"] == "succeeded"
        if success != (record["error"] is None) or success and record["mainArtifact"] is None:
            fail("result-status", "component status, error and main artifact disagree")
        for name in ("mainArtifact", "previewArtifact"):
            artifact = record[name]
            if artifact:
                _artifact(artifact, repository=record["repository"])
                if artifact["sourceSha"] != record["headSha"] or artifact["builtVersion"] != record["version"]:
                    fail("artifact-provenance", "component result artifact belongs to a different build")
        if record["previewArtifact"] and record["previewArtifact"]["kind"] != "container":
            fail("preview-artifact", "preview artifact must be an immutable container")
    elif kind == "ReleaseManifest":
        if record["tag"] != "v" + record["version"]:
            fail("release-tag", "release tag and repository version disagree")
        _unique([c["componentId"] for c in record["components"]], "duplicate release component")
        _unique([t["id"] for t in record["targets"]], "duplicate release target")
        targets = {t["id"]: t for t in record["targets"]}
        bindings = []
        for target in targets.values():
            _target(target)
        for component in record["components"]:
            _package(component["package"])
            if component["mainArtifact"]["kind"] != component["package"]["kind"]:
                fail("artifact-kind", "release package and artifact kind disagree")
            for name in ("mainArtifact", "previewArtifact"):
                if component[name]:
                    _artifact(component[name], published=True, repository=record["repository"])
            _unique(component["targetIds"], "duplicate release component binding")
            for ident in component["targetIds"]:
                if ident not in targets:
                    fail("target-missing", "release component references an unknown target")
                _binding(component["package"], component["workload"], targets[ident])
                bindings.append({"componentId": component["componentId"], "target": targets[ident]})
        validate_resource_ownership(bindings)
    elif kind == "DeploymentRequest":
        _package(record["package"])
        _target(record["target"])
        _artifact(record["artifact"], published=True, repository=record["repository"])
        if record["artifact"]["kind"] != record["package"]["kind"]:
            fail("artifact-kind", "deployment artifact and package disagree")
        _binding(record["package"], record["workload"], record["target"])
    elif kind == "DeploymentResult":
        success = record["status"] == "succeeded"
        if success != record["ready"] or success != (record["error"] is None):
            fail("result-status", "deployment status, ready and error disagree")
    elif kind == "PreviewState":
        _unique([c["componentId"] for c in record["components"]], "duplicate preview component")
        if record["phase"] == "ready" and (record["isolation"] is None or any(c["status"] not in ("ready", "artifact-only") for c in record["components"])):
            fail("preview-isolation", "ready preview requires current isolation and successful components")
        for component in record["components"]:
            state = component["status"]
            if state == "ready" and (component["releaseName"] is None or component["desiredDigest"] is None or component["desiredDigest"] != component["successfulDigest"] or component["error"] is not None):
                fail("preview-component", "ready preview component identity or digest mismatch")
            if state == "artifact-only" and (component["releaseName"] is not None or component["desiredDigest"] is None):
                fail("preview-component", "artifact-only preview must not create a workload")
            if state == "removed" and any(component[n] is not None for n in ("releaseName", "desiredDigest", "successfulDigest")):
                fail("preview-component", "removed preview must not retain workload identity")
            if state == "failed" and component["error"] is None:
                fail("preview-component", "failed preview must carry an error")
    return record


def validate_linked(record: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """Apply independently verified context; caller owns obtaining API proofs."""
    validate_record(record)
    for field in ("repository", "componentId", "headSha", "version", "targetId"):
        if field in context and field in record and context[field] != record[field]:
            fail("linked-identity", "record does not match trusted execution identity")
    actions = context.get("actionsArtifact")
    if actions:
        found = False
        for owner in [record, *record.get("components", [])]:
            for key in ("mainArtifact", "previewArtifact", "artifact"):
                artifact = owner.get(key)
                location = artifact.get("location", {}) if artifact else {}
                if location.get("kind") == "actions-artifact":
                    found = True
                    if any(location[field] != actions.get(field) for field in ("repositoryId", "runId", "runAttempt", "artifactId", "artifactName")):
                        fail("actions-artifact-context", "Actions artifact disagrees with independent API proof")
        if not found:
            fail("actions-artifact-context", "Actions artifact API proof has no matching record")
    account = context.get("resolvedAccount")
    if account and account.get("expected") != account.get("actual"):
        fail("resolved-account-mismatch", "resolved cloud account differs from frozen identity")
    plan = context.get("plan")
    if plan:
        validate_record(plan)
        if record.get("repository") != plan["repository"] or record.get("headSha", plan["headSha"]) != plan["headSha"] or record.get("version", plan["version"]) != plan["version"]:
            fail("linked-identity", "record does not belong to trusted build plan")
        if record["kind"] == "ComponentResult":
            component = next((c for c in plan["components"] if c["id"] == record["componentId"]), None)
            if component is None or record["componentId"] not in {item["componentId"] for item in plan["buildSelection"]}:
                fail("linked-identity", "result component was not selected by trusted plan")
            context = {**context, "component": component}
    if record["kind"] == "DeploymentReceipt":
        proof = context.get("githubDeployment")
        if not proof or str(proof.get("id")) != record["githubDeploymentId"] or str(proof.get("statusId")) != record["githubStatusId"] or proof.get("status") != "success":
            fail("receipt-unverified", "deployment receipt requires independently verified successful GitHub status")
        for field in ("repository", "componentId", "targetId", "artifactDigest", "targetConfigDigest", "idempotencyKey"):
            if proof.get(field) != record[field]:
                fail("receipt-unverified", "GitHub deployment proof does not match receipt")
    if record["kind"] == "ReleaseManifest":
        release = context.get("githubRelease")
        for component in record["components"]:
            for key in ("mainArtifact", "previewArtifact"):
                artifact = component.get(key)
                if artifact and artifact["location"]["kind"] == "actions-artifact":
                    fail("unpublished-artifact", "Public release cannot retain an expiring Actions artifact")
        if not release or release.get("draft") is not False or release.get("tag") != record["tag"] or release.get("targetCommitish", release.get("headSha")) != record["headSha"] or release.get("assetsVerified") is not True:
            fail("release-unverified", "release baseline requires verified published tag/source identity")
        if "activeComponents" in context and set(context["activeComponents"]) != {c["componentId"] for c in record["components"]}:
            fail("release-incomplete", "complete manifest must include every active component")
    if record["kind"] == "ComponentResult" and "component" in context:
        component = context["component"]
        if component["id"] != record["componentId"]:
            fail("linked-identity", "component result belongs to another component")
        if record["status"] == "succeeded" and component["preview"]["mode"] == "container" and record["previewArtifact"] is None:
            fail("preview-artifact", "declared container preview output is missing")
    if record["kind"] == "DeploymentRequest":
        manifest = context.get("manifest")
        if manifest:
            validate_record(manifest)
            entries = {c["componentId"]: c for c in manifest["components"]}
            item = entries.get(record["componentId"])
            if not item or manifest["repository"] != record["repository"] or manifest["version"] != record["releaseVersion"] or manifest["headSha"] != record["releaseHeadSha"] or digest(manifest) != record["manifestDigest"] or item["mainArtifact"] != record["artifact"] or item["workload"] != record["workload"] or item["package"] != record["package"] or record["target"] not in manifest["targets"] or record["target"]["id"] not in item["targetIds"]:
                fail("manifest-mismatch", "deployment request is not bound to complete manifest data")
    if record["kind"] == "PreviewState":
        for field in ("prNumber", "targetId", "namespace", "runId"):
            if field in context and record.get(field) != context[field]:
                fail("linked-identity", "preview state does not match trusted run identity")
    if "bindings" in context:
        validate_resource_ownership(context["bindings"], context.get("providerIdentities"))
    return record


def _archive_name(name: str) -> str:
    name = name.removeprefix("./")
    safe_path(name.rstrip("/"))
    return name.rstrip("/")


def _layer_entries(data: bytes) -> None:
    """Interpret links in a virtual image root; never follow links on the host."""
    links, entries = {}, {}
    def normalize(parts):
        result = []
        for part in parts:
            if part in ('', '.'):
                continue
            if part == '..':
                if not result:
                    fail('unsafe-archive', 'image link escapes virtual root')
                result.pop()
            else:
                if '\\' in part or re.search(r'[\x00-\x1f\x7f]', part):
                    fail('unsafe-archive', 'image link contains unsafe characters')
                result.append(part)
        return result
    try:
        with tarfile.open(fileobj=io.BytesIO(data), mode='r:') as archive:
            total = 0
            for index, member in enumerate(archive):
                name = _archive_name(member.name)
                if index >= MAX_ARCHIVE_ENTRIES or name in entries or not (member.isfile() or member.isdir() or member.issym() or member.islnk()):
                    fail('unsafe-archive', 'unsafe or duplicate image layer entry')
                total += member.size
                if total > MAX_ARCHIVE_BYTES:
                    fail('archive-size', 'image layer exceeds expansion bound')
                entries[name] = member
                if member.issym() or member.islnk():
                    target = member.linkname
                    if not target or re.match(r'^[A-Za-z]:', target):
                        fail('unsafe-archive', 'image link target is invalid')
                    base = [] if target.startswith('/') or member.islnk() else name.split('/')[:-1]
                    links[name] = normalize(base + target.split('/'))
            if any(data[archive.offset:]):
                fail('unsafe-archive', 'image layer contains non-padding trailing bytes')
        def resolve(parts, chain):
            for index in range(1, len(parts) + 1):
                prefix = '/'.join(parts[:index])
                if prefix in links:
                    if prefix in chain or len(chain) > 64:
                        fail('unsafe-archive', 'image link graph contains a cycle')
                    return resolve(links[prefix] + parts[index:], chain | {prefix})
            return '/'.join(parts)
        for name, member in entries.items():
            resolved = resolve(name.split('/'), set())
            if member.islnk() and (resolved not in entries or not entries[resolved].isfile()):
                fail('unsafe-archive', 'image hardlink does not identify a regular file')
    except (tarfile.TarError, OSError) as exc:
        raise ContractError('invalid-archive', 'invalid image layer') from exc


def _tar_entries(data: bytes) -> dict[str, bytes]:
    entries: dict[str, bytes] = {}
    total = 0
    try:
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:*") as archive:
            for index, member in enumerate(archive):
                if index >= MAX_ARCHIVE_ENTRIES or not (member.isdir() or member.isfile()):
                    fail("unsafe-archive", "archive entry type or count is unsafe")
                name = _archive_name(member.name)
                if name in entries:
                    fail("unsafe-archive", "duplicate archive entry")
                if member.isdir():
                    continue
                total += member.size
                if total > MAX_ARCHIVE_BYTES:
                    fail("archive-size", "expanded archive exceeds limit")
                stream = archive.extractfile(member)
                if stream is None:
                    fail("unsafe-archive", "archive file has no readable payload")
                entries[name] = stream.read(MAX_ARCHIVE_BYTES + 1)
            if not data.startswith(b'\x1f\x8b') and any(data[archive.offset:]):
                fail('unsafe-archive', 'archive contains non-padding trailing bytes')
    except (tarfile.TarError, OSError) as exc:
        raise ContractError("invalid-archive", "invalid tar payload") from exc
    return entries


def _validate_openapi(data: bytes, artifact_format: str) -> None:
    """One YAML resolver: trusted Tronador parses the exact original bytes.

    The data-only CLI never loads project configuration or executes source.
    Runner bounds deadline/output and kills its process group on failure.
    """
    if len(data) > MAX_DOCUMENT_BYTES:
        fail("invalid-openapi", "OpenAPI document exceeds the data-only input bound")
    binary = os.environ.get('TRONADOR_TEST_BINARY') or shutil.which('tronador')
    if not binary or not Path(binary).is_absolute():
        fail("openapi-validator-unavailable", "trusted Tronador data validator is required")
    try:
        result = Runner(timeout=15, output_limit=4096).run(
            [binary, 'components', 'validate-openapi', '--format', artifact_format],
            input=data.decode('utf-8'), cwd='/')
    except (UnicodeError, ExecutionError):
        fail("invalid-openapi", "trusted data validator could not validate the OpenAPI document")
    if result.returncode != 0 or result.stdout.strip() != '{"valid":true}':
        fail("invalid-openapi", "OpenAPI document failed trusted data validation")


def validate_artifact(path: Path, artifact: dict[str, Any]) -> None:
    """Check exact payload bytes, or the complete selected OCI descriptor graph."""
    _artifact(artifact)
    size_limit = MAX_DOCUMENT_BYTES if artifact['format'] in {'openapi-json', 'openapi-yaml'} else MAX_ARCHIVE_BYTES
    if path.is_symlink() or not path.is_file() or path.stat().st_size > size_limit:
        fail("artifact-size", "artifact must be a bounded regular file")
    data = path.read_bytes()
    if artifact["format"] != "oci":
        if len(data) != artifact["sizeBytes"] or payload_digest(data) != artifact["digest"]:
            fail("artifact-digest", "artifact payload digest or size differs")
        if artifact["format"] in {"openapi-json", "openapi-yaml"}:
            _validate_openapi(data, artifact["format"])
        elif artifact["format"] == "tar.gz":
            _tar_entries(data)
        elif artifact["format"] == "zip":
            try:
                with zipfile.ZipFile(io.BytesIO(data)) as archive:
                    names: set[str] = set()
                    total = 0
                    for entry in archive.infolist():
                        name = _archive_name(entry.filename)
                        if name in names or len(names) >= MAX_ARCHIVE_ENTRIES or (entry.external_attr >> 16) & 0o170000 == 0o120000:
                            fail("unsafe-archive", "unsafe or duplicate ZIP entry")
                        names.add(name)
                        total += entry.file_size
                        if total > MAX_ARCHIVE_BYTES:
                            fail("archive-size", "expanded ZIP exceeds limit")
                        archive.read(entry)
            except (zipfile.BadZipFile, RuntimeError) as exc:
                raise ContractError("invalid-archive", "invalid ZIP payload") from exc
        return
    entries = _tar_entries(data)
    if entries.get("oci-layout") is None or entries.get("index.json") is None:
        fail("oci-layout", "OCI layout metadata is missing")
    layout = load_record(entries["oci-layout"])
    if layout != {"imageLayoutVersion": "1.0.0"}:
        fail("oci-layout", "unsupported OCI layout version")
    index = load_record(entries["index.json"])
    descriptors = index.get("manifests", [])
    if index.get("schemaVersion") != 2 or not isinstance(descriptors, list) or not descriptors or any(not isinstance(d, dict) for d in descriptors):
        fail("oci-layout", "OCI index has no valid manifest descriptors")
    root = next((d for d in descriptors if d.get("digest") == artifact["digest"]), None)
    if root is None or root.get("size") != artifact["sizeBytes"]:
        fail("oci-digest", "selected OCI descriptor does not match recorded identity")
    reachable = {"oci-layout", "index.json"}
    visited: set[str] = set()
    def visit(descriptor: dict[str, Any], depth: int = 0) -> None:
        if depth > 64 or not isinstance(descriptor, dict):
            fail("oci-descriptor", "OCI descriptor graph is too deep or malformed")
        value = descriptor.get("digest", "")
        if not isinstance(value, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", value) or "urls" in descriptor or type(descriptor.get("size")) is not int:
            fail("oci-descriptor", "unsupported external or malformed OCI descriptor")
        name = "blobs/sha256/" + value[7:]
        blob = entries.get(name)
        if blob is None or payload_digest(blob) != value or len(blob) != descriptor.get("size"):
            fail("oci-integrity", "OCI referenced blob hash or size differs")
        reachable.add(name)
        if value in visited:
            return
        visited.add(value)
        media = descriptor.get("mediaType", "")
        if not isinstance(media, str):
            fail("oci-descriptor", "OCI descriptor media type is malformed")
        if media.endswith("image.index.v1+json") or media.endswith("manifest.list.v2+json"):
            doc = load_record(blob)
            children = doc.get("manifests")
            if doc.get("schemaVersion") != 2 or not isinstance(children, list) or not children:
                fail("oci-descriptor", "OCI image index is malformed")
            for child in children:
                visit(child, depth + 1)
        elif media.endswith("image.manifest.v1+json") or media.endswith("manifest.v2+json"):
            doc = load_record(blob)
            config = doc.get("config", {})
            layers = doc.get("layers", [])
            if doc.get("schemaVersion") != 2 or not isinstance(layers, list):
                fail("oci-descriptor", "OCI image manifest is malformed")
            visit(config, depth + 1)
            for layer in layers:
                visit(layer, depth + 1)
            conf = load_record(entries["blobs/sha256/" + config["digest"][7:]])
            rootfs = conf.get("rootfs", {})
            diff_ids = rootfs.get("diff_ids", []) if isinstance(rootfs, dict) else None
            if not isinstance(diff_ids, list) or len(diff_ids) != len(layers):
                fail("oci-integrity", "OCI layer diffID count differs")
            for layer, expected in zip(layers, diff_ids):
                compressed = entries["blobs/sha256/" + layer["digest"][7:]]
                try:
                    if layer.get("mediaType", "").endswith("+gzip") or layer.get("mediaType", "").endswith(".gzip"):
                        with gzip.GzipFile(fileobj=io.BytesIO(compressed)) as stream:
                            expanded = stream.read(MAX_ARCHIVE_BYTES + 1)
                    else:
                        expanded = compressed
                except (OSError, EOFError) as exc:
                    raise ContractError("oci-integrity", "invalid compressed OCI layer") from exc
                if len(expanded) > MAX_ARCHIVE_BYTES or payload_digest(expanded) != expected:
                    fail("oci-integrity", "OCI uncompressed layer diffID differs")
                _layer_entries(expanded)
    image_media = {"application/vnd.oci.image.manifest.v1+json", "application/vnd.oci.image.index.v1+json",
                   "application/vnd.docker.distribution.manifest.v2+json", "application/vnd.docker.distribution.manifest.list.v2+json"}
    if any(descriptor.get("mediaType") not in image_media for descriptor in descriptors):
        fail("oci-descriptor", "OCI roots must describe an image manifest or image index")
    for descriptor in descriptors:
        visit(descriptor)
    if set(entries) != reachable:
        fail("oci-unexpected-entry", "OCI archive contains unreferenced or unexpected files")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("record", type=Path)
    args = parser.parse_args()
    try:
        value = validate_record(load_record(args.record))
        print(json.dumps({"valid": True, "kind": value["kind"], "apiVersion": API_VERSION}))
        return 0
    except (ContractError, OSError) as exc:
        print(json.dumps({"valid": False, "error": {"code": getattr(exc, "code", "io-error"), "message": str(exc)}}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
