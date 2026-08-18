import dataclasses
import hashlib
import json
import os
import tempfile

from kicad_dfm.core.models import DfmIssue, DfmSummary, Location
from kicad_dfm.services.analysis_results import ANALYSIS_MODES
from kicad_dfm.services.analysis_results import CONTRACT_VERSION
from kicad_dfm.services.analysis_results import KICAD_NATIVE
from kicad_dfm.services.analysis_results import SOURCE_VIEWS_SCHEMA
from kicad_dfm.services.analysis_results import SOURCE_VIEWS_SCHEMA_VERSION
from kicad_dfm.services.analysis_results import canonical_mode
from kicad_dfm.services.analysis_results import source_views_from_payload
from kicad_dfm.services.analysis_results import source_views_payload


CACHE_VERSION = 23
CACHE_DIR_NAME = "HQDMF"
CACHE_NAMESPACE = "analysis-cache-v23"
CACHE_MAX_PAYLOAD_BYTES = 128 * 1024 * 1024
STARTUP_CACHE_MAX_BYTES = CACHE_MAX_PAYLOAD_BYTES
# Deeply duplicated result trees can take several seconds merely to prove that
# they exceed the byte limit.  Keep persistence bounded by structural work too;
# the native snapshot still gives large boards a useful startup cache.
CACHE_MAX_TREE_NODES = 1000000


class CachePayloadTooLarge(OSError):
    pass


def cache_path(
    board_path,
    mode=KICAD_NATIVE,
    input_digest="unknown",
    rules_digest="unknown",
    contract_version=CONTRACT_VERSION,
    language="",
):
    board_path = os.path.abspath(board_path)
    stem = os.path.splitext(os.path.basename(board_path))[0] or "board"
    filename = _cache_filename(
        stem,
        mode,
        input_digest,
        rules_digest,
        contract_version,
        language,
    )
    return os.path.join(
        os.path.dirname(board_path),
        CACHE_DIR_NAME,
        CACHE_NAMESPACE,
        filename,
    )


def legacy_cache_path(board_path):
    """Return the pre-versioned location for migration diagnostics only.

    Legacy payloads are intentionally never read as current cache hits.
    """
    board_path = os.path.abspath(board_path)
    stem = os.path.splitext(os.path.basename(board_path))[0] or "board"
    return os.path.join(os.path.dirname(board_path), CACHE_DIR_NAME, stem + ".dfm-cache.json")


def fallback_cache_path(
    board_path,
    mode=KICAD_NATIVE,
    input_digest="unknown",
    rules_digest="unknown",
    contract_version=CONTRACT_VERSION,
    language="",
):
    identity = normalized_board_path(board_path).encode("utf-8")
    board_digest = hashlib.sha256(identity).hexdigest()[:20]
    filename = _cache_filename(
        board_digest,
        mode,
        input_digest,
        rules_digest,
        contract_version,
        language,
    )
    return os.path.join(tempfile.gettempdir(), "HQDFM", CACHE_NAMESPACE, filename)


def save_analysis_cache(
    board_path,
    profile_id,
    mode,
    analysis_result,
    kicad_result,
    issues,
    summary,
    language="",
    *,
    input_paths=(),
    rules=None,
    contract=None,
    source_views=None,
    contract_version=CONTRACT_VERSION,
    max_payload_bytes=CACHE_MAX_PAYLOAD_BYTES,
    max_tree_nodes=CACHE_MAX_TREE_NODES,
):
    mode = canonical_mode(mode)
    raw_payload = (
        analysis_result,
        kicad_result,
        tuple(issues or ()),
        summary or {},
        contract or {},
        source_views or {},
    )
    if max_payload_bytes is not None and json_size_exceeds(
        raw_payload,
        max_payload_bytes,
        max_tree_nodes=max_tree_nodes,
    ):
        raise CachePayloadTooLarge(
            "DFM cache exceeds the {0} MiB persistence limit".format(
                max_payload_bytes // (1024 * 1024)
            )
        )
    inputs = input_signature(board_path, input_paths)
    input_digest = signature_digest(inputs)
    rules_digest = rules_fingerprint(profile_id, rules)
    payload = {
        "version": CACHE_VERSION,
        "contract_version": int(contract_version),
        "board_path": normalized_board_path(board_path),
        "input_signature": inputs,
        "input_digest": input_digest,
        "rules_digest": rules_digest,
        "profile_id": str(profile_id),
        "language": str(language or ""),
        "mode": mode,
        "analysis_result": json_value(analysis_result),
        "kicad_result": json_value(kicad_result),
        "issues": json_value(tuple(issues or ())),
        "summary": json_value(summary or {}),
        "contract": json_value(contract or {}),
        "source_views": source_views_payload(source_views or {}),
    }
    paths = (
        cache_path(
            board_path,
            mode,
            input_digest,
            rules_digest,
            contract_version,
            language,
        ),
        fallback_cache_path(
            board_path,
            mode,
            input_digest,
            rules_digest,
            contract_version,
            language,
        ),
    )
    error = None
    for path in paths:
        try:
            atomic_json_write(
                path,
                payload,
                max_payload_bytes=max_payload_bytes,
            )
            return path
        except CachePayloadTooLarge:
            raise
        except OSError as exc:
            error = exc
    raise error


def load_analysis_cache(
    board_path,
    profile_id,
    language="",
    *,
    mode=None,
    input_paths=None,
    rules=None,
    contract_version=CONTRACT_VERSION,
    max_payload_bytes=None,
):
    expected_mode = canonical_mode(mode) if mode is not None else None
    expected_rules = rules_fingerprint(profile_id, rules)
    expected_inputs = (
        input_signature(board_path, input_paths or ()) if input_paths is not None else None
    )
    expected_input_digest = signature_digest(expected_inputs) if expected_inputs is not None else None
    candidates = _candidate_paths(board_path, expected_mode)
    candidates.extend(_fallback_candidate_paths(board_path, expected_mode))
    candidates.sort(key=_safe_mtime_ns, reverse=True)
    for path in candidates:
        if max_payload_bytes is not None:
            payload_size = _safe_size(path)
            if payload_size is None or payload_size > max_payload_bytes:
                continue
        try:
            with open(path, "r", encoding="utf-8") as stream:
                payload = json.load(stream)
        except (OSError, ValueError):
            continue
        if not valid_payload(
            payload,
            board_path,
            profile_id,
            language,
            expected_mode,
            expected_rules,
            expected_inputs,
            expected_input_digest,
            contract_version,
        ):
            continue
        return {
            "path": path,
            "mode": payload["mode"],
            "analysis_result": payload.get("analysis_result") or {},
            "kicad_result": payload.get("kicad_result") or {},
            "issues": tuple(issue_from_json(item) for item in payload.get("issues") or ()),
            "summary": {
                category: summary_from_json(category, item)
                for category, item in (payload.get("summary") or {}).items()
            },
            "contract": payload.get("contract") or {},
            "source_views": source_views_from_payload(payload.get("source_views")),
            "input_paths": tuple(item.get("path") for item in payload["input_signature"]),
        }
    return None


def valid_payload(
    payload,
    board_path,
    profile_id,
    language="",
    mode=None,
    rules_digest=None,
    expected_inputs=None,
    expected_input_digest=None,
    contract_version=CONTRACT_VERSION,
):
    if not isinstance(payload, dict):
        return False
    if payload.get("version") != CACHE_VERSION:
        return False
    if payload.get("contract_version") != int(contract_version):
        return False
    try:
        payload_mode = canonical_mode(payload.get("mode"))
    except ValueError:
        return False
    if mode is not None and payload_mode != mode:
        return False
    if payload.get("board_path") != normalized_board_path(board_path):
        return False
    if payload.get("profile_id") != str(profile_id):
        return False
    if payload.get("language", "") != str(language or ""):
        return False
    if payload.get("rules_digest") != rules_digest:
        return False
    if not isinstance(payload.get("analysis_result"), dict):
        return False
    if not isinstance(payload.get("kicad_result"), dict):
        return False
    stored_source_views = payload.get("source_views")
    if stored_source_views is not None and not valid_source_views_payload(
        stored_source_views
    ):
        return False
    stored_inputs = payload.get("input_signature")
    if not isinstance(stored_inputs, list) or not stored_inputs:
        return False
    if expected_inputs is not None:
        return signatures_match(stored_inputs, expected_inputs) and payload.get(
            "input_digest"
        ) == expected_input_digest
    if manifest_file_states_match(stored_inputs):
        # The common startup path only stats the source files. Content hashing
        # is reserved for changed timestamps/sizes, keeping large combined
        # PCB + Gerber caches quick to restore.
        current_inputs = stored_inputs
    else:
        try:
            current_inputs = input_signature_from_manifest(stored_inputs)
        except OSError:
            return False
    return (
        signatures_match(current_inputs, stored_inputs)
        and payload.get("input_digest") == signature_digest(current_inputs)
    )


def valid_source_views_payload(payload):
    return (
        isinstance(payload, dict)
        and payload.get("schema") == SOURCE_VIEWS_SCHEMA
        and payload.get("schema_version") == SOURCE_VIEWS_SCHEMA_VERSION
        and isinstance(payload.get("views"), dict)
    )


def normalized_board_path(board_path):
    return os.path.normcase(os.path.abspath(board_path))


def board_signature(board_path):
    """Compatibility helper returning the current cache file signature."""
    return file_signature(board_path)


def input_signature(board_path, input_paths=()):
    paths = [board_path]
    paths.extend(input_paths or ())
    expanded = []
    for path in paths:
        path = os.path.abspath(os.fspath(path))
        if os.path.isdir(path):
            for root, _directories, filenames in os.walk(path):
                expanded.extend(os.path.join(root, filename) for filename in sorted(filenames))
        else:
            expanded.append(path)
    unique = []
    seen = set()
    for path in expanded:
        normalized = os.path.normcase(os.path.abspath(path))
        if normalized not in seen:
            seen.add(normalized)
            unique.append(path)
    return [file_signature(path) for path in sorted(unique, key=normalized_board_path)]


def input_signature_from_manifest(manifest):
    return [file_signature(item["path"]) for item in manifest]


def manifest_file_states_match(manifest):
    for item in manifest:
        try:
            stat = os.stat(item["path"])
        except (KeyError, OSError, TypeError):
            return False
        if stat.st_size != item.get("size"):
            return False
        mtime_ns = getattr(
            stat,
            "st_mtime_ns",
            int(stat.st_mtime * 1000000000),
        )
        if mtime_ns != item.get("mtime_ns"):
            return False
    return True


def file_signature(path):
    path = os.path.abspath(os.fspath(path))
    stat = os.stat(path)
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return {
        "path": os.path.normcase(path),
        "size": stat.st_size,
        "mtime_ns": getattr(stat, "st_mtime_ns", int(stat.st_mtime * 1000000000)),
        "sha256": digest.hexdigest(),
    }


def signature_digest(signature):
    semantic = [
        {
            "path": item.get("path"),
            "size": item.get("size"),
            "sha256": item.get("sha256"),
        }
        for item in signature
    ]
    encoded = json.dumps(semantic, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def signatures_match(left, right):
    return signature_digest(left) == signature_digest(right)


def rules_fingerprint(profile_id, rules=None):
    payload = {
        "profile_id": str(profile_id),
        "rules": json_value(rules) if rules is not None else None,
    }
    encoded = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def atomic_json_write(path, payload, max_payload_bytes=None):
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    encoded_size = len(encoded.encode("utf-8"))
    if max_payload_bytes is not None and encoded_size > max_payload_bytes:
        raise CachePayloadTooLarge(
            "DFM cache exceeded the persistence limit while encoding"
        )
    directory = os.path.dirname(path)
    os.makedirs(directory, exist_ok=True)
    temporary = path + ".tmp"
    try:
        with open(temporary, "w", encoding="utf-8") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        try:
            if os.path.exists(temporary):
                os.remove(temporary)
        except OSError:
            pass


def json_size_exceeds(value, max_payload_bytes, max_tree_nodes=None):
    """Cheaply reject obviously huge JSON-like trees before copying them."""
    remaining = int(max_payload_bytes)
    remaining_nodes = (
        None if max_tree_nodes is None else max(0, int(max_tree_nodes))
    )
    stack = [value]
    while stack:
        item = stack.pop()
        if remaining_nodes is not None:
            remaining_nodes -= 1
            if remaining_nodes < 0:
                return True
        if dataclasses.is_dataclass(item):
            remaining -= 2 + len(dataclasses.fields(item)) * 2
            stack.extend(
                getattr(item, field.name) for field in dataclasses.fields(item)
            )
        elif isinstance(item, dict):
            remaining -= 2 + len(item) * 2
            for key, child in item.items():
                stack.append(str(key))
                stack.append(child)
        elif isinstance(item, (list, tuple, set)):
            remaining -= 2 + len(item)
            stack.extend(item)
        elif isinstance(item, str):
            remaining -= len(item.encode("utf-8")) + 2
        elif item is None:
            remaining -= 4
        elif isinstance(item, bool):
            remaining -= 4 if item else 5
        elif isinstance(item, (int, float)):
            remaining -= len(str(item))
        else:
            remaining -= len(str(item).encode("utf-8")) + 2
        if remaining < 0:
            return True
    return False


def json_value(value):
    if dataclasses.is_dataclass(value):
        return {field.name: json_value(getattr(value, field.name)) for field in dataclasses.fields(value)}
    if isinstance(value, dict):
        return {str(key): json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [json_value(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def issue_from_json(data):
    data = data if isinstance(data, dict) else {}
    location = data.get("location")
    if isinstance(location, dict):
        location = Location(**{key: location.get(key) for key in Location.__dataclass_fields__})
    else:
        location = None
    return DfmIssue(
        category=data.get("category", ""),
        item=data.get("item", ""),
        severity=data.get("severity", "ok"),
        layer=data.get("layer"),
        value=data.get("value", ""),
        rule=data.get("rule", ""),
        message=data.get("message", ""),
        location=location,
        raw=data.get("raw"),
    )


def summary_from_json(category, data):
    data = data if isinstance(data, dict) else {}
    return DfmSummary(
        category=data.get("category", category),
        display=data.get("display", ""),
        display_inch=data.get("display_inch", ""),
        color=data.get("color", ""),
        issues=tuple(issue_from_json(item) for item in data.get("issues") or ()),
    )


def _cache_filename(stem, mode, input_digest, rules_digest, contract_version, language):
    mode = canonical_mode(mode)
    language_digest = hashlib.sha256(str(language or "").encode("utf-8")).hexdigest()[:8]
    return "{0}.{1}.{2}.{3}.c{4}.{5}.json".format(
        stem,
        mode,
        str(input_digest)[:16],
        str(rules_digest)[:16],
        int(contract_version),
        language_digest,
    )


def _candidate_paths(board_path, mode):
    board_path = os.path.abspath(board_path)
    stem = os.path.splitext(os.path.basename(board_path))[0] or "board"
    directory = os.path.join(os.path.dirname(board_path), CACHE_DIR_NAME, CACHE_NAMESPACE)
    return _matching_json_paths(directory, stem, mode)


def _fallback_candidate_paths(board_path, mode):
    identity = normalized_board_path(board_path).encode("utf-8")
    stem = hashlib.sha256(identity).hexdigest()[:20]
    directory = os.path.join(tempfile.gettempdir(), "HQDFM", CACHE_NAMESPACE)
    return _matching_json_paths(directory, stem, mode)


def _matching_json_paths(directory, stem, mode):
    try:
        filenames = os.listdir(directory)
    except OSError:
        return []
    modes = (mode,) if mode else ANALYSIS_MODES
    prefixes = tuple("{0}.{1}.".format(stem, item) for item in modes)
    return [
        os.path.join(directory, filename)
        for filename in filenames
        if filename.endswith(".json") and filename.startswith(prefixes)
    ]


def _safe_mtime_ns(path):
    try:
        stat = os.stat(path)
        return getattr(stat, "st_mtime_ns", int(stat.st_mtime * 1000000000))
    except OSError:
        return 0


def _safe_size(path):
    try:
        return os.path.getsize(path)
    except OSError:
        return None
