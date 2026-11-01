"""Drain: online log template mining with a fixed-depth parse tree.

Implementation of P. He, J. Zhu, Z. Zheng, M. R. Lyu, "Drain: An Online Log Parsing Approach with
Fixed Depth Tree", ICWS 2017. Lines are first masked (IPs, hex, numbers, block IDs...) so volatile
values do not split templates, then routed by token count and leading tokens to a leaf, where
the most similar cluster absorbs the line or a new cluster starts.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

WILDCARD = "<*>"

# Redaction pseudonyms (``ip-3fa2c1d0``) are keyed per run, so they are always a variable; left
# to the number mask, their hex letters would leak into templates and differ from run to run.
PSEUDONYM_MASK = (r"\b(?:ip|email)-[0-9a-f]{8}\b", WILDCARD)

# Order matters: specific shapes before the generic number mask.
DEFAULT_MASKS: tuple[tuple[str, str], ...] = (
    PSEUDONYM_MASK,
    (r"blk_-?\d+", "blk_<*>"),
    (r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b", WILDCARD),
    (r"\b(?:\d{1,3}\.){3}\d{1,3}(?::\d{1,5})?\b", WILDCARD),
    (r"\b0[xX][0-9a-fA-F]+\b", WILDCARD),
    (r"\b[0-9a-fA-F]{12,}\b", WILDCARD),
    (r"(?<![A-Za-z])-?\d+(?:\.\d+)?(?![A-Za-z])", WILDCARD),
)

_SPLIT = re.compile(r"\s+")


def _has_digit(token: str) -> bool:
    return any(ch.isdigit() for ch in token)


@dataclass
class Cluster:
    id: int
    tokens: list[str]
    size: int = 0

    @property
    def template(self) -> str:
        return " ".join(self.tokens)


@dataclass
class _Node:
    children: dict[str, _Node] = field(default_factory=dict)
    clusters: list[int] = field(default_factory=list)


class Drain:
    """A Drain parse tree. One instance learns templates for one log source."""

    def __init__(
        self,
        *,
        depth: int = 4,
        sim_threshold: float = 0.4,
        max_children: int = 100,
        masks: Sequence[tuple[str, str]] = DEFAULT_MASKS,
    ) -> None:
        if depth < 3:
            msg = "depth must be at least 3"
            raise ValueError(msg)
        self.depth = depth
        self.sim_threshold = sim_threshold
        self.max_children = max_children
        self._masks = [(re.compile(pattern), replacement) for pattern, replacement in masks]
        self._root = _Node()
        self.clusters: list[Cluster] = []

    def mask(self, message: str) -> str:
        for pattern, replacement in self._masks:
            message = pattern.sub(replacement, message)
        return message

    def tokenize(self, message: str) -> list[str]:
        return [t for t in _SPLIT.split(self.mask(message).strip()) if t]

    # -- tree navigation ------------------------------------------------------------------------

    def _leaf(self, tokens: list[str], *, create: bool) -> _Node | None:
        node = self._root.children.get(str(len(tokens)))
        if node is None:
            if not create:
                return None
            node = self._root.children.setdefault(str(len(tokens)), _Node())
        for depth, token in enumerate(tokens[: self.depth - 2]):
            if depth >= len(tokens):
                break
            key = WILDCARD if _has_digit(token) else token
            child = node.children.get(key) or node.children.get(WILDCARD)
            if child is None:
                if not create:
                    return None
                if len(node.children) < self.max_children - 1 or key == WILDCARD:
                    child = node.children.setdefault(key, _Node())
                else:
                    child = node.children.setdefault(WILDCARD, _Node())
            node = child
        return node

    @staticmethod
    def _similarity(template: list[str], tokens: list[str]) -> tuple[float, int]:
        same = wild = 0
        for a, b in zip(template, tokens, strict=True):
            if a == WILDCARD:
                wild += 1
            elif a == b:
                same += 1
        return same / len(tokens) if tokens else 1.0, wild

    def _best(self, leaf: _Node, tokens: list[str]) -> Cluster | None:
        best: Cluster | None = None
        best_key = (-1.0, -1)
        for cid in leaf.clusters:
            cluster = self.clusters[cid]
            sim, wild = self._similarity(cluster.tokens, tokens)
            if sim >= self.sim_threshold and (sim, wild) > best_key:
                best, best_key = cluster, (sim, wild)
        return best

    # -- public API -----------------------------------------------------------------------------

    def add(self, message: str) -> Cluster:
        """Absorb one message and return its (possibly generalised) cluster."""
        tokens = self.tokenize(message)
        if not tokens:
            tokens = [WILDCARD]
        leaf = self._leaf(tokens, create=True)
        if leaf is None:  # pragma: no cover - create=True always returns a node
            msg = "tree insertion failed"
            raise RuntimeError(msg)
        cluster = self._best(leaf, tokens)
        if cluster is None:
            cluster = Cluster(id=len(self.clusters), tokens=list(tokens))
            self.clusters.append(cluster)
            leaf.clusters.append(cluster.id)
        else:
            cluster.tokens = [
                a if a == b else WILDCARD for a, b in zip(cluster.tokens, tokens, strict=True)
            ]
        cluster.size += 1
        return cluster

    def match(self, message: str) -> Cluster | None:
        """Find the cluster a message would join, using the same similarity rule, without learning."""
        tokens = self.tokenize(message) or [WILDCARD]
        leaf = self._leaf(tokens, create=False)
        return None if leaf is None else self._best(leaf, tokens)

    def fit(self, messages: Iterable[str]) -> list[int]:
        """Learn from every message and return each one's cluster id."""
        return [self.add(m).id for m in messages]

    def seed(self, templates: Iterable[str]) -> None:
        """Pre-load known templates (for example from earlier runs) so novelty can be measured.

        Seeding generalises clusters as it goes, so the templates are deduplicated and sorted
        first: the same history always builds the same tree, whatever order a store returns it.
        """
        for template in sorted(set(templates)):
            self.add(template)


def template_id(system: str, template: str) -> str:
    """A stable id for a template string, independent of cluster numbering."""
    digest = hashlib.sha1(f"{system}\x00{template}".encode(), usedforsecurity=False).hexdigest()
    return f"T{digest[:10]}"


def parameters(template: str, message: str) -> list[str]:
    """Values the wildcards stand for (best effort, token aligned)."""
    template_tokens = template.split()
    raw_tokens = [t for t in _SPLIT.split(message.strip()) if t]
    if len(template_tokens) != len(raw_tokens):
        return []
    return [
        raw
        for tpl, raw in zip(template_tokens, raw_tokens, strict=True)
        if WILDCARD in tpl and tpl != raw
    ]


@dataclass(frozen=True)
class DrainSettings:
    masks: tuple[tuple[str, str], ...]
    sim_threshold: float = 0.5
    depth: int = 4


def _m(*patterns: str) -> tuple[tuple[str, str], ...]:
    return tuple((p, WILDCARD) for p in patterns)


# Per-system preprocessing and parameters from the logparser benchmark settings that accompany
# Loghub (Zhu et al., ICSE-SEIP 2019), with ARIA's generic masks appended where they help.
SYSTEM_SETTINGS: dict[str, DrainSettings] = {
    "hdfs": DrainSettings(_m(r"blk_-?\d+", r"(\d+\.){3}\d+(:\d+)?"), 0.5, 4),
    "hadoop": DrainSettings(_m(r"(\d+\.){3}\d+"), 0.5, 4),
    "spark": DrainSettings(_m(r"(\d+\.){3}\d+", r"\b[KGTM]?B\b", r"([\w-]+\.){2,}[\w-]+"), 0.5, 4),
    "zookeeper": DrainSettings(_m(r"(/|)(\d+\.){3}\d+(:\d+)?"), 0.5, 4),
    "bgl": DrainSettings(_m(r"core\.\d+"), 0.5, 4),
    "hpc": DrainSettings(_m(r"=\d+"), 0.5, 4),
    "windows": DrainSettings(_m(r"0x.*?\s"), 0.7, 5),
    "linux": DrainSettings(_m(r"(\d+\.){3}\d+", r"\d{2}:\d{2}:\d{2}"), 0.39, 6),
    "android": DrainSettings(
        _m(
            r"(/[\w-]+)+",
            r"([\w-]+\.){2,}[\w-]+",
            r"\b(\-?\+?\d+)\b|\b0[Xx][a-fA-F\d]+\b|\b[a-fA-F\d]{4,}\b",
        ),
        0.2,
        6,
    ),
    "healthapp": DrainSettings((), 0.2, 4),
    "apache": DrainSettings(_m(r"(\d+\.){3}\d+"), 0.5, 4),
    "proxifier": DrainSettings(
        _m(r"<\d+\ssec", r"([\w-]+\.)+[\w-]+(:\d+)?", r"\d{2}:\d{2}(:\d{2})*", r"[KGTM]B"), 0.6, 3
    ),
    "openssh": DrainSettings(_m(r"(\d+\.){3}\d+", r"([\w-]+\.){2,}[\w-]+"), 0.6, 5),
    "openstack": DrainSettings(_m(r"((\d+\.){3}\d+,?)+", r"/.+?\s", r"\d+"), 0.5, 5),
    "mac": DrainSettings(_m(r"([\w-]+\.){2,}[\w-]+"), 0.7, 6),
}
GENERIC_SETTINGS = DrainSettings(DEFAULT_MASKS, 0.5, 4)


def drain_for(system: str, *, generic_masks: bool = False) -> Drain:
    """A Drain configured for a known system, or with ARIA's generic masks otherwise."""
    settings = SYSTEM_SETTINGS.get(system, GENERIC_SETTINGS)
    masks = settings.masks
    if settings is not GENERIC_SETTINGS:
        # Redaction runs before mining, so the benchmark's IP masks never see a raw address:
        # the per-run pseudonyms that replace them are masked first.
        masks = (PSEUDONYM_MASK, *masks, *(DEFAULT_MASKS if generic_masks else ()))
    return Drain(depth=max(3, settings.depth), sim_threshold=settings.sim_threshold, masks=masks)
