"""Core engine for PROMPTPACK.

The registry is a single JSON document::

    {
      "prompts": {
        "<name>": {
          "versions": [ {version, body, created_at, message, hash}, ... ],
          "tags": { "<tag>": <version> },
          "ab": { "<tag>": [ {version, weight}, ... ] }
        }
      }
    }

Versions are immutable and monotonically increasing (1-based). Tags are mutable
pointers (like git refs) that enable rollbacks. A/B groups attach weighted
variants to a tag for deterministic-by-key or random selection.
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import os
import random
import re
import string
from typing import Any, Dict, List, Optional

DEFAULT_DB = os.environ.get("PROMPTPACK_DB", ".promptpack.json")

_VAR_RE = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")


class PromptPackError(Exception):
    """Base error."""


class NotFoundError(PromptPackError):
    """Requested prompt/version/tag does not exist."""


class ConflictError(PromptPackError):
    """Operation conflicts with existing state."""


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat()


def _hash(body: str) -> str:
    return hashlib.sha256(body.encode("utf-8")).hexdigest()[:12]


class Registry:
    """A file-backed prompt registry."""

    def __init__(self, path: str = DEFAULT_DB):
        self.path = path
        self._data: Dict[str, Any] = {"prompts": {}}
        self._load()

    # ---- persistence -------------------------------------------------
    def _load(self) -> None:
        if os.path.exists(self.path):
            with open(self.path, "r", encoding="utf-8") as fh:
                self._data = json.load(fh)
        self._data.setdefault("prompts", {})

    def save(self) -> None:
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(self._data, fh, indent=2, sort_keys=True)
        os.replace(tmp, self.path)

    # ---- internal helpers --------------------------------------------
    def _prompt(self, name: str) -> Dict[str, Any]:
        try:
            return self._data["prompts"][name]
        except KeyError:
            raise NotFoundError(f"prompt not found: {name!r}")

    def _resolve_version(self, name: str, ref: Optional[str]) -> int:
        """Resolve a ref to a concrete version number.

        ``ref`` may be None (=> latest), an int-like string, or a tag name.
        """
        p = self._prompt(name)
        versions = p["versions"]
        if not versions:
            raise NotFoundError(f"prompt has no versions: {name!r}")
        if ref is None or ref == "latest":
            return versions[-1]["version"]
        if isinstance(ref, int) or (isinstance(ref, str) and ref.isdigit()):
            v = int(ref)
            if not any(x["version"] == v for x in versions):
                raise NotFoundError(f"version not found: {name}@{v}")
            return v
        if ref in p["tags"]:
            return p["tags"][ref]
        raise NotFoundError(f"unknown ref {ref!r} for {name!r}")

    def _version_obj(self, name: str, version: int) -> Dict[str, Any]:
        for x in self._prompt(name)["versions"]:
            if x["version"] == version:
                return x
        raise NotFoundError(f"version not found: {name}@{version}")

    # ---- public API --------------------------------------------------
    def list_prompts(self) -> List[Dict[str, Any]]:
        out = []
        for name, p in sorted(self._data["prompts"].items()):
            latest = p["versions"][-1]["version"] if p["versions"] else 0
            out.append({
                "name": name,
                "versions": len(p["versions"]),
                "latest": latest,
                "tags": dict(sorted(p["tags"].items())),
            })
        return out

    def commit(self, name: str, body: str, message: str = "") -> Dict[str, Any]:
        """Append a new immutable version. Refuses duplicate-of-latest bodies."""
        p = self._data["prompts"].setdefault(
            name, {"versions": [], "tags": {}, "ab": {}}
        )
        if p["versions"] and p["versions"][-1]["body"] == body:
            raise ConflictError(
                f"body identical to latest version of {name!r}; nothing to commit"
            )
        version = (p["versions"][-1]["version"] + 1) if p["versions"] else 1
        obj = {
            "version": version,
            "body": body,
            "message": message,
            "created_at": _now(),
            "hash": _hash(body),
            "vars": sorted(set(_VAR_RE.findall(body))),
        }
        p["versions"].append(obj)
        return obj

    def get(self, name: str, ref: Optional[str] = None) -> Dict[str, Any]:
        version = self._resolve_version(name, ref)
        return dict(self._version_obj(name, version))

    def history(self, name: str) -> List[Dict[str, Any]]:
        return [
            {k: v for k, v in obj.items() if k != "body"}
            for obj in self._prompt(name)["versions"]
        ]

    def tag(self, name: str, tag: str, ref: Optional[str] = None) -> Dict[str, Any]:
        version = self._resolve_version(name, ref)
        self._prompt(name)["tags"][tag] = version
        return {"name": name, "tag": tag, "version": version}

    def rollback(self, name: str, tag: str, ref: str) -> Dict[str, Any]:
        """Point a tag at a prior version (a deliberate, audited move)."""
        p = self._prompt(name)
        if tag not in p["tags"]:
            raise NotFoundError(f"tag not found: {name}:{tag}")
        prev = p["tags"][tag]
        version = self._resolve_version(name, ref)
        p["tags"][tag] = version
        return {"name": name, "tag": tag, "from": prev, "to": version}

    def render(self, name: str, variables: Dict[str, str],
               ref: Optional[str] = None) -> str:
        obj = self.get(name, ref)
        try:
            return string.Template(
                _VAR_RE.sub(r"${\1}", obj["body"])
            ).substitute(variables)
        except KeyError as exc:
            raise PromptPackError(f"missing variable: {exc.args[0]}")

    def diff(self, name: str, ref_a: str, ref_b: str) -> List[Dict[str, Any]]:
        import difflib
        a = self.get(name, ref_a)
        b = self.get(name, ref_b)
        lines = list(difflib.unified_diff(
            a["body"].splitlines(),
            b["body"].splitlines(),
            fromfile=f"{name}@{a['version']}",
            tofile=f"{name}@{b['version']}",
            lineterm="",
        ))
        return lines

    def set_ab(self, name: str, tag: str,
               variants: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Attach weighted A/B variants to a tag.

        ``variants`` is a list of {"version": int, "weight": number}.
        """
        p = self._prompt(name)
        norm = []
        for v in variants:
            ver = self._resolve_version(name, str(v["version"]))
            weight = float(v.get("weight", 1))
            if weight <= 0:
                raise PromptPackError("weights must be positive")
            norm.append({"version": ver, "weight": weight})
        if not norm:
            raise PromptPackError("at least one variant required")
        p["ab"][tag] = norm
        return {"name": name, "tag": tag, "variants": norm}

    def choose(self, name: str, tag: str, key: Optional[str] = None) -> Dict[str, Any]:
        """Select an A/B variant. Deterministic when ``key`` is given."""
        p = self._prompt(name)
        variants = p["ab"].get(tag)
        if not variants:
            # fall back to plain tag pointer
            version = self._resolve_version(name, tag)
            obj = self._version_obj(name, version)
            return {"version": version, "weight": None, "hash": obj["hash"]}
        total = sum(v["weight"] for v in variants)
        if key is not None:
            h = int(hashlib.sha256(key.encode("utf-8")).hexdigest(), 16)
            point = (h % 10_000_000) / 10_000_000 * total
        else:
            point = random.random() * total
        acc = 0.0
        chosen = variants[-1]
        for v in variants:
            acc += v["weight"]
            if point < acc:
                chosen = v
                break
        obj = self._version_obj(name, chosen["version"])
        return {
            "version": chosen["version"],
            "weight": chosen["weight"],
            "hash": obj["hash"],
        }
