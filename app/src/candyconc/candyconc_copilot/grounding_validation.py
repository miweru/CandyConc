"""Envelope/markdown validation layer (K3 Slice 3).

Verbatim move out of ``analysis_grounding``: markdown grounding checks,
response-requirement resolution, ``validate_answer_envelope`` with the
``claim_rules`` cascade, deliverable matching and the accepted-*
interpretation-substance checks. The full lower-layer import surface of
the facade is replicated here on purpose: ``validate_answer_envelope``
seeds the per-claim rule context from ``{**globals(), **locals()}``, so
this module's globals must offer every helper name the wrapper rules in
``claim_rules`` may read. ``analysis_grounding`` stays the facade and
re-exports every name.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Sequence

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

# Full observed-fact layer surface: needed both for direct calls below and
# for the rule-context seeding in validate_answer_envelope (see docstring).
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

import logging as _logging

_LOGGER = _logging.getLogger(__name__)


def validate_markdown_grounding(
    markdown: str,
    accepted_facts: Sequence[ObservedFact],
    *,
    allowed_context: Sequence[str] = (),
) -> List[str]:
    """Return the numeric/range/quote tokens in ``markdown`` that are NOT present
    in the grounding surface of ``accepted_facts``.

    This is the deterministic prose check that backs the 'pass' verdict: even when
    every structured claim is grounded, the free-text ``answer_markdown`` can still
    introduce a fabricated number/percentage/range/quote. Set membership (not
    substring) so "42" is not accepted merely because the evidence holds "1429".
    """
    surface = _joined_surface_text(
        [fact.statement for fact in accepted_facts]
        + [quote for fact in accepted_facts for quote in fact.grounding_quotes]
    )
    quote_surfaces = [
        line
        for fact in accepted_facts
        for line in [fact.statement, *fact.grounding_quotes]
        if str(line or "").strip()
    ]
    allowed_numbers = set(_extract_numeric_tokens(surface))
    allowed_ranges = set(_extract_ranges(surface))
    allowed_context_text = _joined_surface_text(list(allowed_context))

    unsupported: List[str] = []
    factual_markdown = _without_markdown_list_ordinals(markdown)
    analytical_markdown = _prose_outside_examples(factual_markdown)
    (
        unsupported_ratio_bindings,
        supported_ratio_factor_spans,
    ) = _ratio_comparison_binding_status(
        factual_markdown,
        accepted_facts,
    )
    unsupported_rate_bindings, supported_rate_value_spans = (
        _rate_binding_status(factual_markdown, accepted_facts)
    )
    unsupported_percent_bindings, supported_percent_value_spans = (
        _explicit_percent_binding_status(factual_markdown, accepted_facts)
    )
    percent_tokens = _numeric_percent_tokens(analytical_markdown)
    for token in _extract_numeric_tokens_outside_spans(
        factual_markdown,
        [
            *supported_ratio_factor_spans,
            *supported_rate_value_spans,
            *supported_percent_value_spans,
        ],
    ):
        if token in percent_tokens:
            supported = _percent_token_is_supported(token, surface)
        else:
            supported = _numeric_token_is_supported(token, allowed_numbers)
        if not supported:
            unsupported.append(token)
    unsupported.extend(unsupported_ratio_bindings)
    unsupported.extend(unsupported_rate_bindings)
    unsupported.extend(unsupported_percent_bindings)
    unsupported.extend(
        _unsupported_elliptical_count_bindings(
            factual_markdown,
            accepted_facts,
        )
    )
    unsupported.extend(
        _unsupported_postposed_count_bindings(
            factual_markdown,
            accepted_facts,
        )
    )
    unsupported.extend(
        _unsupported_unit_free_row_counts(
            factual_markdown,
            accepted_facts,
        )
    )
    if _normalised_time_trend_status(
        analytical_markdown,
        accepted_facts,
    ) is False:
        unsupported.append("relative Zeitentwicklung")
    if _generic_time_trend_status(
        analytical_markdown,
        accepted_facts,
    ) is False:
        unsupported.append("Zeitentwicklung")
    for rng in _extract_ranges(factual_markdown):
        if rng not in allowed_ranges and not _range_is_covered_by_numbers(
            rng,
            allowed_numbers,
        ):
            unsupported.append(rng)
    if _has_word_count_claim(markdown) and not any(
        "counts" in fact.supports_claims for fact in accepted_facts
    ):
        match = (
            next(
                (
                    candidate
                    for candidate in _WORD_COUNT_PATTERN.finditer(markdown)
                    if not _word_count_match_is_indefinite_article(
                        candidate,
                        markdown,
                    )
                ),
                None,
            )
            or _DOZEN_COUNT_PATTERN.search(markdown)
        )
        if match is not None:
            unsupported.append(match.group(0))
    unsupported.extend(
        _unsupported_count_bindings(analytical_markdown, surface)
    )
    unsupported.extend(
        _unsupported_word_percent_bindings(analytical_markdown, surface)
    )
    unsupported.extend(
        _unsupported_natural_metric_bindings(analytical_markdown, surface)
    )
    unsupported.extend(
        _unsupported_rate_denominator_bindings(
            analytical_markdown,
            surface,
        )
    )
    unsupported.extend(
        _unsupported_syntactic_role_claims(
            analytical_markdown,
            surface,
        )
    )
    unsupported.extend(
        _unsupported_presence_claims(
            analytical_markdown,
            accepted_facts,
        )
    )
    unsupported.extend(
        _unsupported_directional_scope_presence_claims(
            analytical_markdown,
            accepted_facts,
        )
    )
    unsupported.extend(
        _unsupported_partial_exhaustive_claims(
            analytical_markdown,
            accepted_facts,
        )
    )
    unsupported.extend(
        _unsupported_artifact_classifications(
            analytical_markdown,
            accepted_facts,
            question_text=allowed_context_text,
        )
    )
    unsupported.extend(
        _unsupported_pos_claims(analytical_markdown, surface)
    )
    unsupported.extend(
        _unsupported_tool_provenance_claims(
            analytical_markdown,
            accepted_facts,
        )
    )
    unsupported.extend(
        _unsupported_distribution_claims(analytical_markdown, surface)
    )
    unsupported.extend(
        _unsupported_dispersion_interpretations(
            analytical_markdown,
            accepted_facts,
        )
    )
    unsupported.extend(
        _unsupported_scope_design_claims(analytical_markdown, surface)
    )
    unsupported.extend(
        _unsupported_frequency_directions(
            analytical_markdown,
            accepted_facts,
        )
    )
    unsupported.extend(
        _unsupported_keyness_causal_attributions(
            analytical_markdown,
            accepted_facts,
        )
    )
    unsupported.extend(
        _unsupported_correlation_claims(analytical_markdown, surface)
    )
    unsupported.extend(
        _unsupported_field_assignments(analytical_markdown, surface)
    )
    for segment in _extract_grounding_example_segments(markdown):
        # Quotes are phrases, not numbers, so a case-insensitive containment test
        # is appropriate here (no number-substring hazard).
        if (
            not any(
                _quoted_segment_is_supported(segment, quote_surface)
                for quote_surface in quote_surfaces
            )
            and not _quote_is_user_scope_reference(
                segment,
                markdown,
                allowed_context_text,
            )
        ):
            unsupported.append(segment)
    # Stable de-dup preserving order.
    seen: set[str] = set()
    out: List[str] = []
    for item in unsupported:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


def validate_markdown_interpretation(
    markdown: str,
    accepted_facts: Sequence[ObservedFact],
) -> List[str]:
    """Return dominance/category phrases in ``markdown`` that lack an anchor.

    The ``pass`` path can return free-text prose that carries a categorising or
    dominance interpretation ("X ist dominant", "vor allem Y", "typisch für Z")
    that no observed fact authorises. ``validate_markdown_grounding`` only checks
    numbers/ranges/quotes, so such an interpretation slips through. This gate
    closes that hole deterministically: every ``_CATEGORY_PATTERN`` hit in the
    prose must be backed by at least one accepted fact that *both* carries an
    ``interpretation_anchor`` support tag *and* is itself exact (not a partial /
    sampled / derived fact). When no such anchor exists the matched phrase is
    flagged; a non-empty result downgrades the verdict to ``conservative_only``
    so the answer is rebuilt deterministically instead of asserting an
    unsupported dominance claim.
    """
    matches = [
        match.group(0).strip()
        for match in _CATEGORY_PATTERN.finditer(markdown or "")
    ]
    partial_evidence = any(
        fact.exactness in {"partial", "sample_only", "top_n_only", "derived"}
        for fact in accepted_facts
    )
    if partial_evidence and _has_definitive_global_scope_claim(markdown):
        matches.append("korpusweiter Geltungsanspruch")
    if not matches:
        return []
    anchored = any(
        "interpretation_anchor" in fact.supports_claims
        and fact.exactness not in {"partial", "sample_only", "top_n_only", "derived"}
        for fact in accepted_facts
    )
    if anchored and "korpusweiter Geltungsanspruch" not in matches:
        return []
    # Stable de-dup preserving order.
    seen: set[str] = set()
    out: List[str] = []
    for phrase in matches:
        key = phrase.lower()
        if phrase and key not in seen:
            seen.add(key)
            out.append(phrase)
    return out


def _response_requirement_equivalence_key(
    requirement: ResponseRequirement,
) -> tuple[str, str, str, tuple[str, ...]]:
    """Identify repeated user duties independently of their bookkeeping ID."""

    return (
        requirement.claim_kind,
        _normalised_question_text(requirement.description),
        _normalised_question_text(requirement.source_quote),
        tuple(
            _normalised_question_text(check)
            for check in requirement.completion_checks()
        ),
    )


def _response_claim_substance(claim: ClaimDraft) -> tuple[str, str]:
    return (
        " ".join(str(claim.text or "").casefold().split()),
        str(claim.claim_kind or "observation"),
    )


def resolve_equivalent_response_requirement_coverage(
    envelope: AnswerEnvelope,
    accepted_claim_ids: Sequence[str],
    response_requirements: Sequence[Any],
) -> Dict[str, str]:
    """Assign repeated response slots from verified claim substance.

    Counted duties such as "three steps" become equivalent slots with distinct
    internal IDs.  Models frequently repeat or omit those IDs even when all
    requested content is present.  IDs therefore act only as a preference:
    accepted, structurally eligible, distinct claims are assigned one-to-one.
    Heterogeneous duties remain untouched and ambiguous assignments fail closed.

    The return value contains accepted claims that exceed the repeated group's
    cardinality or duplicate another claim's visible substance.
    """

    requirements = normalise_response_requirements(
        list(response_requirements or [])
    )
    groups: Dict[
        tuple[str, str, str, tuple[str, ...]],
        List[ResponseRequirement],
    ] = {}
    for requirement in requirements:
        groups.setdefault(
            _response_requirement_equivalence_key(requirement), []
        ).append(requirement)
    repeated_groups = [
        group for group in groups.values() if len(group) > 1
    ]
    if not repeated_groups:
        return {}

    group_by_requirement_id = {
        requirement.id: group
        for group in repeated_groups
        for requirement in group
    }
    groups_by_claim_kind: Dict[str, List[List[ResponseRequirement]]] = {}
    for group in repeated_groups:
        groups_by_claim_kind.setdefault(group[0].claim_kind, []).append(group)

    accepted = set(accepted_claim_ids)
    overflow: Dict[str, str] = {}
    for group in repeated_groups:
        requirement_ids = [item.id for item in group]
        requirement_id_set = set(requirement_ids)
        representative = group[0]
        cardinality = _counted_response_cardinality(
            " ".join(
                part
                for part in (
                    representative.source_quote,
                    representative.description,
                )
                if str(part or "").strip()
            )
        )
        maximum = cardinality[1] if cardinality is not None else len(group)
        candidates: List[
            tuple[int, ClaimDraft, List[str], tuple[str, str]]
        ] = []
        for position, claim in enumerate(envelope.claims):
            if (
                claim.id not in accepted
                or claim.claim_kind != representative.claim_kind
            ):
                continue
            current_id = str(claim.response_requirement_id or "").strip()
            completion_reasons = _response_requirement_condition_reasons(
                claim.text,
                representative,
                assertion_level=claim.assertion_level,
            )
            associated = current_id in requirement_id_set
            if not associated:
                # Empty or provider-invented IDs are safe to repair only when
                # this claim kind has one unambiguous repeated duty and the
                # claim structurally is one of its units. In particular, a
                # standalone interpretation must not become a third hypothesis
                # merely because hypotheses also use claim_kind interpretation.
                requirement_surface = " ".join(
                    part
                    for part in (
                        representative.description,
                        representative.source_quote,
                    )
                    if str(part or "").strip()
                )
                structurally_same_unit = not (
                    _RESPONSE_REQUIREMENT_HYPOTHESIS_PATTERN.search(
                        requirement_surface
                    )
                ) or bool(
                    claim.assertion_level == "tentative"
                    and _RESPONSE_CLAIM_HYPOTHESIS_PATTERN.search(
                        claim.text or ""
                    )
                )
                associated = bool(
                    current_id not in group_by_requirement_id
                    and len(groups_by_claim_kind.get(claim.claim_kind, [])) == 1
                    and structurally_same_unit
                )
            if not associated:
                continue
            candidates.append(
                (
                    position,
                    claim,
                    completion_reasons,
                    _response_claim_substance(claim),
                )
            )

        # Complete claims get the finite slots before incomplete repair cores;
        # original answer order remains stable within each class.
        candidates.sort(key=lambda item: (bool(item[2]), item[0]))
        used_ids: set[str] = set()
        used_substance: set[tuple[str, str]] = set()
        pending: List[tuple[ClaimDraft, List[str], tuple[str, str]]] = []
        for _position, claim, completion_reasons, substance in candidates:
            current_id = str(claim.response_requirement_id or "").strip()
            if substance in used_substance:
                claim.response_requirement_id = ""
                overflow[claim.id] = (
                    "Ein gezählter Antwortslot braucht eigenständige "
                    "Substanz; dieser Claim wiederholt einen bereits "
                    "berücksichtigten Antwortbestandteil."
                )
                continue
            if current_id in requirement_id_set and current_id not in used_ids:
                claim.response_requirement_id = current_id
                claim._response_requirement_completion_reasons = list(
                    completion_reasons
                )
                claim._response_requirement_assignment_reasons = list(
                    completion_reasons
                )
                used_ids.add(current_id)
                used_substance.add(substance)
                continue
            pending.append((claim, completion_reasons, substance))

        missing_ids = [
            requirement_id
            for requirement_id in requirement_ids
            if requirement_id not in used_ids
        ]
        for claim, completion_reasons, substance in pending:
            if not missing_ids:
                if maximum is None or len(used_substance) < maximum:
                    claim.response_requirement_id = ""
                    claim._response_requirement_completion_reasons = list(
                        completion_reasons
                    )
                    claim._response_requirement_assignment_reasons = list(
                        completion_reasons
                    )
                    used_substance.add(substance)
                    continue
                claim.response_requirement_id = ""
                overflow[claim.id] = (
                    "Der Claim überschreitet die ausdrücklich verlangte "
                    "Anzahl eigenständiger Antwortbestandteile."
                )
                continue
            requirement_id = missing_ids.pop(0)
            claim.response_requirement_id = requirement_id
            claim._response_requirement_completion_reasons = list(
                completion_reasons
            )
            claim._response_requirement_assignment_reasons = list(
                completion_reasons
            )
            used_ids.add(requirement_id)
            used_substance.add(substance)
    return overflow


def validate_answer_envelope(
    envelope: AnswerEnvelope,
    observed_facts: Sequence[ObservedFact],
    *,
    forbidden_claims: Sequence[str] | None = None,
    question_text: str = "",
    deliverable_kind: str = "",
    analysis_family: str = "",
    response_requirements: Sequence[Any] = (),
) -> tuple[List[str], List[str], Dict[str, List[str]]]:
    """Validate the envelope's claims against the observed facts.

    Severity-Politik (Produktentscheid 2026-08): ein Claim wird nur noch
    ZURUECKGEWIESEN, wenn eine HARTE Regel anschlaegt (Fabrikationsklassen,
    siehe ``claim_rules.HARD_RULE_NAMES``) oder seine ``fact_ids`` nicht
    aufloesbar sind. Befunde ADVISORY-eingestufter Regeln blockieren nicht:
    der Claim bleibt akzeptiert und die Begruendungen werden als
    Annotationen in ``envelope.advisories`` (claim_id -> Liste) abgelegt,
    damit nachgelagerte Schichten sie an die UI durchreichen koennen.

    Rueckgabe unveraendert ``(accepted, rejected, reasons)``; ``rejected``
    und ``reasons`` enthalten ausschliesslich harte Befunde, wodurch
    Repair-/Verifier-Schleifen nur noch bei Fabrikation anspringen.
    """

    fact_index = {fact.id: fact for fact in observed_facts}
    if len(fact_index) != len(observed_facts):
        # Colliding fact ids mean a claim could validate against the wrong row.
        # _compact_id makes ids collision-resistant; a residual collision is a bug.
        _LOGGER.warning(
            "validate_answer_envelope: %d observed facts collapsed to %d unique ids "
            "(fact-id collision) — claims may resolve to the wrong fact.",
            len(observed_facts), len(fact_index),
        )
    accepted: List[str] = []
    rejected: List[str] = []
    reasons: Dict[str, List[str]] = {}
    advisories: Dict[str, List[str]] = {}
    forbidden_claims = list(forbidden_claims or [])
    requirement_by_id = {
        requirement.id: requirement
        for requirement in normalise_response_requirements(
            list(response_requirements or [])
        )
    }
    normalized_requirements = list(requirement_by_id.values())
    metadata_value_counts = _metadata_value_counts(observed_facts)
    question_term = _question_term(question_text)
    anomalies_by_fact = (
        _pos_filtered_handle_anomalies(observed_facts)
        if deliverable_kind == "followup_questions"
        else {}
    )
    method_step_positions = {
        claim.id: index
        for index, claim in enumerate(
            [
                candidate
                for candidate in envelope.claims
                if candidate.claim_kind == "interpretation"
            ],
            start=1,
        )
    }
    accepted_followup_texts: List[str] = []
    expanded_kwic_fact_ids = {
        fact.id
        for fact in observed_facts
        if fact.fact_kind == "kwic_example"
        and "erweiter" in fact.statement.casefold()
        and "kontext" in fact.statement.casefold()
    }
    for claim in envelope.claims:
        # Validation may run more than once on a retained claim.  Clear the
        # private slot diagnostics so an earlier attempt cannot leak into the
        # current decision.
        claim._response_requirement_assignment_reasons = []
        claim._response_requirement_completion_reasons = []
        claim._unfulfilled_response_requirement_id = ""
        claim.advisories = []
        if not claim.fact_ids or any(fact_id not in fact_index for fact_id in claim.fact_ids):
            rejected.append(claim.id)
            reasons[claim.id] = ["Claim ohne gültige fact_ids."]
            continue
        facts = [fact_index[fact_id] for fact_id in claim.fact_ids]
        quote_surfaces = [
            line
            for fact in facts
            for line in [fact.statement, *fact.grounding_quotes]
            if str(line or "").strip()
        ]
        source_evidence_ids = {
            source_id
            for fact in facts
            for source_id in fact.source_evidence_ids
            if source_id
        }
        fact_provenance_sets = {
            frozenset(
                source_id
                for source_id in fact.source_evidence_ids
                if source_id
            )
            for fact in facts
        }
        cross_source_fact_mix = bool(
            len(facts) > 1
            and len(source_evidence_ids) > 1
            and len(fact_provenance_sets) > 1
        )
        source_surface = _joined_surface_text(
            [fact.statement for fact in facts]
            + [quote for fact in facts for quote in fact.grounding_quotes]
        )
        analytical_prose = _prose_outside_examples(claim.text)
        normalised_time_trend_status = _normalised_time_trend_status(
            analytical_prose,
            facts,
        )
        generic_time_trend_status = _generic_time_trend_status(
            analytical_prose,
            facts,
        )
        # Tokenised number/range sets for membership tests (not substring, which
        # would accept a fabricated "42" inside an evidence "1429").
        allowed_numbers = set(_extract_numeric_tokens(source_surface))
        allowed_ranges = set(_extract_ranges(source_surface))
        claim_reasons: List[str] = []
        response_requirement_id = str(
            getattr(claim, "response_requirement_id", "") or ""
        ).strip()
        response_assignment_reasons: List[str] = []
        response_completion_reasons: List[str] = []
        # K3 Slice 2 (step 3): the per-claim rule cascade moved verbatim
        # into ``claim_rules`` wrapper rules. CLAIM_RULE_REGISTRY keeps the
        # exact original evaluation order; every rule receives the full
        # local context (module globals + per-claim locals) and writes any
        # name it (re)binds back into the context for later rules.
        #
        # Severity-Split: jede Regel laeuft weiterhin (spaetere Regeln lesen
        # Namen, die fruehere binden), aber ihre Befunde werden per
        # Laengen-Snapshot der geteilten ``claim_reasons``-Liste der Regel
        # zugeordnet und nach Registry-Severity getrennt. Nur harte Befunde
        # weisen den Claim zurueck; advisory-Befunde werden als Annotationen
        # gesammelt und blockieren nicht.
        _vae_ctx = {**globals(), **locals()}
        hard_claim_reasons: List[str] = []
        advisory_claim_reasons: List[str] = []
        for _vae_rule_entry in CLAIM_RULE_REGISTRY:
            _reasons_before = len(_vae_ctx["claim_reasons"])
            _vae_rule_entry[1](_vae_ctx)
            _appended_reasons = list(
                _vae_ctx["claim_reasons"][_reasons_before:]
            )
            if not _appended_reasons:
                continue
            if _vae_rule_entry[3] == "hard":
                hard_claim_reasons.extend(_appended_reasons)
            else:
                advisory_claim_reasons.extend(_appended_reasons)
        claim.advisories = list(advisory_claim_reasons)
        if advisory_claim_reasons:
            advisories[claim.id] = advisory_claim_reasons
        if hard_claim_reasons:
            rejected.append(claim.id)
            reasons[claim.id] = hard_claim_reasons
            continue
        accepted.append(claim.id)
        if claim.claim_kind == "followup":
            accepted_followup_texts.append(claim.text)

    coverage_rejections = resolve_equivalent_response_requirement_coverage(
        envelope,
        accepted,
        normalized_requirements,
    )
    if coverage_rejections:
        coverage_rejection_ids = set(coverage_rejections)
        accepted = [
            claim_id
            for claim_id in accepted
            if claim_id not in coverage_rejection_ids
        ]
        for claim in envelope.claims:
            if claim.id not in coverage_rejections:
                continue
            if claim.id not in rejected:
                rejected.append(claim.id)
            reasons[claim.id] = [coverage_rejections[claim.id]]

    # Advisory-Annotationen am Envelope durchreichen (claim_id -> Befunde),
    # damit Verdict/UI sie anzeigen koennen, ohne dass sie blockieren.
    envelope.advisories = advisories
    return accepted, rejected, reasons


def envelope_matches_deliverable_kind(
    envelope: AnswerEnvelope,
    *,
    deliverable_kind: str,
    question_text: str = "",
) -> tuple[bool, str]:
    if _HYPOTHESIS_STRUCTURE_CONDITION_PATTERN.search(question_text or ""):
        observations = [
            claim
            for claim in envelope.claims
            if claim.claim_kind == "observation"
        ]
        hypotheses = [
            claim for claim in envelope.claims if _claim_is_hypothesis(claim)
        ]
        interpretations = [
            claim
            for claim in envelope.claims
            if claim.claim_kind == "interpretation"
            and not _claim_is_hypothesis(claim)
        ]
        missing_sections = [
            label
            for label, values in (
                ("Beobachtung", observations),
                ("Interpretation", interpretations),
                ("Hypothese", hypotheses),
            )
            if not values
        ]
        if missing_sections:
            return (
                False,
                "Die ausdrücklich verlangte Trennung ist unvollständig; es "
                "fehlt mindestens ein eigenständiger Claim für: "
                + ", ".join(missing_sections)
                + ".",
            )
    if deliverable_kind == "followup_questions":
        required_count = (
            _requested_followup_question_count(question_text) or 3
        )
        followup_count = sum(
            claim.claim_kind == "followup" for claim in envelope.claims
        )
        if followup_count >= required_count:
            return True, ""
        return (
            False,
            "Der Antworttyp verlangt mindestens "
            f"{required_count} konkrete, evidenzmotivierte "
            f"Anschlussfragen; enthalten sind {followup_count}.",
        )
    if deliverable_kind == "overview":
        observation_count = sum(
            claim.claim_kind == "observation" for claim in envelope.claims
        )
        interpretation_count = sum(
            claim.claim_kind == "interpretation" for claim in envelope.claims
        )
        if observation_count >= 1 and interpretation_count >= 1:
            return True, ""
        if observation_count < 1:
            return (
                False,
                "Ein Forschungsüberblick braucht mindestens eine konkrete, "
                "belegte Beobachtung.",
            )
        return (
            False,
            "Ein Forschungsüberblick verlangt zusätzlich mindestens eine "
            "vorsichtig evidenzgebundene Interpretation.",
        )
    if deliverable_kind == "method_advice":
        requested_steps = _requested_method_step_count(question_text)
        advice_count = sum(
            claim.claim_kind == "interpretation" for claim in envelope.claims
        )
        if requested_steps is not None and advice_count == requested_steps:
            return True, ""
        if requested_steps:
            return (
                False,
                "Die Nutzerfrage verlangt genau "
                f"{requested_steps} getrennte Analyseschritte; enthalten sind "
                f"{advice_count}.",
            )
        if advice_count >= 1:
            return True, ""
        return False, "Methodische Beratung verlangt mindestens einen konkreten Schritt."
    return True, ""


def _claim_is_hypothesis(claim: ClaimDraft) -> bool:
    return bool(
        claim.claim_kind == "interpretation"
        and (
            _HYPOTHESIS_PROPOSAL_PATTERN.search(claim.text or "")
            or (
                claim.assertion_level == "tentative"
                and _RESPONSE_CLAIM_HYPOTHESIS_PATTERN.search(
                    claim.text or ""
                )
            )
        )
    )


def missing_response_requirements(
    envelope: AnswerEnvelope,
    accepted_claim_ids: Sequence[str],
    rejected_claim_ids: Sequence[str],
    response_requirements: Sequence[Any],
) -> List[ResponseRequirement]:
    requirements = normalise_response_requirements(
        list(response_requirements or [])
    )
    if not requirements:
        return []
    accepted = set(accepted_claim_ids) - set(rejected_claim_ids)
    resolve_equivalent_response_requirement_coverage(
        envelope,
        list(accepted),
        requirements,
    )
    requirement_by_id = {item.id: item for item in requirements}
    fulfilled: set[str] = set()
    eligible_by_requirement: Dict[str, List[tuple[str, str]]] = {
        requirement.id: [] for requirement in requirements
    }
    used_substance: set[tuple[str, str]] = set()
    for claim in envelope.claims:
        if claim.id not in accepted or not claim.response_requirement_id:
            continue
        requirement = requirement_by_id.get(claim.response_requirement_id)
        if requirement is None or requirement.claim_kind != claim.claim_kind:
            continue
        if list(
            getattr(
                claim,
                "_response_requirement_assignment_reasons",
                [],
            )
            or []
        ):
            continue
        if (
            _RESPONSE_REQUIREMENT_ANNOUNCEMENT_PATTERN.search(claim.text or "")
            or _RESPONSE_REQUIREMENT_HEADING_PATTERN.search(claim.text or "")
        ):
            continue
        substance = (
            " ".join(str(claim.text or "").casefold().split()),
            claim.claim_kind,
        )
        eligible_by_requirement[requirement.id].append(substance)
    for requirement in requirements:
        # MEHR ABDECKUNG IST NICHT WENIGER. Die Bedingung lautete
        # ``len(candidates) != 1``: genau ein deckender Claim erfuellte die
        # Pflicht, zwei oder drei liessen sie als UNERFUELLT gelten.
        # Nachgemessen am 2026-08-28: 0 -> nein, 1 -> ja, 2 -> nein,
        # 3 -> nein.
        #
        # Das ist nicht nur falsch, es treibt die Schleife: eine unerfuellte
        # Pflicht laesst _accepted_claims_complete scheitern, das Tor setzt
        # verdict auf retry, und die ganze Antwort wird neu synthetisiert,
        # zuletzt gemessen sieben Mal zu je rund 360 Sekunden. Das Modell
        # schrieb also eine BESSER gedeckte Antwort und bekam dafuer eine
        # Neuschrift.
        #
        # ``used_substance`` bleibt unangetastet: ein und derselbe Claim
        # darf weiterhin nicht zwei Pflichten decken. Deshalb wird der
        # erste noch UNVERBRAUCHTE Kandidat genommen, nicht blind der
        # erste: sonst bliebe eine Pflicht offen, obwohl ein freier Claim
        # sie deckt.
        for substance in eligible_by_requirement[requirement.id]:
            if substance in used_substance:
                continue
            used_substance.add(substance)
            fulfilled.add(requirement.id)
            break
    return [
        requirement
        for requirement in requirements
        if requirement.id not in fulfilled
    ]


def response_requirements_complete(
    envelope: AnswerEnvelope,
    accepted_claim_ids: Sequence[str],
    rejected_claim_ids: Sequence[str],
    response_requirements: Sequence[Any],
) -> tuple[bool, str]:
    missing = missing_response_requirements(
        envelope,
        accepted_claim_ids,
        rejected_claim_ids,
        response_requirements,
    )
    if not missing:
        return True, ""
    return (
        False,
        "Die verifizierte Antwort lässt ausdrücklich verlangte "
        "Antwortbestandteile aus: "
        + "; ".join(
            f"{item.id}: {item.description}" for item in missing
        )
        + ".",
    )


_REQUIRED_CLAIM_KINDS_BY_DELIVERABLE = {
    "analysis_report": {"observation", "interpretation"},
    "contrast_report": {"observation", "interpretation"},
    "overview": {"observation", "interpretation"},
    "method_advice": {"interpretation"},
    "followup_questions": {"followup"},
    "lookup_answer": {"observation"},
}


def _deterministic_result_surface_supplies_observation(
    observed_facts: Sequence[ObservedFact],
    *,
    question_text: str = "",
) -> bool:
    """Avoid asking the model to prose-paraphrase tables rendered from facts."""

    has_ngram_rows = any(
        fact.fact_kind == "ranked_row"
        and any(
            "ngram_frequency" in str(source_id or "").casefold()
            for source_id in fact.source_evidence_ids
        )
        for fact in observed_facts
    )
    has_lexical_metrics = any(
        fact.fact_kind == "distribution"
        and re.search(
            r"\bttr\s*=.*\bsttr\s*=.*\bmattr\s*=",
            _joined_surface_text([fact.statement, *fact.grounding_quotes]),
            re.IGNORECASE,
        )
        for fact in observed_facts
    )
    has_expanded_kwic = any(
        fact.fact_kind == "kwic_example"
        and "erweiter" in fact.statement.casefold()
        and "kontext" in fact.statement.casefold()
        for fact in observed_facts
    )
    has_semantic_retrieval_rows = any(
        fact.fact_kind == "kwic_example"
        and any(
            "semantic_search" in str(source_id or "").casefold()
            or "transformer_search" in str(source_id or "").casefold()
            for source_id in fact.source_evidence_ids
        )
        for fact in observed_facts
    )
    has_requested_frequency_rows = bool(
        _requested_frequency_result_count(question_text) is not None
        and any(
            fact.fact_kind == "ranked_row"
            and any(
                "frequency_list" in str(source_id or "").casefold()
                for source_id in fact.source_evidence_ids
            )
            for fact in observed_facts
        )
    )
    has_requested_kwic_rows = bool(
        _question_requests_kwic_table(question_text)
        and any(
            fact.fact_kind == "kwic_example"
            and any(
                "run_cqlf_query" in str(source_id or "").casefold()
                or "kwic" in str(source_id or "").casefold()
                for source_id in fact.source_evidence_ids
            )
            for fact in observed_facts
        )
    )
    has_requested_collocation_rows = bool(
        re.search(r"\bkollokat\w*\b", question_text or "", re.IGNORECASE)
        and any(
            fact.fact_kind == "ranked_row"
            and any(
                "collocate_stats" in str(source_id or "").casefold()
                for source_id in fact.source_evidence_ids
            )
            for fact in observed_facts
        )
    )
    return (
        has_ngram_rows
        or has_lexical_metrics
        or has_expanded_kwic
        or has_semantic_retrieval_rows
        or has_requested_frequency_rows
        or has_requested_kwic_rows
        or has_requested_collocation_rows
    )


def _observed_facts_supply_confirmation_boundary(
    observed_facts: Sequence[ObservedFact],
) -> bool:
    """A bounded semantic result already proves the universal-scope caveat."""

    return any(
        fact.fact_kind == "limitation"
        and any(
            "semantic_search" in str(source_id or "").casefold()
            or "transformer_search" in str(source_id or "").casefold()
            for source_id in fact.source_evidence_ids
        )
        for fact in observed_facts
    )


def accepted_followups_have_research_breadth(
    envelope: AnswerEnvelope,
    accepted_claim_ids: Sequence[str],
    rejected_claim_ids: Sequence[str],
    *,
    question_text: str = "",
) -> bool:
    if (
        _DATA_QUALITY_METHOD_PATTERN.search(question_text or "")
        and _PRIMARY_DATA_QUALITY_FOLLOWUP_PATTERN.search(
            question_text or ""
        )
    ):
        return True
    accepted = set(accepted_claim_ids) - set(rejected_claim_ids)
    followups = [
        claim
        for claim in envelope.claims
        if claim.id in accepted and claim.claim_kind == "followup"
    ]
    required_count = _requested_followup_question_count(question_text) or 3
    if required_count < 3:
        return True
    quality_count = sum(
        _is_primary_data_quality_followup(claim)
        for claim in followups
    )
    return quality_count <= 1 and len(followups) - quality_count >= 2


def accepted_method_advice_addresses_quality_signals(
    envelope: AnswerEnvelope,
    accepted_claim_ids: Sequence[str],
    rejected_claim_ids: Sequence[str],
    observed_facts: Sequence[ObservedFact],
) -> bool:
    """Require visible annotation/accounting anomalies to precede interpretation."""

    signal_fact_ids = set(_pos_filtered_handle_anomalies(observed_facts))
    for fact in observed_facts:
        for quote in fact.grounding_quotes:
            match = re.fullmatch(
                r"denominator_minus_pos_sum=(-?\d+)",
                str(quote or "").strip(),
                re.IGNORECASE,
            )
            if match is not None and int(match.group(1)) != 0:
                signal_fact_ids.add(fact.id)
                break
    if not signal_fact_ids:
        return True

    accepted = set(accepted_claim_ids) - set(rejected_claim_ids)
    return any(
        claim.id in accepted
        and signal_fact_ids.intersection(claim.fact_ids)
        and _DATA_QUALITY_METHOD_PATTERN.search(claim.text or "")
        and (
            _PRIMARY_DATA_QUALITY_FOLLOWUP_PATTERN.search(
                claim.text or ""
            )
            or _SYSTEMATIC_DATA_QUALITY_PATTERN.search(
                claim.text or ""
            )
        )
        for claim in envelope.claims
    )


def _has_exact_negative_method_conclusion(
    claims: Sequence[ClaimDraft],
    observed_facts: Sequence[ObservedFact],
) -> bool:
    """Recognise a complete negative method result without forcing two labels."""

    fact_index = {fact.id: fact for fact in observed_facts}
    for claim in claims:
        linked_facts = [
            fact_index[fact_id]
            for fact_id in claim.fact_ids
            if fact_id in fact_index
        ]
        if (
            linked_facts
            and all(
                fact.fact_kind == "negative_result"
                and fact.exactness == "exact"
                for fact in linked_facts
            )
            and _NEGATIVE_METHOD_CONCLUSION_PATTERN.search(
                claim.text or ""
            )
            and not _has_positive_extra_clause(claim.text or "")
        ):
            return True
    return False


_NGRAM_INTERPRETATION_REQUEST_PATTERN = re.compile(
    r"\b(?:formulierungsroutine\w*|formelhaft\w*|phraseolog\w*|"
    r"routinenkandidat\w*|routine\w*\s+prüfenswert\w*)\b",
    re.IGNORECASE,
)
_NGRAM_NEGATIVE_ONLY_PATTERN = re.compile(
    r"\b(?:kein(?:e|en|er|es)?|nicht)\b[^.!?\n]{0,80}"
    r"\b(?:kandidat\w*|routine\w*|hypothese\w*)\b",
    re.IGNORECASE,
)
_KWIC_LOCAL_READING_PATTERN = re.compile(
    r"\b(?:lesart\w*|bedeutungsbeitrag\w*|geltungsbeitrag\w*|"
    r"verort\w*|lokalisier\w*|lokalität\w*|lokalitaet\w*|"
    r"geograph\w*|räumlich\w*|raeumlich\w*|"
    r"bezugsrahmen\w*|rahmenbeitrag\w*|anbindung\w*|bindung\w*|"
    r"bezug\w*|zuordnung\w*|zugehörig\w*|zugehoerig\w*|"
    r"modifizier\w*|adverbial\w*|adjunkt\w*|"
    r"präpositional\w*|praepositional\w*|reading\w*|locative\w*|"
    r"modifier\w*|prepositional\w*|attachment\w*|reference\w*)\b",
    re.IGNORECASE,
)
_KWIC_COMMUNICATIVE_READING_PATTERN = re.compile(
    r"\b(?:vorwurf\w*|kritik\w*|kritisier\w*|beschuldig\w*|"
    r"bewertung\w*|wertend\w*|warnung\w*|frage\w*|aufforder\w*|"
    r"zurückweis\w*|zurueckweis\w*|accus\w*|critic\w*|evaluat\w*|"
    r"warning\w*|question\w*|request\w*|rejection\w*)\b",
    re.IGNORECASE,
)
_KWIC_CONTEXT_BOUND_READING_PATTERN = re.compile(
    r"\b(?:satz\w*|text\w*|beleg\w*|kontext\w*|aussage\w*|"
    r"äußerung\w*|aeusserung\w*|passage\w*|excerpt\w*|utterance\w*|"
    r"sentence\w*|context\w*)\b",
    re.IGNORECASE,
)
_KWIC_INTERPRETATION_REQUEST_PATTERN = re.compile(
    r"\b(?:analysier\w*|interpretier\w*|deut\w*|einordn\w*|"
    r"analyse\w*|interpret\w*|explain\w*)\b",
    re.IGNORECASE,
)
_KEYNESS_IDENTIFIER_INTERPRETATION_PATTERN = re.compile(
    r"\b(?:handle\w*|account\w*|nutzer\w*|profil\w*|quelle\w*|"
    r"sampling\w*|stichprob\w*|zusammensetz\w*|verarbeit\w*|"
    r"annotat\w*|label\w*|technisch\w*|plattform\w*|thread\w*|"
    r"dokumentdispersion\w*|dispersion\w*|konzentrat\w*)\b",
    re.IGNORECASE,
)
_KEYNESS_VISIBLE_IDENTIFIER_PATTERN = re.compile(
    r"\b(?:sichtbar\w*|ausschnitt\w*|zeil\w*|spitz\w*|ergebnis\w*|"
    r"muster\w*)\b",
    re.IGNORECASE,
)
_KEYNESS_IDENTIFIER_DOMINANCE_PATTERN = re.compile(
    r"\b(?:dominier\w*|überwieg\w*|ueberwieg\w*|mehrheit\w*|"
    r"hauptsächlich\w*|hauptsaechlich\w*|größtenteils\w*|"
    r"groesstenteils\w*|vor\s+allem|"
    r"getragen\w*|prägen\w*|praegen\w*|häuf\w*|haeuf\w*)\b",
    re.IGNORECASE,
)


def _claim_mentions_ngram_fact(
    claim: ClaimDraft,
    fact_index: Dict[str, ObservedFact],
) -> bool:
    claim_text = " ".join((claim.text or "").split()).casefold()
    for fact_id in claim.fact_ids:
        fact = fact_index.get(fact_id)
        if fact is None or fact.fact_kind != "ranked_row":
            continue
        if "interpretation_anchor" not in fact.supports_claims:
            continue
        if any(term.casefold() in claim_text for term in _ngram_surface_terms(fact)):
            return True
    return False


def _claimed_ngram_terms(
    claim: ClaimDraft,
    fact_index: Dict[str, ObservedFact],
) -> set[str]:
    claim_text = " ".join((claim.text or "").split()).casefold()
    return {
        term.casefold()
        for fact_id in claim.fact_ids
        for fact in [fact_index.get(fact_id)]
        if fact is not None and fact.fact_kind == "ranked_row"
        for term in _ngram_surface_terms(fact)
        if term.casefold() in claim_text
    }


def _ngram_claim_is_negative_only(
    claim: ClaimDraft,
    fact_index: Dict[str, ObservedFact],
) -> bool:
    text = " ".join((claim.text or "").split()).casefold()
    for term in sorted(
        _claimed_ngram_terms(claim, fact_index),
        key=len,
        reverse=True,
    ):
        text = text.replace(term, " ")
    return _NGRAM_NEGATIVE_ONLY_PATTERN.search(text) is not None


def _required_ngram_candidate_count(
    observed_facts: Sequence[ObservedFact],
) -> int:
    visible_terms = {
        term.casefold()
        for fact in observed_facts
        if fact.fact_kind == "ranked_row"
        for term in _ngram_surface_terms(fact)
    }
    return min(3, len(visible_terms))


def accepted_ngram_interpretation_is_substantive(
    claims: Sequence[ClaimDraft],
    observed_facts: Sequence[ObservedFact],
) -> bool:
    interpretations = [
        claim for claim in claims if claim.claim_kind == "interpretation"
    ]
    fact_index = {fact.id: fact for fact in observed_facts}
    candidate_terms: set[str] = set()
    for claim in interpretations:
        terms = _claimed_ngram_terms(claim, fact_index)
        if (
            len(terms) == 1
            and _NGRAM_HYPOTHESIS_PATTERN.search(claim.text or "")
            and _NGRAM_EPISTEMIC_PATTERN.search(claim.text or "")
            and not _ngram_claim_is_negative_only(claim, fact_index)
        ):
            candidate_terms.update(terms)
    required_candidates = _required_ngram_candidate_count(observed_facts)
    return bool(
        required_candidates > 0
        and len(candidate_terms) >= required_candidates
        and _NGRAM_VALIDATION_PATTERN.search(
            " ".join(claim.text for claim in interpretations)
        )
    )


def _unsupported_multi_ngram_candidate_claim(
    claim: ClaimDraft,
    facts: Sequence[ObservedFact],
) -> bool:
    fact_index = {fact.id: fact for fact in facts}
    terms = _claimed_ngram_terms(claim, fact_index)
    return bool(
        len(terms) > 1
        and _NGRAM_HYPOTHESIS_PATTERN.search(claim.text or "")
        and _NGRAM_EPISTEMIC_PATTERN.search(claim.text or "")
    )


def accepted_keyness_interpretation_is_substantive(
    claims: Sequence[ClaimDraft],
    observed_facts: Sequence[ObservedFact],
) -> bool:
    """Require a concrete reading when visible keyness is identifier-dominated."""

    for claim in claims:
        for sentence in re.split(r"(?<=[.!?])\s+|\n+", claim.text or ""):
            direction_match = _KEYNESS_DIRECTION_GROUP_PATTERN.search(sentence)
            if (
                direction_match is None
                or _UNIVERSAL_ABSENCE_PATTERN.search(sentence) is None
            ):
                continue
            direction = direction_match.group("direction").casefold()
            for fact in observed_facts:
                if fact.fact_kind != "ranked_row":
                    continue
                surface = _joined_surface_text(
                    [fact.statement, *fact.grounding_quotes]
                )
                fact_directions = {
                    value.casefold()
                    for value in _source_values_for_field("direction", surface)
                }
                if fact_directions != {direction}:
                    continue
                for scope_field, count_field in (
                    ("target", "target_freq"),
                    ("reference", "reference_freq"),
                ):
                    scope_labels = _source_values_for_field(scope_field, surface)
                    counts = _field_numeric_values(surface, (count_field,))
                    if (
                        len(scope_labels) == 1
                        and any(
                            _contains_literal_label(sentence, label)
                            for label in scope_labels
                        )
                        and any(float(count) != 0.0 for count in counts)
                    ):
                        return False

    labels: List[str] = []
    for fact in observed_facts:
        if fact.fact_kind != "ranked_row":
            continue
        surface = " ".join([fact.statement, *fact.grounding_quotes])
        if not (
            "target_freq=" in surface
            and "reference_freq=" in surface
        ):
            continue
        match = re.search(
            r"\bzeigt\s+['\"„](?P<label>[^'\"“]+)['\"“]\s+mit\b",
            fact.statement or "",
            re.IGNORECASE,
        )
        if match is not None:
            labels.append(match.group("label").strip())
    if len(labels) < 4:
        return True
    identifier_share = sum(label.startswith("@") for label in labels) / len(labels)
    if identifier_share < 0.5:
        return True
    return any(
        claim.claim_kind == "interpretation"
        and _KEYNESS_IDENTIFIER_INTERPRETATION_PATTERN.search(
            claim.text or ""
        )
        and _KEYNESS_VISIBLE_IDENTIFIER_PATTERN.search(claim.text or "")
        and _KEYNESS_IDENTIFIER_DOMINANCE_PATTERN.search(claim.text or "")
        for claim in claims
    )


def _expanded_kwic_context_text(fact: ObservedFact) -> str:
    statement = str(fact.statement or "")
    match = re.search(
        r"\b(?:lautet|reads?)\s*:\s*(?P<context>.+)$",
        statement,
        re.IGNORECASE,
    )
    if match is not None:
        return match.group("context").strip(" \t\"'„“")
    candidates = [
        str(quote or "")
        for quote in fact.grounding_quotes
        if not re.fullmatch(r"(?:pos|doc_id)\s*=.*", str(quote or ""))
    ]
    return max(candidates, key=len, default="")


def _kwic_claim_has_source_specific_anchor(
    claim_text: str,
    expanded_facts: Sequence[ObservedFact],
    *,
    question_text: str,
) -> bool:
    question_tokens = set(_semantic_theme_tokens(question_text))
    query_term_tokens = set(
        _semantic_theme_tokens(_question_term(question_text))
    )
    expanded_context_tokens = {
        token
        for fact in expanded_facts
        for token in _semantic_theme_tokens(
            _expanded_kwic_context_text(fact)
        )
    }
    if query_term_tokens and not query_term_tokens.issubset(
        expanded_context_tokens
    ):
        return False
    source_tokens = {
        token
        for token in expanded_context_tokens
        if token not in question_tokens
    }
    if not source_tokens:
        return True
    claim_tokens = set(_semantic_theme_tokens(claim_text))
    matched_source_tokens = {
        source
        for source in source_tokens
        if any(
            source == claim
            or (
                len(source) >= 5
                and len(claim) >= 5
                and source[:5] == claim[:5]
            )
            for claim in claim_tokens
        )
    }
    # The query expression itself is not a substantive interpretation. Require
    # at least one additional visible content anchor in the same bounded local
    # claim; candidate attachment heads such as a visible noun satisfy this.
    return bool(matched_source_tokens)


def accepted_kwic_interpretation_is_substantive(
    claims: Sequence[ClaimDraft],
    observed_facts: Sequence[ObservedFact],
    *,
    question_text: str = "",
) -> bool:
    fact_index = {fact.id: fact for fact in observed_facts}
    for claim in claims:
        if claim.claim_kind != "interpretation":
            continue
        linked = [
            fact_index[fact_id]
            for fact_id in claim.fact_ids
            if fact_id in fact_index
        ]
        expanded_context_facts = [
            fact
            for fact in linked
            if (
                fact.fact_kind == "kwic_example"
                and "erweiter" in fact.statement.casefold()
                and "kontext" in fact.statement.casefold()
            )
        ]
        if not expanded_context_facts:
            continue
        text = claim.text or ""
        source_anchored = _kwic_claim_has_source_specific_anchor(
            text,
            expanded_context_facts,
            question_text=question_text,
        )
        bounded_local_reading = bool(
            _KWIC_LOCAL_READING_PATTERN.search(text)
            and _ATTACHMENT_QUALIFIER_PATTERN.search(text)
            and not (
                _CATEGORICAL_ATTACHMENT_PATTERN.search(text)
                and _KWIC_AMBIGUITY_PATTERN.search(text) is None
            )
        )
        bounded_communicative_reading = bool(
            _KWIC_COMMUNICATIVE_READING_PATTERN.search(text)
            and _KWIC_CONTEXT_BOUND_READING_PATTERN.search(text)
        )
        # Source anchors and interpretive substance must belong to the same
        # proposition. The user asked for a reading of the concrete passage,
        # not necessarily a syntactic attachment analysis: a bounded account
        # of its communicative action is equally substantive.
        if source_anchored and (
            bounded_local_reading or bounded_communicative_reading
        ):
            return True
        continue

    # A transparent multi-row KWIC sample is itself legitimate qualitative
    # evidence. It may motivate a bounded reading of visible variation without
    # an extra full-document lookup, provided the same claim names content from
    # at least two distinct rows and does not promote the sample to the corpus.
    for claim in claims:
        if (
            claim.claim_kind != "interpretation"
            or claim.assertion_level == "exact"
            or not _is_explicitly_bounded_claim(claim.text or "")
        ):
            continue
        linked_sample_facts = [
            fact_index[fact_id]
            for fact_id in claim.fact_ids
            if fact_id in fact_index
            and fact_index[fact_id].fact_kind == "kwic_example"
            and fact_index[fact_id].exactness == "sample_only"
            and not (
                "erweiter" in fact_index[fact_id].statement.casefold()
                and "kontext" in fact_index[fact_id].statement.casefold()
            )
        ]
        if len(linked_sample_facts) < 2:
            continue
        claim_tokens = set(_semantic_theme_tokens(claim.text or ""))
        question_tokens = set(_semantic_theme_tokens(question_text))
        anchored_rows = 0
        for fact in linked_sample_facts:
            match_surfaces = [
                match.group("span")
                for quote in fact.grounding_quotes
                for match in [
                    re.search(
                        r'match\[\d+\]="(?P<span>[^"]+)"',
                        str(quote or ""),
                        re.IGNORECASE,
                    )
                ]
                if match is not None
            ]
            source_text = " ".join(match_surfaces) or _expanded_kwic_context_text(
                fact
            )
            source_tokens = set(_semantic_theme_tokens(source_text)) - question_tokens
            if any(
                source == candidate
                or (
                    len(source) >= 5
                    and len(candidate) >= 5
                    and source[:5] == candidate[:5]
                )
                for source in source_tokens
                for candidate in claim_tokens
            ):
                anchored_rows += 1
        if anchored_rows >= 2:
            return True
    return False


def missing_word_sketch_profile_facts(
    claims: Sequence[ClaimDraft],
    observed_facts: Sequence[ObservedFact],
) -> List[ObservedFact]:
    """Return visible sketch facts that the model-owned profile omitted."""

    required_facts = [
        fact
        for fact in observed_facts
        if fact.fact_kind in {"metadata", "ranked_row"}
        and any(
            "word_sketch" in str(source_id or "").casefold()
            for source_id in fact.source_evidence_ids
        )
    ]
    missing: List[ObservedFact] = []
    for fact in required_facts:
        linked_claims = [
            claim for claim in claims if fact.id in claim.fact_ids
        ]
        if not linked_claims:
            missing.append(fact)
            continue
        if fact.fact_kind != "ranked_row":
            continue
        fact_surface = _joined_surface_text(
            [fact.statement, *fact.grounding_quotes]
        )
        labels = _source_values_for_field("word", fact_surface)
        f_values = _field_numeric_values(fact_surface, ("f", "frequency"))
        if not labels or not f_values:
            continue
        # Claims are already schema-bounded to MAX_CLAIM_TEXT_CHARS. Do not use
        # the 220-character evidence-preview helper here: a complete multi-row
        # profile can legitimately mention a later partner after that boundary.
        claim_surface = " || ".join(
            " ".join(str(claim.text or "").split())
            for claim in linked_claims
            if str(claim.text or "").strip()
        )
        claim_numbers = set(_extract_numeric_tokens(claim_surface))
        for match in _WORD_SKETCH_COUNT_UNIT_PATTERN.finditer(claim_surface):
            value = _number_word_value(match.group("number"))
            if value:
                claim_numbers.add(value)
        if not any(
            _contains_literal_label(claim_surface, label)
            for label in labels
        ) or not set(f_values).intersection(claim_numbers):
            missing.append(fact)
    return missing


def word_sketch_metric_units_are_clear(
    claims: Sequence[ClaimDraft],
) -> bool:
    """Require a compact unit explanation when raw sketch fields are shown."""

    surface = _joined_surface_text([claim.text for claim in claims])
    f_is_visible = re.search(
        r"(?<![\w2₂])f\s*[=:]",
        surface,
        re.IGNORECASE,
    )
    f2_is_visible = re.search(
        r"\bf(?:2|₂)\s*[=:]",
        surface,
        re.IGNORECASE,
    )
    if f_is_visible and re.search(
        r"\b(?:Dependenz|Abhängigkeits|Abhaengigkeits|Relations)"
        r"ereignis\w*\b",
        surface,
        re.IGNORECASE,
    ) is None:
        return False
    if f2_is_visible and re.search(
        r"\b(?:marginal\w*\s+(?:Token)?häufigkeit|"
        r"marginal\w*\s+(?:Token)?haeufigkeit|"
        r"(?:Token)?häufigkeit\s+des\s+Partners|"
        r"(?:Token)?haeufigkeit\s+des\s+Partners|"
        r"collocate\s+marginal\s+frequency)\b",
        surface,
        re.IGNORECASE,
    ) is None:
        return False
    return True


def accepted_word_sketch_profile_covers_visible_facts(
    claims: Sequence[ClaimDraft],
    observed_facts: Sequence[ObservedFact],
) -> bool:
    """Require a requested profile to account for every visible sketch row."""

    return not missing_word_sketch_profile_facts(claims, observed_facts)


_WORD_SKETCH_PROFILE_SYNTHESIS_PATTERN = re.compile(
    r"\b(?:sowohl\b[^.!?\n]{0,180}\bals\s+auch|"
    r"einerseits\b[^.!?\n]{0,180}\bandererseits|"
    r"unterschied\w*[^.!?\n]{0,100}\b(?:beziehungsdomän\w*|"
    r"dependenzbeziehung\w*|relation\w*|anbindung\w*|"
    r"(?:grammatisch|syntaktisch|relational)\w*\s+domän\w*)|"
    r"differenzier\w*[^.!?\n]{0,80}\bzwischen\b[^.!?\n]{0,160}"
    r"\b(?:beziehung\w*|verbindung\w*|syntax|relation\w*|anbindung\w*)|"
    r"spannweite\b[^.!?\n]{0,140}\b(?:syntax|relation\w*|"
    r"beziehung\w*|anbindung\w*)|"
    r"beziehungsdomän\w*|relations?domän\w*|nebeneinander|"
    r"gegenüberstell\w*|"
    r"gegenueberstell\w*)\b",
    re.IGNORECASE,
)


def accepted_word_sketch_interpretation_is_substantive(
    claims: Sequence[ClaimDraft],
    observed_facts: Sequence[ObservedFact],
) -> bool:
    """Require a profile-level reading, not a relabelled table row."""

    relation_facts = [
        fact
        for fact in observed_facts
        if fact.fact_kind == "metadata"
        and any(
            "word_sketch" in str(source_id or "").casefold()
            for source_id in fact.source_evidence_ids
        )
    ]
    relation_ids = {fact.id for fact in relation_facts}
    interpretations = [
        claim for claim in claims if claim.claim_kind == "interpretation"
    ]
    if not interpretations:
        return False
    if len(relation_ids) < 2:
        return any(
            relation_ids.intersection(claim.fact_ids)
            for claim in interpretations
        )
    return any(
        len(relation_ids.intersection(claim.fact_ids)) >= 2
        and _WORD_SKETCH_PROFILE_SYNTHESIS_PATTERN.search(claim.text or "")
        for claim in interpretations
    )


_SEMANTIC_PATTERN_SYNTHESIS_REQUEST_PATTERN = re.compile(
    r"(?:\b(?:wiederkehr\w*|rekurrent\w*|recurr\w*|recurrent\w*)\b"
    r"[^.!?\n]{0,120}\b(?:muster\w*|pattern\w*)\b|"
    r"\b(?:muster\w*|pattern\w*)\b[^.!?\n]{0,120}"
    r"\b(?:zusammenfass\w*|synthes\w*|summari[sz]\w*)\b)",
    re.IGNORECASE,
)


def accepted_semantic_pattern_interpretation_is_substantive(
    claims: Sequence[ClaimDraft],
    observed_facts: Sequence[ObservedFact],
    *,
    question_text: str = "",
    analysis_family: str = "",
    deliverable_kind: str = "",
) -> bool:
    """Require requested pattern readings to connect multiple result facts."""

    semantic_pattern_requested = bool(
        _SEMANTIC_PATTERN_SYNTHESIS_REQUEST_PATTERN.search(
            question_text or ""
        )
    )
    open_research_overview = bool(
        analysis_family == "open_research"
        and deliverable_kind == "overview"
    )
    if not semantic_pattern_requested and not open_research_overview:
        return True

    if semantic_pattern_requested:
        synthesis_fact_ids = {
            fact.id
            for fact in observed_facts
            if fact.fact_kind == "kwic_example"
            and any(
                "semantic_search" in str(source_id or "").casefold()
                or "transformer_search" in str(source_id or "").casefold()
                for source_id in fact.source_evidence_ids
            )
        }
    else:
        # Metadata and corpus-size bookkeeping establish scope but cannot by
        # themselves turn an open overview into substantive corpus analysis.
        synthesis_fact_ids = {
            fact.id
            for fact in observed_facts
            if fact.fact_kind in {"ranked_row", "kwic_example", "distribution"}
        }
        if len(synthesis_fact_ids) < 2:
            return True

    return any(
        claim.claim_kind == "interpretation"
        and (
            not open_research_overview
            or claim.assertion_level == "tentative"
        )
        and len(synthesis_fact_ids.intersection(claim.fact_ids)) >= 2
        for claim in claims
    )


def accepted_claims_match_deliverable(
    envelope: AnswerEnvelope,
    accepted_claim_ids: Sequence[str],
    rejected_claim_ids: Sequence[str],
    *,
    deliverable_kind: str,
    question_text: str = "",
    observed_facts: Sequence[ObservedFact] = (),
    analysis_family: str = "",
) -> bool:
    accepted = set(accepted_claim_ids) - set(rejected_claim_ids)
    accepted_claims = [
        claim for claim in envelope.claims if claim.id in accepted
    ]
    accepted_kinds = {claim.claim_kind for claim in accepted_claims}
    required_kinds = set(
        _REQUIRED_CLAIM_KINDS_BY_DELIVERABLE.get(
            deliverable_kind,
            set(),
        )
    )
    if _deterministic_result_surface_supplies_observation(
        observed_facts,
        question_text=question_text,
    ):
        required_kinds.discard("observation")
    exact_negative_method_conclusion = bool(
        deliverable_kind == "analysis_report"
        and _has_exact_negative_method_conclusion(
            accepted_claims,
            observed_facts,
        )
    )
    if deliverable_kind == "capability_report":
        return bool(accepted_claims) and not rejected_claim_ids
    deliverable_ok, _reason = envelope_matches_deliverable_kind(
        AnswerEnvelope(claims=accepted_claims),
        deliverable_kind=deliverable_kind,
        question_text=question_text,
    )
    if not (
        (required_kinds <= accepted_kinds and deliverable_ok)
        or (exact_negative_method_conclusion and deliverable_ok)
    ):
        return False
    if (
        _is_confirmation_pressure_prompt(question_text)
        and not _accepted_claims_reject_confirmation_pressure(
            accepted_claims
        )
        and not _observed_facts_supply_confirmation_boundary(
            observed_facts
        )
    ):
        return False
    if deliverable_kind in {
        "analysis_report",
        "contrast_report",
        "overview",
    }:
        observation_texts = {
            _normalised_question_text(claim.text)
            for claim in accepted_claims
            if claim.claim_kind == "observation"
        }
        distinct_interpretation = any(
            _normalised_question_text(claim.text)
            not in observation_texts
            for claim in accepted_claims
            if claim.claim_kind == "interpretation"
        )
        if not distinct_interpretation and not exact_negative_method_conclusion:
            return False
    if (
        deliverable_kind == "followup_questions"
        and not accepted_followups_have_research_breadth(
            envelope,
            accepted_claim_ids,
            rejected_claim_ids,
            question_text=question_text,
        )
    ):
        return False
    lowered_question = _normalised_question_text(question_text)
    if (
        _NGRAM_INTERPRETATION_REQUEST_PATTERN.search(question_text or "")
        and any(
            any(
                "ngram_frequency" in str(source_id or "").casefold()
                for source_id in fact.source_evidence_ids
            )
            for fact in observed_facts
        )
        and not accepted_ngram_interpretation_is_substantive(
            accepted_claims,
            observed_facts,
        )
    ):
        return False
    if (
        deliverable_kind == "contrast_report"
        and not accepted_keyness_interpretation_is_substantive(
            accepted_claims,
            observed_facts,
        )
    ):
        return False
    kwic_interpretation_required = bool(
        deliverable_kind == "analysis_report"
        and (
            any(
                fact.fact_kind == "kwic_example"
                and "erweiter" in fact.statement.casefold()
                and "kontext" in fact.statement.casefold()
                for fact in observed_facts
            )
            or (
                analysis_family == "kwic_context"
                and _KWIC_INTERPRETATION_REQUEST_PATTERN.search(
                    question_text or ""
                )
                and sum(
                    fact.fact_kind == "kwic_example"
                    and fact.exactness == "sample_only"
                    for fact in observed_facts
                )
                >= 2
            )
        )
    )
    if kwic_interpretation_required and not accepted_kwic_interpretation_is_substantive(
        accepted_claims,
        observed_facts,
        question_text=question_text,
    ):
        return False
    if not accepted_semantic_pattern_interpretation_is_substantive(
        accepted_claims,
        observed_facts,
        question_text=question_text,
        analysis_family=analysis_family,
        deliverable_kind=deliverable_kind,
    ):
        return False
    if (
        analysis_family == "word_sketch_profile"
        and not accepted_word_sketch_profile_covers_visible_facts(
            accepted_claims,
            observed_facts,
        )
    ):
        return False
    if (
        analysis_family == "word_sketch_profile"
        and not accepted_word_sketch_interpretation_is_substantive(
            accepted_claims,
            observed_facts,
        )
    ):
        return False
    if (
        analysis_family == "word_sketch_profile"
        and not word_sketch_metric_units_are_clear(accepted_claims)
    ):
        return False
    if (
        "lexikal" in lowered_question
        and "divers" in lowered_question
        and re.search(
            r"\b(?:ohne|kein(?:e|en|er|es)?)\s+referenzkorpus\b",
            lowered_question,
        )
        and not any(
            _is_lexical_reference_boundary_claim(claim.text)
            for claim in accepted_claims
        )
    ):
        return False
    if (
        "lexikal" in lowered_question
        and "divers" in lowered_question
        and _LEXICAL_ROBUSTNESS_REQUEST_PATTERN.search(
            question_text or ""
        )
    ):
        accepted_text = " ".join(
            claim.text for claim in accepted_claims
        )
        if not (
            re.search(r"\bttr\b", accepted_text, re.IGNORECASE)
            and _LEXICAL_ROBUSTNESS_ANSWER_PATTERN.search(accepted_text)
        ):
            return False
        if (
            _lexical_window_parameters_differ(observed_facts)
            and _UNEQUAL_WINDOW_BOUNDARY_PATTERN.search(accepted_text) is None
        ):
            return False
    return True
