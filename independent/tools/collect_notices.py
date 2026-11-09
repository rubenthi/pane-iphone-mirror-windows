"""Stage exact third-party license texts for review; does not authorize release.

Uses only the standard library and the new independent audit module. Production
input is fresh locked Cargo metadata plus its matching saved audit. Saved metadata
is an explicit fixture mode. Nothing in the existing application's source is read.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
import time
import uuid

from audit_licenses import AuditError, SpdxParser, audit_metadata, expression_issues, load_cargo_metadata


class NoticeError(ValueError):
    pass


# Automatic collection is deliberately limited to complete MIT and Unicode-3.0
# texts. Other policy-approved SPDX identities require manual complete-text review.
SUPPORTED_TEXTS = frozenset({"MIT", "Unicode-3.0"})

# Match the complete standard MIT grant/condition/disclaimer, not isolated titles.
MIT_BODY = '''Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in
all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
THE SOFTWARE'''

UNICODE_BODY = '''Permission is hereby granted, free of charge, to any person obtaining a
copy of data files and any associated documentation (the "Data Files") or
software and any associated documentation (the "Software") to deal in the
Data Files or Software without restriction, including without limitation
the rights to use, copy, modify, merge, publish, distribute, and/or sell
copies of the Data Files or Software, and to permit persons to whom the
Data Files or Software are furnished to do so, provided that either (a)
this copyright and permission notice appear with all copies of the Data
Files or Software, or (b) this copyright and permission notice appear in
associated Documentation.

THE DATA FILES AND SOFTWARE ARE PROVIDED "AS IS", WITHOUT WARRANTY OF ANY
KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT OF
THIRD PARTY RIGHTS.

IN NO EVENT SHALL THE COPYRIGHT HOLDER OR HOLDERS INCLUDED IN THIS NOTICE
BE LIABLE FOR ANY CLAIM, OR ANY SPECIAL INDIRECT OR CONSEQUENTIAL DAMAGES,
OR ANY DAMAGES WHATSOEVER RESULTING FROM LOSS OF USE, DATA OR PROFITS,
WHETHER IN AN ACTION OF CONTRACT, NEGLIGENCE OR OTHER TORTIOUS ACTION,
ARISING OUT OF OR IN CONNECTION WITH THE USE OR PERFORMANCE OF THE DATA
FILES OR SOFTWARE.

Except as contained in this notice, the name of a copyright holder shall
not be used in advertising or otherwise to promote the sale, use or other
dealings in these Data Files or Software without prior written
authorization of the copyright holder.'''

UNICODE_PREAMBLE = '''NOTICE TO USER: Carefully read the following legal agreement. BY
DOWNLOADING, INSTALLING, COPYING OR OTHERWISE USING DATA FILES, AND/OR
SOFTWARE, YOU UNEQUIVOCALLY ACCEPT, AND AGREE TO BE BOUND BY, ALL OF THE
TERMS AND CONDITIONS OF THIS AGREEMENT. IF YOU DO NOT AGREE, DO NOT
DOWNLOAD, INSTALL, COPY, DISTRIBUTE OR USE THE DATA FILES OR SOFTWARE.'''


class Choices(SpdxParser):
    """Compute alternatives with SPDX precedence, preserving AND obligations."""

    def alternatives(self) -> list[frozenset[str]]:
        result = self.or_choices()
        if self.peek() is not None:
            raise NoticeError("invalid expression after policy validation")
        return result

    def or_choices(self) -> list[frozenset[str]]:
        result = self.and_choices()
        while self.peek() == "OR":
            self.take()
            result += self.and_choices()
            self.bound(result)
        return result

    @staticmethod
    def bound(items: list) -> None:
        if len(items) > 64:
            raise NoticeError("complex license expression requires manual review")

    def and_choices(self) -> list[frozenset[str]]:
        result = self.primary_choices()
        while self.peek() == "AND":
            self.take()
            right = self.primary_choices()
            result = [left | other for left in result for other in right]
            self.bound(result)
        return result

    def primary_choices(self) -> list[frozenset[str]]:
        token = self.take()
        if token == "(":
            result = self.or_choices()
            if self.take() != ")":
                raise NoticeError("unclosed expression")
            return result
        return [frozenset({token})]


def choose_licenses(expression: str) -> list[str]:
    issues = expression_issues(expression)
    if issues:
        raise NoticeError("; ".join(issues))
    alternatives = Choices(expression).alternatives()
    # Prefer the MIT route, including MIT over Unlicense or Apache. This only
    # chooses OR branches: mandatory AND terms remain in the resulting set.
    chosen = min(alternatives, key=lambda x: ("MIT" not in x, len(x), sorted(x)))
    unsupported = chosen - SUPPORTED_TEXTS
    if unsupported:
        raise NoticeError("manual complete-text review required for: " + ", ".join(sorted(unsupported)))
    return sorted(chosen)


def confined_file(base: Path, path: Path) -> Path:
    base = base.resolve(strict=True)
    candidate = path.resolve(strict=True)
    try:
        candidate.relative_to(base)
    except ValueError as error:
        raise NoticeError("license file escapes package directory") from error
    if not candidate.is_file():
        raise NoticeError("license candidate is not a regular file")
    return candidate


def license_candidates(package: dict) -> list[tuple[str, bytes]]:
    base = Path(package["manifest_path"]).parent.resolve(strict=True)
    paths = []
    declared = package.get("license_file")
    if declared:
        if not isinstance(declared, str):
            raise NoticeError("invalid declared license file")
        paths.append(base / declared)
    # Only immediate, known license/notice files; never crawl package source.
    for path in sorted(base.iterdir(), key=lambda p: p.name.lower()):
        if re.fullmatch(r"(?:licen[sc]e|copying|notice)(?:[-_.][A-Za-z0-9_.-]+)?", path.name, re.I):
            paths.append(path)
    candidates, seen = [], set()
    for path in paths:
        resolved = confined_file(base, path)
        if resolved in seen:
            continue
        seen.add(resolved)
        data = resolved.read_bytes()
        if not data or len(data) > 1_000_000:
            raise NoticeError("empty or unexpectedly large license text requires review")
        try:
            data.decode("utf-8-sig")
        except UnicodeDecodeError as error:
            raise NoticeError("license encoding requires review") from error
        candidates.append((resolved.relative_to(base).as_posix(), data))
    return candidates


def has_copyright_attribution(text: str) -> bool:
    """Require a real holder line, not the MIT body's reference to a notice."""
    pattern = r"^[ \t]*copyright[ \t]+(?:(?:\(c\)|©)[ \t]*|(?=[12][0-9]{3}(?:\D|$)))([^\r\n]+)"
    for match in re.finditer(pattern, text, re.I | re.M):
        holder = re.sub(r"[0-9\s,.;:\-–—()]+", "", match[1]).lower()
        if (re.search(r"[a-z]", holder) and not any(char in holder for char in "[]<>")
                and holder not in {"allrightsreserved", "copyrightholder", "copyrightholders", "yearname"}):
            return True
    return False


def matches_license(data: bytes, license_id: str) -> bool:
    text = data.decode("utf-8-sig")
    normalized = " ".join(text.lower().split())
    if license_id == "MIT":
        body = " ".join(MIT_BODY.lower().split())
        position = normalized.find(body)
        if position == -1 or normalized[position + len(body):].strip() not in {"", "."}:
            return False
        # Only title and actual attribution headers may precede the full grant.
        grant_start = re.search(r"permission\s+is\s+hereby\s+granted", text, re.I)
        if grant_start is None:
            return False
        headers = [line.strip() for line in text[:grant_start.start()].splitlines() if line.strip()]
        if headers and headers[0].lower() in {"the mit license (mit)", "mit license"}:
            headers.pop(0)
        return bool(headers) and all(has_copyright_attribution(line) for line in headers)
    if license_id == "Unicode-3.0":
        body = " ".join(UNICODE_BODY.lower().split())
        preamble = " ".join(UNICODE_PREAMBLE.lower().split())
        if not normalized.endswith(preamble + " " + body):
            return False
        prefix = normalized[:-(len(preamble) + len(body) + 1)].strip()
        expected = "unicode license v3 copyright and permission notice "
        return (prefix.startswith(expected) and "unicode, inc." in prefix
                and has_copyright_attribution(prefix[len(expected):]))
    return False


def build_plan(metadata: dict, saved_audit: dict) -> tuple[dict, dict[str, bytes]]:
    fresh = audit_metadata(metadata)
    if fresh["dependency_policy_status"] != "passed":
        raise NoticeError("fresh dependency audit is blocked")
    if saved_audit != fresh:
        raise NoticeError("saved audit does not match fresh locked Cargo metadata; regenerate audit")
    packages = {p["id"]: p for p in metadata["packages"]}
    index = {
        "schema_version": 1,
        "purpose": "Exact dependency notice staging for review; not legal certification or a shipped bundle.",
        "release_gate": {"status": "blocked", "authorized": False,
                         "reason": "Root license/copyright decision and release authorization remain pending."},
        "packages": [],
    }
    files, identities, unresolved = {}, set(), []
    for record in fresh["dependencies"]:
        name, version = record["name"], record["version"]
        if not re.fullmatch(r"[A-Za-z0-9_-]+", name) or not re.fullmatch(r"[A-Za-z0-9.+-]+", version):
            raise NoticeError("unsafe package name/version")
        identity = f"{name}-{version}"
        if identity.casefold() in identities:
            raise NoticeError("duplicate package name/version requires source review")
        identities.add(identity.casefold())
        # A crates.io URL is published only for that exact known registry.
        if record["source"] != "registry+https://github.com/rust-lang/crates.io-index":
            raise NoticeError(f"{identity}: non-crates.io source requires public source review")
        try:
            chosen = choose_licenses(record["license_expression"])
            candidates = license_candidates(packages[record["id"]])
            selected = {}
            for license_id in chosen:
                matching = [(path, data) for path, data in candidates if matches_license(data, license_id)]
                if not matching:
                    raise NoticeError(f"missing, mismatched, or unattributed {license_id} license text")
                # Prefer the explicitly named license, but always validate content.
                matching.sort(key=lambda item: (license_id.lower() not in item[0].lower(), item[0]))
                path, data = matching[0]
                selected.setdefault(path, {"data": data, "licenses": []})["licenses"].append(license_id)
            notices = []
            for number, (source_name, selection) in enumerate(sorted(selected.items()), 1):
                filename = f"{identity}/{number:02d}.txt"
                files[filename] = selection["data"]
                notices.append({"path": filename, "package_license_file": source_name,
                                "licenses": selection["licenses"],
                                "kind": selection.get("kind", "license-text"),
                                "sha256": hashlib.sha256(selection["data"]).hexdigest()})
            index["packages"].append({"name": name, "version": version,
                                      "source_url": f"https://crates.io/crates/{name}/{version}",
                                      "declared_license_expression": record["license_expression"],
                                      "chosen_licenses": chosen, "notices": notices})
        except (NoticeError, OSError, ValueError) as error:
            unresolved.append(f"{identity}: {error}")
    if unresolved:
        raise NoticeError("notice collection requires review:\n" + "\n".join(unresolved))
    index["dependency_count"] = len(index["packages"])
    return index, files


def stage_plan(index: dict, files: dict[str, bytes], stage_root: Path, allowed_root: Path) -> Path:
    """Append an atomic unique snapshot; never replace or delete existing data."""
    allowed_root = allowed_root.resolve(strict=True)
    stage_root = stage_root.resolve()
    try:
        stage_root.relative_to(allowed_root)
    except ValueError as error:
        raise NoticeError("staging directory escapes allowed target directory") from error
    stage_root.mkdir(parents=True, exist_ok=True)
    token = uuid.uuid4().hex
    pending = stage_root / f".pending-{token}"
    final = stage_root / f"snapshot-{token}"
    pending.mkdir()
    # An interrupted write leaves a plainly named pending directory. No cleanup
    # traverses or deletes computed paths; only complete snapshots are renamed.
    for relative, data in files.items():
        path = Path(relative)
        if path.is_absolute() or ".." in path.parts or "\\" in relative or ":" in relative:
            raise NoticeError("unsafe generated notice path")
        output = pending / path
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("xb") as stream:
            stream.write(data)
    with (pending / "index.json").open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(index, ensure_ascii=False, indent=2) + "\n")
    # Windows indexers/sync clients can briefly hold a newly written directory.
    # Retry only the atomic rename; never fall back to a partial copy or deletion.
    for attempt in range(6):
        try:
            pending.rename(final)
            break
        except PermissionError:
            if attempt == 5:
                raise
            time.sleep(min(0.05 * (2 ** attempt), 0.4))
    return final


def main(argv: list[str] | None = None) -> int:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest-path", type=Path, default=root / "native" / "Cargo.toml")
    parser.add_argument("--audit-json", type=Path, default=root / "native" / "target" / "license-audit.json")
    parser.add_argument("--metadata-json", type=Path, help="Explicit isolated fixture mode; does not run Cargo")
    parser.add_argument("--dry-run", action="store_true", help="Validate all texts without writing a snapshot")
    args = parser.parse_args(argv)
    try:
        if args.metadata_json and not args.dry_run:
            raise NoticeError("saved metadata fixture mode requires --dry-run; staging requires fresh Cargo metadata")
        metadata = (json.loads(args.metadata_json.read_text(encoding="utf-8-sig"))
                    if args.metadata_json else load_cargo_metadata(args.manifest_path))
        audit = json.loads(args.audit_json.read_text(encoding="utf-8-sig"))
        index, files = build_plan(metadata, audit)
        print(f"Validated {index['dependency_count']} dependencies and {len(files)} exact license text files.")
        if not args.dry_run:
            target = root / "native" / "target"
            try:
                target.resolve().relative_to(root)
            except ValueError as error:
                raise NoticeError("target directory escapes independent project") from error
            target.mkdir(parents=True, exist_ok=True)
            output = stage_plan(index, files, target / "third-party-notices", root)
            print(f"Staged review snapshot: {output}")
        print("Release remains blocked; staging is not legal certification.")
        return 0
    except (AuditError, NoticeError, OSError, ValueError, TypeError, KeyError) as error:
        print(f"BLOCKED: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
