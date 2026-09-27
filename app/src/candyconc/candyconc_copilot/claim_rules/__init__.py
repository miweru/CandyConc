"""Family-scoped claim rules for the grounding validate layer.

K3 Slice 2: one module per analysis family plus ``_shared`` for the
cross-family predicate and number-binding machinery. All symbols are
byte-verbatim moves out of ``analysis_grounding``, which re-exports
every one of them eagerly. Modules here import only the lower
grounding layers (schemas/evidence/contracts) and ``_shared``, never
the facade.
"""

from ._shared import (
    _vae_rule_claim_restates_user_task,
    _vae_rule_response_requirement_id,
    _vae_rule_claim_bundles_analytical_units,
    _vae_rule_lexical_absence_overreads_contextual_retrieval,
    _vae_rule_expanded_kwic_fact_ids,
    _vae_rule_has_cross_source_literal_separation,
    _vae_rule_normalised_time_trend_status,
    _vae_rule_generic_time_trend_status,
    _vae_rule_nonpositive_only_claim_has_positive_assertion,
    _vae_rule_negative_or_unknown_limitation,
    _vae_rule_flattened_cqlf_query,
    _vae_rule_negative_or_unknown_limitation_2,
    _vae_rule_unsupported_raw_pos_inference,
    _vae_rule_unsupported_pos_inventory_provenance,
    _vae_rule_unsupported_natural_pos_label,
    _vae_rule_unsupported_absolute_association_magnitude,
    _vae_rule_empty_collocation_profile_is_overread,
    _vae_rule_unsupported_collocation_pos_composition,
    _vae_rule_is_explicitly_bounded_claim,
    _vae_rule_unsupported_platform_handle_label,
    _vae_rule_unsupported_document_class_label,
    _vae_rule_unsupported_user_handle_identity,
    _vae_rule_absolute_counts_called_relative,
    _vae_rule_unsupported_register_theme_inference,
    _vae_rule_unsupported_grammatical_profile_inference,
    _vae_rule_result_is_mislabeled_as_sample,
    _vae_rule_declared_sample_cardinality_is_wrong,
    _vae_rule_is_explicitly_bounded_claim_2,
    _vae_rule_is_explicitly_bounded_claim_3,
    _vae_rule_unsupported_syntactic_roles,
    _vae_rule_unsupported_presence,
    _vae_rule_unsupported_directional_presence,
    _vae_rule_unsupported_hashtag_label,
    _vae_rule_unsupported_partial_exhaustivity,
    _vae_rule_unsupported_artifacts,
    _vae_rule_unsupported_ngram_function_frequency,
    _vae_rule_unsupported_text_origin,
    _vae_rule_unsupported_pos,
    _vae_rule_unsupported_provenance,
    _vae_rule_unsupported_distribution,
    _vae_rule_unsupported_scope_design,
    _vae_rule_unsupported_diversity,
    _vae_rule_source_attributed_cross_sentence_inference,
    _vae_rule_source_attributed_unmarked_causal_link,
    _vae_rule_source_attributed_cross_sentence_predicate_transfer,
    _vae_rule_unsupported_correlations,
    _vae_rule_merges_cross_result_rankings,
    _vae_rule_analytical_prose,
    _vae_rule_claim,
    _vae_rule_uses_technical_partition_as_content_axis,
    _vae_rule_claim_2,
    _vae_rule_deliverable_kind,
    _vae_rule_near_duplicate_research_question,
    _vae_rule_followup_correlation_is_operationalised,
    _vae_rule_followup_mixes_aggregate_and_token_validation,
    _vae_rule_followup_uses_sentence_length_as_complexity,
    _vae_rule_distribution_substitutes_for_thematic_analysis,
    _vae_rule_distribution_substitutes_for_function_analysis,
    _vae_rule_pos_inventory_substitutes_for_morphosyntax,
    _vae_rule_collocation_substitutes_for_discourse_function,
    _vae_rule_local_association_lacks_collocation_design,
    _vae_rule_accounting_gap_lacks_token_reconciliation,
    _vae_rule_claim_mentions_specific_fact_anchor,
    _vae_rule_overview_observation_is_provenance_only,
    _vae_rule_analytical_prose_2,
    _vae_rule_is_rank_range_claim,
    _vae_rule_numeric_tokens,
    _vae_rule_unsupported_count_bindings,
    _vae_rule_unsupported_ratio_bindings,
    _vae_rule_unsupported_rate_bindings,
    _vae_rule_unsupported_percent_bindings,
    _vae_rule_unsupported_elliptical_counts,
    _vae_rule_unsupported_postposed_counts,
    _vae_rule_unsupported_unit_free_counts,
    _vae_rule_unsupported_word_percent_bindings,
    _vae_rule_unsupported_natural_metrics,
    _vae_rule_unsupported_metric_maxima,
    _vae_rule_unsupported_metric_ranges,
    _vae_rule_unsupported_rate_denominators,
    _vae_rule_unsupported_assignments,
    _vae_rule_row_field_assignments_are_atomic,
    _vae_rule_RAW_TRUNCATION_MARKER_PATTERN,
    _vae_rule_INTERNAL_GROUNDING_MARKER_PATTERN,
    _vae_rule_unsupported_quoted_segments,
    _vae_rule_claim_3,
    _vae_rule_claim_corpus_token_basis_is_visible,
    _vae_rule_claim_total_hits_basis_is_visible,
    _vae_rule_has_positive_partition_purpose_claim,
    _vae_rule_fact,
    _vae_rule_unmeasured_magnitude,
    _vae_rule_item,
    _vae_rule_stronger_than_exactness,
)
from .kwic import (
    _vae_rule_unsupported_kwic_source_role_attribution,
    _vae_rule_unsupported_context_interpretations,
    _vae_rule_unsupported_open_window_interpretations,
    _vae_rule_unsupported_kwic_diversity,
    _vae_rule_unsupported_kwic_prevalence,
    _vae_rule_unsupported_kwic_subset_counts,
    _vae_rule_unsupported_exact_kwic_category_claim,
    _vae_rule_has_definitive_global_scope_claim,
)
from .ngram import (
    _vae_rule_unsupported_ngram_units,
    _vae_rule_unsupported_ngram_contexts,
    _vae_rule_unsupported_multi_ngram_candidate_claim,
    _vae_rule_unsupported_ngram_semantic_validation,
)
from .keyness import (
    _vae_rule_unsupported_keyness_label,
    _vae_rule_unsupported_keyness_same_items_claim,
    _vae_rule_unsupported_balanced_keyness_global_rank_claim,
    _vae_rule_unsupported_keyness_lexical_core_claim,
    _vae_rule_unsupported_absolute_keyness_magnitude,
    _vae_rule_unsupported_keyness_causes,
)
from .frequency import (
    _vae_rule_unsupported_absolute_frequency_magnitude,
    _vae_rule_unsupported_frequency_theme_inference,
    _vae_rule_unsupported_frequency_copresence_inference,
    _vae_rule_followup_infers_morphology_from_surface_frequency,
    _vae_rule_unsupported_frequency_directions,
    _vae_rule_followup_confounds_raw_frequency_with_length,
    _vae_rule_pmw_inconsistent_with_count,
)
from .semantic import (
    _vae_rule_has_positive_semantic_cooccurrence_claim,
    _vae_rule_semantic_retrieval_is_mislabeled_as_frequency,
    _vae_rule_semantic_retrieval_is_mislabeled_as_centrality,
    _vae_rule_uses_single_collocation_as_semantic_similarity,
)
from .metadata import (
    _vae_rule_metadata_values_are_falsely_absent,
    _vae_rule_negative_or_unknown_limitation_4,
    _vae_rule_negative_or_unknown_limitation_5,
    _vae_rule_negative_or_unknown_limitation_6,
)
from .term_binding import (
    _vae_rule_term_result_mismatch,
)
from .wordsketch import (
    _vae_rule_word_sketch_violations,
    _vae_rule_word_sketch_evidence_is_falsely_absent,
)
from .dispersion import (
    _vae_rule_negative_or_unknown_limitation_3,
    _vae_rule_unsupported_dispersion_interpretations,
)

# --------------------------------------------------------------------------- #
# Severity-Politik (Produktentscheid 2026-08): hart blockiert wird NUR
# Fabrikation. Jede Regel traegt eine severity ('hard' | 'advisory').
#
#   hard      -> die Rueckweisung des Claims (Blockieren, Repair-Schleifen).
#   advisory  -> beratende Annotation; der Claim bleibt akzeptiert und die
#                Begruendung wird als Annotation am Envelope durchgereicht.
#
# HART sind ausschliesslich die vier gepinnten Fabrikationsklassen:
#   (a) unaufloesbare/erfundene Referenzen und ungebundene oder falsch
#       gebundene Zahlen (inkl. nicht wortgetreuer Zitate),
#   (b) Negativ-Claims ohne Such-Anker ("kein Beleg fuer X" ohne X-Suche
#       in der Evidenz),
#   (c) die explizite Forbidden-Claims-Liste (DEFAULT_FORBIDDEN_CLAIMS),
#   (d) direkte Widersprueche zur Evidenz, wo die bestehende Regel den
#       Widerspruch EXAKT prueft (Richtung, Kardinalitaet, faelschlich
#       behauptete Absenz sichtbarer Evidenz).
#
# Der Default ist advisory: die Severity wird AUSSCHLIESSLICH aus der
# Mitgliedschaft in HARD_RULE_NAMES abgeleitet. Eine neu registrierte
# Regel kann daher nie versehentlich hart sein; hart wird sie nur durch
# eine bewusste Erweiterung der gepinnten Liste (plus Anpassung von
# tests/ai/test_severity_policy.py).
# --------------------------------------------------------------------------- #
RULE_SEVERITY_HARD = "hard"
RULE_SEVERITY_ADVISORY = "advisory"
DEFAULT_RULE_SEVERITY = RULE_SEVERITY_ADVISORY

HARD_RULE_NAMES: frozenset[str] = frozenset({
    # (a) ungebundene/falsch gebundene Zahlen + erfundene Zitate
    "numeric_tokens",
    "unsupported_count_bindings",
    "unsupported_ratio_bindings",
    "unsupported_rate_bindings",
    "unsupported_percent_bindings",
    "unsupported_elliptical_counts",
    "unsupported_postposed_counts",
    "unsupported_unit_free_counts",
    "unsupported_word_percent_bindings",
    "unsupported_natural_metrics",
    "unsupported_metric_maxima",
    "unsupported_metric_ranges",
    "unsupported_rate_denominators",
    "unsupported_assignments",
    "row_field_assignments_are_atomic",
    "unsupported_quoted_segments",
    # (b) Negativ-/Praesenz-Claims ohne Such-Anker in der Evidenz
    "unsupported_presence",
    # (c) Forbidden-Claims-Liste (DEFAULT_FORBIDDEN_CLAIMS)
    "item",
    # (d) direkte, exakt gepruefte Widersprueche zur Evidenz
    "unsupported_directional_presence",
    "unsupported_frequency_directions",
    # H9/V3: f/pmw-Paar widerspricht dem eindeutigen Tokennenner arithmetisch.
    "pmw_inconsistent_with_count",
    "normalised_time_trend_status",
    "declared_sample_cardinality_is_wrong",
    "word_sketch_evidence_is_falsely_absent",
    "metadata_values_are_falsely_absent",
    # H10/G2: gepaarte Term<->Ergebnis-Bindung; ein Claim, der Term T ein
    # Ergebnis N zuschreibt, waehrend die Evidenz FUER T ein anderes
    # Ergebnis traegt, ist ein exakt geprüfter Evidenz-Widerspruch.
    "term_result_mismatch",
    "claim_corpus_token_basis_is_visible",
    "claim_total_hits_basis_is_visible",
})


def rule_severity(rule_name: str) -> str:
    """Severity einer Regel: hart nur bei gepinnter Fabrikationsklasse."""

    if rule_name in HARD_RULE_NAMES:
        return RULE_SEVERITY_HARD
    return DEFAULT_RULE_SEVERITY


# Ordered rule table for the per-claim cascade of
# ``analysis_grounding.validate_answer_envelope``. The order is the
# exact original statement order and MUST NOT be changed: later rules
# read names earlier rules bind. ``families`` is descriptive metadata
# (explicit ``analysis_family`` gates found inside the block; an empty
# tuple means the rule guards itself and applies to every family).
# The dispatch loop in the facade applies every rule unconditionally,
# so the block-internal gating stays the single source of truth.
_CLAIM_RULE_ORDER = (
    ("claim_restates_user_task", _vae_rule_claim_restates_user_task, ()),
    ("response_requirement_id", _vae_rule_response_requirement_id, ()),
    ("claim_bundles_analytical_units", _vae_rule_claim_bundles_analytical_units, ()),
    ("lexical_absence_overreads_contextual_retrieval", _vae_rule_lexical_absence_overreads_contextual_retrieval, ()),
    ("expanded_kwic_fact_ids", _vae_rule_expanded_kwic_fact_ids, ("kwic_context",)),
    ("has_cross_source_literal_separation", _vae_rule_has_cross_source_literal_separation, ()),
    ("normalised_time_trend_status", _vae_rule_normalised_time_trend_status, ()),
    ("generic_time_trend_status", _vae_rule_generic_time_trend_status, ()),
    ("nonpositive_only_claim_has_positive_assertion", _vae_rule_nonpositive_only_claim_has_positive_assertion, ()),
    ("negative_or_unknown_limitation", _vae_rule_negative_or_unknown_limitation, ()),
    ("flattened_cqlf_query", _vae_rule_flattened_cqlf_query, ()),
    ("negative_or_unknown_limitation_2", _vae_rule_negative_or_unknown_limitation_2, ()),
    ("unsupported_raw_pos_inference", _vae_rule_unsupported_raw_pos_inference, ()),
    ("unsupported_pos_inventory_provenance", _vae_rule_unsupported_pos_inventory_provenance, ()),
    ("unsupported_natural_pos_label", _vae_rule_unsupported_natural_pos_label, ()),
    ("unsupported_absolute_frequency_magnitude", _vae_rule_unsupported_absolute_frequency_magnitude, ()),
    ("unsupported_absolute_association_magnitude", _vae_rule_unsupported_absolute_association_magnitude, ()),
    ("empty_collocation_profile_is_overread", _vae_rule_empty_collocation_profile_is_overread, ()),
    ("unsupported_collocation_pos_composition", _vae_rule_unsupported_collocation_pos_composition, ()),
    ("is_explicitly_bounded_claim", _vae_rule_is_explicitly_bounded_claim, ()),
    ("word_sketch_violations", _vae_rule_word_sketch_violations, ()),
    ("word_sketch_evidence_is_falsely_absent", _vae_rule_word_sketch_evidence_is_falsely_absent, ()),
    ("negative_or_unknown_limitation_3", _vae_rule_negative_or_unknown_limitation_3, ()),
    ("unsupported_frequency_theme_inference", _vae_rule_unsupported_frequency_theme_inference, ()),
    ("unsupported_frequency_copresence_inference", _vae_rule_unsupported_frequency_copresence_inference, ()),
    ("unsupported_platform_handle_label", _vae_rule_unsupported_platform_handle_label, ()),
    ("unsupported_document_class_label", _vae_rule_unsupported_document_class_label, ()),
    ("unsupported_user_handle_identity", _vae_rule_unsupported_user_handle_identity, ()),
    ("followup_infers_morphology_from_surface_frequency", _vae_rule_followup_infers_morphology_from_surface_frequency, ()),
    ("absolute_counts_called_relative", _vae_rule_absolute_counts_called_relative, ()),
    ("unsupported_register_theme_inference", _vae_rule_unsupported_register_theme_inference, ()),
    ("unsupported_grammatical_profile_inference", _vae_rule_unsupported_grammatical_profile_inference, ()),
    ("result_is_mislabeled_as_sample", _vae_rule_result_is_mislabeled_as_sample, ()),
    ("declared_sample_cardinality_is_wrong", _vae_rule_declared_sample_cardinality_is_wrong, ()),
    ("unsupported_keyness_label", _vae_rule_unsupported_keyness_label, ()),
    ("negative_or_unknown_limitation_4", _vae_rule_negative_or_unknown_limitation_4, ()),
    ("is_explicitly_bounded_claim_2", _vae_rule_is_explicitly_bounded_claim_2, ()),
    ("is_explicitly_bounded_claim_3", _vae_rule_is_explicitly_bounded_claim_3, ()),
    ("unsupported_syntactic_roles", _vae_rule_unsupported_syntactic_roles, ()),
    ("unsupported_presence", _vae_rule_unsupported_presence, ()),
    ("unsupported_directional_presence", _vae_rule_unsupported_directional_presence, ()),
    ("unsupported_keyness_same_items_claim", _vae_rule_unsupported_keyness_same_items_claim, ()),
    ("unsupported_balanced_keyness_global_rank_claim", _vae_rule_unsupported_balanced_keyness_global_rank_claim, ()),
    ("unsupported_keyness_lexical_core_claim", _vae_rule_unsupported_keyness_lexical_core_claim, ()),
    ("unsupported_absolute_keyness_magnitude", _vae_rule_unsupported_absolute_keyness_magnitude, ()),
    ("unsupported_keyness_causes", _vae_rule_unsupported_keyness_causes, ()),
    ("unsupported_hashtag_label", _vae_rule_unsupported_hashtag_label, ()),
    ("unsupported_partial_exhaustivity", _vae_rule_unsupported_partial_exhaustivity, ()),
    ("unsupported_artifacts", _vae_rule_unsupported_artifacts, ()),
    ("unsupported_ngram_units", _vae_rule_unsupported_ngram_units, ()),
    ("unsupported_ngram_contexts", _vae_rule_unsupported_ngram_contexts, ()),
    ("unsupported_multi_ngram_candidate_claim", _vae_rule_unsupported_multi_ngram_candidate_claim, ("ngram_profile",)),
    ("unsupported_ngram_function_frequency", _vae_rule_unsupported_ngram_function_frequency, ()),
    ("unsupported_ngram_semantic_validation", _vae_rule_unsupported_ngram_semantic_validation, ()),
    ("unsupported_text_origin", _vae_rule_unsupported_text_origin, ()),
    ("unsupported_pos", _vae_rule_unsupported_pos, ()),
    ("unsupported_provenance", _vae_rule_unsupported_provenance, ()),
    ("unsupported_distribution", _vae_rule_unsupported_distribution, ()),
    ("unsupported_dispersion_interpretations", _vae_rule_unsupported_dispersion_interpretations, ()),
    ("unsupported_scope_design", _vae_rule_unsupported_scope_design, ()),
    ("unsupported_diversity", _vae_rule_unsupported_diversity, ()),
    ("unsupported_kwic_source_role_attribution", _vae_rule_unsupported_kwic_source_role_attribution, ()),
    ("source_attributed_cross_sentence_inference", _vae_rule_source_attributed_cross_sentence_inference, ()),
    ("source_attributed_unmarked_causal_link", _vae_rule_source_attributed_unmarked_causal_link, ()),
    ("source_attributed_cross_sentence_predicate_transfer", _vae_rule_source_attributed_cross_sentence_predicate_transfer, ()),
    ("unsupported_context_interpretations", _vae_rule_unsupported_context_interpretations, ()),
    ("unsupported_open_window_interpretations", _vae_rule_unsupported_open_window_interpretations, ()),
    ("unsupported_kwic_diversity", _vae_rule_unsupported_kwic_diversity, ()),
    ("unsupported_kwic_prevalence", _vae_rule_unsupported_kwic_prevalence, ()),
    ("unsupported_kwic_subset_counts", _vae_rule_unsupported_kwic_subset_counts, ()),
    ("unsupported_exact_kwic_category_claim", _vae_rule_unsupported_exact_kwic_category_claim, ()),
    ("unsupported_frequency_directions", _vae_rule_unsupported_frequency_directions, ()),
    ("pmw_inconsistent_with_count", _vae_rule_pmw_inconsistent_with_count, ("frequency_analysis",)),
    ("unsupported_correlations", _vae_rule_unsupported_correlations, ()),
    ("merges_cross_result_rankings", _vae_rule_merges_cross_result_rankings, ()),
    ("analytical_prose", _vae_rule_analytical_prose, ()),
    ("has_positive_semantic_cooccurrence_claim", _vae_rule_has_positive_semantic_cooccurrence_claim, ()),
    ("semantic_retrieval_is_mislabeled_as_frequency", _vae_rule_semantic_retrieval_is_mislabeled_as_frequency, ()),
    ("semantic_retrieval_is_mislabeled_as_centrality", _vae_rule_semantic_retrieval_is_mislabeled_as_centrality, ()),
    ("claim", _vae_rule_claim, ()),
    ("negative_or_unknown_limitation_5", _vae_rule_negative_or_unknown_limitation_5, ()),
    ("negative_or_unknown_limitation_6", _vae_rule_negative_or_unknown_limitation_6, ()),
    ("metadata_values_are_falsely_absent", _vae_rule_metadata_values_are_falsely_absent, ()),
    ("term_result_mismatch", _vae_rule_term_result_mismatch, ()),
    ("uses_technical_partition_as_content_axis", _vae_rule_uses_technical_partition_as_content_axis, ()),
    ("uses_single_collocation_as_semantic_similarity", _vae_rule_uses_single_collocation_as_semantic_similarity, ()),
    ("claim_2", _vae_rule_claim_2, ()),
    ("deliverable_kind", _vae_rule_deliverable_kind, ()),
    ("near_duplicate_research_question", _vae_rule_near_duplicate_research_question, ()),
    ("followup_correlation_is_operationalised", _vae_rule_followup_correlation_is_operationalised, ()),
    ("followup_mixes_aggregate_and_token_validation", _vae_rule_followup_mixes_aggregate_and_token_validation, ()),
    ("followup_uses_sentence_length_as_complexity", _vae_rule_followup_uses_sentence_length_as_complexity, ()),
    ("followup_confounds_raw_frequency_with_length", _vae_rule_followup_confounds_raw_frequency_with_length, ()),
    ("distribution_substitutes_for_thematic_analysis", _vae_rule_distribution_substitutes_for_thematic_analysis, ()),
    ("distribution_substitutes_for_function_analysis", _vae_rule_distribution_substitutes_for_function_analysis, ()),
    ("pos_inventory_substitutes_for_morphosyntax", _vae_rule_pos_inventory_substitutes_for_morphosyntax, ()),
    ("collocation_substitutes_for_discourse_function", _vae_rule_collocation_substitutes_for_discourse_function, ()),
    ("local_association_lacks_collocation_design", _vae_rule_local_association_lacks_collocation_design, ()),
    ("accounting_gap_lacks_token_reconciliation", _vae_rule_accounting_gap_lacks_token_reconciliation, ()),
    ("claim_mentions_specific_fact_anchor", _vae_rule_claim_mentions_specific_fact_anchor, ()),
    ("overview_observation_is_provenance_only", _vae_rule_overview_observation_is_provenance_only, ()),
    ("analytical_prose_2", _vae_rule_analytical_prose_2, ()),
    ("is_rank_range_claim", _vae_rule_is_rank_range_claim, ()),
    ("numeric_tokens", _vae_rule_numeric_tokens, ()),
    ("unsupported_count_bindings", _vae_rule_unsupported_count_bindings, ()),
    ("unsupported_ratio_bindings", _vae_rule_unsupported_ratio_bindings, ()),
    ("unsupported_rate_bindings", _vae_rule_unsupported_rate_bindings, ()),
    ("unsupported_percent_bindings", _vae_rule_unsupported_percent_bindings, ()),
    ("unsupported_elliptical_counts", _vae_rule_unsupported_elliptical_counts, ()),
    ("unsupported_postposed_counts", _vae_rule_unsupported_postposed_counts, ()),
    ("unsupported_unit_free_counts", _vae_rule_unsupported_unit_free_counts, ()),
    ("unsupported_word_percent_bindings", _vae_rule_unsupported_word_percent_bindings, ()),
    ("unsupported_natural_metrics", _vae_rule_unsupported_natural_metrics, ()),
    ("unsupported_metric_maxima", _vae_rule_unsupported_metric_maxima, ()),
    ("unsupported_metric_ranges", _vae_rule_unsupported_metric_ranges, ()),
    ("unsupported_rate_denominators", _vae_rule_unsupported_rate_denominators, ()),
    ("unsupported_assignments", _vae_rule_unsupported_assignments, ()),
    ("row_field_assignments_are_atomic", _vae_rule_row_field_assignments_are_atomic, ()),
    ("RAW_TRUNCATION_MARKER_PATTERN", _vae_rule_RAW_TRUNCATION_MARKER_PATTERN, ()),
    ("INTERNAL_GROUNDING_MARKER_PATTERN", _vae_rule_INTERNAL_GROUNDING_MARKER_PATTERN, ()),
    ("unsupported_quoted_segments", _vae_rule_unsupported_quoted_segments, ()),
    ("claim_3", _vae_rule_claim_3, ()),
    ("claim_corpus_token_basis_is_visible", _vae_rule_claim_corpus_token_basis_is_visible, ()),
    ("claim_total_hits_basis_is_visible", _vae_rule_claim_total_hits_basis_is_visible, ()),
    ("has_positive_partition_purpose_claim", _vae_rule_has_positive_partition_purpose_claim, ()),
    ("fact", _vae_rule_fact, ()),
    ("has_definitive_global_scope_claim", _vae_rule_has_definitive_global_scope_claim, ()),
    ("unmeasured_magnitude", _vae_rule_unmeasured_magnitude, ()),
    ("item", _vae_rule_item, ()),
    ("stronger_than_exactness", _vae_rule_stronger_than_exactness, ()),
)

# Public registry rows: ``(name, rule, families, severity)``. The severity is
# DERIVED from ``HARD_RULE_NAMES`` (default advisory), never stated inline, so
# adding a row above cannot introduce a hard rule by accident.
CLAIM_RULE_REGISTRY = tuple(
    (name, rule, families, rule_severity(name))
    for name, rule, families in _CLAIM_RULE_ORDER
)

# Guard: every pinned hard name must exist in the registry (a typo in the
# pinned list would otherwise silently demote the rule to advisory).
_REGISTRY_RULE_NAMES = frozenset(entry[0] for entry in CLAIM_RULE_REGISTRY)
_UNKNOWN_HARD_NAMES = HARD_RULE_NAMES - _REGISTRY_RULE_NAMES
if _UNKNOWN_HARD_NAMES:  # pragma: no cover - import-time integrity guard
    raise RuntimeError(
        "HARD_RULE_NAMES enthaelt unbekannte Regelnamen: "
        + ", ".join(sorted(_UNKNOWN_HARD_NAMES))
    )


# --------------------------------------------------------------------------- #
# K3 Slice 3: aggregated declarative rule table. The mechanical
# ``_unsupported_*`` predicates are PatternRule rows executed by the ONE
# generic executor ``claim_rules._table.run_pattern_rule``. The thin
# functions above them keep the historical names/signatures. Bespoke rules
# stay ordinary functions. New mechanical rules should be added as rows.
# --------------------------------------------------------------------------- #
from ._table import (  # noqa: E402,F401
    EVIDENCE_CHECKS,
    EXCEPTION_CHECKS,
    PER_MATCH_EXCEPTIONS,
    SENTENCE_EXCEPTION_CHECKS,
    PatternRule,
    RuleInputs,
    run_pattern_rule,
)
from . import _shared as _shared_rules_module  # noqa: E402
from . import frequency as _frequency_rules_module  # noqa: E402
from . import keyness as _keyness_rules_module  # noqa: E402
from . import ngram as _ngram_rules_module  # noqa: E402

PATTERN_RULE_TABLE: tuple[PatternRule, ...] = (
    *_shared_rules_module.PATTERN_RULES,
    *_keyness_rules_module.PATTERN_RULES,
    *_frequency_rules_module.PATTERN_RULES,
    *_ngram_rules_module.PATTERN_RULES,
)
