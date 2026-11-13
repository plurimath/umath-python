"""Replay one pinned plurimath-testsuite unicode generation on the installed wheel.

The pin (ci/testsuite-pin.yml, plurimath-stage/pin/1) names the testsuite
commit, the generation and its snapshot digest. ci/testsuite-replay.json is
this consumer's own record of what it executes: the row count per boundary
and the SHA-256 of the sorted executed IDs. Every check in
docs/stage-corpus-contract.adoc runs before any row does:

* the checkout is at the pinned commit;
* the named ledger entry (not the latest) is selected and matches the pin;
* the snapshot digest is recomputed from the files on disk;
* every payload is listed in provenance.yaml with its bytes, SHA-256 and row
  IDs, and nothing on disk is unlisted;
* row IDs are unique across the generation and the counts match the ledger.

Boundaries:

* ``raw-tree`` rows run through ``umath.parse_legacy_raw``: the preprocessed
  text and the whole raw tree, or the refusal byte offset, must be equal.
* ``typed-model`` rows run through ``umath.parse_model_json`` for their
  outcome only (accepted or refused). The Ruby LML Document and the Rust
  codec JSON are different shapes; no tree equality is claimed for them.
* Legacy-oracle payloads (MathML and other target renderings of the old
  facade) are counted and not executed: this package has no such output.

Nothing is skipped: every row of an executed boundary runs, and the set of
executed IDs must equal the one recorded in ci/testsuite-replay.json.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
PIN = ROOT / "ci/testsuite-pin.yml"
EXPECTATION = ROOT / "ci/testsuite-replay.json"
REPOSITORY = "https://github.com/plurimath/plurimath-testsuite"
EXECUTED = ("raw-tree", "typed-model")


class ReplayError(RuntimeError):
    """The pinned generation failed verification or replay."""


def _yaml():
    import yaml
    loader = getattr(yaml, "CSafeLoader", None)
    if loader is None:
        raise ReplayError("PyYAML without libyaml: the generation must be read with CSafeLoader")
    return lambda data: yaml.load(data, Loader=loader)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_pin(path=PIN) -> dict:
    pin = _yaml()(Path(path).read_bytes())
    required = {"schema", "repository", "commit", "language", "generation", "snapshot_digest"}
    if not isinstance(pin, dict) or set(pin) != required:
        raise ReplayError("pin must carry exactly the plurimath-stage/pin/1 keys")
    if pin["schema"] != "plurimath-stage/pin/1" or pin["repository"] != REPOSITORY:
        raise ReplayError("pin schema or repository differs from plurimath-stage/pin/1")
    if not re.fullmatch(r"[0-9a-f]{40}", str(pin["commit"])):
        raise ReplayError("pin commit must be a full 40-hex SHA")
    if pin["language"] != "unicode":
        raise ReplayError("this consumer replays the unicode language only")
    if not isinstance(pin["generation"], int) or isinstance(pin["generation"], bool) or pin["generation"] < 1:
        raise ReplayError("pin generation must be a positive integer")
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", str(pin["snapshot_digest"])):
        raise ReplayError("pin snapshot_digest must be sha256:<64 hex>")
    return pin


def checkout(pin: dict, destination: Path) -> Path:
    """Fetch exactly the pinned commit into a fresh directory."""
    destination = Path(destination)
    if destination.exists():
        raise ReplayError(f"{destination} already exists; replay needs a fresh checkout")
    git = lambda *args: subprocess.run(["git", *args], cwd=destination, check=True,
                                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    destination.mkdir(parents=True)
    git("init", "-q")
    git("config", "core.autocrlf", "false")
    git("remote", "add", "origin", pin["repository"] + ".git")
    git("fetch", "-q", "--depth", "1", "origin", pin["commit"])
    git("checkout", "-q", "--detach", "FETCH_HEAD")
    return destination


def _safe(relative: str) -> str:
    parts = relative.split("/")
    if PurePosixPath(relative).is_absolute() or any(part in ("", ".", "..") for part in parts) or "\\" in relative:
        raise ReplayError(f"unsafe path in generation: {relative!r}")
    return relative


def snapshot_digest(directory: Path) -> tuple[str, dict]:
    """sha256 over '<sha256>  <relative path>\\n' lines, ordered by path bytes."""
    files = {}
    for path in sorted(directory.rglob("*")):
        if path.is_symlink():
            raise ReplayError(f"symlink in generation: {path}")
        if path.is_file():
            relative = _safe(path.relative_to(directory).as_posix())
            files[relative] = path.read_bytes()
    if not files:
        raise ReplayError("empty generation")
    lines = "".join(f"{sha256(files[name])}  {name}\n" for name in sorted(files, key=lambda name: name.encode("utf-8")))
    return "sha256:" + sha256(lines.encode("utf-8")), files


def verify(checkout_root: Path, pin: dict) -> dict:
    """Run every contract check before any row is replayed."""
    load = _yaml()
    root = Path(checkout_root)
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, check=True, text=True,
                          stdout=subprocess.PIPE).stdout.strip()
    if head != pin["commit"]:
        raise ReplayError(f"checkout is at {head}, pin names {pin['commit']}")
    ledger = load((root / "generations" / (pin["language"] + ".yaml")).read_bytes())
    if ledger.get("schema") != "plurimath-stage/ledger/1" or ledger.get("language") != pin["language"]:
        raise ReplayError("ledger schema or language differs")
    entries = [entry for entry in ledger["entries"] if entry.get("generation") == pin["generation"]]
    if len(entries) != 1:
        raise ReplayError(f"ledger has {len(entries)} entries for generation {pin['generation']}")
    entry = entries[0]
    if entry["snapshot_digest"] != pin["snapshot_digest"]:
        raise ReplayError("ledger snapshot digest differs from the pin")
    expected_path = f"stages/{pin['language']}/generations/{pin['generation']:06d}"
    if entry["path"] != expected_path:
        raise ReplayError(f"ledger path {entry['path']} is not {expected_path}")
    directory = root / _safe(entry["path"])
    digest, files = snapshot_digest(directory)
    if digest != pin["snapshot_digest"]:
        raise ReplayError(f"recomputed snapshot digest {digest} differs from the pin")
    provenance = load(files["provenance.yaml"])
    if (provenance.get("language"), provenance.get("generation")) != (pin["language"], pin["generation"]):
        raise ReplayError("provenance language or generation differs from the pin")
    listed = [_safe(payload["path"]) for payload in provenance["payloads"]]
    if len(set(listed)) != len(listed):
        raise ReplayError("provenance lists a payload twice")
    if set(listed) != set(files) - {"provenance.yaml"}:
        raise ReplayError("payload files on disk differ from provenance (missing or unlisted)")
    seen, documents = set(), []
    for payload in provenance["payloads"]:
        data = files[payload["path"]]
        if len(data) != payload["bytes"] or sha256(data) != payload["sha256"]:
            raise ReplayError(f"{payload['path']} bytes or SHA-256 differ from provenance")
        document = load(data)
        ids = [case["id"] for case in document["cases"]]
        if ids != list(payload["rows"]):
            raise ReplayError(f"{payload['path']} row IDs differ from provenance")
        if seen & set(ids) or len(set(ids)) != len(ids):
            raise ReplayError(f"{payload['path']} repeats a row ID")
        seen.update(ids)
        documents.append((payload["path"], document))
    if len(documents) != entry["payloads"] or len(seen) != entry["rows"]:
        raise ReplayError("payload or row count differs from the ledger entry")
    return {"head": head, "entry": entry, "documents": documents, "provenance_sha256": sha256(files["provenance.yaml"])}


def _raw(stage, case, decode, ordered):
    source, decimal = case["input"]["str"], case.get("options", {}).get("decimal", ".")
    expected = case["expected"]
    if set(expected) == {"refusal"}:
        try:
            stage.parse_legacy_raw(source, decimal=decimal)
        except stage.ParseError as error:
            actual = error.grammar_byte_offset
            if actual != expected["refusal"]["byte_offset"]:
                return f"refusal at grammar byte {actual}, expected {expected['refusal']['byte_offset']}"
            return None
        return "accepted, expected a refusal"
    if set(expected) != {"preprocessed", "tree"}:
        raise ReplayError(f"{case['id']}: unknown raw-tree expectation keys {sorted(expected)}")
    try:
        result = stage.parse_legacy_raw(source, decimal=decimal)
    except stage.ParseError as error:
        return f"refused at grammar byte {error.grammar_byte_offset}, expected a tree"
    if result.text != expected["preprocessed"]["str"]:
        return "preprocessed text differs"
    if ordered(result.tree) != ordered(decode(expected["tree"], result.text)):
        return "raw tree differs"
    return None


def _model(stage, case):
    source, decimal = case["input"]["str"], case.get("options", {}).get("decimal", ".")
    expected = case["expected"]
    if set(expected) not in ({"refusal"}, {"preprocessed", "tree"}):
        raise ReplayError(f"{case['id']}: unknown typed-model expectation keys {sorted(expected)}")
    refused = "refusal" in expected
    try:
        stage.parse_model_json(source, decimal=decimal)
    except stage.ModelParseError:
        return None if refused else "refused, expected a model"
    return "accepted, expected a refusal" if refused else None


def replay(verified: dict) -> dict:
    import umath as stage
    if Path(stage.__file__).resolve().is_relative_to(ROOT / "src"):
        raise ReplayError("replay must exercise an installed wheel, not the source checkout")
    # Generation 5 rows nest up to 170 wire levels; decode/ordered recurse
    # about once per level. Raise the limit rather than drop deep rows.
    sys.setrecursionlimit(max(sys.getrecursionlimit(), 5000))
    sys.path.insert(0, str(ROOT / "tests"))
    from test_full_legacy_corpus import decode
    from test_legacy_policy import ordered
    executed = {boundary: [] for boundary in EXECUTED}
    counted, failures = {}, []
    for path, document in verified["documents"]:
        boundary = document.get("boundary")
        if boundary not in EXECUTED:
            key = boundary or document.get("schema")
            counted[key] = counted.get(key, 0) + len(document["cases"])
            continue
        for case in document["cases"]:
            problem = _raw(stage, case, decode, ordered) if boundary == "raw-tree" else _model(stage, case)
            executed[boundary].append(case["id"])
            if problem:
                failures.append({"id": case["id"], "payload": path, "boundary": boundary, "problem": problem})
    return {
        "executed_ids": sorted(executed["raw-tree"] + executed["typed-model"]),
        "executed": {boundary: {"rows": len(ids), "ids_sha256": sha256("".join(i + "\n" for i in sorted(ids)).encode("utf-8"))}
                     for boundary, ids in executed.items()},
        "not_executed": counted,
        "failures": failures,
    }


def run(pin_path=PIN, expectation_path=EXPECTATION, workdir=None, evidence=None) -> dict:
    pin = load_pin(pin_path)
    expectation = json.loads(Path(expectation_path).read_text(encoding="utf-8"))
    if {key: expectation.get(key) for key in ("commit", "generation", "snapshot_digest")} != \
            {key: pin[key] for key in ("commit", "generation", "snapshot_digest")}:
        raise ReplayError("ci/testsuite-replay.json describes a different pin")
    workdir = Path(workdir or ROOT / ".testsuite")
    verified = verify(checkout(pin, workdir), pin)
    report = {"pin": pin, "provenance_sha256": verified["provenance_sha256"], **replay(verified)}
    if evidence:
        # One ID per line, for scripts/validate-unicode-external.rb --executed.
        Path(evidence).with_name("executed-ids.txt").write_text(
            "".join(i + "\n" for i in report["executed_ids"]), encoding="utf-8")
        Path(evidence).write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    summary = {"executed": report["executed"], "not_executed": report["not_executed"], "failures": len(report["failures"])}
    print(json.dumps(summary, indent=2))
    for failure in report["failures"][:40]:
        print(f"FAIL {failure['id']} [{failure['boundary']}] {failure['problem']}")
    if report["failures"]:
        raise ReplayError(f"{len(report['failures'])} pinned rows disagree with the installed wheel")
    if report["executed"] != expectation["executed"]:
        raise ReplayError("executed rows or IDs differ from ci/testsuite-replay.json")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--pin", default=PIN)
    parser.add_argument("--expectation", default=EXPECTATION)
    parser.add_argument("--workdir")
    parser.add_argument("--evidence", default=ROOT / ".ci-evidence/corpus-replay.json")
    args = parser.parse_args()
    Path(args.evidence).parent.mkdir(exist_ok=True)
    run(args.pin, args.expectation, args.workdir, args.evidence)


if __name__ == "__main__":
    main()
