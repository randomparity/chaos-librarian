"""Per-rule tests for ``rule_sidecar_language_consistent`` (E_SIDECAR_LANGUAGE_INVALID).

The original ``test_semantic.py`` had no class for this rule — coverage
came only from invalid-corpus YAML fixtures via ``test_invalid_corpus.py``.
After the `rules/` split, this module fills the visible gap with the
minimum positive + negative cases that match the level of detail in the
other per-rule modules.
"""

from __future__ import annotations

from chaos_librarian.validation import codes
from chaos_librarian.validation.pipeline import IssueCollector
from chaos_librarian.validation.semantic import run_semantic_pass


def _asset_with_eng_subtitle() -> dict[str, object]:
    return {
        "id": "a",
        "role": "primary_video",
        "container": "mkv",
        "duration_seconds": 1,
        "subtitles": [{"language": "eng", "mode": "sidecar", "source": "generated"}],
    }


class TestRuleSidecarLanguageConsistent:
    """create_sidecar (target, language) must be unique per scenario.

    WHY: manifest v3 keys ``ManifestSidecar`` lookups on ``(asset_id, language)``.
    A duplicate pair leaves the key ambiguous. The previously-enforced
    "language must be declared on the asset" check was dropped (#39): a
    timeline-only sidecar is legal, and so is overriding a declared
    subtitle with a timeline event (phase A skips the declared write in
    that case to avoid orphaning a file on disk).
    """

    def test_undeclared_language_accepted(
        self, minimal_scenario, empty_index, as_list, as_dict
    ) -> None:
        """WHY: Issue #39 - a timeline create_sidecar whose language is not
        declared on the asset is now valid; the materializer treats it as
        a timeline-only sidecar (no phase-A write, only phase-B)."""
        raw = minimal_scenario(
            timeline=[
                {
                    "id": "e1",
                    "at": "1s",
                    "action": "create_sidecar",
                    "target": "a",
                    "to": "r/a.fra.srt",
                    "language": "fra",  # not declared; legal post-#39
                },
            ],
        )
        bundle = as_dict(as_list(as_list(raw["works"])[0]["variants"])[0]["bundle"])
        assets = as_list(bundle["assets"])
        assets[0] = _asset_with_eng_subtitle()
        collector = IssueCollector()
        run_semantic_pass(raw, empty_index, collector)
        assert not any(i.code == codes.E_SIDECAR_LANGUAGE_INVALID for i in collector.issues)

    def test_duplicate_target_language_flagged(
        self, minimal_scenario, empty_index, as_list, as_dict
    ) -> None:
        raw = minimal_scenario(
            timeline=[
                {
                    "id": "e1",
                    "at": "1s",
                    "action": "create_sidecar",
                    "target": "a",
                    "to": "r/a.eng.srt",
                    "language": "eng",
                },
                {
                    "id": "e2",
                    "at": "2s",
                    "action": "create_sidecar",
                    "target": "a",
                    "to": "r/a.eng.alt.srt",
                    "language": "eng",  # duplicate (target, language)
                },
            ],
        )
        bundle = as_dict(as_list(as_list(raw["works"])[0]["variants"])[0]["bundle"])
        assets = as_list(bundle["assets"])
        assets[0] = _asset_with_eng_subtitle()
        collector = IssueCollector()
        run_semantic_pass(raw, empty_index, collector)
        issues = [i for i in collector.issues if i.code == codes.E_SIDECAR_LANGUAGE_INVALID]
        assert any("duplicate" in i.message for i in issues)

    def test_consistent_event_no_issue(
        self, minimal_scenario, empty_index, as_list, as_dict
    ) -> None:
        raw = minimal_scenario(
            timeline=[
                {
                    "id": "e1",
                    "at": "1s",
                    "action": "create_sidecar",
                    "target": "a",
                    "to": "r/a.eng.srt",
                    "language": "eng",
                },
            ],
        )
        bundle = as_dict(as_list(as_list(raw["works"])[0]["variants"])[0]["bundle"])
        assets = as_list(bundle["assets"])
        assets[0] = _asset_with_eng_subtitle()
        collector = IssueCollector()
        run_semantic_pass(raw, empty_index, collector)
        assert not any(i.code == codes.E_SIDECAR_LANGUAGE_INVALID for i in collector.issues)
