"""Service catalog (component criticality) and keyword lexicon."""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

CATALOG_PATH = Path("config/service_catalog.yaml")
LEXICON_PATH = Path("config/lexicon.yaml")


@dataclass(frozen=True)
class ServiceCatalog:
    default: float
    exact: dict[str, dict[str, float]]
    patterns: tuple[tuple[re.Pattern[str], float], ...]

    def criticality(self, system: str, component: str | None) -> float:
        if not component:
            return self.default
        exact = self.exact.get(system, {})
        if component in exact:
            return exact[component]
        for pattern, value in self.patterns:
            if pattern.search(component):
                return value
        return self.default


@lru_cache(maxsize=4)
def load_catalog(path: Path = CATALOG_PATH) -> ServiceCatalog:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    exact = {
        system: {str(k): float(v) for k, v in comps.items()}
        for system, comps in (raw.get("systems") or {}).items()
    }
    patterns = tuple(
        (re.compile(item["pattern"], re.IGNORECASE), float(item["criticality"]))
        for item in raw.get("patterns", [])
    )
    return ServiceCatalog(float(raw.get("default", 0.4)), exact, patterns)


@lru_cache(maxsize=4)
def load_lexicon(path: Path = LEXICON_PATH) -> dict[str, re.Pattern[str]]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {name: re.compile(pattern, re.IGNORECASE) for name, pattern in raw["categories"].items()}
