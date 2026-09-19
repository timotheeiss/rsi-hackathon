from __future__ import annotations

import fcntl
import hashlib
import json
import os
import random
import re
import tempfile
from contextlib import contextmanager
from pathlib import Path

from ..config import HackathonCfg, task_names
from .settings import Settings


def read_json(path: Path) -> dict:
    return json.loads(path.read_text())


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".pending-", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(value, stream, indent=2, ensure_ascii=False, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def tree_digest(root: Path) -> str:
    h = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError(f"symlinks are not allowed in experiment inputs: {path}")
        if path.is_file() and "__pycache__" not in path.parts and not path.name.endswith(".pyc"):
            h.update(path.relative_to(root).as_posix().encode() + b"\0")
            h.update(hashlib.sha256(path.read_bytes()).digest())
    return h.hexdigest()


@contextmanager
def experiment_lock(root: Path):
    root.mkdir(parents=True, exist_ok=True)
    with (root / ".lock").open("w") as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError(f"another process owns {root}") from None
        try:
            yield
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)


def split_tasks(cfg: Settings, contract: HackathonCfg) -> dict:
    splits = {}
    for name, domain in cfg.domains.items():
        available = task_names(contract.domain(name))
        known = set(available)

        def from_file(filename):
            if not filename:
                return None
            names = [x for x in re.split(r"[,\s]+", cfg.path(filename).read_text().strip()) if x]
            if not names or len(set(names)) != len(names) or not set(names) <= known:
                raise ValueError(f"{name}: split file is empty, duplicated, or has unknown tasks: {filename}")
            return names

        dev, holdout = from_file(domain.dev_file), from_file(domain.holdout_file)
        reserved = set(dev or []) | set(holdout or [])
        remaining = [n for n in available if n not in reserved]
        random.Random(f"{cfg.seed}:{name}").shuffle(remaining)
        if dev is None:
            dev, remaining = remaining[:domain.dev_size], remaining[domain.dev_size:]
            if len(dev) != domain.dev_size:
                raise ValueError(f"{name}: too few development tasks")
        if holdout is None:
            holdout = remaining[:domain.holdout_size]
            if len(holdout) != domain.holdout_size:
                raise ValueError(f"{name}: too few holdout tasks")
        if set(dev) & set(holdout):
            raise ValueError(f"{name}: development and holdout tasks overlap")
        splits[name] = {"dev": dev, "holdout": holdout}
    return splits


def manifest(cfg: Settings, contract: HackathonCfg) -> dict:
    splits = split_tasks(cfg, contract)
    return {
        "version": 1, "settings": cfg.identity(), "splits": splits,
        "contract_sha256": digest(cfg.contract.read_bytes()),
        "dependency_lock_sha256": digest((cfg.root / "uv.lock").read_bytes()) if (cfg.root / "uv.lock").exists() else None,
        "runtime_sha256": tree_digest(Path(__file__).parents[1]),
        "data_sha256": {d: {n: tree_digest(contract.domain(d).dataset_dir / n)
                             for names in split.values() for n in names}
                        for d, split in splits.items()},
        "seed_sha256": {d: tree_digest(cfg.path(spec.skill)) for d, spec in cfg.domains.items()},
    }
