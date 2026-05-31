"""Semantic-validation pass — thin dispatcher over ``validation/rules/``.

Each ``E_*`` rule lives in its own module under ``validation/rules/``.
``_RULES`` lists them in declared run order (the order is part of the
consumer contract — see ``docs/superpowers/specs/...sprint-1-validate-design.md``).
``run_semantic_pass`` is the only public surface exported here; it is
imported by ``validation/pipeline.py``.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING

from chaos_librarian.validation.rules.asset_path_safety import (
    rule_asset_id_container_safe,
    rule_remux_container_safe,
)
from chaos_librarian.validation.rules.content_reference import rule_content_reference
from chaos_librarian.validation.rules.create_sidecar_content import (
    rule_create_sidecar_content,
)
from chaos_librarian.validation.rules.duration_syntax import rule_duration_syntax
from chaos_librarian.validation.rules.extract_track_unknown import (
    rule_extract_track_unknown,
)
from chaos_librarian.validation.rules.hierarchy import (
    rule_hierarchy_invariants,
    rule_hierarchy_timeline,
    rule_media_action_compatible_with_parent,
    rule_rendered_path_collisions,
)
from chaos_librarian.validation.rules.id_duplicate import rule_id_duplicate
from chaos_librarian.validation.rules.materialize_media_matrix import (
    rule_materialize_media_matrix,
)
from chaos_librarian.validation.rules.network_fs_chaos import (
    rule_network_fs_chaos_pairing,
    rule_network_fs_chaos_target,
)
from chaos_librarian.validation.rules.network_lag import rule_network_lag
from chaos_librarian.validation.rules.path_containment import rule_path_containment
from chaos_librarian.validation.rules.path_duplicate import rule_path_duplicate
from chaos_librarian.validation.rules.profile_budgets import rule_profile_budgets
from chaos_librarian.validation.rules.profile_opt_in import rule_profile_opt_in
from chaos_librarian.validation.rules.raw_helpers import Rule
from chaos_librarian.validation.rules.sidecar_language import rule_sidecar_language_consistent
from chaos_librarian.validation.rules.sidecar_target import rule_sidecar_target
from chaos_librarian.validation.rules.slow_copy import (
    rule_slow_copy_path_collision,
    rule_slow_copy_timing,
    rule_slow_copy_unpaired,
)
from chaos_librarian.validation.rules.symlink_target import rule_symlink_target_escape
from chaos_librarian.validation.rules.target_unknown import (
    rule_root_unknown,
    rule_target_unknown,
)
from chaos_librarian.validation.rules.timeline_lifecycle import rule_timeline_lifecycle
from chaos_librarian.validation.rules.timeline_order import rule_timeline_order

if TYPE_CHECKING:
    from chaos_librarian.scenario_io import LineIndex
    from chaos_librarian.validation.pipeline import IssueCollector


_RULES: list[Rule] = [
    rule_id_duplicate,
    rule_path_duplicate,
    rule_duration_syntax,
    rule_target_unknown,
    rule_content_reference,
    rule_symlink_target_escape,
    rule_profile_opt_in,
    rule_profile_budgets,
    rule_root_unknown,
    rule_hierarchy_invariants,
    rule_rendered_path_collisions,
    rule_slow_copy_unpaired,
    rule_slow_copy_timing,
    rule_slow_copy_path_collision,
    rule_network_lag,
    rule_network_fs_chaos_target,
    rule_network_fs_chaos_pairing,
    rule_path_containment,
    rule_timeline_order,
    rule_timeline_lifecycle,
    rule_hierarchy_timeline,
    rule_asset_id_container_safe,
    rule_remux_container_safe,
    rule_materialize_media_matrix,
    rule_media_action_compatible_with_parent,
    rule_sidecar_language_consistent,
    rule_sidecar_target,
    rule_extract_track_unknown,
    rule_create_sidecar_content,
]


def run_semantic_pass(
    raw_data: Mapping[str, object],
    line_index: LineIndex,
    collector: IssueCollector,
) -> None:
    """Apply every registered rule in declared order."""
    for rule in _RULES:
        rule(raw_data, line_index, collector)
