"""ITSM ticket models trained on the UCI incident-management event log.

Given the fields a ServiceNow-style ticket has when it is opened, two calibrated linear models
estimate the ticket's eventual priority (with a conformal set) and the risk that it breaches its
SLA. The ITIL impact x urgency matrix is learned from the data (the most common final priority
per pair) rather than assumed, and acts as the auditable rule for ticket-only triage.

Training uses only open-time fields, and the splits are by open time (oldest 70% train), so the
models never learn from outcomes or from the future.
"""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np

from aria.contracts.base import Severity
from aria.contracts.inputs import TicketContext
from aria.severity.model import (
    LinearModel,
    calibrate,
    expected_calibration_error,
    fit_linear_model,
    nll,
)

CATEGORICAL = (
    "category",
    "subcategory",
    "symptom",
    "contact_type",
    "location",
    "assignment_group",
    "impact",
    "urgency",
)
BOOLEAN = ("knowledge", "priority_confirmation")
PRIORITY_SEVERITY = {
    "1": Severity.SEV1,
    "2": Severity.SEV2,
    "3": Severity.SEV3,
    "4": Severity.SEV4,
    "5": Severity.SEV4,
}
_LEVEL = re.compile(r"^\s*(\d)")


def level(value: str | None) -> str | None:
    """'2 - High' -> '2'. Missing or unparseable values -> None."""
    match = _LEVEL.match(value or "")
    return match.group(1) if match else None


def ticket_fields(ticket: TicketContext) -> dict[str, Any]:
    return {
        "category": ticket.category,
        "subcategory": ticket.subcategory,
        "symptom": ticket.symptom,
        "contact_type": ticket.contact_type,
        "location": ticket.location,
        "assignment_group": ticket.assignment_group,
        "impact": level(ticket.impact) or ticket.impact,
        "urgency": level(ticket.urgency) or ticket.urgency,
        "knowledge": ticket.knowledge,
        "priority_confirmation": ticket.priority_confirmation,
        "opened_at": ticket.opened_at,
    }


@dataclass
class TicketEncoder:
    """One-hot encoding with an 'other' bucket per field; rare values fold into 'other'."""

    vocab: dict[str, list[str]]

    @classmethod
    def fit(cls, rows: Sequence[Mapping[str, Any]], *, min_count: int = 20) -> TicketEncoder:
        vocab: dict[str, list[str]] = {}
        for name in CATEGORICAL:
            counts = Counter(
                str(row.get(name)) for row in rows if row.get(name) not in (None, "", "?")
            )
            vocab[name] = sorted(value for value, n in counts.items() if n >= min_count)
        return cls(vocab)

    def names(self) -> list[str]:
        names = [f"{field}={value}" for field, values in self.vocab.items() for value in values]
        names += [f"{field}=other" for field in self.vocab]
        names += [f"{field}=missing" for field in self.vocab]
        names += [f"{field}" for field in BOOLEAN]
        names += ["opened.business_hours", "opened.weekend"]
        return names

    def row(self, fields: Mapping[str, Any]) -> dict[str, float]:
        out: dict[str, float] = {}
        for name, values in self.vocab.items():
            raw = fields.get(name)
            if raw in (None, "", "?"):
                out[f"{name}=missing"] = 1.0
            elif str(raw) in values:
                out[f"{name}={raw}"] = 1.0
            else:
                out[f"{name}=other"] = 1.0
        for name in BOOLEAN:
            out[name] = 1.0 if fields.get(name) else 0.0
        opened = fields.get("opened_at")
        if isinstance(opened, datetime):
            out["opened.business_hours"] = 1.0 if 8 <= opened.hour < 18 else 0.0
            out["opened.weekend"] = 1.0 if opened.weekday() >= 5 else 0.0
        return out


@dataclass
class TicketPrediction:
    priority: str
    severity: Severity
    probabilities: dict[str, float]
    prediction_set: list[str]
    sla_breach_risk: float | None
    matrix_priority: str | None


@dataclass
class TicketModels:
    encoder: TicketEncoder
    priority: LinearModel
    sla: LinearModel | None
    matrix: dict[str, str]  # "impact|urgency" -> most common final priority level
    version: str
    metadata: dict[str, Any]

    def predict(self, ticket: TicketContext) -> TicketPrediction:
        fields = ticket_fields(ticket)
        row = self.encoder.row(fields)
        x = self.priority.matrix([row])
        probs = self.priority.predict_proba(x)[0]
        pset = self.priority.prediction_sets(probs[None, :])[0]
        best = self.priority.classes[int(np.argmax(probs))]
        breach = None
        if self.sla is not None:
            breach = float(
                self.sla.predict_proba(self.sla.matrix([row]))[0][self.sla.classes.index("breach")]
            )
        key = f"{fields.get('impact')}|{fields.get('urgency')}"
        return TicketPrediction(
            priority=best,
            severity=PRIORITY_SEVERITY.get(best, Severity.SEV3),
            probabilities={
                c: round(float(p), 6) for c, p in zip(self.priority.classes, probs, strict=True)
            },
            prediction_set=pset,
            sla_breach_risk=None if breach is None else round(breach, 4),
            matrix_priority=self.matrix.get(key),
        )

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "format": "aria.ticket_models.v1",
            "version": self.version,
            "vocab": self.encoder.vocab,
            "priority": self.priority.to_dict(),
            "sla": self.sla.to_dict() if self.sla else None,
            "matrix": self.matrix,
            "metadata": self.metadata,
        }
        path.write_text(json.dumps(payload, indent=1, sort_keys=True), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> TicketModels:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if raw.get("format") != "aria.ticket_models.v1":
            msg = f"unsupported ticket model format {raw.get('format')!r}"
            raise ValueError(msg)
        return cls(
            encoder=TicketEncoder({k: list(v) for k, v in raw["vocab"].items()}),
            priority=LinearModel.from_dict(raw["priority"]),
            sla=LinearModel.from_dict(raw["sla"]) if raw.get("sla") else None,
            matrix=dict(raw["matrix"]),
            version=str(raw["version"]),
            metadata=dict(raw.get("metadata") or {}),
        )


def learn_matrix(rows: Sequence[Mapping[str, Any]], *, min_count: int = 5) -> dict[str, str]:
    """Most common final priority for each impact x urgency pair seen at least ``min_count`` times."""
    votes: dict[str, Counter[str]] = defaultdict(Counter)
    for row in rows:
        target = level(row.get("priority"))
        if target and row.get("impact") and row.get("urgency"):
            votes[f"{row['impact']}|{row['urgency']}"][target] += 1
    return {
        key: c.most_common(1)[0][0]
        for key, c in sorted(votes.items())
        if sum(c.values()) >= min_count
    }


def summary_fields(summary: Mapping[str, Any]) -> dict[str, Any]:
    """Open-time fields from an aggregated UCI incident (``itsm_incidents`` row or dict)."""
    return {
        "category": summary.get("category"),
        "subcategory": summary.get("subcategory"),
        "symptom": summary.get("symptom"),
        "contact_type": summary.get("contact_type"),
        "location": summary.get("location"),
        "assignment_group": summary.get("first_assignment_group"),
        "impact": level(summary.get("impact")),
        "urgency": level(summary.get("urgency")),
        "knowledge": summary.get("knowledge"),
        "priority_confirmation": summary.get("priority_confirmation"),
        "opened_at": summary.get("opened_at"),
        "priority": summary.get("priority"),
        "made_sla": summary.get("made_sla"),
        "split": summary.get("split", "train"),
    }


def fit_ticket_models(
    summaries: Sequence[Mapping[str, Any]],
    *,
    alpha: float = 0.1,
    min_count: int = 20,
    seed: int = 0,
) -> tuple[TicketModels, dict[str, Any]]:
    rows = [summary_fields(s) for s in summaries if level(s.get("priority"))]
    by_split: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_split[row["split"]].append(row)
    train, calib = by_split["train"], by_split["calib"]
    if not train:
        msg = "no training tickets with a priority"
        raise ValueError(msg)
    half = len(calib) // 2
    temp_rows, conf_rows = calib[:half], calib[half:]  # calib is time-ordered: no peeking ahead
    encoder = TicketEncoder.fit(train, min_count=min_count)
    names = encoder.names()
    classes = sorted({level(r["priority"]) or "" for r in rows} - {""})

    def xy(subset: Sequence[Mapping[str, Any]]) -> tuple[np.ndarray, list[str]]:
        x = np.array(
            [[encoder.row(r).get(n, 0.0) for n in names] for r in subset], dtype=np.float64
        )
        return x, [level(r["priority"]) or "" for r in subset]

    x_tr, y_tr = xy(train)
    priority = fit_linear_model(
        "ticket_priority", x_tr, y_tr, classes=classes, feature_names=names, c=0.5, seed=seed
    )
    x_t, y_t = xy(temp_rows)
    x_c, y_c = xy(conf_rows)
    calibrate(priority, x_t, y_t, x_c, y_c, alpha=alpha)

    sla: LinearModel | None = None
    sla_rows = [r for r in train if r.get("made_sla") is not None]
    if len({r["made_sla"] for r in sla_rows}) == 2:

        def sla_xy(subset: Sequence[Mapping[str, Any]]) -> tuple[np.ndarray, list[str]]:
            kept = [r for r in subset if r.get("made_sla") is not None]
            x = np.array(
                [[encoder.row(r).get(n, 0.0) for n in names] for r in kept], dtype=np.float64
            )
            return x, ["met" if r["made_sla"] else "breach" for r in kept]

        x_s, y_s = sla_xy(sla_rows)
        sla = fit_linear_model(
            "ticket_sla",
            x_s,
            y_s,
            classes=["met", "breach"],
            feature_names=names,
            c=0.5,
            class_weight=None,
            seed=seed,
        )
        st_x, st_y = sla_xy(temp_rows)
        sc_x, sc_y = sla_xy(conf_rows)
        calibrate(sla, st_x, st_y, sc_x, sc_y, alpha=alpha)

    version = f"ticket-{datetime.now(UTC):%Y%m%d}-{len(train)}"
    priority.version = version
    if sla is not None:
        sla.version = version

    def metrics(x: np.ndarray, y: list[str]) -> dict[str, Any]:
        if not y:
            return {}
        idx = np.array([classes.index(v) for v in y])
        probs = priority.predict_proba(x)
        sets = priority.prediction_sets(probs)
        return {
            "n": len(y),
            "accuracy": round(float((probs.argmax(axis=1) == idx).mean()), 4),
            "nll": round(nll(probs, idx), 4),
            "ece": round(expected_calibration_error(probs, idx), 4),
            "coverage": round(float(np.mean([v in s for v, s in zip(y, sets, strict=True)])), 4),
        }

    report = {
        "version": version,
        "n": {split: len(items) for split, items in by_split.items()},
        "classes": classes,
        "priority": {"train": metrics(x_tr, y_tr), "conformal_split": metrics(x_c, y_c)},
        "sla_model": sla is not None,
    }
    models = TicketModels(
        encoder=encoder,
        priority=priority,
        sla=sla,
        matrix=learn_matrix(train),
        version=version,
        metadata={
            "source": "UCI incident management process enriched event log (id 498)",
            **report,
        },
    )
    return models, report
