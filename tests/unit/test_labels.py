from __future__ import annotations

from aria.contracts import Severity
from aria.data.labels import label_window, load_rubric, tag_stats


def _label(pairs: list[tuple[str, str]]) -> Severity:
    rubric = load_rubric()
    severity, _ = label_window(tag_stats(pairs, rubric), rubric)
    return severity


def test_no_alerts_is_sev4() -> None:
    assert _label([]) == Severity.SEV4


def test_one_minor_alert_is_not_an_incident() -> None:
    assert _label([("APPTO", "R01-M0-N0")]) == Severity.SEV4


def test_minor_alerts_in_bulk_are_sev3() -> None:
    assert _label([("APPREAD", f"R01-M0-N{i}") for i in range(5)]) == Severity.SEV3


def test_any_major_alert_is_at_least_sev3() -> None:
    assert _label([("KERNDTLB", "R01-M0-N0")]) == Severity.SEV3


def test_major_alerts_on_many_nodes_escalate() -> None:
    assert _label([("KERNSTOR", f"R01-M0-N{i}") for i in range(8)]) == Severity.SEV2
    assert _label([("KERNSTOR", f"R01-M{i // 16}-N{i % 16}") for i in range(64)]) == Severity.SEV1


def test_critical_alert_spread_decides_sev1_vs_sev2() -> None:
    assert _label([("KERNRTSP", "R01-M0-N0")]) == Severity.SEV2
    assert _label([("KERNRTSP", f"R01-M0-N{i}") for i in range(4)]) == Severity.SEV1


def test_unknown_tags_use_the_default_class() -> None:
    rubric = load_rubric()
    assert rubric.impact("NEWTAG") == rubric.default_class == "major"


def test_label_detail_records_the_counts_and_tags() -> None:
    rubric = load_rubric()
    _, detail = label_window(tag_stats([("KERNRTSP", "a"), ("APPTO", "b")], rubric), rubric)
    assert detail["counts"]["critical_alerts"] == 1
    assert detail["tags"] == {"KERNRTSP": 1, "APPTO": 1}
