from __future__ import annotations

from typing import Any



# --------------------------------------------------------------------------- #
# K3 Slice 1 decomposition facade (verbatim moves, behaviour-preserving).
#
# The symbols below moved to grounding_schemas.py, grounding_evidence.py and
# grounding_contracts.py. Every previously importable name (public AND private)
# is re-imported here explicitly, one per line, so that
#   * every existing `from .analysis_grounding import X` keeps working,
#   * `analysis_grounding.<name>` attribute access keeps working, and
#   * tests may keep monkeypatching `analysis_grounding.<name>`: all code
#     REMAINING in this module resolves the moved helpers through THIS
#     module's globals (facade-patchable). Code INSIDE a grounding submodule
#     binds submodule-locally, and no current test patches across that seam.
# --------------------------------------------------------------------------- #
from .grounding_schemas import MODE_VALUES  # noqa: F401
from .grounding_schemas import TRACK_VALUES  # noqa: F401
from .grounding_schemas import DELIVERABLE_KINDS  # noqa: F401
from .grounding_schemas import ANALYSIS_FAMILIES  # noqa: F401
from .grounding_schemas import EVIDENCE_KINDS  # noqa: F401
from .grounding_schemas import FACT_KINDS  # noqa: F401
from .grounding_schemas import EXACTNESS_VALUES  # noqa: F401
from .grounding_schemas import CLAIM_SUPPORT_VALUES  # noqa: F401
from .grounding_schemas import CLAIM_KINDS  # noqa: F401
from .grounding_schemas import _CLAIM_KIND_ALIASES  # noqa: F401
from .grounding_schemas import ASSERTION_LEVELS  # noqa: F401
from .grounding_schemas import GROUNDING_VERDICTS  # noqa: F401
from .grounding_schemas import CLAIM_ID_LIMIT  # noqa: F401
from .grounding_schemas import MAX_ANSWER_CLAIMS  # noqa: F401
from .grounding_schemas import MAX_VERDICT_CLAIM_IDS  # noqa: F401
from .grounding_schemas import MAX_VERDICT_REASON_CHARS  # noqa: F401
from .grounding_schemas import MAX_FACT_IDS_PER_CLAIM  # noqa: F401
from .grounding_schemas import MAX_CLAIM_TEXT_CHARS  # noqa: F401
from .grounding_schemas import MAX_RESPONSE_REQUIREMENTS  # noqa: F401
from .grounding_schemas import MAX_RESPONSE_REQUIREMENT_CHARS  # noqa: F401
from .grounding_schemas import DEFAULT_GROUNDING_ROW_LIMIT  # noqa: F401
from .grounding_schemas import DEFAULT_SYNTHESIS_FACT_LIMIT  # noqa: F401
from .grounding_schemas import CONTRACT_REVIEW_VERDICTS  # noqa: F401
from .grounding_schemas import CLARIFICATION_QUESTION_LIMIT  # noqa: F401
from .grounding_schemas import DEFAULT_FORBIDDEN_CLAIMS  # noqa: F401
from .grounding_schemas import KWIC_GROUNDING_QUOTE_LIMIT  # noqa: F401
from .grounding_schemas import TOOL_BUNDLES  # noqa: F401
from .grounding_schemas import OPEN_RESEARCH_CANDIDATES  # noqa: F401
from .grounding_schemas import TRACK_TOOL_CANDIDATES  # noqa: F401
from .grounding_schemas import TRACK_TOOL_LIMITS  # noqa: F401
from .grounding_schemas import GROUNDING_TRIGGER_TOOLS  # noqa: F401
from .grounding_schemas import BOUNDED_CORPUS_EVIDENCE_KINDS  # noqa: F401
from .grounding_schemas import OPEN_RESEARCH_INCOMPATIBLE_EVIDENCE_KINDS  # noqa: F401
from .grounding_schemas import ANALYSIS_CONTRACT_DOC  # noqa: F401
from .grounding_schemas import RESPONSE_REQUIREMENTS_DOC  # noqa: F401
from .grounding_schemas import NON_AUTHORITATIVE_GROUNDING_TOOLS  # noqa: F401
from .grounding_schemas import CONTRACT_VERIFIER_DOC  # noqa: F401
from .grounding_schemas import OBSERVED_FACTS_DOC  # noqa: F401
from .grounding_schemas import ANSWER_ENVELOPE_DOC  # noqa: F401
from .grounding_schemas import GROUNDING_VERIFIER_DOC  # noqa: F401
from .grounding_schemas import KWIC_RELATION_ADJUDICATOR_DOC  # noqa: F401
from .grounding_schemas import _compact_text  # noqa: F401
from .grounding_schemas import _normalise_claim_text  # noqa: F401
from .grounding_schemas import _user_facing_evidence_gap  # noqa: F401
from .grounding_schemas import _format_log_ratio_metric  # noqa: F401
from .grounding_schemas import _compact_id  # noqa: F401
from .grounding_schemas import _normalise_text_list  # noqa: F401
from .grounding_schemas import _normalise_claim_id_list  # noqa: F401
from .grounding_schemas import _normalise_enum  # noqa: F401
from .grounding_schemas import _coerce_bool  # noqa: F401
from .grounding_schemas import _extract_json  # noqa: F401
from .grounding_schemas import ResponseRequirement  # noqa: F401
from .grounding_schemas import _RESPONSE_REQUEST_VERB_PATTERN  # noqa: F401
from .grounding_schemas import _source_quote_is_bounded_question_span  # noqa: F401
from .grounding_schemas import _response_text_tokens  # noqa: F401
from .grounding_schemas import _tokens_are_contiguous_span  # noqa: F401
from .grounding_schemas import EvidenceItem  # noqa: F401
from .grounding_schemas import EvidenceBundle  # noqa: F401
from .grounding_schemas import ObservedFact  # noqa: F401
from .grounding_schemas import _INTERNAL_FACT_REFERENCE_PATTERN  # noqa: F401
from .grounding_schemas import _RESPONSE_REQUIREMENT_ANNOUNCEMENT_PATTERN  # noqa: F401
from .grounding_schemas import _RESPONSE_REQUIREMENT_HEADING_PATTERN  # noqa: F401
from .grounding_schemas import _RESPONSE_REQUIREMENT_FALSIFIER_PATTERN  # noqa: F401
from .grounding_schemas import _RESPONSE_CLAIM_FALSIFIER_PATTERN  # noqa: F401
from .grounding_schemas import _RESPONSE_CLAIM_EXTERNAL_CORPUS_FALSIFIER_PATTERN  # noqa: F401
from .grounding_schemas import _RESPONSE_CLAIM_FALSIFIER_MODALITY_PATTERN  # noqa: F401
from .grounding_schemas import _RESPONSE_CLAIM_INVALID_FALSIFIER_PATTERN  # noqa: F401
from .grounding_schemas import _RESPONSE_CLAIM_EMPIRICAL_COUNTER_RESULT_PATTERN  # noqa: F401
from .grounding_schemas import _RESPONSE_REQUIREMENT_LIMITATION_PATTERN  # noqa: F401
from .grounding_schemas import _RESPONSE_CLAIM_LIMITATION_PATTERN  # noqa: F401
from .grounding_schemas import _RESPONSE_REQUIREMENT_HYPOTHESIS_PATTERN  # noqa: F401
from .grounding_schemas import _RESPONSE_CLAIM_HYPOTHESIS_PATTERN  # noqa: F401
from .grounding_schemas import _HYPOTHESIS_PROPOSAL_PATTERN  # noqa: F401
from .grounding_schemas import _ANALYTICAL_CLAIM_LABEL_PATTERN  # noqa: F401
from .grounding_schemas import _ALTERNATIVE_HYPOTHESIS_PATTERN  # noqa: F401
from .grounding_schemas import _claim_contains_possible_falsifier  # noqa: F401
from .grounding_schemas import _claim_uses_external_corpus_as_falsifier  # noqa: F401
from .grounding_schemas import _is_testable_hypothesis_claim  # noqa: F401
from .grounding_schemas import _claim_bundles_analytical_units  # noqa: F401
from .grounding_schemas import _claim_restates_user_task  # noqa: F401
from .grounding_schemas import _strip_internal_fact_references  # noqa: F401
from .grounding_schemas import ClaimDraft  # noqa: F401
from .grounding_schemas import AnswerEnvelope  # noqa: F401
from .grounding_schemas import GroundingVerdict  # noqa: F401
from .grounding_schemas import ContractReview  # noqa: F401
from .grounding_schemas import analysis_contract_schema  # noqa: F401
from .grounding_schemas import response_requirements_schema  # noqa: F401
from .grounding_schemas import contract_review_schema  # noqa: F401
from .grounding_schemas import observed_facts_schema  # noqa: F401
from .grounding_schemas import grounding_verdict_schema  # noqa: F401
from .grounding_schemas import default_track_for_family  # noqa: F401
from .grounding_schemas import default_deliverable_kind_for_family  # noqa: F401
from .grounding_schemas import _COMPATIBLE_DELIVERABLES_BY_FAMILY  # noqa: F401
from .grounding_schemas import compatible_deliverable_kind  # noqa: F401
from .grounding_schemas import _ordered_allowed_tools  # noqa: F401
from .grounding_schemas import resolve_allowed_tools  # noqa: F401
from .grounding_schemas import _normalised_question_text  # noqa: F401
from .grounding_schemas import _has_any_phrase  # noqa: F401
from .grounding_schemas import _metadata_request_needs_interpretation  # noqa: F401
from .grounding_schemas import _explicit_interpretation_request  # noqa: F401
from .grounding_schemas import frage_ist_blosses_nachschlagen  # noqa: F401
from .grounding_schemas import _dedupe_ordered_strs  # noqa: F401
from .grounding_schemas import _is_followup_prompt  # noqa: F401
from .grounding_evidence import _semantic_row_score_kinds  # noqa: F401
from .grounding_evidence import _semantic_rows_include_embedding_scores  # noqa: F401
from .grounding_evidence import _semantic_candidate_generation_uses_vectors  # noqa: F401
from .grounding_evidence import result_scope_from_output  # noqa: F401
from .grounding_evidence import output_is_truncated  # noqa: F401
from .grounding_evidence import output_is_partial  # noqa: F401
from .grounding_evidence import output_is_sampled  # noqa: F401
from .grounding_evidence import _count_or_sample_len  # noqa: F401
from .grounding_evidence import _sample_items  # noqa: F401
from .grounding_evidence import _grounding_row_sample  # noqa: F401
from .grounding_evidence import _surface_row_dict  # noqa: F401
from .grounding_evidence import _surface_semantic_meta  # noqa: F401
from .grounding_evidence import _surface_cluster_dict  # noqa: F401
from .grounding_evidence import _normalise_example_text  # noqa: F401
from .grounding_evidence import _simple_analysis_input_quote  # noqa: F401
from .grounding_evidence import _row_quote  # noqa: F401
from .grounding_evidence import _kwic_quote  # noqa: F401
from .grounding_evidence import _metric_quote  # noqa: F401
from .grounding_evidence import _cluster_sample_values  # noqa: F401
from .grounding_evidence import _cluster_is_informative  # noqa: F401
from .grounding_evidence import _informative_clusters  # noqa: F401
from .grounding_evidence import _IDENTIFIER_METADATA_FIELD_RE  # noqa: F401
from .grounding_evidence import _PARTITION_METADATA_FIELDS  # noqa: F401
from .grounding_evidence import _metadata_value_priority  # noqa: F401
from .grounding_evidence import _metadata_field_has_analytical_entries  # noqa: F401
from .grounding_evidence import extract_raw_surface  # noqa: F401
from .grounding_evidence import (  # noqa: F401
    werkzeugausgabe_ohne_betreiberpfad,
)
from .grounding_evidence import build_grounding_surface  # noqa: F401
from .grounding_contracts import _RESPONSE_COUNT_WORDS  # noqa: F401
from .grounding_contracts import _COUNTED_RESPONSE_UNIT_PATTERN  # noqa: F401
from .grounding_contracts import _UNCOUNTED_RESPONSE_UNIT_PATTERN  # noqa: F401
from .grounding_contracts import _NEGATED_RESPONSE_REQUEST_PATTERN  # noqa: F401
from .grounding_contracts import _DISTRIBUTIVE_RESPONSE_CONDITION_PATTERN  # noqa: F401
from .grounding_contracts import _HYPOTHESIS_STRUCTURE_CONDITION_PATTERN  # noqa: F401
from .grounding_contracts import _RESPONSE_STRUCTURE_CONDITION_PATTERN  # noqa: F401
from .grounding_contracts import _is_presentation_only_structure_instruction  # noqa: F401
from .grounding_contracts import _explicit_response_request_clauses  # noqa: F401
from .grounding_contracts import _response_unit_is_negated  # noqa: F401
from .grounding_contracts import _explicit_counted_response_groups  # noqa: F401
from .grounding_contracts import _response_unit_family  # noqa: F401
from .grounding_contracts import _response_count_value  # noqa: F401
from .grounding_contracts import _counted_response_cardinality  # noqa: F401
from .grounding_contracts import _counted_response_requirement  # noqa: F401
from .grounding_contracts import _hypothesis_response_cardinality  # noqa: F401
from .grounding_contracts import _counted_requirement_claim_kind  # noqa: F401
from .grounding_contracts import _response_requirement_unit  # noqa: F401
from .grounding_contracts import _explicit_uncounted_response_requirements  # noqa: F401
from .grounding_contracts import normalise_response_requirements  # noqa: F401
from .grounding_contracts import AnalysisContract  # noqa: F401
from .grounding_contracts import _response_requirement_condition_reasons  # noqa: F401
from .grounding_contracts import answer_envelope_schema  # noqa: F401
from .grounding_contracts import _metadata_request_is_focused  # noqa: F401
from .grounding_contracts import _HYPOTHESIS_GENERATION_ACTION_PATTERN  # noqa: F401
from .grounding_contracts import _HYPOTHESIS_EVIDENCE_CUE_PATTERN  # noqa: F401
from .grounding_contracts import _requires_contextual_hypothesis_evidence  # noqa: F401
from .grounding_contracts import _is_exploratory_prompt  # noqa: F401
from .grounding_contracts import _is_theme_overview_prompt  # noqa: F401
from .grounding_contracts import _is_method_help_prompt  # noqa: F401
from .grounding_contracts import _is_confirmation_pressure_prompt  # noqa: F401
from .grounding_contracts import _CONFIRMATION_BOUNDARY_SCOPE_PATTERN  # noqa: F401
from .grounding_contracts import _CONFIRMATION_BOUNDARY_NEGATION_PATTERN  # noqa: F401
from .grounding_contracts import _CONFIRMATION_BOUNDARY_INFERENCE_PATTERN  # noqa: F401
from .grounding_contracts import _CONFIRMATION_BOUNDARY_UNSUPPORTED_PATTERN  # noqa: F401
from .grounding_contracts import _accepted_claims_reject_confirmation_pressure  # noqa: F401
from .grounding_contracts import _is_comparative_prompt  # noqa: F401
from .grounding_contracts import _DOCSET_COMPARATIVE_PHRASES  # noqa: F401
from .grounding_contracts import _has_explicit_comparison_pair  # noqa: F401
from .grounding_contracts import _is_docset_comparative_prompt  # noqa: F401
from .grounding_contracts import _is_broad_comparative_profile_prompt  # noqa: F401
from .grounding_contracts import _is_human_ai_contrast_prompt  # noqa: F401
from .grounding_contracts import same_corpus_collocation_terms  # noqa: F401
from .grounding_contracts import same_corpus_collocation_method_requirements  # noqa: F401
from .grounding_contracts import _requests_complementary_evidence  # noqa: F401
from .grounding_contracts import _heuristic_tool_bundle  # noqa: F401
from .grounding_contracts import _method_help_required_evidence  # noqa: F401
from .grounding_contracts import _contrast_required_evidence  # noqa: F401
from .grounding_contracts import heuristic_analysis_contract  # noqa: F401
from .grounding_contracts import fallback_analysis_contract  # noqa: F401
from .grounding_contracts import _requested_register_value  # noqa: F401
from .grounding_contracts import _METHOD_STEP_COUNTS  # noqa: F401
from .grounding_contracts import _requested_method_step_count  # noqa: F401
from .grounding_contracts import _requested_followup_question_count  # noqa: F401
from .grounding_contracts import Recipe  # noqa: F401
from .grounding_contracts import RECIPES  # noqa: F401
from .grounding_contracts import RECIPES_BY_ID  # noqa: F401
from .grounding_contracts import get_recipe  # noqa: F401
from .grounding_contracts import recipe_index  # noqa: F401
from .grounding_contracts import render_briefing  # noqa: F401
from .grounding_contracts import select_recipe  # noqa: F401

from .claim_rules import CLAIM_RULE_REGISTRY  # noqa: F401
from .claim_rules._shared import _GROUP_SEP  # noqa: F401
from .claim_rules._shared import _NUMBER_TOKEN_SOURCE  # noqa: F401
from .claim_rules._shared import _NUMBER_PATTERN  # noqa: F401
from .claim_rules._shared import _RANGE_PATTERN  # noqa: F401
from .claim_rules._shared import _WORD_RANGE_PATTERN  # noqa: F401
from .claim_rules._shared import _RANK_RANGE_CONTEXT_PATTERN  # noqa: F401
from .claim_rules._shared import _PERCENT_PATTERN  # noqa: F401
from .claim_rules._shared import _NUMERIC_PERCENT_PATTERN  # noqa: F401
from .claim_rules._shared import _COUNT_WORD_VALUES  # noqa: F401
from .claim_rules._shared import _GERMAN_COMPOUND_NUMBER_UNITS  # noqa: F401
from .claim_rules._shared import _GERMAN_TENS  # noqa: F401
from .claim_rules._shared import _GERMAN_LARGE_NUMBER_SCALES  # noqa: F401
from .claim_rules._shared import _number_word_value  # noqa: F401
from .claim_rules._shared import _NUMBER_WORD_TOKEN_SOURCE  # noqa: F401
from .claim_rules._shared import _COUNT_WORD_PATTERN_SOURCE  # noqa: F401
from .claim_rules._shared import _LARGE_COUNT_WORD_PATTERN_SOURCE  # noqa: F401
from .claim_rules._shared import _EMPIRICAL_COUNT_WORD_PATTERN_SOURCE  # noqa: F401
from .claim_rules._shared import _WORD_COUNT_PATTERN  # noqa: F401
from .claim_rules._shared import _EXPLICIT_SINGLE_COUNT_QUALIFIER_PATTERN  # noqa: F401
from .claim_rules._shared import _word_count_match_is_indefinite_article  # noqa: F401
from .claim_rules._shared import _DOZEN_COUNT_PATTERN  # noqa: F401
from .claim_rules._shared import _EXISTENTIAL_KWIC_EVIDENCE_PATTERN  # noqa: F401
from .claim_rules._shared import _DIGIT_COUNT_PATTERN  # noqa: F401
from .claim_rules._shared import _RESULT_CARDINALITY_NOUN_SOURCE  # noqa: F401
from .claim_rules._shared import _RESULT_CARDINALITY_DESCRIPTOR_SOURCE  # noqa: F401
from .claim_rules._shared import _WORD_RESULT_COUNT_PATTERN  # noqa: F401
from .claim_rules._shared import _DIGIT_RESULT_COUNT_PATTERN  # noqa: F401
from .claim_rules._shared import _COUNT_VALUE_PATTERN  # noqa: F401
from .claim_rules._shared import _MARKDOWN_LIST_ORDINAL_PATTERN  # noqa: F401
from .claim_rules._shared import _CLAIM_STEP_ORDINAL_PATTERN  # noqa: F401
from .claim_rules._shared import _INLINE_LIST_ORDINAL_PATTERN  # noqa: F401
from .claim_rules._shared import _QUOTED_SEGMENT_PATTERN  # noqa: F401
from .claim_rules._shared import _INLINE_CODE_SEGMENT_PATTERN  # noqa: F401
from .claim_rules._shared import _MARKDOWN_BLOCKQUOTE_PATTERN  # noqa: F401
from .claim_rules._shared import _COMPACT_BLOCKQUOTE_PATTERN  # noqa: F401
from .claim_rules._shared import _EMPIRICAL_EXAMPLE_CUE_SOURCE  # noqa: F401
from .claim_rules._shared import _UNQUOTED_EMPIRICAL_EXAMPLE_PATTERN  # noqa: F401
from .claim_rules._shared import _UNDELIMITED_WORDING_EXAMPLE_PATTERN  # noqa: F401
from .claim_rules._shared import _WORDING_FIRST_EXAMPLE_PATTERN  # noqa: F401
from .claim_rules._shared import _ORIGINAL_FORMULATION_EXAMPLE_PATTERN  # noqa: F401
from .claim_rules._shared import _TEXT_BOUNDARY_EXAMPLE_PATTERN  # noqa: F401
from .claim_rules._shared import _UNPAIRED_EMPIRICAL_QUOTE_PATTERN  # noqa: F401
from .claim_rules._shared import _EMPIRICAL_QUOTE_CLOSERS  # noqa: F401
from .claim_rules._shared import _CATEGORY_PATTERN  # noqa: F401
from .claim_rules._shared import _WEAK_CATEGORY_PATTERN  # noqa: F401
from .claim_rules._shared import _PARTIAL_MAGNITUDE_PATTERN  # noqa: F401
from .claim_rules._shared import _OPERATIONALISED_MAGNITUDE_PATTERN  # noqa: F401
from .claim_rules._shared import _BOUNDED_SCOPE_PATTERN  # noqa: F401
from .claim_rules._shared import _GLOBAL_SCOPE_PATTERN  # noqa: F401
from .claim_rules._shared import _PARTITION_PURPOSE_PATTERN  # noqa: F401
from .claim_rules._shared import _CROSS_RESULT_RANKING_PATTERN  # noqa: F401
from .claim_rules._shared import _SEPARATE_RESULT_SPACE_PATTERN  # noqa: F401
from .claim_rules._shared import _RESULT_SCOPE_MARKER_PATTERN  # noqa: F401
from .claim_rules._shared import _RESULT_SCOPE_CONTRAST_PATTERN  # noqa: F401
from .claim_rules._shared import _CROSS_SOURCE_LITERAL_SEPARATION_PATTERN  # noqa: F401
from .claim_rules._shared import _CROSS_SOURCE_ANAPHORIC_JOIN_PATTERN  # noqa: F401
from .claim_rules._shared import _CORPUS_PURPOSE_CLAIM_PATTERN  # noqa: F401
from .claim_rules._shared import _EXPLICIT_CORPUS_PURPOSE_EVIDENCE_PATTERN  # noqa: F401
from .claim_rules._shared import _TEXT_PRODUCTION_ORIGIN_PATTERN  # noqa: F401
from .claim_rules._shared import _TEXT_PRODUCTION_INFERENCE_PATTERN  # noqa: F401
from .claim_rules._shared import _TEXT_PRODUCTION_EVIDENCE_PATTERN  # noqa: F401
from .claim_rules._shared import _LEMMA_CLAIM_PATTERN  # noqa: F401
from .claim_rules._shared import _LEMMA_QUERY_CLAIM_PATTERN  # noqa: F401
from .claim_rules._shared import _PROPOSED_LEMMA_ANALYSIS_PATTERN  # noqa: F401
from .claim_rules._shared import _EXISTING_LEMMA_RESULT_PATTERN  # noqa: F401
from .claim_rules._shared import _DIVERSITY_NORMATIVE_PATTERN  # noqa: F401
from .claim_rules._shared import _DIVERSITY_METHOD_SUPERLATIVE_PATTERN  # noqa: F401
from .claim_rules._shared import _DIVERSITY_METHOD_RELATION_PATTERN  # noqa: F401
from .claim_rules._shared import _DIVERSITY_CROSS_METRIC_MAGNITUDE_PATTERN  # noqa: F401
from .claim_rules._shared import _DIVERSITY_CROSS_METRIC_INTERPRETATION_PATTERN  # noqa: F401
from .claim_rules._shared import _TTR_TOKEN_BASE_PATTERN  # noqa: F401
from .claim_rules._shared import _LEXICAL_ROBUSTNESS_REQUEST_PATTERN  # noqa: F401
from .claim_rules._shared import _LEXICAL_ROBUSTNESS_ANSWER_PATTERN  # noqa: F401
from .claim_rules._shared import _TTR_WINDOW_DEPENDENCE_PATTERN  # noqa: F401
from .claim_rules._shared import _ROBUSTNESS_REFERENCE_CONFUSION_PATTERN  # noqa: F401
from .claim_rules._shared import _LEXICAL_REFERENCE_INTERPRETABILITY_PATTERN  # noqa: F401
from .claim_rules._shared import _LEXICAL_RATING_INTERPRETATION_SCOPE_PATTERN  # noqa: F401
from .claim_rules._shared import _STTR_VARIANCE_SMOOTHING_PATTERN  # noqa: F401
from .claim_rules._shared import _STTR_UNSUPPORTED_VARIABILITY_PATTERN  # noqa: F401
from .claim_rules._shared import _LEXICAL_DENSITY_CONFUSION_PATTERN  # noqa: F401
from .claim_rules._shared import _EQUAL_WINDOW_ASSUMPTION_PATTERN  # noqa: F401
from .claim_rules._shared import _UNEQUAL_WINDOW_BOUNDARY_PATTERN  # noqa: F401
from .claim_rules._shared import _TTR_STTR_ROBUSTNESS_EQUIVOCATION_PATTERN  # noqa: F401
from .claim_rules._shared import _TTR_CATEGORICAL_SIZE_DECLINE_PATTERN  # noqa: F401
from .claim_rules._shared import _TTR_SIZE_TENDENCY_QUALIFIER_PATTERN  # noqa: F401
from .claim_rules._shared import _TTR_EXCLUSIVE_SMALL_SCOPE_PATTERN  # noqa: F401
from .claim_rules._shared import _N_TYPES_AS_TOKENS_PATTERN  # noqa: F401
from .claim_rules._shared import _MISSING_FILTER_POLICY_PATTERN  # noqa: F401
from .claim_rules._shared import _WHOLE_CORPUS_ANALYSIS_TOKEN_PATTERN  # noqa: F401
from .claim_rules._shared import _CONTEXT_CODING_EVIDENCE_PATTERN  # noqa: F401
from .claim_rules._shared import _RELATIVE_FREQUENCY_PATTERN  # noqa: F401
from .claim_rules._shared import _TIME_COMPARISON_PATTERN  # noqa: F401
from .claim_rules._shared import _TIME_CHANGE_PATTERN  # noqa: F401
from .claim_rules._shared import _GENERIC_TIME_TREND_PATTERN  # noqa: F401
from .claim_rules._shared import _EXPLICIT_CAUSAL_EVIDENCE_PATTERN  # noqa: F401
from .claim_rules._shared import _NEGATED_PURPOSE_PATTERN  # noqa: F401
from .claim_rules._shared import _NEGATIVE_OR_UNKNOWN_CLAIM_PATTERN  # noqa: F401
from .claim_rules._shared import _EPISTEMIC_SCOPE_LIMITATION_PATTERN  # noqa: F401
from .claim_rules._shared import _MISSING_CORPUS_TOKEN_PATTERN  # noqa: F401
from .claim_rules._shared import _MISSING_TOTAL_HITS_PATTERN  # noqa: F401
from .claim_rules._shared import _METADATA_VALUE_COUNT_QUOTE_PATTERN  # noqa: F401
from .claim_rules._shared import _FOLLOWUP_METADATA_AXIS_PATTERN  # noqa: F401
from .claim_rules._shared import _EXPLICIT_SINGLETON_SCOPE_CLOSURE_PATTERN  # noqa: F401
from .claim_rules._shared import _FOLLOWUP_RANKING_CONTEXT_PATTERN  # noqa: F401
from .claim_rules._shared import _FOLLOWUP_CONTROLLED_RERANK_PATTERN  # noqa: F401
from .claim_rules._shared import _FOLLOWUP_RERANK_INTENT_PATTERN  # noqa: F401
from .claim_rules._shared import _FOLLOWUP_CONTEXT_CHANGE_TARGET_PATTERN  # noqa: F401
from .claim_rules._shared import _FOLLOWUP_SCOPE_CHANGE_PATTERN  # noqa: F401
from .claim_rules._shared import _FOLLOWUP_SETTLED_DENOMINATOR_SCOPE_PATTERN  # noqa: F401
from .claim_rules._shared import _POS_INFERENCE_TARGET_PATTERN  # noqa: F401
from .claim_rules._shared import _POS_INFERENCE_BRIDGE_PATTERN  # noqa: F401
from .claim_rules._shared import _POS_INVENTORY_CLAIM_PATTERN  # noqa: F401
from .claim_rules._shared import _METHODOLOGICAL_TEST_INTENT_PATTERN  # noqa: F401
from .claim_rules._shared import _METHOD_PROPOSAL_MODALITY_PATTERN  # noqa: F401
from .claim_rules._shared import _ANALYSIS_OPERATION_PATTERN  # noqa: F401
from .claim_rules._shared import _THEME_INFERENCE_PATTERN  # noqa: F401
from .claim_rules._shared import _SEMANTIC_CLASS_ASSIGNMENT_PATTERN  # noqa: F401
from .claim_rules._shared import _TENTATIVE_THEME_PATTERN  # noqa: F401
from .claim_rules._shared import _THEME_VALIDATION_PATTERN  # noqa: F401
from .claim_rules._shared import _PLATFORM_SPECIFIC_HANDLE_PATTERN  # noqa: F401
from .claim_rules._shared import _DOCUMENT_CLASS_LABEL_PATTERN  # noqa: F401
from .claim_rules._shared import _ASSERTED_USER_HANDLE_PATTERN  # noqa: F401
from .claim_rules._shared import _OPEN_HANDLE_IDENTITY_TEST_PATTERN  # noqa: F401
from .claim_rules._shared import _DIRECT_HANDLE_QUALIFIER_PATTERN  # noqa: F401
from .claim_rules._shared import _FOLLOWUP_PRESUPPOSED_EFFECT_PATTERN  # noqa: F401
from .claim_rules._shared import _OPEN_EFFECT_QUESTION_PATTERN  # noqa: F401
from .claim_rules._shared import _UNOBSERVED_RELATION_PRESUPPOSITION_PATTERN  # noqa: F401
from .claim_rules._shared import _OPEN_RELATION_TEST_PATTERN  # noqa: F401
from .claim_rules._shared import _EXPLICIT_CAUSAL_DESIGN_PATTERN  # noqa: F401
from .claim_rules._shared import _RELATIVE_FREQUENCY_PHRASE_PATTERN  # noqa: F401
from .claim_rules._shared import _ABSOLUTE_F_VALUE_PATTERN  # noqa: F401
from .claim_rules._shared import _RELATIVE_FREQUENCY_VALUE_PATTERN  # noqa: F401
from .claim_rules._shared import _ABSOLUTE_ASSOCIATION_MAGNITUDE_PATTERN  # noqa: F401
from .claim_rules._shared import _EXPLICIT_ASSOCIATION_MAGNITUDE_REFERENCE_PATTERN  # noqa: F401
from .claim_rules._shared import _REGISTER_PATTERN  # noqa: F401
from .claim_rules._shared import _CORRELATION_QUESTION_PATTERN  # noqa: F401
from .claim_rules._shared import _OBSERVATION_UNIT_PATTERN  # noqa: F401
from .claim_rules._shared import _AGGREGATE_POS_MANUAL_AGREEMENT_PATTERN  # noqa: F401
from .claim_rules._shared import _PAIRED_TOKEN_LABEL_VALIDATION_PATTERN  # noqa: F401
from .claim_rules._shared import _SENTENCE_LENGTH_COMPLEXITY_PATTERN  # noqa: F401
from .claim_rules._shared import _EXPLICIT_COMPLEXITY_PROXY_TEST_PATTERN  # noqa: F401
from .claim_rules._shared import _LOCAL_ASSOCIATION_GOAL_PATTERN  # noqa: F401
from .claim_rules._shared import _COLLOCATION_CONTEXT_UNIT_PATTERN  # noqa: F401
from .claim_rules._shared import _ASSOCIATION_REFERENCE_PATTERN  # noqa: F401
from .claim_rules._shared import _CATEGORY_SUM_TOTAL_GAP_PATTERN  # noqa: F401
from .claim_rules._shared import _TOKEN_ACCOUNTING_METHOD_PATTERN  # noqa: F401
from .claim_rules._shared import _DISTRIBUTION_METHOD_PATTERN  # noqa: F401
from .claim_rules._shared import _POS_INVENTORY_METHOD_PATTERN  # noqa: F401
from .claim_rules._shared import _EXPLICIT_POS_DISTRIBUTION_CLAIM_PATTERN  # noqa: F401
from .claim_rules._shared import _MORPHOSYNTACTIC_ANALYSIS_TARGET_PATTERN  # noqa: F401
from .claim_rules._shared import _THEMATIC_OR_SEMANTIC_REACH_PATTERN  # noqa: F401
from .claim_rules._shared import _CONTEXTUAL_MEANING_PATTERN  # noqa: F401
from .claim_rules._shared import _EXPLICIT_CONTEXT_METHOD_PATTERN  # noqa: F401
from .claim_rules._shared import _FUNCTION_OR_ROLE_TARGET_PATTERN  # noqa: F401
from .claim_rules._shared import _GRAMMATICAL_PROFILE_PATTERN  # noqa: F401
from .claim_rules._shared import _STYLE_OR_TEXTTYPE_PATTERN  # noqa: F401
from .claim_rules._shared import _STYLE_INFERENCE_BRIDGE_PATTERN  # noqa: F401
from .claim_rules._shared import _CURRENT_RESULT_AS_SAMPLE_PATTERN  # noqa: F401
from .claim_rules._shared import _LOCAL_COOCCURRENCE_QUESTION_PATTERN  # noqa: F401
from .claim_rules._shared import _FOCAL_NODE_PATTERN  # noqa: F401
from .claim_rules._shared import _METHOD_STEP_TEXT_ORDINAL_PATTERN  # noqa: F401
from .claim_rules._shared import _LEADING_METHOD_STEP_ORDINAL_PATTERN  # noqa: F401
from .claim_rules._shared import _METHOD_STEP_ORDINAL_VALUES  # noqa: F401
from .claim_rules._shared import _REDUNDANT_LEMMA_ANALYSIS_PATTERN  # noqa: F401
from .claim_rules._shared import _LEMMA_ANNOTATION_QA_PATTERN  # noqa: F401
from .claim_rules._shared import _SINGLETON_DISTINCTIVENESS_PATTERN  # noqa: F401
from .claim_rules._shared import _EXPLICIT_NEW_COMPARATOR_PATTERN  # noqa: F401
from .claim_rules._shared import _SELF_CORPUS_COMPARATOR_PATTERN  # noqa: F401
from .claim_rules._shared import _COLLOCATION_METHOD_MENTION_PATTERN  # noqa: F401
from .claim_rules._shared import _EMPTY_COLLOCATION_PROFILE_OVERREAD_PATTERN  # noqa: F401
from .claim_rules._shared import _EMPTY_COLLOCATION_PARAMETER_BOUND_ZERO_PATTERN  # noqa: F401
from .claim_rules._shared import _EMPTY_COLLOCATION_PROFILE_TEST_PATTERN  # noqa: F401
from .claim_rules._shared import _COLLOCATION_POS_COMPOSITION_PATTERN  # noqa: F401
from .claim_rules._shared import _DISCOURSE_FUNCTION_TARGET_PATTERN  # noqa: F401
from .claim_rules._shared import _QUALITATIVE_CONTEXT_VALIDATION_PATTERN  # noqa: F401
from .claim_rules._shared import _COLLOCATION_PROFILE_COMPARISON_PATTERN  # noqa: F401
from .claim_rules._shared import _UNIVERSAL_ABSENCE_PATTERN  # noqa: F401
from .claim_rules._shared import _HASHTAG_LABEL_PATTERN  # noqa: F401
from .claim_rules._shared import _DOCUMENT_GROUP_PRESUPPOSITION_PATTERN  # noqa: F401
from .claim_rules._shared import _CONDITIONAL_AVAILABILITY_PATTERN  # noqa: F401
from .claim_rules._shared import _COLLOCATION_SYNTAX_GOAL_PATTERN  # noqa: F401
from .claim_rules._shared import _EXPLICIT_SYNTACTIC_METHOD_PATTERN  # noqa: F401
from .claim_rules._shared import _DATA_QUALITY_METHOD_PATTERN  # noqa: F401
from .claim_rules._shared import _PRIMARY_DATA_QUALITY_FOLLOWUP_PATTERN  # noqa: F401
from .claim_rules._shared import _SYSTEMATIC_DATA_QUALITY_PATTERN  # noqa: F401
from .claim_rules._shared import _TECHNICAL_PARTITION_MENTION_PATTERN  # noqa: F401
from .claim_rules._shared import _PARTITION_CONTENT_COMPARISON_PATTERN  # noqa: F401
from .claim_rules._shared import _PARTITION_QA_FRAMING_PATTERN  # noqa: F401
from .claim_rules._shared import _PARTITION_QA_MEASUREMENT_PATTERN  # noqa: F401
from .claim_rules._shared import _PARTITION_QA_OPERATION_PATTERN  # noqa: F401
from .claim_rules._shared import _RAW_TRUNCATION_MARKER_PATTERN  # noqa: F401
from .claim_rules._shared import _INTERNAL_GROUNDING_MARKER_PATTERN  # noqa: F401
from .claim_rules._shared import _SYNTACTIC_GENERALISATION_PATTERN  # noqa: F401
from .claim_rules._shared import _SYNTACTIC_FUNCTION_GENERALISATION_PATTERN  # noqa: F401
from .claim_rules._shared import _CATEGORICAL_SYNTACTIC_ROLE_PATTERNS  # noqa: F401
from .claim_rules._shared import _SYNTACTIC_ROLE_VALUE_ALIASES  # noqa: F401
from .claim_rules._shared import _NEGATIVE_PRESENCE_PATTERN  # noqa: F401
from .claim_rules._shared import _FACTUAL_LIST_PRESENCE_PATTERN  # noqa: F401
from .claim_rules._shared import _ROW_SCOPE_ABSENCE_PATTERN  # noqa: F401
from .claim_rules._shared import _ROW_SCOPE_PRESENCE_PATTERN  # noqa: F401
from .claim_rules._shared import _PARTIAL_EXHAUSTIVE_RESULT_PATTERN  # noqa: F401
from .claim_rules._shared import _ARTIFACT_CLASSIFICATION_PATTERN  # noqa: F401
from .claim_rules._shared import _ARTIFACT_QUALIFIER_PATTERN  # noqa: F401
from .claim_rules._shared import _EXPLICIT_ARTIFACT_EVIDENCE_PATTERN  # noqa: F401
from .claim_rules._shared import _PRESCRIBED_ARTIFACT_HANDLING_PATTERN  # noqa: F401
from .claim_rules._shared import _NATURAL_POS_PATTERNS  # noqa: F401
from .claim_rules._shared import _KWIC_PROVENANCE_PATTERN  # noqa: F401
from .claim_rules._shared import _SEMANTIC_PROVENANCE_PATTERN  # noqa: F401
from .claim_rules._shared import _UNIFORM_DISPERSION_PATTERN  # noqa: F401
from .claim_rules._shared import _COMPLETENESS_CLAIM_PATTERN  # noqa: F401
from .claim_rules._shared import _REPRESENTATIVENESS_CLAIM_PATTERN  # noqa: F401
from .claim_rules._shared import _CORRELATION_DIRECTION_PATTERN  # noqa: F401
from .claim_rules._shared import _INFERENTIAL_OBSERVATION_PATTERN  # noqa: F401
from .claim_rules._shared import _CROSS_TOOL_CAUSAL_PATTERN  # noqa: F401
from .claim_rules._shared import _CAUSAL_ASSERTION_PATTERN  # noqa: F401
from .claim_rules._shared import _NEGATIVE_METHOD_CONCLUSION_PATTERN  # noqa: F401
from .claim_rules._shared import _METHOD_ONLY_NEGATIVE_CONCLUSION_PATTERN  # noqa: F401
from .claim_rules._shared import _PURE_EPISTEMIC_NEGATION_PATTERN  # noqa: F401
from .claim_rules._shared import _LEXICAL_SUBSTITUTION_PATTERN  # noqa: F401
from .claim_rules._shared import _INTENTIONAL_LEXICAL_AVOIDANCE_PATTERN  # noqa: F401
from .claim_rules._shared import _EXPLICIT_TESTABLE_HYPOTHESIS_PATTERN  # noqa: F401
from .claim_rules._shared import _NEGATIVE_RESULT_POSITIVE_ASSERTION_PATTERN  # noqa: F401
from .claim_rules._shared import _NEGATED_CAUSAL_RELATION_PATTERN  # noqa: F401
from .claim_rules._shared import _METHODOLOGICAL_SCOPE_EXPLANATION_PATTERN  # noqa: F401
from .claim_rules._shared import _METHODOLOGICAL_SCOPE_EVIDENCE_PATTERN  # noqa: F401
from .claim_rules._shared import _INCOMMENSURABLE_RESULTS_PATTERN  # noqa: F401
from .claim_rules._shared import _FIELD_ASSIGNMENT_PATTERN  # noqa: F401
from .claim_rules._shared import _ROW_SCOPED_FIELD_NAMES  # noqa: F401
from .claim_rules._shared import _DECIMAL_METRIC_FIELD_NAMES  # noqa: F401
from .claim_rules._shared import _HIT_COUNT_FIELD_NAMES  # noqa: F401
from .claim_rules._shared import _TOTAL_HIT_COUNT_FIELD_NAMES  # noqa: F401
from .claim_rules._shared import _RESULT_COUNT_FIELD_NAMES  # noqa: F401
from .claim_rules._shared import _DOCUMENT_COUNT_FIELD_NAMES  # noqa: F401
from .claim_rules._shared import _CLUSTER_COUNT_FIELD_NAMES  # noqa: F401
from .claim_rules._shared import _RATIO_PERCENT_FIELD_NAMES  # noqa: F401
from .claim_rules._shared import _EXPLICIT_PERCENT_FIELD_NAMES  # noqa: F401
from .claim_rules._shared import _INTEGER_COUNT_FIELD_NAMES  # noqa: F401
from .claim_rules._shared import _FIELD_VALUE_ATOM_PATTERN  # noqa: F401
from .claim_rules._shared import _GROUP_SEP_CHARS  # noqa: F401
from .claim_rules._shared import _FIELD_NAME_ALIASES  # noqa: F401
from .claim_rules._shared import _normalize_number_token  # noqa: F401
from .claim_rules._shared import _number_has_integer_grouping_context  # noqa: F401
from .claim_rules._shared import _extract_numeric_tokens  # noqa: F401
from .claim_rules._shared import _normalise_field_value  # noqa: F401
from .claim_rules._shared import _source_values_for_field  # noqa: F401
from .claim_rules._shared import _canonical_field_name  # noqa: F401
from .claim_rules._shared import _unsupported_field_assignments  # noqa: F401
from .claim_rules._shared import _SLASH_SEPARATED_ROW_FIELD_PATTERN  # noqa: F401
from .claim_rules._shared import _unsupported_slash_separated_row_field_bindings  # noqa: F401
from .claim_rules._shared import _literal_value_occurrences  # noqa: F401
from .claim_rules._shared import _literal_value_occurs_in_compound  # noqa: F401
from .claim_rules._shared import _RELATION_LABEL_ALIASES  # noqa: F401
from .claim_rules._shared import _row_label_surface_forms  # noqa: F401
from .claim_rules._shared import _row_label_mentions  # noqa: F401
from .claim_rules._shared import _row_binding_mentions  # noqa: F401
from .claim_rules._shared import _row_field_assignments_are_atomic  # noqa: F401
from .claim_rules._shared import _WORD_PERCENT_PATTERN  # noqa: F401
from .claim_rules._shared import _NATURAL_PERCENT_VALUE_PATTERN  # noqa: F401
from .claim_rules._shared import _LOG_RATIO_LABEL_PATTERN  # noqa: F401
from .claim_rules._shared import _RATE_VALUE_PATTERN  # noqa: F401
from .claim_rules._shared import _NATURAL_METRIC_PATTERNS  # noqa: F401
from .claim_rules._shared import _ORDINAL_RANK_STEMS  # noqa: F401
from .claim_rules._shared import _ORDINAL_RANK_STEM_SOURCE  # noqa: F401
from .claim_rules._shared import _ORDINAL_RANK_PATTERN  # noqa: F401
from .claim_rules._shared import _PREDICATIVE_ORDINAL_RANK_PATTERN  # noqa: F401
from .claim_rules._shared import _COPULATIVE_ORDINAL_RANK_PATTERN  # noqa: F401
from .claim_rules._shared import _ORDERED_LIST_ENTRY_RANK_PATTERN  # noqa: F401
from .claim_rules._shared import _LIST_ENTRY_IN_RANKING_PATTERN  # noqa: F401
from .claim_rules._shared import _PRECEDING_ENTRIES_RANK_PATTERN  # noqa: F401
from .claim_rules._shared import _WORD_RANK_PATTERN  # noqa: F401
from .claim_rules._shared import _RANK_ONE_PATTERNS  # noqa: F401
from .claim_rules._shared import _METRIC_MAXIMUM_PATTERN  # noqa: F401
from .claim_rules._shared import _NAMED_METRIC_RANGE_PATTERN  # noqa: F401
from .claim_rules._shared import _RESULT_WIDE_METRIC_RANGE_PATTERN  # noqa: F401
from .claim_rules._shared import _FRACTION_PERCENT_VALUES  # noqa: F401
from .claim_rules._shared import _FRACTION_RATIOS  # noqa: F401
from .claim_rules._shared import _DISTRIBUTIVE_FRACTION_RATIOS  # noqa: F401
from .claim_rules._shared import _FRACTION_PERCENT_PATTERN  # noqa: F401
from .claim_rules._shared import _DISTRIBUTIVE_FRACTION_PATTERN  # noqa: F401
from .claim_rules._shared import _TIMES_COUNT_PATTERN  # noqa: F401
from .claim_rules._shared import _RATIO_COMPARISON_PATTERN  # noqa: F401
from .claim_rules._shared import _NAMED_FREQUENCY_FACTOR_PATTERN  # noqa: F401
from .claim_rules._shared import _RATIO_BINDING_PATTERNS  # noqa: F401
from .claim_rules._shared import _EXPLICIT_COUNT_PERCENT_PATTERN  # noqa: F401
from .claim_rules._shared import _EXPLICIT_SLASH_PERCENT_PATTERN  # noqa: F401
from .claim_rules._shared import _EXPLICIT_POSTPOSED_PERCENT_PATTERN  # noqa: F401
from .claim_rules._shared import _EXPLICIT_COUNT_PERCENT_PATTERNS  # noqa: F401
from .claim_rules._shared import _ELLIPTICAL_COUNT_COMPARISON_PATTERN  # noqa: F401
from .claim_rules._shared import _POSTPOSED_ELLIPTICAL_COUNT_PATTERN  # noqa: F401
from .claim_rules._shared import _UNIT_FREE_ROW_COUNT_PATTERNS  # noqa: F401
from .claim_rules._shared import _RATE_DENOMINATOR_PATTERNS  # noqa: F401
from .claim_rules._shared import _ROW_LABEL_FIELD_NAMES  # noqa: F401
from .claim_rules._shared import _count_fields_for_claim_fragment  # noqa: F401
from .claim_rules._shared import _field_numeric_values  # noqa: F401
from .claim_rules._shared import _dozen_count_value  # noqa: F401
from .claim_rules._shared import _unsupported_count_bindings  # noqa: F401
from .claim_rules._shared import _row_count_for_label  # noqa: F401
from .claim_rules._shared import _displayed_scaled_quotient_matches  # noqa: F401
from .claim_rules._shared import _fact_provenance_surfaces  # noqa: F401
from .claim_rules._shared import _rate_token_is_supported  # noqa: F401
from .claim_rules._shared import _rate_binding_status  # noqa: F401
from .claim_rules._shared import _explicit_percent_binding_status  # noqa: F401
from .claim_rules._shared import _ratio_comparison_binding_status  # noqa: F401
from .claim_rules._shared import _unsupported_elliptical_count_bindings  # noqa: F401
from .claim_rules._shared import _count_token_value  # noqa: F401
from .claim_rules._shared import _unsupported_named_count_pair_bindings  # noqa: F401
from .claim_rules._shared import _unsupported_postposed_count_bindings  # noqa: F401
from .claim_rules._shared import _unsupported_unit_free_row_counts  # noqa: F401
from .claim_rules._shared import _single_fact_numeric_value  # noqa: F401
from .claim_rules._shared import _normalised_time_trend_status  # noqa: F401
from .claim_rules._shared import _normalised_rates_by_year  # noqa: F401
from .claim_rules._shared import _time_change_matches_ratio  # noqa: F401
from .claim_rules._shared import _generic_time_trend_status  # noqa: F401
from .claim_rules._shared import _unsupported_syntactic_role_claims  # noqa: F401
from .claim_rules._shared import _source_row_label_lookup  # noqa: F401
from .claim_rules._shared import _unsupported_presence_claims  # noqa: F401
from .claim_rules._shared import _contains_literal_label  # noqa: F401
from .claim_rules._shared import _unsupported_directional_scope_presence_claims  # noqa: F401
from .claim_rules._shared import _unsupported_hashtag_label  # noqa: F401
from .claim_rules._shared import _unsupported_partial_exhaustive_claims  # noqa: F401
from .claim_rules._shared import _unsupported_artifact_classifications  # noqa: F401
from .claim_rules._shared import _match_is_part_of_proposed_test  # noqa: F401
from .claim_rules._shared import _match_is_part_of_conditional_test  # noqa: F401
from .claim_rules._shared import _unsupported_text_production_inferences  # noqa: F401
from .claim_rules._shared import _unsupported_pos_claims  # noqa: F401
from .claim_rules._shared import _unsupported_tool_provenance_claims  # noqa: F401
from .claim_rules._shared import _unsupported_distribution_claims  # noqa: F401
from .claim_rules._shared import _unsupported_scope_design_claims  # noqa: F401
from .claim_rules._shared import _LEXICAL_RATING_WORD_PATTERN  # noqa: F401
from .claim_rules._shared import _LEXICAL_RATING_DENIAL_PATTERN  # noqa: F401
from .claim_rules._shared import _is_lexical_reference_boundary_claim  # noqa: F401
from .claim_rules._shared import _has_relative_sttr_mattr_preference  # noqa: F401
from .claim_rules._shared import _supported_equal_window_boundary_comparison  # noqa: F401
from .claim_rules._shared import _lexical_window_parameters_differ  # noqa: F401
from .claim_rules._shared import _unsupported_lexical_diversity_claims  # noqa: F401
from .claim_rules._shared import _unsupported_correlation_claims  # noqa: F401
from .claim_rules._shared import _unsupported_rate_denominator_bindings  # noqa: F401
from .claim_rules._shared import _extract_numeric_tokens_outside_spans  # noqa: F401
from .claim_rules._shared import _natural_metric_bindings  # noqa: F401
from .claim_rules._shared import _unsupported_natural_metric_bindings  # noqa: F401
from .claim_rules._shared import _canonical_claim_metric  # noqa: F401
from .claim_rules._shared import _visible_metric_values_by_label  # noqa: F401
from .claim_rules._shared import _unsupported_metric_maximum_claims  # noqa: F401
from .claim_rules._shared import _unsupported_result_wide_metric_ranges  # noqa: F401
from .claim_rules._shared import _numeric_percent_tokens  # noqa: F401
from .claim_rules._shared import _unsupported_word_percent_bindings  # noqa: F401
from .claim_rules._shared import _fraction_percent_is_supported  # noqa: F401
from .claim_rules._shared import _ratio_share_is_supported  # noqa: F401
from .claim_rules._shared import _percent_token_is_supported  # noqa: F401
from .claim_rules._shared import _numeric_token_is_supported  # noqa: F401
from .claim_rules._shared import _extract_ranges  # noqa: F401
from .claim_rules._shared import _has_word_range_claim  # noqa: F401
from .claim_rules._shared import _has_word_count_claim  # noqa: F401
from .claim_rules._shared import _is_existential_kwic_evidence_claim  # noqa: F401
from .claim_rules._shared import _has_digit_count_claim  # noqa: F401
from .claim_rules._shared import _without_markdown_list_ordinals  # noqa: F401
from .claim_rules._shared import _without_claim_step_ordinals  # noqa: F401
from .claim_rules._shared import _extract_quoted_segments  # noqa: F401
from .claim_rules._shared import _extract_blockquote_segments  # noqa: F401
from .claim_rules._shared import _unpaired_empirical_quote_matches  # noqa: F401
from .claim_rules._shared import _prose_outside_examples  # noqa: F401
from .claim_rules._shared import _normalise_quote_for_match  # noqa: F401
from .claim_rules._shared import _normalised_quote_occurs  # noqa: F401
from .claim_rules._shared import _quoted_segment_is_supported  # noqa: F401
from .claim_rules._shared import _EMPIRICAL_QUOTE_CONTEXT_PATTERN  # noqa: F401
from .claim_rules._shared import _SCOPE_QUOTE_CONTEXT_PATTERN  # noqa: F401
from .claim_rules._shared import _extract_empirical_inline_code_segments  # noqa: F401
from .claim_rules._shared import _extract_grounding_example_segments  # noqa: F401
from .claim_rules._shared import _SOURCE_ATTRIBUTED_CAUSAL_READING_PATTERN  # noqa: F401
from .claim_rules._shared import _SOURCE_ATTRIBUTED_CAUSAL_LINK_PATTERN  # noqa: F401
from .claim_rules._shared import _SOURCE_READING_TOKEN_STOPWORDS  # noqa: F401
from .claim_rules._shared import _CROSS_SENTENCE_INFERENCE_PATTERN  # noqa: F401
from .claim_rules._shared import _SOURCE_READING_CLAUSE_SPLIT_PATTERN  # noqa: F401
from .claim_rules._shared import _LIKELY_PREDICATE_TOKEN_PATTERN  # noqa: F401
from .claim_rules._shared import _source_passage_sentence_units  # noqa: F401
from .claim_rules._shared import _source_attributed_cross_sentence_inference  # noqa: F401
from .claim_rules._shared import _source_attributed_unmarked_causal_link  # noqa: F401
from .claim_rules._shared import _source_attributed_cross_sentence_predicate_transfer  # noqa: F401
from .claim_rules._shared import _grounded_source_attributed_causal_reading  # noqa: F401
from .claim_rules._shared import _quote_is_user_scope_reference  # noqa: F401
from .claim_rules._shared import _quote_is_negative_temporal_field_example  # noqa: F401
from .claim_rules._shared import _quote_is_negative_lexical_rating_example  # noqa: F401
from .claim_rules._shared import _joined_surface_text  # noqa: F401
from .claim_rules._shared import _stronger_than_exactness  # noqa: F401
from .claim_rules._shared import _unmeasured_partial_magnitude_claims  # noqa: F401
from .claim_rules._shared import _has_definitive_global_scope_claim  # noqa: F401
from .claim_rules._shared import _is_explicitly_bounded_claim  # noqa: F401
from .claim_rules._shared import _fact_bound_values  # noqa: F401
from .claim_rules._shared import _clause_supporting_source_ids  # noqa: F401
from .claim_rules._shared import _supports_distinct_sources  # noqa: F401
from .claim_rules._shared import _has_cross_source_literal_separation  # noqa: F401
from .claim_rules._shared import _has_positive_extra_clause  # noqa: F401
from .claim_rules._shared import _is_grounded_methodological_explanation  # noqa: F401
from .claim_rules._shared import _has_unnegated_pattern  # noqa: F401
from .claim_rules._shared import _metadata_value_counts  # noqa: F401
from .claim_rules._shared import _metadata_fields_mentioned  # noqa: F401
from .claim_rules._shared import _metadata_singleton_values  # noqa: F401
from .claim_rules._shared import _unsupported_raw_pos_inference  # noqa: F401
from .claim_rules._shared import _unsupported_pos_inventory_provenance  # noqa: F401
from .claim_rules._shared import _NATURAL_POS_LABELS  # noqa: F401
from .claim_rules._shared import _unsupported_natural_pos_label  # noqa: F401
from .claim_rules._shared import _unsupported_absolute_association_magnitude  # noqa: F401
from .claim_rules._shared import _empty_collocation_profile_is_overread  # noqa: F401
from .claim_rules._shared import _unsupported_collocation_pos_composition  # noqa: F401
from .claim_rules._shared import _collocation_substitutes_for_discourse_function  # noqa: F401
from .claim_rules._shared import _facts_contain_relational_evidence  # noqa: F401
from .claim_rules._shared import _unsupported_platform_handle_label  # noqa: F401
from .claim_rules._shared import _unsupported_document_class_label  # noqa: F401
from .claim_rules._shared import _unsupported_user_handle_identity  # noqa: F401
from .claim_rules._shared import _followup_presupposes_effect_without_design  # noqa: F401
from .claim_rules._shared import _followup_presupposes_unobserved_relation  # noqa: F401
from .claim_rules._shared import _absolute_counts_called_relative  # noqa: F401
from .claim_rules._shared import _unsupported_register_theme_inference  # noqa: F401
from .claim_rules._shared import _followup_correlation_is_operationalised  # noqa: F401
from .claim_rules._shared import _followup_mixes_aggregate_and_token_validation  # noqa: F401
from .claim_rules._shared import _followup_uses_sentence_length_as_complexity  # noqa: F401
from .claim_rules._shared import _distribution_substitutes_for_thematic_analysis  # noqa: F401
from .claim_rules._shared import _distribution_substitutes_for_function_analysis  # noqa: F401
from .claim_rules._shared import _pos_inventory_substitutes_for_morphosyntax  # noqa: F401
from .claim_rules._shared import _pos_filtered_lexicon_called_pos_distribution  # noqa: F401
from .claim_rules._shared import _local_association_lacks_collocation_design  # noqa: F401
from .claim_rules._shared import _accounting_gap_lacks_token_reconciliation  # noqa: F401
from .claim_rules._shared import _lexical_absence_overreads_contextual_retrieval  # noqa: F401
from .claim_rules._shared import _unsupported_grammatical_profile_inference  # noqa: F401
from .claim_rules._shared import _result_is_mislabeled_as_sample  # noqa: F401
from .claim_rules._shared import _DECLARED_SAMPLE_CARDINALITY_PATTERN  # noqa: F401
from .claim_rules._shared import _declared_sample_cardinality_is_wrong  # noqa: F401
from .claim_rules._shared import _local_cooccurrence_anchors  # noqa: F401
from .claim_rules._shared import _overview_observation_is_provenance_only  # noqa: F401
from .claim_rules._shared import _method_step_text_ordinal  # noqa: F401
from .claim_rules._shared import _strip_redundant_method_step_ordinal  # noqa: F401
from .claim_rules._shared import _claim_mentions_specific_fact_anchor  # noqa: F401
from .claim_rules._shared import _claim_has_structural_fact_anchor  # noqa: F401
from .claim_rules._shared import _merges_cross_result_rankings  # noqa: F401
from .claim_rules._shared import _followup_reasks_known_singleton_axis  # noqa: F401
from .claim_rules._shared import _followup_reasks_settled_denominator_scope  # noqa: F401
from .claim_rules._shared import _followup_changes_analysis_scope  # noqa: F401
from .claim_rules._shared import _followup_confuses_context_with_reranking  # noqa: F401
from .claim_rules._shared import _presupposes_unseen_document_groups  # noqa: F401
from .claim_rules._shared import _uses_collocation_as_syntax_method  # noqa: F401
from .claim_rules._shared import _pos_filtered_handle_anomalies  # noqa: F401
from .claim_rules._shared import _pos_filtered_handle_fact_ids  # noqa: F401
from .claim_rules._shared import _is_data_quality_followup  # noqa: F401
from .claim_rules._shared import _is_systematic_data_quality_followup  # noqa: F401
from .claim_rules._shared import _is_primary_data_quality_followup  # noqa: F401
from .claim_rules._shared import _uses_technical_partition_as_content_axis  # noqa: F401
from .claim_rules._shared import _near_duplicate_research_question  # noqa: F401
from .claim_rules._shared import _has_positive_partition_purpose_claim  # noqa: F401
from .claim_rules._shared import _range_is_covered_by_numbers  # noqa: F401
from .claim_rules._shared import _is_rank_range_claim  # noqa: F401
from .claim_rules._shared import _is_negative_or_unknown_limitation  # noqa: F401
from .claim_rules._shared import _is_authoritative_evidence_item  # noqa: F401
from .claim_rules._shared import _MODEL_FACT_FUNCTION_WORDS  # noqa: F401
from .claim_rules._shared import _MODEL_FACT_SCAFFOLD_PREFIXES  # noqa: F401
from .claim_rules._shared import _model_fact_content_terms  # noqa: F401
from .claim_rules._shared import _unsupported_model_fact_terms  # noqa: F401
from .claim_rules._shared import _nonpositive_only_claim_has_positive_assertion  # noqa: F401
from .claim_rules._shared import _safe_multi_field_statement_frame  # noqa: F401
from .claim_rules._shared import _model_fact_has_atomic_quote_support  # noqa: F401
from .claim_rules._shared import _sanitise_model_fact_contract  # noqa: F401
from .claim_rules._shared import _violates_forbidden_claim  # noqa: F401
from .claim_rules._shared import _looks_like_opaque_id  # noqa: F401
from .claim_rules._shared import _SEMANTIC_THEME_STOPWORDS  # noqa: F401
from .claim_rules._shared import _semantic_theme_tokens  # noqa: F401
from .claim_rules.kwic import _NO_NEGATION_CLAIM_PATTERN  # noqa: F401
from .claim_rules.kwic import _NEGATION_TOKEN_PATTERN  # noqa: F401
from .claim_rules.kwic import _CATEGORICAL_ATTACHMENT_PATTERN  # noqa: F401
from .claim_rules.kwic import _ATTACHMENT_QUALIFIER_PATTERN  # noqa: F401
from .claim_rules.kwic import _KWIC_SEMANTIC_DIVERSITY_PATTERN  # noqa: F401
from .claim_rules.kwic import _PARTIAL_KWIC_PREVALENCE_PATTERN  # noqa: F401
from .claim_rules.kwic import _PARTIAL_KWIC_DISCOURSE_SYSTEM_PATTERN  # noqa: F401
from .claim_rules.kwic import _VISIBLE_KWIC_SUBSET_COUNT_PATTERN  # noqa: F401
from .claim_rules.kwic import _KWIC_EVALUATIVE_CATEGORY_PATTERN  # noqa: F401
from .claim_rules.kwic import _VISIBLE_EPISTEMIC_QUALIFIER_PATTERN  # noqa: F401
from .claim_rules.kwic import _KWIC_AGGREGATE_CATEGORY_SCOPE_PATTERN  # noqa: F401
from .claim_rules.kwic import _CONTEXT_CODING_ASSIGNMENT_PATTERN  # noqa: F401
from .claim_rules.kwic import _KWIC_POSITION_ANCHOR_PATTERN  # noqa: F401
from .claim_rules.kwic import _KWIC_DOCUMENT_ANCHOR_PATTERN  # noqa: F401
from .claim_rules.kwic import _KWIC_ROW_ANCHOR_PATTERN  # noqa: F401
from .claim_rules.kwic import _KWIC_LITERAL_MEMBERSHIP_PATTERN  # noqa: F401
from .claim_rules.kwic import _KWIC_METALINGUISTIC_CATEGORY_PATTERN  # noqa: F401
from .claim_rules.kwic import _KWIC_REFERENCE_RESOLUTION_PATTERN  # noqa: F401
from .claim_rules.kwic import _EXPLICIT_REFERENCE_EVIDENCE_PATTERN  # noqa: F401
from .claim_rules.kwic import _KWIC_PARTICIPANT_TYPING_PATTERN  # noqa: F401
from .claim_rules.kwic import _KWIC_PRONOUN_ROLE_FRAME_PATTERN  # noqa: F401
from .claim_rules.kwic import _KWIC_NAMED_ROLE_ASSIGNMENT_PATTERN  # noqa: F401
from .claim_rules.kwic import _KWIC_CONTENT_PARAPHRASE_PATTERN  # noqa: F401
from .claim_rules.kwic import _KWIC_NEW_PARTICIPANT_TYPE_PATTERN  # noqa: F401
from .claim_rules.kwic import _KWIC_SOURCE_ROLE_ATTRIBUTION_PATTERN  # noqa: F401
from .claim_rules.kwic import _KWIC_ANONYMIZATION_PATTERN  # noqa: F401
from .claim_rules.kwic import _KWIC_ANONYMIZATION_EVIDENCE_PATTERN  # noqa: F401
from .claim_rules.kwic import _KWIC_CATEGORICAL_PURPOSE_PATTERN  # noqa: F401
from .claim_rules.kwic import _KWIC_PURPOSE_EVIDENCE_PATTERN  # noqa: F401
from .claim_rules.kwic import _KWIC_REPETITION_PATTERN  # noqa: F401
from .claim_rules.kwic import _QUOTED_CONTENT_PATTERN  # noqa: F401
from .claim_rules.kwic import _KWIC_SAFE_META_PREDICATES  # noqa: F401
from .claim_rules.kwic import _KWIC_AUXILIARY_PREDICATES  # noqa: F401
from .claim_rules.kwic import _KWIC_AS_COLLOCATION_METHOD_PATTERN  # noqa: F401
from .claim_rules.kwic import _EXPLICIT_COLLOCATION_METHOD_PATTERN  # noqa: F401
from .claim_rules.kwic import _kwic_predicate_stem  # noqa: F401
from .claim_rules.kwic import _unsupported_kwic_event_paraphrases  # noqa: F401
from .claim_rules.kwic import _OPEN_KWIC_RIGHT_EDGE_PATTERN  # noqa: F401
from .claim_rules.kwic import _KWIC_WINDOW_QUOTE_PATTERN  # noqa: F401
from .claim_rules.kwic import _unsupported_open_kwic_window_interpretations  # noqa: F401
from .claim_rules.kwic import _unsupported_kwic_repetition_claims  # noqa: F401
from .claim_rules.kwic import _unsupported_kwic_categorical_purpose  # noqa: F401
from .claim_rules.kwic import _kwic_participant_type_is_literal  # noqa: F401
from .claim_rules.kwic import _unsupported_kwic_source_role_attribution  # noqa: F401
from .claim_rules.kwic import _unsupported_expanded_context_interpretations  # noqa: F401
from .claim_rules.kwic import _unsupported_kwic_semantic_diversity_claims  # noqa: F401
from .claim_rules.kwic import _unsupported_partial_kwic_prevalence_claims  # noqa: F401
from .claim_rules.kwic import _unsupported_visible_kwic_subset_counts  # noqa: F401
from .claim_rules.kwic import _kwic_fact_identity  # noqa: F401
from .claim_rules.kwic import _kwic_subset_membership_term  # noqa: F401
from .claim_rules.kwic import _normalise_kwic_category  # noqa: F401
from .claim_rules.kwic import _fact_local_context_labels  # noqa: F401
from .claim_rules.kwic import _claim_is_visibly_tentative  # noqa: F401
from .claim_rules.kwic import _kwic_category_claim_is_supported  # noqa: F401
from .claim_rules.kwic import _coded_kwic_prevalence_is_supported  # noqa: F401
from .claim_rules.kwic import _unsupported_exact_kwic_category_claim  # noqa: F401
from .claim_rules.kwic import _followup_uses_kwic_as_collocation_statistic  # noqa: F401
from .claim_rules.kwic import _KWIC_AMBIGUITY_PATTERN  # noqa: F401
from .claim_rules.ngram import _NGRAM_GRAMMATICAL_UNIT_PATTERN  # noqa: F401
from .claim_rules.ngram import _NGRAM_CONTEXT_DIVERSITY_PATTERN  # noqa: F401
from .claim_rules.ngram import _NGRAM_FUNCTION_FREQUENCY_PATTERN  # noqa: F401
from .claim_rules.ngram import _NGRAM_DISPERSION_SEMANTIC_TEST_PATTERN  # noqa: F401
from .claim_rules.ngram import _unsupported_ngram_unit_classifications  # noqa: F401
from .claim_rules.ngram import _unsupported_ngram_context_diversity_claims  # noqa: F401
from .claim_rules.ngram import _unsupported_ngram_function_frequency_claims  # noqa: F401
from .claim_rules.ngram import _unsupported_ngram_semantic_validation_claims  # noqa: F401
from .claim_rules.ngram import _NGRAM_HYPOTHESIS_PATTERN  # noqa: F401
from .claim_rules.ngram import _NGRAM_VALIDATION_PATTERN  # noqa: F401
from .claim_rules.ngram import _NGRAM_EPISTEMIC_PATTERN  # noqa: F401
from .claim_rules.ngram import _ngram_surface_terms  # noqa: F401
from .claim_rules.keyness import _KEYNESS_LABEL_PATTERN  # noqa: F401
from .claim_rules.keyness import _KEYNESS_SCOPE_REFERENCE_PATTERN  # noqa: F401
from .claim_rules.keyness import _KEYNESS_METHOD_TARGET_PATTERN  # noqa: F401
from .claim_rules.keyness import _KEYNESS_SAME_ITEMS_PATTERN  # noqa: F401
from .claim_rules.keyness import _KEYNESS_GLOBAL_TOP_PATTERN  # noqa: F401
from .claim_rules.keyness import _KEYNESS_LEXICAL_CORE_PATTERN  # noqa: F401
from .claim_rules.keyness import _KEYNESS_DIRECTION_GROUP_PATTERN  # noqa: F401
from .claim_rules.keyness import _ABSOLUTE_KEYNESS_MAGNITUDE_PATTERN  # noqa: F401
from .claim_rules.keyness import _EXPLICIT_KEYNESS_MAGNITUDE_CRITERION_PATTERN  # noqa: F401
from .claim_rules.keyness import _KEYNESS_CAUSAL_ATTRIBUTION_PATTERN  # noqa: F401
from .claim_rules.keyness import _KEYNESS_CAUSAL_QUALIFIER_PATTERN  # noqa: F401
from .claim_rules.keyness import _unsupported_keyness_same_items_claim  # noqa: F401
from .claim_rules.keyness import _facts_use_balanced_keyness_selection  # noqa: F401
from .claim_rules.keyness import _unsupported_balanced_keyness_global_rank_claim  # noqa: F401
from .claim_rules.keyness import _unsupported_keyness_lexical_core_claim  # noqa: F401
from .claim_rules.keyness import _unsupported_absolute_keyness_magnitude  # noqa: F401
from .claim_rules.keyness import _unsupported_keyness_causal_attributions  # noqa: F401
from .claim_rules.keyness import _unsupported_keyness_label  # noqa: F401
from .claim_rules.frequency import _FOLLOWUP_SETTLED_FREQUENCY_NORMALIZATION_PATTERN  # noqa: F401
from .claim_rules.frequency import _ASSERTED_FREQUENCY_THEME_PREMISE_PATTERN  # noqa: F401
from .claim_rules.frequency import _FREQUENCY_COPRESENCE_PATTERN  # noqa: F401
from .claim_rules.frequency import _EXPLICIT_LIST_COPRESENCE_PATTERN  # noqa: F401
from .claim_rules.frequency import _ABSOLUTE_FREQUENCY_MAGNITUDE_PATTERN  # noqa: F401
from .claim_rules.frequency import _EXPLICIT_FREQUENCY_MAGNITUDE_REFERENCE_PATTERN  # noqa: F401
from .claim_rules.frequency import _RAW_FREQUENCY_LENGTH_RELATION_PATTERN  # noqa: F401
from .claim_rules.frequency import _LENGTH_NORMALISATION_PATTERN  # noqa: F401
from .claim_rules.frequency import _FREQUENCY_METHOD_PATTERN  # noqa: F401
from .claim_rules.frequency import _MORPHOLOGICAL_CATEGORY_PATTERN  # noqa: F401
from .claim_rules.frequency import _EXPLICIT_MORPHOLOGY_METHOD_PATTERN  # noqa: F401
from .claim_rules.frequency import _FREQUENCY_DIRECTION_PATTERN  # noqa: F401
from .claim_rules.frequency import _unsupported_frequency_directions  # noqa: F401
from .claim_rules.frequency import _unsupported_frequency_theme_inference  # noqa: F401
from .claim_rules.frequency import _unsupported_absolute_frequency_magnitude  # noqa: F401
from .claim_rules.frequency import _unsupported_frequency_copresence_inference  # noqa: F401
from .claim_rules.frequency import _followup_confounds_raw_frequency_with_length  # noqa: F401
from .claim_rules.frequency import _frequency_substitutes_for_contextual_meaning  # noqa: F401
from .claim_rules.frequency import _followup_infers_morphology_from_surface_frequency  # noqa: F401
from .claim_rules.frequency import _followup_reasks_settled_frequency_normalization  # noqa: F401
from .claim_rules.semantic import _SEMANTIC_COOCCURRENCE_CLAIM_PATTERN  # noqa: F401
from .claim_rules.semantic import _SEMANTIC_COOCCURRENCE_NEGATION_PATTERN  # noqa: F401
from .claim_rules.semantic import _SEMANTIC_RETRIEVAL_FREQUENCY_RANK_PATTERN  # noqa: F401
from .claim_rules.semantic import _SEMANTIC_RETRIEVAL_CORPUS_PREVALENCE_PATTERN  # noqa: F401
from .claim_rules.semantic import _SEMANTIC_RETRIEVAL_PREVALENCE_TERM_PATTERN  # noqa: F401
from .claim_rules.semantic import _SEMANTIC_RETRIEVAL_CENTRALITY_PATTERN  # noqa: F401
from .claim_rules.semantic import _SOURCE_ATTRIBUTED_CENTRALITY_MENTION_PATTERN  # noqa: F401
from .claim_rules.semantic import _NEGATED_PREVALENCE_PREFIX_PATTERN  # noqa: F401
from .claim_rules.semantic import _SEMANTIC_SIMILARITY_GOAL_PATTERN  # noqa: F401
from .claim_rules.semantic import _uses_single_collocation_as_semantic_similarity  # noqa: F401
from .claim_rules.semantic import _has_positive_semantic_cooccurrence_claim  # noqa: F401
from .claim_rules.semantic import _semantic_retrieval_is_mislabeled_as_frequency  # noqa: F401
from .claim_rules.semantic import _semantic_retrieval_is_mislabeled_as_centrality  # noqa: F401
from .claim_rules.metadata import _FOLLOWUP_COMPLETE_METADATA_INVENTORY_PATTERN  # noqa: F401
from .claim_rules.metadata import _FOLLOWUP_SETTLED_METADATA_USABILITY_PATTERN  # noqa: F401
from .claim_rules.metadata import _METADATA_SINGLETON_CLAIM_PATTERN  # noqa: F401
from .claim_rules.metadata import _METADATA_UNIVERSAL_HOMOGENEITY_PATTERN  # noqa: F401
from .claim_rules.metadata import _METADATA_HOMOGENEITY_PATTERN  # noqa: F401
from .claim_rules.metadata import _METADATA_VISIBLE_VALUE_QUALIFIER_PATTERN  # noqa: F401
from .claim_rules.metadata import _METADATA_CONFIRMATION_PATTERN  # noqa: F401
from .claim_rules.metadata import _MORE_DOCUMENTS_FOR_METADATA_VARIANCE_PATTERN  # noqa: F401
from .claim_rules.metadata import _metadata_homogeneity_is_prejudged  # noqa: F401
from .claim_rules.metadata import _metadata_fields_asserted_singleton  # noqa: F401
from .claim_rules.metadata import _followup_reasks_complete_metadata_inventory  # noqa: F401
from .claim_rules.metadata import _followup_reasks_settled_metadata_usability  # noqa: F401
from .claim_rules.wordsketch import _STATISTICAL_CERTAINTY_PATTERN  # noqa: F401
from .claim_rules.wordsketch import _EXPLICIT_SIGNIFICANCE_EVIDENCE_PATTERN  # noqa: F401
from .claim_rules.wordsketch import _WORD_SKETCH_PREVALENCE_PATTERN  # noqa: F401
from .claim_rules.wordsketch import _WORD_SKETCH_ABSOLUTE_PREVALENCE_PATTERN  # noqa: F401
from .claim_rules.wordsketch import _WORD_SKETCH_EMPHASISED_SEGMENT_PATTERN  # noqa: F401
from .claim_rules.wordsketch import _WORD_SKETCH_COUNT_UNIT_PATTERN  # noqa: F401
from .claim_rules.wordsketch import _WORD_SKETCH_ONCE_PATTERN  # noqa: F401
from .claim_rules.wordsketch import _WORD_SKETCH_FALSE_ABSENCE_PATTERN  # noqa: F401
from .claim_rules.wordsketch import _WORD_SKETCH_QUERY_ROLE_PATTERN  # noqa: F401
from .claim_rules.wordsketch import _WORD_SKETCH_QUERY_PARTICIPATION_PATTERN  # noqa: F401
from .claim_rules.wordsketch import _WORD_SKETCH_QUERY_FUNCTION_OVERREAD_PATTERN  # noqa: F401
from .claim_rules.wordsketch import _WORD_SKETCH_ROW_CONTEXT_PATTERN  # noqa: F401
from .claim_rules.wordsketch import _WORD_SKETCH_UNSUPPORTED_POS_PATTERN  # noqa: F401
from .claim_rules.wordsketch import _WORD_SKETCH_RELATION_THRESHOLD_PATTERN  # noqa: F401
from .claim_rules.wordsketch import _WORD_SKETCH_UNREPORTED_RELATION_PATTERN  # noqa: F401
from .claim_rules.wordsketch import _WORD_SKETCH_PARTNER_EXCLUSIVITY_PATTERN  # noqa: F401
from .claim_rules.wordsketch import _word_sketch_semantic_violations  # noqa: F401
from .claim_rules.wordsketch import _word_sketch_evidence_is_falsely_absent  # noqa: F401
from .claim_rules.dispersion import _DISPERSION_SEMANTIC_SCOPE_PATTERN  # noqa: F401
from .claim_rules.dispersion import _JUILLAND_CONCENTRATION_DIRECTION_PATTERN  # noqa: F401
from .claim_rules.dispersion import _DP_EVENNESS_DIRECTION_PATTERN  # noqa: F401
from .claim_rules.dispersion import _LOW_CONCENTRATION_PATTERN  # noqa: F401
from .claim_rules.dispersion import _UNSOURCED_DISPERSION_THRESHOLD_PATTERN  # noqa: F401
from .claim_rules.dispersion import _MAXIMUM_DOCUMENT_RANGE_PATTERN  # noqa: F401
from .claim_rules.dispersion import _CONCENTRATION_INTERPRETATION_PATTERN  # noqa: F401
from .claim_rules.dispersion import _CAUSAL_EVIDENCE_LINK_PATTERN  # noqa: F401
from .claim_rules.dispersion import _FEW_DOCUMENT_CONCENTRATION_PATTERN  # noqa: F401
from .claim_rules.dispersion import _LOCAL_REPEAT_CONCENTRATION_PATTERN  # noqa: F401
from .claim_rules.dispersion import _unsupported_dispersion_interpretations  # noqa: F401

# --------------------------------------------------------------------------- #
# K3 Slice 3: the deterministic evidence/observed-fact layer moved verbatim
# to ``grounding_facts`` and the envelope/markdown validation layer to
# ``grounding_validation``. Same facade contract as above: every previously
# importable name (public AND private) is re-imported here explicitly.
# --------------------------------------------------------------------------- #
from .grounding_facts import payload_preview  # noqa: F401
from .grounding_facts import make_evidence_item  # noqa: F401
from .grounding_facts import _frequency_group_by  # noqa: F401
from .grounding_facts import _CONTENT_POS_PREFIXES  # noqa: F401
from .grounding_facts import frequency_parameters_supply_content_rows  # noqa: F401
from .grounding_facts import _frequency_is_content_profile  # noqa: F401
from .grounding_facts import evidence_kinds_for_item  # noqa: F401
from .grounding_facts import evidence_kinds_for_fact  # noqa: F401
from .grounding_facts import _metadata_values_for_field  # noqa: F401
from .grounding_facts import _metadata_blocks_human_ai_contrast  # noqa: F401
from .grounding_facts import _metadata_inventory_items  # noqa: F401
from .grounding_facts import _TEMPORAL_METADATA_FIELD_PATTERN  # noqa: F401
from .grounding_facts import _metadata_blocks_trend  # noqa: F401
from .grounding_facts import _metadata_blocks_requested_register  # noqa: F401
from .grounding_facts import _effective_required_evidence  # noqa: F401
from .grounding_facts import effective_analysis_contract  # noqa: F401
from .grounding_facts import _has_completed_collocation_profile  # noqa: F401
from .grounding_facts import _evidence_query_args  # noqa: F401
from .grounding_facts import _collocation_bool  # noqa: F401
from .grounding_facts import _CollocationProfileSignature  # noqa: F401
from .grounding_facts import _effective_evidence_scope  # noqa: F401
from .grounding_facts import _collocation_profile_record  # noqa: F401
from .grounding_facts import _collocation_profile_matches_request  # noqa: F401
from .grounding_facts import _selected_collocation_profiles  # noqa: F401
from .grounding_facts import _matching_collocation_count_items  # noqa: F401
from .grounding_facts import same_corpus_collocation_evidence_gaps  # noqa: F401
from .grounding_facts import _QUERY_DIAGNOSTIC_REQUEST_PATTERN  # noqa: F401
from .grounding_facts import _is_requested_query_diagnostic  # noqa: F401
from .grounding_facts import _structured_query_diagnostic  # noqa: F401
from .grounding_facts import build_evidence_bundle  # noqa: F401
from .grounding_facts import required_evidence_fact_gaps  # noqa: F401
from .grounding_facts import parse_structured_payload  # noqa: F401
from .grounding_facts import unique_observed_fact_id  # noqa: F401
from .grounding_facts import normalise_observed_facts  # noqa: F401
from .grounding_facts import _make_fact  # noqa: F401
from .grounding_facts import _item_exactness  # noqa: F401
from .grounding_facts import _limitation_facts_for_item  # noqa: F401
from .grounding_facts import _not_applicable_facts_for_item  # noqa: F401
from .grounding_facts import _query_error_facts  # noqa: F401
from .grounding_facts import _semantic_meta_search_mode  # noqa: F401
from .grounding_facts import _semantic_item_exactness  # noqa: F401
from .grounding_facts import _semantic_meta_limitations  # noqa: F401
from .grounding_facts import _semantic_meta_limitation_facts  # noqa: F401
from .grounding_facts import _frequency_row_facts  # noqa: F401
from .grounding_facts import _frequency_pos_scope_fact  # noqa: F401
from .grounding_facts import _frequency_scope_facts  # noqa: F401
from .grounding_facts import _query_count_facts  # noqa: F401
from .grounding_facts import _collocation_method_facts  # noqa: F401
from .grounding_facts import _collocation_comparison_facts  # noqa: F401
from .grounding_facts import _annotation_sensitive_cqlf_query  # noqa: F401
from .grounding_facts import _kwic_annotation_risk_rows  # noqa: F401
from .grounding_facts import _kwic_facts  # noqa: F401
from .grounding_facts import _expanded_kwic_context_facts  # noqa: F401
from .grounding_facts import _lexical_diversity_facts  # noqa: F401
from .grounding_facts import _trend_facts  # noqa: F401
from .grounding_facts import _metric_row_facts  # noqa: F401
from .grounding_facts import _returned_metric_row_count_fact  # noqa: F401
from .grounding_facts import _docset_scope_facts  # noqa: F401
from .grounding_facts import _dispersion_facts  # noqa: F401
from .grounding_facts import _table_metric_facts  # noqa: F401
from .grounding_facts import _relation_metadata_facts  # noqa: F401
from .grounding_facts import _document_row_facts  # noqa: F401
from .grounding_facts import _metadata_available_fields_fact  # noqa: F401
from .grounding_facts import _metadata_value_facts  # noqa: F401
from .grounding_facts import _metadata_contract_boundary_facts  # noqa: F401
from .grounding_facts import _GOVERNANCE_METADATA_FIELD_PATTERN  # noqa: F401
from .grounding_facts import _UNRESOLVED_METADATA_VALUE_PATTERN  # noqa: F401
from .grounding_facts import _metadata_governance_limitation_facts  # noqa: F401
from .grounding_facts import _semantic_row_facts  # noqa: F401
from .grounding_facts import _semantic_visible_row_count_fact  # noqa: F401
from .grounding_facts import _compare_row_facts  # noqa: F401
from .grounding_facts import _contrast_row_facts  # noqa: F401
from .grounding_facts import _cluster_facts  # noqa: F401
from .grounding_facts import _cluster_label_fact  # noqa: F401
from .grounding_facts import _plan_facts  # noqa: F401
from .grounding_facts import _keyness_direction_contexts  # noqa: F401
from .grounding_facts import deterministic_observed_facts  # noqa: F401
from .grounding_facts import select_balanced_observed_facts  # noqa: F401
from .grounding_facts import select_synthesis_window  # noqa: F401
from .grounding_facts import synthese_fenster_kappe  # noqa: F401
from .grounding_facts import validate_observed_facts  # noqa: F401
from .grounding_facts import _SINGLE_LEXICAL_CQLF_QUERY_PATTERN  # noqa: F401
from .grounding_facts import _CQLF_SEQUENCE_DESCRIPTION_PATTERN  # noqa: F401
from .grounding_facts import _fact_cqlf_queries  # noqa: F401
from .grounding_facts import _misdescribed_multi_token_cqlf_query  # noqa: F401
from .grounding_facts import _exact_lexical_search  # noqa: F401
from .grounding_facts import _cqlf_query_scope_statement  # noqa: F401
from .grounding_facts import _requested_frequency_result_count  # noqa: F401
from .grounding_facts import _question_requests_kwic_table  # noqa: F401
from .grounding_facts import _question_term  # noqa: F401
from .grounding_facts import _COMPARABLE_METADATA_FIELDS  # noqa: F401
from .grounding_validation import validate_markdown_grounding  # noqa: F401
from .grounding_validation import validate_markdown_interpretation  # noqa: F401
from .grounding_validation import _response_requirement_equivalence_key  # noqa: F401
from .grounding_validation import _response_claim_substance  # noqa: F401
from .grounding_validation import resolve_equivalent_response_requirement_coverage  # noqa: F401
from .grounding_validation import validate_answer_envelope  # noqa: F401
from .grounding_validation import envelope_matches_deliverable_kind  # noqa: F401
from .grounding_validation import _claim_is_hypothesis  # noqa: F401
from .grounding_validation import missing_response_requirements  # noqa: F401
from .grounding_validation import response_requirements_complete  # noqa: F401
from .grounding_validation import _REQUIRED_CLAIM_KINDS_BY_DELIVERABLE  # noqa: F401
from .grounding_validation import _deterministic_result_surface_supplies_observation  # noqa: F401
from .grounding_validation import _observed_facts_supply_confirmation_boundary  # noqa: F401
from .grounding_validation import accepted_followups_have_research_breadth  # noqa: F401
from .grounding_validation import accepted_method_advice_addresses_quality_signals  # noqa: F401
from .grounding_validation import _has_exact_negative_method_conclusion  # noqa: F401
from .grounding_validation import _NGRAM_INTERPRETATION_REQUEST_PATTERN  # noqa: F401
from .grounding_validation import _NGRAM_NEGATIVE_ONLY_PATTERN  # noqa: F401
from .grounding_validation import _KWIC_LOCAL_READING_PATTERN  # noqa: F401
from .grounding_validation import _KWIC_COMMUNICATIVE_READING_PATTERN  # noqa: F401
from .grounding_validation import _KWIC_CONTEXT_BOUND_READING_PATTERN  # noqa: F401
from .grounding_validation import _KWIC_INTERPRETATION_REQUEST_PATTERN  # noqa: F401
from .grounding_validation import _KEYNESS_IDENTIFIER_INTERPRETATION_PATTERN  # noqa: F401
from .grounding_validation import _KEYNESS_VISIBLE_IDENTIFIER_PATTERN  # noqa: F401
from .grounding_validation import _KEYNESS_IDENTIFIER_DOMINANCE_PATTERN  # noqa: F401
from .grounding_validation import _claim_mentions_ngram_fact  # noqa: F401
from .grounding_validation import _claimed_ngram_terms  # noqa: F401
from .grounding_validation import _ngram_claim_is_negative_only  # noqa: F401
from .grounding_validation import _required_ngram_candidate_count  # noqa: F401
from .grounding_validation import accepted_ngram_interpretation_is_substantive  # noqa: F401
from .grounding_validation import _unsupported_multi_ngram_candidate_claim  # noqa: F401
from .grounding_validation import accepted_keyness_interpretation_is_substantive  # noqa: F401
from .grounding_validation import _expanded_kwic_context_text  # noqa: F401
from .grounding_validation import _kwic_claim_has_source_specific_anchor  # noqa: F401
from .grounding_validation import accepted_kwic_interpretation_is_substantive  # noqa: F401
from .grounding_validation import missing_word_sketch_profile_facts  # noqa: F401
from .grounding_validation import word_sketch_metric_units_are_clear  # noqa: F401
from .grounding_validation import accepted_word_sketch_profile_covers_visible_facts  # noqa: F401
from .grounding_validation import _WORD_SKETCH_PROFILE_SYNTHESIS_PATTERN  # noqa: F401
from .grounding_validation import accepted_word_sketch_interpretation_is_substantive  # noqa: F401
from .grounding_validation import _SEMANTIC_PATTERN_SYNTHESIS_REQUEST_PATTERN  # noqa: F401
from .grounding_validation import accepted_semantic_pattern_interpretation_is_substantive  # noqa: F401
from .grounding_validation import accepted_claims_match_deliverable  # noqa: F401

import logging as _logging

_LOGGER = _logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# Back-compat / discoverability re-export.
#
# The deterministic grounding flow is composed by ``GroundingPipeline`` in the
# sibling ``grounding_pipeline`` module (a thin, behaviour-preserving facade
# over the functions above). It is re-exported here so callers can discover the
# seam from the canonical grounding module.
#
# Resolved lazily via PEP 562 ``__getattr__`` rather than a top-level import,
# because ``grounding_pipeline`` imports FROM this module at load time; a direct
# import here would be a circular import whenever ``grounding_pipeline`` is the
# first of the pair to be imported.
# --------------------------------------------------------------------------- #
# K3 Slice 2: the markdown builders moved verbatim to
# ``grounding_markdown``. They are re-exported lazily through the same
# PEP 562 seam (controlled name re-export at module end), because
# ``grounding_markdown`` imports FROM this module at load time; an eager
# import here would be circular in one of the two import orders.
_GROUNDING_MARKDOWN_EXPORTS = frozenset(
    {
        "_PROVENANCE_LABELS",
        "_TECHNICAL_METADATA_FIELDS",
        "_analysis_execution_limitation_lines",
        "_analysis_provenance_lines",
        "_build_contrast_markdown",
        "_build_exploratory_markdown",
        "_build_followup_markdown",
        "_build_kwic_presence_markdown",
        "_build_metadata_capability_markdown",
        "_build_method_advice_markdown",
        "_build_semantic_markdown",
        "_build_term_frequency_markdown",
        "_build_term_profile_markdown",
        "_build_word_sketch_markdown",
        "_claim_repeats_lexical_diversity_metrics",
        "_claim_repeats_requested_collocation_rows",
        "_claim_repeats_requested_frequency_rows",
        "_claim_repeats_requested_kwic_row",
        "_claim_repeats_requested_ngram_rows",
        "_claim_repeats_semantic_candidate_row",
        "_coerce_number",
        "_direct_lexical_search_summary",
        "_directional_keyness_result_table",
        "_display_number",
        "_dominant_query_term",
        "_expanded_kwic_context_lines",
        "_kwic_text_from_row",
        "_markdown_cell",
        "_metadata_field_is_analytical",
        "_metadata_field_is_technical",
        "_metadata_value_list",
        "_requested_collocation_result_tables",
        "_requested_frequency_result_table",
        "_requested_kwic_result_table",
        "_requested_ngram_result_count",
        "_requested_ngram_result_table",
        "_retrieval_assessment_excerpt_lines",
        "_retrieval_assessment_exclusion_lines",
        "_retrieval_precision_note",
        "_safe_float",
        "_semantic_text_from_row",
        "_semantic_theme_labels_from_rows",
        "_semantic_theme_labels_from_texts",
        "_semantic_theme_terms_from_rows",
        "_semantic_theme_terms_from_texts",
        "_term_profile_context_labels",
        "_word_like_token",
        "blocked_claim_notes",
        "build_claim_preserving_grounded_markdown",
        "build_conservative_markdown",
        "build_grounded_markdown",
        "build_verified_claim_markdown",
        "evidence_manifest",
        "exact_zero_lexical_search",
        "grounded_fact_notes",
    }
)


def __getattr__(name: str) -> Any:  # pragma: no cover - thin lazy re-export
    if name in {"GroundingPipeline", "GroundingResult"}:
        from . import grounding_pipeline as _gp

        return getattr(_gp, name)
    if name in _GROUNDING_MARKDOWN_EXPORTS:
        from . import grounding_markdown as _gm

        return getattr(_gm, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
