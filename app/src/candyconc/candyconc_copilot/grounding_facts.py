"""Deterministic evidence and observed-fact layer (K3 Slice 3).

Verbatim move out of ``analysis_grounding``: evidence-item construction,
evidence-kind resolution, the per-tool observed-fact builders, balanced
fact selection and observed-fact validation, plus the lexical-search /
question-text helpers this layer reads. ``analysis_grounding`` stays the
facade and re-exports every name. Import from there unless you are
inside the grounding package.
"""

from __future__ import annotations

from candyconc.answer_language import choose as _t

import hashlib
import json
import logging
import re
from dataclasses import dataclass, replace
from typing import Any, Dict, List, Sequence, Tuple

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


_LOGGER = logging.getLogger(__name__)


def payload_preview(output: Any, *, limit: int = 220) -> str:
    if not isinstance(output, dict):
        return _compact_text(output, limit)
    preview: Dict[str, Any] = {}
    for key in ("status", "message", "total"):
        if key in output:
            preview[key] = output.get(key)
    rows = output.get("rows")
    if isinstance(rows, list) and rows:
        preview["rows"] = rows[:2]
    tables = output.get("tables")
    if isinstance(tables, dict) and tables:
        preview["tables"] = list(tables.keys())[:4]
    offsets = output.get("offsets")
    if isinstance(offsets, list) and offsets:
        preview["offsets"] = offsets[:6]
    clusters = output.get("clusters")
    if isinstance(clusters, list) and clusters:
        preview["clusters"] = clusters[:2]
    return _compact_text(preview or output, limit)


def make_evidence_item(
    *,
    item_id: str,
    tool: str,
    tool_call_id: str,
    query: Any,
    output: Any,
    analysis_family: str,
) -> EvidenceItem:
    status = "success"
    if isinstance(output, dict):
        status = str(output.get("status", "success") or "success")
    from .view_row_selection import perioden_mit_pfad

    # A thinned period series names each shown period's path (view_row_selection).
    raw_surface = perioden_mit_pfad(extract_raw_surface(output, werkzeug=tool), output)
    fact_surface = extract_raw_surface(output, bounded=False, werkzeug=tool)
    # Keep ordinary tool arguments parseable. The old 180-character cut split
    # realistic stop-word JSON at character 180, so provenance silently lost
    # the filter that actually defined the reported ranking.
    query_text = _compact_text(query, 512)
    grounding_surface = build_grounding_surface(raw_surface)
    # Was aus der EIGENEN Eingabe des Modells stammt, wird beim Anlegen
    # markiert, nicht spaeter am Text erraten. Die Zitatwache schliesst es
    # ueber diese Liste aus.
    eingabe_surface: List[str] = []
    analysis_input_quote = _simple_analysis_input_quote(query)
    if analysis_input_quote:
        grounding_surface.append(analysis_input_quote)
        eingabe_surface.append(analysis_input_quote)
    if query_text:
        arg_zeile = _compact_text(f"tool_args={query_text}", 220)
        grounding_surface.append(arg_zeile)
        eingabe_surface.append(arg_zeile)
    # Die Werkzeuge spiegeln ihre Argumente in der Ausgabe zurueck. Diese
    # Echos sind ebenfalls Eingabe, keine Belege.
    for feld in ("query", "term", "node", "word", "requested_term"):
        for flaeche in (raw_surface, fact_surface):
            echo = flaeche.get(feld) if isinstance(flaeche, dict) else None
            if isinstance(echo, str) and echo.strip():
                eingabe_surface.append(echo)
                eingabe_surface.append(f"{feld}={echo}")
    return EvidenceItem(
        id=_compact_id(item_id, 96),
        tool=_compact_text(tool, 48),
        tool_call_id=_compact_id(tool_call_id, 96),
        query=query_text,
        status=status,
        truncated=bool(raw_surface.get("truncated")),
        grounding_truncated=bool(raw_surface.get("grounding_truncated")),
        result_scope=result_scope_from_output(output),
        payload_preview=payload_preview(output),
        raw_surface=raw_surface,
        fact_surface=fact_surface,
        grounding_surface=list(dict.fromkeys(grounding_surface)),
        eingabe_surface=list(dict.fromkeys(eingabe_surface)),
        raw_ref=_compact_text(f"{tool_call_id}:{tool}", 80),
        analysis_family=_compact_text(analysis_family, 32),
        partial=bool(fact_surface.get("partial")),
        sampled=bool(fact_surface.get("sampled")),
    )


def _frequency_group_by(item: EvidenceItem) -> str:
    value = item.raw_surface.get("group_by")
    if value in (None, ""):
        try:
            args = json.loads(item.query) if item.query else {}
        except (TypeError, ValueError, json.JSONDecodeError):
            args = {}
        if isinstance(args, dict):
            value = args.get("group_by")
    # frequency_list defaults to word when group_by is omitted.
    return str(value or "word").strip().casefold()


_CONTENT_POS_PREFIXES = (
    "NOUN",
    "PROPN",
    "VERB",
    "ADJ",
    "NN",
    "NE",
    "VV",
    "ADJA",
    "ADJD",
)


def frequency_parameters_supply_content_rows(
    *,
    group_by: Any,
    pos: Any,
) -> bool:
    """Return whether frequency arguments request a content-word profile."""

    grouping = str(group_by or "word").strip().casefold()
    pos_prefix = str(pos or "").strip().upper()
    return grouping in {"word", "lemma"} and any(
        pos_prefix.startswith(prefix)
        for prefix in _CONTENT_POS_PREFIXES
    )


def _frequency_is_content_profile(item: EvidenceItem) -> bool:
    value = item.raw_surface.get("pos")
    if value in (None, ""):
        try:
            args = json.loads(item.query) if item.query else {}
        except (TypeError, ValueError, json.JSONDecodeError):
            args = {}
        if isinstance(args, dict):
            value = args.get("pos")
    return frequency_parameters_supply_content_rows(
        group_by=_frequency_group_by(item),
        pos=value,
    )


def evidence_kinds_for_item(item: EvidenceItem) -> List[str]:
    kinds: set[str] = set()
    if item.tool == "run_cqlf_query":
        if isinstance(item.raw_surface.get("rows"), list) and item.raw_surface.get("rows"):
            kinds.add("kwic_rows")
            kinds.add("contextual_rows")
        if item.raw_surface.get("total") not in (None, ""):
            kinds.add("total_hits")
    elif item.tool == "kwic_context":
        if item.raw_surface.get("kw") not in (None, ""):
            kinds.add("kwic_rows")
            kinds.add("contextual_rows")
            kinds.add("expanded_context")
    elif item.tool == "frequency_list":
        if isinstance(item.raw_surface.get("rows"), list) and item.raw_surface.get("rows"):
            kinds.add("frequency_rows")
            if _frequency_group_by(item) in {"word", "lemma"}:
                kinds.add("lexical_frequency_rows")
            if _frequency_is_content_profile(item):
                kinds.add("content_rows")
        if item.raw_surface.get("total") not in (None, ""):
            kinds.add("total_hits")
    elif item.tool == "query_count":
        # Q3: der exakte Einzelterm-Count traegt die total_hits-Evidenz.
        if item.raw_surface.get("total") not in (None, ""):
            kinds.add("total_hits")
    elif item.tool in {
        "collocate_stats",
        "keyness",
        "compare_collocates",
        "contrast_collocates",
        "ngram_frequency",
    }:
        if isinstance(item.raw_surface.get("rows"), list) and item.raw_surface.get("rows"):
            kinds.add("metric_rows")
    elif item.tool == "word_sketch":
        if isinstance(item.raw_surface.get("tables"), dict) and item.raw_surface.get("tables"):
            kinds.add("metric_rows")
    elif item.tool == "lexical_diversity":
        if any(
            item.raw_surface.get(key) not in (None, "")
            for key in ("ttr", "sttr", "mattr", "guiraud", "n_tokens", "n_types")
        ):
            kinds.add("metric_rows")
    elif item.tool == "trend_analysis":
        if isinstance(item.raw_surface.get("periods"), list) and item.raw_surface.get("periods"):
            kinds.add("metric_rows")
    elif item.tool == "dispersion_offsets":
        if any(
            item.raw_surface.get(key) not in (None, "")
            for key in ("dp", "profile", "coverage_ratio", "nonzero_partitions", "peak_partition", "peak_share")
        ):
            kinds.add("dispersion_profile")
        if item.raw_surface.get("total_hits") not in (None, ""):
            kinds.add("total_hits")
    elif item.tool == "document_search":
        if isinstance(item.raw_surface.get("rows"), list) and item.raw_surface.get("rows"):
            kinds.add("document_rows")
            kinds.add("content_rows")
            kinds.add("contextual_rows")
    elif item.tool == "metadata_values":
        if isinstance(item.raw_surface.get("values"), dict) and item.raw_surface.get("values"):
            kinds.add("metadata_rows")
    elif item.tool == "documentation_search":
        if isinstance(item.raw_surface.get("rows"), list) and item.raw_surface.get("rows"):
            kinds.add("documentation_rows")
    elif item.tool == "semantic_search":
        if isinstance(item.raw_surface.get("rows"), list) and item.raw_surface.get("rows"):
            kinds.add("content_rows")
            kinds.add("contextual_rows")
            if (
                _semantic_rows_include_embedding_scores(
                    item.raw_surface.get("rows")
                )
                or _semantic_candidate_generation_uses_vectors(
                    item.raw_surface
                )
            ):
                kinds.add("semantic_rows")
    elif item.tool in {"semantic_cluster", "semantic_cluster_words"}:
        if _informative_clusters(item.raw_surface):
            kinds.add("cluster_rows")
            kinds.add("content_rows")
            kinds.add("contextual_rows")
    return sorted(kinds)


def evidence_kinds_for_fact(
    fact: ObservedFact,
    item: EvidenceItem,
) -> List[str]:
    """Map a fact to the evidence shape it actually reports.

    Item-level capability is too coarse here: a scope fact from a frequency
    result does not itself report any frequency row.
    """

    if fact.fact_kind == "limitation":
        return []
    surface = "\n".join(
        [fact.statement, *fact.grounding_quotes]
    ).casefold()
    statement_assignments = {
        match.group(1).casefold()
        for match in _FIELD_ASSIGNMENT_PATTERN.finditer(fact.statement)
    }
    reports_row_binding = bool(
        statement_assignments.intersection(_ROW_SCOPED_FIELD_NAMES)
        or _extract_grounding_example_segments(fact.statement)
    )
    has_row = bool(
        re.search(
            r"(?:^|\n)(?:row|metric|kwic|table\[[^\]]+\])\[\d+\]",
            surface,
        )
    )
    kinds: set[str] = set()
    if item.tool == "run_cqlf_query":
        if has_row and reports_row_binding:
            kinds.add("kwic_rows")
            kinds.add("contextual_rows")
        if re.search(r"(?:^|\n)total=", surface):
            kinds.add("total_hits")
    elif item.tool == "kwic_context":
        if has_row or "kwic[" in surface:
            kinds.add("kwic_rows")
            kinds.add("contextual_rows")
            kinds.add("expanded_context")
    elif item.tool == "frequency_list":
        if has_row and reports_row_binding:
            kinds.add("frequency_rows")
            if _frequency_group_by(item) in {"word", "lemma"}:
                kinds.add("lexical_frequency_rows")
            if _frequency_is_content_profile(item):
                kinds.add("content_rows")
        if re.search(r"(?:^|\n)total=", surface):
            kinds.add("total_hits")
    elif item.tool == "query_count":
        if re.search(r"(?:^|\n)total=", surface):
            kinds.add("total_hits")
    elif item.tool in {
        "collocate_stats",
        "keyness",
        "compare_collocates",
        "contrast_collocates",
        "word_sketch",
        "ngram_frequency",
    }:
        if has_row and reports_row_binding:
            kinds.add("metric_rows")
    elif item.tool == "lexical_diversity":
        if any(
            marker in surface
            for marker in ("ttr=", "sttr=", "mattr=", "guiraud=", "n_tokens=", "n_types=")
        ):
            kinds.add("metric_rows")
    elif item.tool == "trend_analysis":
        if "period[" in surface:
            kinds.add("metric_rows")
    elif item.tool == "dispersion_offsets":
        if any(
            marker in surface
            for marker in (
                "dp=",
                "profile=",
                "coverage_ratio=",
                "nonzero_partitions=",
                "peak_partition=",
                "peak_share=",
            )
        ):
            kinds.add("dispersion_profile")
        if "total_hits=" in surface:
            kinds.add("total_hits")
    elif item.tool == "document_search":
        if has_row and reports_row_binding:
            kinds.add("document_rows")
            kinds.add("content_rows")
            kinds.add("contextual_rows")
    elif item.tool == "documentation_search":
        if has_row and reports_row_binding:
            kinds.add("documentation_rows")
    elif item.tool == "metadata_values":
        if fact.fact_kind in {"metadata", "negative_result"}:
            kinds.add("metadata_rows")
    elif item.tool == "semantic_search":
        if has_row and reports_row_binding:
            kinds.add("content_rows")
            kinds.add("contextual_rows")
            if (
                "score_kind=cosine" in surface
                or _semantic_rows_include_embedding_scores(
                    item.raw_surface.get("rows")
                )
                or _semantic_candidate_generation_uses_vectors(
                    item.raw_surface
                )
            ):
                kinds.add("semantic_rows")
    elif item.tool in {"semantic_cluster", "semantic_cluster_words"}:
        if "cluster[" in surface:
            kinds.add("cluster_rows")
            kinds.add("content_rows")
            kinds.add("contextual_rows")
    return sorted(kinds)


def _metadata_values_for_field(
    evidence_items: Sequence[EvidenceItem],
    field_name: str,
) -> List[str]:
    values: List[str] = []
    wanted = field_name.lower()
    for item in evidence_items:
        diagnostics = item.raw_surface.get("diagnostics")
        if isinstance(diagnostics, dict):
            for key in (f"{wanted}_values", wanted):
                entries = diagnostics.get(key)
                if isinstance(entries, list):
                    for entry in entries:
                        cleaned = _normalise_example_text(entry)
                        if cleaned and cleaned not in values:
                            values.append(cleaned)
                else:
                    cleaned = _normalise_example_text(entries)
                    if cleaned and cleaned not in values:
                        values.append(cleaned)
        if item.tool != "metadata_values":
            continue
        raw_values = item.raw_surface.get("values")
        if not isinstance(raw_values, dict):
            continue
        for field_name, entries in raw_values.items():
            if str(field_name).lower() != wanted:
                continue
            if isinstance(entries, list):
                for entry in entries:
                    cleaned = _normalise_example_text(entry)
                    if cleaned and cleaned not in values:
                        values.append(cleaned)
            else:
                cleaned = _normalise_example_text(entries)
                if cleaned and cleaned not in values:
                    values.append(cleaned)
    return values


def _metadata_blocks_human_ai_contrast(
    contract: AnalysisContract,
    evidence_items: Sequence[EvidenceItem],
) -> bool:
    if contract.analysis_family != "contrast_keyness":
        return False
    model_values = [value.lower() for value in _metadata_values_for_field(evidence_items, "model")]
    text_type_values = [value.lower() for value in _metadata_values_for_field(evidence_items, "text_type")]
    visible_axis = set(model_values or text_type_values)
    if not visible_axis:
        return False
    has_human = any(value in {"human", "mensch", "menschen"} for value in visible_axis)
    has_ai = any(value in {"ai", "ki", "llm", "machine", "synthetic"} for value in visible_axis)
    return has_human and not has_ai


def _metadata_inventory_items(
    evidence_items: Sequence[EvidenceItem],
) -> List[EvidenceItem]:
    return [item for item in evidence_items if item.tool == "metadata_values"]


_TEMPORAL_METADATA_FIELD_PATTERN = re.compile(
    r"(?:^|_)(?:date|datum|year|jahr|month|monat|time|zeit)(?:_|$)",
    re.IGNORECASE,
)


def _metadata_blocks_trend(
    contract: AnalysisContract,
    evidence_items: Sequence[EvidenceItem],
) -> bool:
    if contract.analysis_family != "trend_analysis":
        return False
    inventories = _metadata_inventory_items(evidence_items)
    if not inventories:
        return False
    for item in inventories:
        if item.raw_surface.get("available_fields_truncated"):
            return False
        fields = {
            str(field).strip()
            for field in item.raw_surface.get("available_fields", [])
            if str(field).strip()
        }
        values = item.raw_surface.get("values")
        if isinstance(values, dict):
            fields.update(str(field).strip() for field in values if str(field).strip())
        if any(_TEMPORAL_METADATA_FIELD_PATTERN.search(field) for field in fields):
            return False
    return True


def _metadata_blocks_requested_register(
    contract: AnalysisContract,
    evidence_items: Sequence[EvidenceItem],
) -> bool:
    requested = _requested_register_value(contract.question_scope)
    if not requested:
        return False
    inventories = _metadata_inventory_items(evidence_items)
    if not inventories:
        return False
    for item in inventories:
        if item.raw_surface.get("available_fields_truncated"):
            return False
        available_fields = {
            str(field).strip().casefold()
            for field in item.raw_surface.get("available_fields", [])
            if str(field).strip()
        }
        values = item.raw_surface.get("values")
        register_values: List[str] = []
        if isinstance(values, dict):
            register_values = [
                _normalise_example_text(value).casefold()
                for value in values.get("register", [])
                if _normalise_example_text(value)
            ] if isinstance(values.get("register"), list) else []
        if "register" not in available_fields and not register_values:
            continue
        if "register" in set(item.raw_surface.get("sampled_value_fields", [])):
            return False
        return requested not in set(register_values)
    return True


def _effective_required_evidence(
    contract: AnalysisContract,
    evidence_items: Sequence[EvidenceItem],
) -> List[str]:
    required = list(contract.required_evidence)
    if _metadata_blocks_human_ai_contrast(contract, evidence_items):
        required = [kind for kind in required if kind != "metric_rows"]
    if _metadata_blocks_trend(contract, evidence_items):
        required = [kind for kind in required if kind != "metric_rows"]
    if _metadata_blocks_requested_register(contract, evidence_items):
        required = [
            kind
            for kind in required
            if kind not in {"kwic_rows", "expanded_context", "total_hits"}
        ]
    if any(
        _is_requested_query_diagnostic(contract, item)
        for item in evidence_items
    ):
        # A requested syntax diagnosis intentionally stops before corpus
        # execution. Parser evidence fulfills that request; pretending that
        # KWIC rows or a hit count should nevertheless exist creates a false
        # incomplete-answer state.
        required = [
            kind
            for kind in required
            if kind not in {"kwic_rows", "expanded_context", "total_hits"}
        ]
    if (
        contract.deliverable_kind == "method_advice"
        and {"metadata_rows", "content_rows"}.issubset(
            {
                kind
                for item in evidence_items
                for kind in evidence_kinds_for_item(item)
            }
        )
    ):
        # Method advice proposes what to investigate next; it does not claim
        # the result of that future investigation. Structural inventory plus
        # substantive lexical evidence can therefore support useful next
        # steps without forcing an arbitrary retrieval query merely because a
        # contextual tool happens to be available.
        required = [kind for kind in required if kind != "contextual_rows"]
    return required


def effective_analysis_contract(
    contract: AnalysisContract,
    evidence_items: Sequence[EvidenceItem],
) -> AnalysisContract:
    """Return the evidence contract that final synthesis must actually obey."""

    required_evidence = _effective_required_evidence(contract, evidence_items)
    if required_evidence == contract.required_evidence:
        return contract
    return replace(contract, required_evidence=required_evidence)


def _has_completed_collocation_profile(item: EvidenceItem) -> bool:
    """Distinguish a valid empty profile from an absent or failed result."""

    if (
        item.tool != "collocate_stats"
        or str(item.status or "").strip().casefold() == "error"
    ):
        return False
    if isinstance(item.raw_surface.get("rows"), list):
        return True
    for key in ("result_count", "rows_seen"):
        value = item.raw_surface.get(key)
        try:
            if value not in (None, "") and float(value) == 0:
                return True
        except (TypeError, ValueError):
            continue
    return False


def _is_floor_thinned_collocation(item: EvidenceItem) -> bool:
    """True for a *successful* collocate_stats result that returned no rows.

    The min_freq reliability floor thinned every candidate. This is a valid
    linguistic finding, not a failure: the raw tool-parameter facts are then
    suppressed in favour of a linguistic floor statement (Haertung r4, Fix 4).
    """
    if item.tool != "collocate_stats":
        return False
    if str(item.status or "").strip().casefold() in {
        "error",
        "not_applicable",
        "unsupported",
        "unavailable",
    }:
        return False
    rows = item.raw_surface.get("rows")
    if isinstance(rows, list) and len(rows) > 0:
        return False
    for key in ("result_count", "rows_seen"):
        value = item.raw_surface.get(key)
        try:
            if value not in (None, "") and float(value) > 0:
                return False
        except (TypeError, ValueError):
            continue
    if isinstance(rows, list):
        return True
    for key in ("result_count", "rows_seen"):
        value = item.raw_surface.get(key)
        try:
            if value not in (None, "") and float(value) == 0:
                return True
        except (TypeError, ValueError):
            continue
    return False


def _evidence_query_args(item: EvidenceItem) -> Dict[str, Any]:
    try:
        args = json.loads(item.query) if item.query else {}
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return dict(args) if isinstance(args, dict) else {}


def _collocation_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    folded = str(value or "").strip().casefold()
    if folded in {"1", "true", "yes", "ja"}:
        return True
    if folded in {"0", "false", "no", "nein"}:
        return False
    return None


@dataclass(frozen=True)
class _CollocationProfileSignature:
    attribute: str
    window: int
    within_sentence: bool
    min_freq: int
    sort_by: str
    corpus_id: str
    docset_id: str

    @property
    def count_signature(self) -> Tuple[str, str, str]:
        return (self.attribute, self.corpus_id, self.docset_id)


def _effective_evidence_scope(item: EvidenceItem) -> Tuple[str, str] | None:
    """Return the executed scope; request arguments are not execution evidence."""

    scope = item.raw_surface.get("scope")
    if not isinstance(scope, dict):
        return None
    corpus_id = _normalise_example_text(scope.get("corpus_id"))
    if not corpus_id:
        return None
    return (
        corpus_id.casefold(),
        _normalise_example_text(scope.get("docset_id")),
    )


def _collocation_profile_record(
    item: EvidenceItem,
) -> Tuple[str, _CollocationProfileSignature] | None:
    """Return the effective node and method/scope of a completed profile."""

    if not _has_completed_collocation_profile(item):
        return None
    method = item.raw_surface.get("method")
    scope = _effective_evidence_scope(item)
    if not isinstance(method, dict) or scope is None:
        return None
    requested_term = _normalise_example_text(item.raw_surface.get("requested_term"))
    effective_term = _normalise_example_text(item.raw_surface.get("effective_term"))
    if not requested_term or (effective_term and effective_term != requested_term):
        return None
    attribute = _normalise_example_text(method.get("attribute")).casefold()
    sort_by = _normalise_example_text(item.raw_surface.get("sort_by")).casefold()
    within_sentence = _collocation_bool(item.raw_surface.get("within_sentence"))
    try:
        window = int(item.raw_surface["window"])
        min_freq = int(item.raw_surface["min_freq"])
    except (KeyError, TypeError, ValueError):
        return None
    if (
        attribute not in {"word", "lemma"}
        or not sort_by
        or within_sentence is None
        or window < 1
        or min_freq < 1
    ):
        return None
    return (
        requested_term,
        _CollocationProfileSignature(
            attribute=attribute,
            window=window,
            within_sentence=within_sentence,
            min_freq=min_freq,
            sort_by=sort_by,
            corpus_id=scope[0],
            docset_id=scope[1],
        ),
    )


def _collocation_profile_matches_request(
    signature: _CollocationProfileSignature,
    question_text: str,
) -> bool:
    requirements = same_corpus_collocation_method_requirements(question_text)
    return all(
        getattr(signature, key) == value
        for key, value in requirements.items()
    )


def _selected_collocation_profiles(
    question_text: str,
    evidence_items: Sequence[EvidenceItem],
) -> Tuple[List[EvidenceItem], bool]:
    """Select one shared-method profile per requested lexical form."""

    candidates = [
        item
        for item in evidence_items
        if _has_completed_collocation_profile(item)
    ]
    requested_terms = same_corpus_collocation_terms(question_text)
    if not requested_terms:
        return candidates[:4], True

    records: List[Tuple[EvidenceItem, str, _CollocationProfileSignature]] = []
    signature_order: List[_CollocationProfileSignature] = []
    for item in candidates:
        record = _collocation_profile_record(item)
        if record is None:
            continue
        term, signature = record
        if not _collocation_profile_matches_request(signature, question_text):
            continue
        records.append((item, term.casefold(), signature))
        if signature not in signature_order:
            signature_order.append(signature)

    requested_keys = [term.casefold() for term in requested_terms]
    common_signature = next(
        (
            signature
            for signature in signature_order
            if all(
                any(
                    term == requested_key
                    and candidate_signature == signature
                    for _item, term, candidate_signature in records
                )
                for requested_key in requested_keys
            )
        ),
        None,
    )
    if common_signature is not None:
        return [
            next(
                item
                for item, term, signature in records
                if term == requested_key and signature == common_signature
            )
            for requested_key in requested_keys
        ], True

    selected = [
        next(
            (
                item
                for item, term, _signature in records
                if term == requested_key
            ),
            None,
        )
        for requested_key in requested_keys
    ]
    return [item for item in selected if item is not None], False


def _matching_collocation_count_items(
    requested_terms: Sequence[str],
    profiles: Sequence[EvidenceItem],
    evidence_items: Sequence[EvidenceItem],
) -> Dict[str, EvidenceItem]:
    """Join node totals to profiles by term, attribute and executed scope."""

    profile_signatures = {
        record[1]
        for item in profiles
        if (record := _collocation_profile_record(item)) is not None
    }
    if len(profile_signatures) != 1:
        return {}
    required_signature = next(iter(profile_signatures)).count_signature
    requested_keys = {term.casefold() for term in requested_terms}
    matched: Dict[str, EvidenceItem] = {}
    for item in evidence_items:
        if (
            item.tool not in {"query_count", "run_cqlf_query"}
            or str(item.status or "").strip().casefold()
            in {"error", "not_applicable", "unsupported", "unavailable"}
            or item.raw_surface.get("total") in (None, "")
        ):
            continue
        attribute, term = _exact_lexical_search(item)
        scope = _effective_evidence_scope(item)
        if (
            term.casefold() not in requested_keys
            or scope is None
            or (attribute, scope[0], scope[1]) != required_signature
        ):
            continue
        matched.setdefault(term.casefold(), item)
    return matched


def same_corpus_collocation_evidence_gaps(
    contract: AnalysisContract,
    evidence_items: Sequence[EvidenceItem],
) -> List[str]:
    """Require one profile and one exact node count per named lexical form."""

    if contract.analysis_family != "collocation":
        return []
    terms = same_corpus_collocation_terms(contract.question_scope)
    if not terms:
        return []
    profiles, comparable = _selected_collocation_profiles(
        contract.question_scope,
        evidence_items,
    )
    profiled_terms = {
        record[0].casefold()
        for item in evidence_items
        if (record := _collocation_profile_record(item)) is not None
        and _collocation_profile_matches_request(record[1], contract.question_scope)
    }
    count_items = _matching_collocation_count_items(
        terms,
        profiles,
        evidence_items,
    )
    gaps: List[str] = []
    for term in terms:
        key = term.casefold()
        if key not in profiled_terms:
            gaps.append(_t(f"Kollokationsprofil für Wortform '{term}'", f"""Collocation profile for word form '{term}'"""))
        if "query_count" in contract.allowed_tools and key not in count_items:
            gaps.append(_t(f"Knotenfrequenz für Wortform '{term}'", f"""Node frequency for word form '{term}'"""))
    if len(profiled_terms.intersection(term.casefold() for term in terms)) == len(
        terms
    ) and not comparable:
        rendered_terms = ", ".join(f"'{term}'" for term in terms)
        gaps.append(
            _t("Direkt vergleichbare Kollokationsprofile für die Wortformen "
            f"{rendered_terms} mit identischem Attribut, Fenster, "
            "Satzgrenzenmodus, Mindestfrequenz, Sortiermaß und Korpus-Scope "
            "sowie Übereinstimmung mit ausdrücklich verlangten Parametern", f"""Directly comparable collocation profiles for word forms {rendered_terms}, with identical attribute, window, sentence boundaries, minimum frequency, sorting measure and corpus scope, matching any explicitly requested parameters""")
        )
    return gaps


_QUERY_DIAGNOSTIC_REQUEST_PATTERN = re.compile(
    r"\b(?:ungültig\w*|ungueltig\w*|malformed|invalid|syntaxfehler\w*|"
    r"syntaktisch\w*\s+fehlerhaft\w*)\b[^.!?\n]{0,180}"
    r"\b(?:diagnostizier\w*|erklär\w*|erklaer\w*|korrigier\w*|"
    r"fehler\w*|diagnos\w*)\b|"
    r"\b(?:diagnostizier\w*|diagnos\w*)\b[^.!?\n]{0,180}"
    r"\b(?:abfrage|query|syntax|fehler)\w*\b",
    re.IGNORECASE,
)


def _is_requested_query_diagnostic(
    contract: AnalysisContract,
    item: EvidenceItem,
) -> bool:
    if (
        item.tool not in {"run_cqlf_query", "query_count"}
        or str(item.status or "").strip().casefold() != "error"
        or _QUERY_DIAGNOSTIC_REQUEST_PATTERN.search(
            contract.question_scope or ""
        )
        is None
    ):
        return False
    return _structured_query_diagnostic(item) is not None


def _structured_query_diagnostic(
    item: EvidenceItem,
) -> tuple[str, List[str], List[str]] | None:
    """Return parser-owned diagnostics, never a generic runtime error."""

    raw = item.raw_surface if isinstance(item.raw_surface, dict) else {}
    query = _normalise_example_text(raw.get("query"))
    diagnostics = raw.get("diagnostics")
    if not query or not isinstance(diagnostics, dict):
        return None
    errors = [
        _normalise_example_text(error)
        for error in list(diagnostics.get("errors", []) or [])
        if _normalise_example_text(error)
    ]
    if not errors:
        return None
    suggestions = [
        _normalise_example_text(suggestion)
        for suggestion in list(diagnostics.get("suggestions", []) or [])
        if _normalise_example_text(suggestion)
    ]
    return query, errors, suggestions


def build_evidence_bundle(
    contract: AnalysisContract,
    items: Sequence[EvidenceItem],
) -> EvidenceBundle:
    saw_error = False
    saw_partial = False
    saw_truncated = False
    present_evidence = sorted(
        {
            kind
            for item in items
            for kind in evidence_kinds_for_item(item)
        }
    )
    effective_contract = effective_analysis_contract(contract, items)
    required_evidence = effective_contract.required_evidence
    missing_required_evidence = [
        kind
        for kind in required_evidence
        if kind not in set(present_evidence)
    ]
    missing_required_evidence = _dedupe_ordered_strs(
        missing_required_evidence
        + same_corpus_collocation_evidence_gaps(contract, items)
    )
    if not items:
        saw_error = True
    for item in items:
        if (
            str(item.status or "").strip().lower() == "error"
            and not _is_requested_query_diagnostic(contract, item)
        ):
            saw_error = True
        if item.partial or item.sampled:
            saw_partial = True
        if item.truncated:
            saw_truncated = True
            # A bounded evidence view (for example semantic Top-N or displayed
            # frequency rows) can still support a complete answer about that
            # explicitly bounded view. Exactness and limitation facts constrain
            # claim strength; only errors or missing required evidence fail closed.
    # Failed exploratory attempts remain diagnostic, but a later successful
    # call that supplies every required evidence kind supersedes them. Otherwise
    # a repaired malformed query would permanently downgrade a correct answer.
    unresolved_error = saw_error and (
        not required_evidence or bool(missing_required_evidence)
    )
    supports_full_answer = bool(items) and not (
        missing_required_evidence or saw_partial or unresolved_error
    )
    if missing_required_evidence:
        incomplete_reason = "missing_required_evidence"
    elif unresolved_error:
        incomplete_reason = "insufficient_evidence"
    elif saw_partial:
        incomplete_reason = "partial_evidence"
    elif saw_truncated:
        incomplete_reason = "truncated_evidence"
    else:
        incomplete_reason = ""
    return EvidenceBundle(
        contract=effective_contract.to_dict(),
        items=[
            item.to_dict(include_fact_surface=False)
            for item in items
        ],
        tool_sequence=[item.tool for item in items],
        grounding_surface=[
            line
            for item in items
            for line in item.grounding_surface[:8]
        ][:24],
        present_evidence=present_evidence,
        missing_required_evidence=missing_required_evidence,
        incomplete_reason=incomplete_reason,
        supports_full_answer=supports_full_answer,
    )


def required_evidence_fact_gaps(
    contract: AnalysisContract,
    observed_facts: Sequence[ObservedFact],
    evidence_items: Sequence[EvidenceItem],
) -> List[str]:
    required_evidence = effective_analysis_contract(
        contract,
        evidence_items,
    ).required_evidence
    if not required_evidence:
        return []
    if not evidence_items:
        return list(required_evidence)
    if not observed_facts:
        if contract.analysis_family == "open_research":
            present = {
                kind
                for item in evidence_items
                for kind in evidence_kinds_for_item(item)
            }
            return [kind for kind in required_evidence if kind not in present]
        return list(required_evidence)
    evidence_index = {
        str(item.id): item
        for item in evidence_items
        if str(item.id).strip()
    }
    covered: set[str] = set()
    for fact in observed_facts:
        for source_id in fact.source_evidence_ids:
            item = evidence_index.get(str(source_id))
            if item is None:
                continue
            covered.update(evidence_kinds_for_fact(fact, item))
    if contract.analysis_family == "open_research":
        covered.update(
            {
                kind
                for item in evidence_items
                for kind in evidence_kinds_for_item(item)
            }
        )
    return _dedupe_ordered_strs([
        kind
        for kind in required_evidence
        if kind not in covered
    ] + same_corpus_collocation_evidence_gaps(contract, evidence_items))


def parse_structured_payload(result: Any) -> Any:
    if isinstance(result, (dict, list)):
        if isinstance(result, list):
            return result
        choices = result.get("choices")
        if isinstance(choices, list) and choices:
            message = dict(choices[0].get("message", {}) or {})
            content = message.get("content")
            if isinstance(content, (dict, list)):
                return content
            if isinstance(content, str):
                return _extract_json(content)
    if isinstance(result, str):
        return _extract_json(result)
    return None


def unique_observed_fact_id(
    fact: ObservedFact,
    used_ids: set[str],
    *,
    ordinal: int,
) -> str:
    if fact.id not in used_ids:
        return fact.id
    seed = (
        f"{ordinal}|{fact.id}|{fact.fact_kind}|{fact.statement}|"
        + "|".join(fact.source_evidence_ids)
        + "|"
        + "|".join(fact.grounding_quotes)
    )
    digest = hashlib.blake2s(
        seed.encode("utf-8"),
        digest_size=6,
    ).hexdigest()
    prefix = fact.id[: 96 - len(digest) - 1]
    candidate = f"{prefix}~{digest}"
    counter = 2
    while candidate in used_ids:
        suffix = f"~{digest[:8]}{counter}"
        candidate = candidate[: 96 - len(suffix)] + suffix
        counter += 1
    return candidate


def normalise_observed_facts(raw: Any) -> List[ObservedFact]:
    if not isinstance(raw, list):
        return []
    result: List[ObservedFact] = []
    seen: set[str] = set()
    for index, item in enumerate(raw, start=1):
        fact = ObservedFact.from_raw(item)
        if fact is None:
            continue
        fact.id = unique_observed_fact_id(
            fact,
            seen,
            ordinal=index,
        )
        seen.add(fact.id)
        result.append(fact)
    return result


def _make_fact(
    *,
    fact_id: str,
    statement: str,
    fact_kind: str,
    source_evidence_id: str,
    grounding_quotes: Sequence[str],
    exactness: str,
    supports_claims: Sequence[str],
    limitations: Sequence[str] | None = None,
    statement_limit: int = 280,
    quote_limit: int = 220,
) -> ObservedFact | None:
    fact = ObservedFact(
        id=_compact_id(fact_id, 96),
        statement=_compact_text(statement, statement_limit),
        fact_kind=_normalise_enum(fact_kind, FACT_KINDS, "metadata"),
        source_evidence_ids=[_compact_id(source_evidence_id, 96)],
        grounding_quotes=_normalise_text_list(
            list(grounding_quotes),
            max_items=16,
            item_limit=quote_limit,
        ),
        exactness=_normalise_enum(exactness, EXACTNESS_VALUES, "exact"),
        supports_claims=[
            item
            for item in _normalise_text_list(list(supports_claims), max_items=6, item_limit=40)
            if item in CLAIM_SUPPORT_VALUES
        ],
        limitations=_normalise_text_list(list(limitations or []), max_items=4, item_limit=160),
    )
    if not fact.statement or not fact.grounding_quotes:
        return None
    return fact


def _item_exactness(item: EvidenceItem, *, sample_only: bool = False, top_n_only: bool = False) -> str:
    if item.sampled:
        return "sample_only"
    if item.partial:
        return "partial"
    if item.truncated:
        return "top_n_only" if top_n_only else "partial"
    if item.grounding_truncated and top_n_only:
        return "top_n_only"
    if sample_only:
        return "sample_only"
    return "exact"


def _limitation_facts_for_item(item: EvidenceItem) -> List[ObservedFact]:
    facts: List[ObservedFact] = []
    if item.partial or item.sampled:
        flags = [
            name
            for name, enabled in (
                ("partial", item.partial),
                ("sampled", item.sampled),
            )
            if enabled
        ]
        quote = next(
            (
                line
                for line in item.grounding_surface
                if any(line.startswith(f"{flag}=") for flag in flags)
            ),
            "",
        )
        statement = (
            _t("Die zurückgegebenen Einzelzeilen sind eine Stichprobe; "
            "korpusweite Zählungen oder andere explizit als vollständig "
            "ausgewiesene Kennwerte desselben Laufs bleiben davon unberührt.", 'The returned individual rows are a sample. Corpus-wide counts and other metrics explicitly reported as complete in the same run retain their full scope.')
            if item.sampled
            else
            _t("Die Tool-Ausgabe ist als Teilberechnung markiert; sie belegt "
            "keine vollständige Korpusauswertung.", 'The tool output is marked as a partial calculation. It does not establish a complete corpus analysis.')
        )
        fact = _make_fact(
            fact_id=f"{item.id}_partial_limitation",
            statement=statement,
            fact_kind="limitation",
            source_evidence_id=item.id,
            grounding_quotes=(
                [quote] if quote else list(item.grounding_surface[:1])
            ),
            exactness="sample_only" if item.sampled else "partial",
            supports_claims=[],
            limitations=[
                (
                    _t("Qualitative Deutungen beziehen sich nur auf die "
                    "gezogenen Zeilen; nicht sichtbare Treffer wurden nicht "
                    "inhaltlich geprüft.", 'Qualitative interpretations concern the sampled lines. Unseen matches were not examined for content.')
                    if item.sampled
                    else
                    _t("Aussagen über das vollständige Korpus sind daraus nicht "
                    "ableitbar.", 'These results do not establish claims about the complete corpus.')
                )
            ],
        )
        if fact is not None:
            facts.append(fact)
    if item.truncated:
        quote = next(
            (
                line
                for line in item.grounding_surface
                if line.startswith("truncated=")
            ),
            "",
        )
        is_kwic_window = item.tool == "run_cqlf_query"
        fact = _make_fact(
            fact_id=f"{item.id}_limitation",
            statement=(
                _t("Die exakte Gesamttrefferzahl ist bekannt, aber semantisch "
                "prüfbar sind nur die zurückgegebenen KWIC-Kontexte.", 'The exact total hit count is known, but only the returned concordance contexts can be examined for meaning.')
                if is_kwic_window
                else
                _t("Die zurückgegebene Ergebnisliste ist auf den sichtbaren "
                "Top-N-Ausschnitt begrenzt; belegt sind nur diese Ränge.", 'The returned result list contains a visible top-N excerpt. It establishes these ranks only.')
            ),
            fact_kind="limitation",
            source_evidence_id=item.id,
            grounding_quotes=(
                [quote] if quote else list(item.grounding_surface[:1])
            ),
            exactness="partial",
            supports_claims=[],
            limitations=[
                (
                    _t("Nicht zurückgegebene Kontexte wurden qualitativ nicht "
                    "analysiert.", 'Contexts that were not returned were not analysed qualitatively.')
                    if is_kwic_window
                    else
                    _t("Aussagen über niedrigere, nicht dargestellte Ränge sind "
                    "daraus nicht ableitbar.", 'Lower ranks outside the display cannot be assessed from this result.')
                )
            ],
        )
        if fact is not None:
            facts.append(fact)
    return facts


def _not_applicable_facts_for_item(item: EvidenceItem) -> List[ObservedFact]:
    if item.status.strip().lower() not in {"not_applicable", "unsupported", "unavailable"}:
        return []
    message = _normalise_example_text(item.raw_surface.get("message"))
    if not message:
        return []
    quotes = [
        line
        for line in item.grounding_surface
        if line.startswith("status=") or line.startswith("message=")
    ]
    fact = _make_fact(
        fact_id=f"{item.id}_not_applicable",
        statement=(
            _t(f"Die angeforderte Analyse mit dem Tool {item.tool} ist nicht anwendbar: "
            f"{message}", f"""The requested analysis with {item.tool} is not applicable: {message}""")
        ),
        fact_kind="negative_result",
        source_evidence_id=item.id,
        grounding_quotes=quotes,
        exactness="exact",
        supports_claims=["interpretation_anchor"],
        limitations=[message],
    )
    return [fact] if fact is not None else []


def _query_error_facts(item: EvidenceItem) -> List[ObservedFact]:
    if (
        item.tool not in {"run_cqlf_query", "query_count"}
        or item.status.strip().casefold() != "error"
    ):
        return []
    diagnostics = item.raw_surface.get("diagnostics")
    if not isinstance(diagnostics, dict):
        return []
    errors = [
        _normalise_example_text(value)
        for value in list(diagnostics.get("errors") or [])
        if _normalise_example_text(value)
    ]
    suggestions = [
        _normalise_example_text(value)
        for value in list(diagnostics.get("suggestions") or [])
        if _normalise_example_text(value)
    ]
    query = _normalise_example_text(item.raw_surface.get("query"))
    quotes = [
        line
        for line in item.grounding_surface
        if line.startswith("query=")
        or line.startswith("message=")
        or line.startswith("diagnostics.")
    ]
    if not errors or not query:
        return []
    facts: List[ObservedFact] = []
    error_fact = _make_fact(
        fact_id=f"{item.id}_query_error",
        statement=(
            _t(f"Die wörtlich ausgeführte CQLF-Abfrage '{query}' wurde wegen "
            f"folgender Syntaxdiagnose abgelehnt: {', '.join(errors)}.", f"""The executed CQLF query '{query}' was rejected with this syntax diagnostic: {', '.join(errors)}.""")
        ),
        fact_kind="negative_result",
        source_evidence_id=item.id,
        grounding_quotes=quotes,
        exactness="exact",
        supports_claims=["interpretation_anchor"],
        limitations=[_t("Für die ungültige Abfrage liegen keine Treffer vor.", 'No hit results are available for the invalid query.')],
    )
    if error_fact is not None:
        facts.append(error_fact)
    if suggestions:
        suggestion_fact = _make_fact(
            fact_id=f"{item.id}_query_suggestion",
            statement=(
                _t("Die deterministische Syntaxdiagnostik schlägt als korrigierte, "
                f"in diesem fehlgeschlagenen Lauf noch nicht ausgeführte Fassung "
                f"'{suggestions[0]}' vor.", f"""The deterministic syntax diagnostic suggests '{suggestions[0]}' as a corrected query. It has not been executed in this failed run.""")
            ),
            fact_kind="metadata",
            source_evidence_id=item.id,
            grounding_quotes=quotes,
            exactness="derived",
            supports_claims=["interpretation_anchor"],
            limitations=[_t("Der Korrekturvorschlag wurde nicht automatisch ausgeführt.", 'The suggested correction was not executed automatically.')],
        )
        if suggestion_fact is not None:
            facts.append(suggestion_fact)
    return facts


def _semantic_meta_search_mode(item: EvidenceItem) -> str:
    meta = item.raw_surface.get("meta")
    if not isinstance(meta, dict):
        return ""
    value = meta.get("exactness")
    candidate_generation = meta.get("candidateGeneration")
    if value in (None, "") and isinstance(candidate_generation, dict):
        value = candidate_generation.get("searchMode")
    return str(value or "").strip().lower()


def _semantic_item_exactness(item: EvidenceItem) -> str:
    if item.truncated:
        return "top_n_only"
    mode = _semantic_meta_search_mode(item)
    if mode in {"exact", "approximate"}:
        return "top_n_only"
    if mode == "unknown":
        return "partial"
    return "top_n_only"


def _semantic_meta_limitations(item: EvidenceItem) -> List[str]:
    try:
        query_args = json.loads(item.query) if item.query else {}
    except (TypeError, ValueError, json.JSONDecodeError):
        query_args = {}
    if not isinstance(query_args, dict):
        query_args = {}
    search_text = _normalise_example_text(
        query_args.get("term") or query_args.get("query")
    )
    search_scope = (
        f" nach '{search_text}'" if search_text else ""
    )
    score_kinds = _semantic_row_score_kinds(item.raw_surface.get("rows"))
    vector_candidates = _semantic_candidate_generation_uses_vectors(
        item.raw_surface
    )
    if score_kinds == ["lexical"] and vector_candidates:
        limitations: List[str] = [
            _t("Die semantische Suche"
            f"{search_scope} erzeugt ihre Kandidaten einbettungsbasiert und "
            "ordnet die sichtbare Top-N-Liste lexikalisch priorisiert. Die "
            "ausgewiesenen lexikalischen Scores sind keine "
            "Einbettungsähnlichkeiten; die Treffer bilden zudem keine "
            "vollständige Themenverteilung des Korpus.", f"""Semantic search{search_scope} generates candidates using embeddings and ranks the visible top-N list with lexical priority. The reported lexical scores are not embedding similarities. The matches do not establish a complete topic distribution across the corpus.""")
        ]
    elif score_kinds == ["lexical"]:
        limitations: List[str] = [
            _t("Die semantische Suche"
            f"{search_scope} musste ersatzweise lexikalisch ranken. Die "
            "sichtbaren Top-N-Treffer belegen daher weder "
            "Einbettungsähnlichkeit noch eine vollständige Themenverteilung.", f"""Semantic search{search_scope} used lexical ranking as a fallback. The visible top-N matches establish neither embedding similarity nor a complete topic distribution.""")
        ]
    else:
        limitations = [
            _t("Die semantische Suche"
            f"{search_scope} liefert eine nach Ähnlichkeit zum freien Suchtext "
            "geordnete Top-N-Auswahl. Die sichtbaren Top-N-Treffer bilden "
            "weder eine vollständige "
            "Themenverteilung des Korpus noch eine lexikalische Treffermenge.", f"""Semantic search{search_scope} returns a top-N selection ranked by similarity to the free-text query. The visible matches establish neither a complete topic distribution across the corpus nor an exact lexical hit population.""")
        ]
    if "lexical" in score_kinds and score_kinds != ["lexical"]:
        limitations.append(
            _t("Die sichtbare Trefferliste mischt lexikalische und einbettungsbasierte "
            "Scores; deren Ränge sind methodisch nicht unmittelbar vergleichbar.", 'The visible result list mixes lexical and embedding scores. Their ranks are not directly comparable.')
        )
    fallback = item.raw_surface.get("fallback")
    if isinstance(fallback, dict):
        requested_level = str(fallback.get("requested_level", "") or "").strip()
        used_level = str(fallback.get("used_level", "") or "").strip()
        if requested_level and used_level and requested_level != used_level:
            requested_label = {
                "sentence": _t("Satzebene", 'sentence level'),
                "doc": _t("Dokumentebene", 'document level'),
            }.get(requested_level, requested_level)
            used_label = {
                "sentence": _t("Satzebene", 'sentence level'),
                "doc": _t("Dokumentebene", 'document level'),
            }.get(used_level, used_level)
            limitations.append(
                _t(f"Gesucht wurde auf {requested_label}; verfügbar war nur die "
                f"{used_label}. Thema und Bewertung lassen sich deshalb nicht "
                "einem isolierten Satz zuordnen.", f"""The requested search unit was {requested_label}, but only {used_label} was available. Topic and evaluation therefore cannot be assigned to an isolated sentence.""")
            )
    mode = _semantic_meta_search_mode(item)
    if mode == "approximate":
        limitations.append(
            _t("Die semantische Kandidatensuche ist als approximate markiert; Aussagen nur als Top-N-/Ranking-Evidenz behandeln.", 'Semantic candidate retrieval is marked approximate. These results provide top-N ranking evidence.')
        )
    elif mode == "unknown":
        limitations.append(
            _t("Der Kandidatenmodus der semantischen Suche ist unbekannt; Aussagen nur konservativ aus sichtbaren Treffern ableiten.", 'The semantic candidate retrieval mode is unknown. Interpretations must be based on the visible matches.')
        )
    return limitations


def _semantic_meta_limitation_facts(item: EvidenceItem) -> List[ObservedFact]:
    limitations = _semantic_meta_limitations(item)
    if not limitations:
        return []
    quotes = [
        line
        for line in item.grounding_surface
        if line.startswith(
            (
                "tool_args=",
                "truncated=",
                "exactness=",
                "searchMode=",
                "fallback=",
            )
        )
    ]
    fact = _make_fact(
        fact_id=f"{item.id}_semantic_meta_limitation",
        statement=limitations[0],
        fact_kind="limitation",
        source_evidence_id=item.id,
        grounding_quotes=quotes[:2] or list(item.grounding_surface[:1]),
        exactness=_semantic_item_exactness(item),
        supports_claims=[],
        limitations=limitations,
    )
    return [fact] if fact is not None else []


def _frequency_row_facts(item: EvidenceItem) -> List[ObservedFact]:
    rows = item.raw_surface.get("rows")
    if not isinstance(rows, list):
        return []
    try:
        query_args = json.loads(item.query) if item.query else {}
    except (TypeError, ValueError, json.JSONDecodeError):
        query_args = {}
    group_by = str(
        query_args.get("group_by", "word")
        if isinstance(query_args, dict)
        else "word"
    ).strip().casefold() or "word"
    pos_filter = (
        str(query_args.get("pos", "") or "").strip()
        if isinstance(query_args, dict)
        else ""
    )
    scope_bits = [
        f"{key}={query_args.get(key)}"
        for key in ("group_by", "pos")
        if isinstance(query_args, dict)
        and query_args.get(key) not in (None, "")
    ]
    scope_suffix = (
        _t(" in der getrennten Auswertung (", ' in the separate analysis (') + ", ".join(scope_bits) + ")"
        if scope_bits
        else ""
    )
    query_quote = (
        next(
            (
                line
                for line in item.grounding_surface
                if line.startswith("tool_args=")
            ),
            "",
        )
        if scope_bits
        else ""
    )
    unit_scope = {
        "word": _t(" für Oberflächenformen", ' for surface forms'),
        "lemma": _t(" für Lemmata", ' for lemmas'),
        "pos": _t(" für POS-Kategorien", ' for POS categories'),
    }.get(group_by, "")
    stopwords = (
        query_args.get("stopwords")
        if isinstance(query_args, dict)
        else None
    )
    stopword_count = (
        len(
            {
                str(value).strip()
                for value in stopwords
                if str(value).strip()
            }
        )
        if isinstance(stopwords, list)
        else 0
    )
    filter_suffix = (
        _t(f" Der Aufruf schließt genau {stopword_count} explizit angegebene "
        "Wortformen aus.", f""" The call excludes exactly {stopword_count} explicitly specified word forms.""")
        if stopword_count
        else ""
    )
    dimension_limitations: List[str] = []
    if group_by == "word" and not pos_filter:
        dimension_limitations.append(
            _t("Die Zeile ist nach Oberflächenform gruppiert und enthält keinen "
            "POS-Filter; sie belegt keine Wortartzuweisung für sämtliche "
            "Vorkommen der Form.", 'The row is grouped by surface form without a POS filter. It does not establish a POS assignment for every occurrence of the form.')
        )
    elif group_by == "word" and pos_filter:
        dimension_limitations.append(
            _t(f"Die Zeile zählt Oberflächenformen innerhalb des Filters "
            f"pos={pos_filter}; sie belegt keine Wortartzuweisung außerhalb "
            "dieses gefilterten Laufs.", f"""The row counts surface forms within pos={pos_filter}. POS assignments outside this filtered run are not established.""")
        )
    facts: List[ObservedFact] = []
    for index, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            continue
        word = _normalise_example_text(row.get("word") or row.get("kw"))
        count = row.get("f")
        rank = row.get("rank")
        if rank in (None, ""):
            rank = index
        per_million = row.get("per_million")
        if not word or count in (None, ""):
            continue
        quotes = [
            line
            for line in (
                # H11.8: NICHT 'row[i]'. Ein Fakt wird ueber seine ID
                # zitiert, nicht ueber einen rows-Pfad. Die alte
                # Beschriftung sah wie ein Referenzpfad aus, war aber
                # keiner, und sie zaehlte zudem gegenlaeufig zur
                # Itemoberflaeche. Zwei Bedeutungen von 'row[1]' im selben
                # Kontext sind eine Einladung zum Fehlgriff.
                _row_quote("zeile", index, row),
                _metric_quote(index, row),
                f"rank={index}",
                query_quote,
                (
                    f"stopword_count={stopword_count}"
                    if stopword_count
                    else ""
                ),
            )
            if line
        ]
        supports = ["counts", "interpretation_anchor"]
        normalisation_suffix = (
            _t(f" und per_million={per_million}", f" and per_million={per_million}")
            if per_million not in (None, "")
            else ""
        )
        handle_quality_signal = bool(word.startswith("@") and pos_filter)
        visible_label = (
            _t(f"die handleartige Form '{word}' (sichtbares Annotations- oder "
            f"Tokenisierungs-Prüfsignal für pos={pos_filter})", f"""the handle-like form '{word}' (visible annotation or tokenisation signal to review for pos={pos_filter})""")
            if handle_quality_signal
            else f"'{word}'"
        )
        if rank not in (None, ""):
            supports.append("ranks")
            statement = (
                _t(f"Die sichtbare Frequenzzeile{unit_scope}{scope_suffix} "
                f"zeigt {visible_label} "
                f"auf Rang {rank} "
                f"mit f={count}{normalisation_suffix}; "
                "f ist die Zählung im gewählten Korpus- oder "
                f"Subkorpus-Scope.{filter_suffix}", f"""The visible frequency row{unit_scope}{scope_suffix} shows {visible_label} at rank {rank} with f={count}{normalisation_suffix}. f is the count within the selected corpus or subcorpus scope.{filter_suffix}""")
            )
            fact_kind = "ranked_row"
        else:
            statement = (
                _t(f"Die sichtbare Frequenzzeile{unit_scope}{scope_suffix} "
                f"zeigt {visible_label} "
                f"mit f={count}{normalisation_suffix}; "
                "f ist die Zählung im gewählten Korpus- oder Subkorpus-Scope."
                f"{filter_suffix}", f"""The visible frequency row{unit_scope}{scope_suffix} shows {visible_label} with f={count}{normalisation_suffix}. f is the count within the selected corpus or subcorpus scope.{filter_suffix}""")
            )
            fact_kind = "count"
        row_limitations = [
            _t("Die Rangliste ist auf sichtbare Top-N-Einträge begrenzt; "
            "diese Begrenzung macht die f-Werte der sichtbaren Einträge "
            "nicht zu Stichprobenzählungen.", 'The ranking shows visible top-N entries. This display limit does not make their f values sample counts.'),
            *dimension_limitations,
        ]
        if handle_quality_signal:
            row_limitations.append(
                _t("Aus der handleartigen Form allein folgen weder eine "
                "Nutzeridentität noch eine korrekte POS-Zuweisung.", 'A handle-like form alone establishes neither user identity nor correct POS assignment.')
            )
        fact = _make_fact(
            fact_id=f"{item.id}_freq_{index}",
            statement=statement,
            fact_kind=fact_kind,
            source_evidence_id=item.id,
            grounding_quotes=quotes,
            exactness=_item_exactness(item, top_n_only=True),
            supports_claims=supports,
            limitations=row_limitations,
        )
        if fact is not None:
            facts.append(fact)
    return facts


def _frequency_pos_scope_fact(item: EvidenceItem) -> List[ObservedFact]:
    try:
        query_args = json.loads(item.query) if item.query else {}
    except (TypeError, ValueError, json.JSONDecodeError):
        query_args = {}
    if not isinstance(query_args, dict) or query_args.get("group_by") != "pos":
        return []
    rows_seen = item.raw_surface.get("rows_seen")
    total = item.raw_surface.get("total")
    if rows_seen in (None, "") and total in (None, ""):
        return []
    quotes = [
        _compact_text(f"{key}={value}", 220)
        for key, value in (("rows_seen", rows_seen), ("total", total))
        if value not in (None, "")
    ]
    query_quote = next(
        (line for line in item.grounding_surface if line.startswith("tool_args=")),
        "",
    )
    if query_quote:
        quotes.append(query_quote)
    scope_fact = _make_fact(
        fact_id=f"{item.id}_pos_scope",
        statement=(
            _t("Die POS-Frequenzausgabe (group_by=pos) meldet ", 'The POS frequency output (group_by=pos) reports ')
            + ", ".join(
                f"{key}={value}"
                for key, value in (("rows_seen", rows_seen), ("total", total))
                if value not in (None, "")
            )
            + _t(" Kategorien.", ' categories.')
        ),
        fact_kind="distribution",
        source_evidence_id=item.id,
        grounding_quotes=quotes,
        exactness="exact",
        supports_claims=["counts", "interpretation_anchor"],
        limitations=[
            _t("Die Kardinalität beschreibt den vollständigen Tool-Output; "
            "im Modellkontext können nur einzelne Zeileninhalte sichtbar sein.", 'The cardinality describes the complete tool output. The model context may show the contents of only some rows.')
        ],
    )
    facts = [scope_fact] if scope_fact is not None else []

    rows = item.raw_surface.get("rows")
    denominator_tokens = item.raw_surface.get("denominator_tokens")
    complete_rows = (
        isinstance(rows, list)
        and not item.truncated
        and rows_seen not in (None, "")
        and total not in (None, "")
        and int(rows_seen) == int(total) == len(rows)
    )
    if complete_rows and denominator_tokens not in (None, ""):
        try:
            pos_counted_tokens = sum(
                int(row["f"])
                for row in rows
                if isinstance(row, dict) and row.get("f") not in (None, "")
            )
            denominator = int(denominator_tokens)
        except (KeyError, TypeError, ValueError):
            pos_counted_tokens = -1
            denominator = -1
        if pos_counted_tokens >= 0 and denominator >= 0:
            difference = denominator - pos_counted_tokens
            coverage_fact = _make_fact(
                fact_id=f"{item.id}_pos_token_accounting",
                statement=(
                    _t(f"Die {len(rows)} vollständig zurückgegebenen POS-Zeilen "
                    f"summieren sich auf {pos_counted_tokens} gezählte "
                    f"Tokenzuweisungen; der ausgewiesene Nenner umfasst "
                    f"{denominator} Tokens, die Differenz beträgt "
                    f"{difference}.", f"""The {len(rows)} fully returned POS rows sum to {pos_counted_tokens} counted token assignments. The reported denominator contains {denominator} tokens, a difference of {difference}.""")
                ),
                fact_kind="distribution",
                source_evidence_id=item.id,
                grounding_quotes=[
                    _compact_text(
                        f"rows_seen={len(rows)}",
                        220,
                    ),
                    _compact_text(
                        f"sum(pos_rows[*].f)={pos_counted_tokens}",
                        220,
                    ),
                    _compact_text(
                        f"denominator_tokens={denominator}",
                        220,
                    ),
                    _compact_text(
                        f"denominator_minus_pos_sum={difference}",
                        220,
                    ),
                ],
                exactness="derived",
                supports_claims=[
                    "counts",
                    "interpretation_anchor",
                ],
                limitations=[
                    _t("Die Differenz belegt allein weder fehlende POS-Tags noch "
                    "einen Taggingfehler; Marker-, Filter- und "
                    "Indexierungsregeln müssen dafür separat geprüft werden.", 'This difference alone establishes neither missing POS tags nor a tagging error. Marker, filter and indexing rules require separate examination.')
                ],
            )
            if coverage_fact is not None:
                facts.append(coverage_fact)
    return facts


def _frequency_scope_facts(item: EvidenceItem) -> List[ObservedFact]:
    """Expose the exact token denominator instead of letting prose guess it."""
    corpus_tokens = item.raw_surface.get("corpus_tokens")
    if corpus_tokens in (None, ""):
        return []
    denominator_tokens = item.raw_surface.get("denominator_tokens")
    denominator_scope = _normalise_example_text(
        item.raw_surface.get("denominator_scope")
    )
    denominator_source = _normalise_example_text(
        item.raw_surface.get("denominator_source")
    )
    quotes = [_compact_text(f"corpus_tokens={corpus_tokens}", 220)]
    scope_bits: List[str] = []
    for key, value in (
        ("denominator_tokens", denominator_tokens),
        ("denominator_scope", denominator_scope),
        ("denominator_source", denominator_source),
    ):
        if value not in (None, ""):
            quotes.append(_compact_text(f"{key}={value}", 220))
            scope_bits.append(f"{key}={value}")
    scope_suffix = (
        _t(" Der Normalisierungsnenner ist explizit als ", ' The normalisation denominator is explicitly marked as ')
        + "; ".join(scope_bits)
        + _t(" ausgewiesen.", '.')
        if scope_bits
        else ""
    )
    fact = _make_fact(
        fact_id=f"{item.id}_corpus_tokens",
        statement=(
            _t("Die Frequenzauswertung weist für den gewählten Korpus- oder "
            f"Subkorpus-Scope corpus_tokens={corpus_tokens} als "
            f"Gesamtkorpusgröße aus.{scope_suffix}", f"""The frequency analysis reports corpus_tokens={corpus_tokens} as the total size of the selected corpus or subcorpus scope.{scope_suffix}""")
        ),
        fact_kind="count",
        source_evidence_id=item.id,
        grounding_quotes=quotes,
        exactness="exact",
        supports_claims=["counts", "interpretation_anchor"],
    )
    return [fact] if fact is not None else []


def _query_count_facts(item: EvidenceItem) -> List[ObservedFact]:
    """Q3: exakter Einzelterm-Count mit seiner Normalisierungsbasis."""
    facts: List[ObservedFact] = _frequency_scope_facts(item)
    total = item.raw_surface.get("total")
    if total in (None, ""):
        return facts
    query = str(item.raw_surface.get("query") or "").strip()
    if not query and item.query:
        try:
            query_args = json.loads(item.query)
        except (TypeError, ValueError, json.JSONDecodeError):
            query_args = {}
        if isinstance(query_args, dict):
            query = str(query_args.get("query") or "").strip()
    quotes = [_compact_text(f"total={total}", 220)]
    if query:
        query_quote = next(
            (
                line
                for line in item.grounding_surface
                if line == f"query={query}"
                or line.startswith("analysis_input=")
                or line.startswith("tool_args=")
            ),
            "",
        )
        if query_quote:
            quotes.append(query_quote)
        # H10/G2 Term-Provenienz: das total gehoert GENAU zu dieser Query.
        # Die Paarbindung (claim_rules.term_binding) liest das Paar
        # total=/query= aus den Zitaten; deshalb wird die Provenienz-Zeile
        # synthetisiert, wenn die Surface sie nicht woertlich traegt
        # (deterministic_observed_facts nimmt Fakten-Zitate in die
        # Validierungs-Surface auf, der Validator akzeptiert sie also).
        if not query_quote or not query_quote.startswith("query="):
            quotes.append(_compact_text(f"query={query}", 220))
    if query and re.search(r"\blemma\s*(?:=|in\b)", query, re.IGNORECASE):
        query_description = _t(f"die explizite Lemma-Abfrage '{query}'", f"""the explicit lemma query '{query}'""")
    elif query:
        query_description = _t(f"die Klartext- oder CQLF-Suchanfrage '{query}'", f"""the plain-text or CQLF query '{query}'""")
    else:
        query_description = _t("die übergebene Suchanfrage", 'the submitted query')
    fact = _make_fact(
        fact_id=f"{item.id}_total",
        statement=(
            _t(f"Die exakte Trefferzahl für {query_description} "
            f"(query_count) ist total={total}.", f"""The exact hit count for {query_description} (query_count) is total={total}.""")
        ),
        fact_kind="count",
        source_evidence_id=item.id,
        grounding_quotes=quotes,
        exactness="exact",
        supports_claims=["counts", "comparisons", "interpretation_anchor"],
    )
    if fact is not None:
        facts.append(fact)
    pmw = item.raw_surface.get("per_million")
    if pmw not in (None, ""):
        pmw_fact = _make_fact(
            fact_id=f"{item.id}_pmw",
            statement=(
                _t(f"Die vorgerechnete Normalisierung ist per_million={pmw} "
                "pro Million Wortformen ohne Satzzeichen (denominator_tokens).", f"""The calculated normalisation is per_million={pmw} per million word forms excluding punctuation (denominator_tokens).""")
            ),
            fact_kind="count",
            source_evidence_id=item.id,
            grounding_quotes=[_compact_text(f"per_million={pmw}", 220)],
            exactness="exact",
            supports_claims=[
                "counts",
                "comparisons",
                "interpretation_anchor",
            ],
        )
        if pmw_fact is not None:
            facts.append(pmw_fact)
    return facts


def _collocation_method_facts(item: EvidenceItem) -> List[ObservedFact]:
    if item.tool != "collocate_stats" or not item.query:
        return []
    # Fix 4: floor-thinned collocations get a linguistic floor fact instead of
    # the raw method parameters (requested_term/term_mode/attribute).
    if _is_floor_thinned_collocation(item):
        return []
    try:
        args = json.loads(item.query)
    except (TypeError, ValueError, json.JSONDecodeError):
        return []
    if not isinstance(args, dict):
        return []
    raw_method = item.raw_surface.get("method")
    raw_attribute = raw_method.get("attribute") if isinstance(raw_method, dict) else None
    scope = item.raw_surface.get("scope")
    scope = scope if isinstance(scope, dict) else {}
    requested_term = item.raw_surface.get("requested_term") or args.get("term")
    effective_term = item.raw_surface.get("effective_term") or args.get("term")
    term_mode = item.raw_surface.get("term_mode")
    settings = [
        f"{key}={value}"
        for key, value in (
            ("requested_term", requested_term),
            ("effective_term", effective_term),
            ("term_mode", term_mode),
            ("attribute", raw_attribute),
            ("window", item.raw_surface.get("window")),
            ("within_sentence", item.raw_surface.get("within_sentence")),
            ("min_freq", item.raw_surface.get("min_freq")),
            ("sort_by", item.raw_surface.get("sort_by")),
            ("corpus_id", scope.get("corpus_id")),
            ("docset_id", scope.get("docset_id")),
        )
        if value not in (None, "")
    ]
    quotes = [
        line
        for line in item.grounding_surface
        if line.startswith(
            (
                "requested_term=",
                "effective_term=",
                "term_mode=",
                "window=",
                "within_sentence=",
                "min_freq=",
                "sort_by=",
                "scope:",
                "method:",
            )
        )
    ]
    if not settings or not quotes:
        return []
    # H6 (B6): Bei adaptiv gesenktem Floor (<5) sind nicht-leere Ergebnisse
    # deterministisch als explorativ zu kennzeichnen. min_freq und rows
    # werden defensiv aus dem Tool-Output gelesen. Fehlt min_freq oder ist
    # das Ergebnis leer: Alt-Verhalten ohne Zusatz-Limitation.
    rows = item.raw_surface.get("rows")
    result_is_nonempty = isinstance(rows, list) and len(rows) > 0
    if not result_is_nonempty:
        for count_key in ("result_count", "rows_seen"):
            count_value = item.raw_surface.get(count_key)
            try:
                if count_value not in (None, "") and float(count_value) > 0:
                    result_is_nonempty = True
                    break
            except (TypeError, ValueError):
                continue
    try:
        effective_floor = int(item.raw_surface.get("min_freq"))
    except (TypeError, ValueError):
        effective_floor = None
    method_limitations: List[str] = []
    if result_is_nonempty and effective_floor is not None and 1 <= effective_floor < 5:
        method_limitations.append(
            _t("Explorativ, n klein: Floor adaptiv unter 5. Nach f berichten, "
            "keine Signifikanz aus ll/chi2/t, Kollokate mit KWIC-Beleg "
            "absichern.", 'Exploratory, small n: adaptive frequency threshold below 5. Report f. Significance from ll/chi2/t is not established. Check collocates against concordance evidence.')
        )
    fact = _make_fact(
        fact_id=f"{item.id}_method",
        statement=(
            _t("Die sichtbare Kollokationsausgabe wurde mit ", 'The visible collocation output was calculated with ')
            + "; ".join(settings)
            + _t(" berechnet.", '.')
        ),
        fact_kind="metadata",
        source_evidence_id=item.id,
        grounding_quotes=quotes,
        exactness="exact",
        supports_claims=["interpretation_anchor"],
        limitations=method_limitations,
    )
    facts = [fact] if fact is not None else []
    if (
        requested_term not in (None, "")
        and effective_term not in (None, "")
        and str(requested_term) != str(effective_term)
    ):
        mismatch_fact = _make_fact(
            fact_id=f"{item.id}_node_mismatch",
            statement=(
                _t(f"Der angefragte Kollokationsknoten '{requested_term}' wurde "
                f"nicht unverändert ausgewertet; der effektive Knoten lautet "
                f"'{effective_term}' (term_mode={term_mode}).", f"""The requested collocation node '{requested_term}' was evaluated as '{effective_term}' (term_mode={term_mode}).""")
            ),
            fact_kind="limitation",
            source_evidence_id=item.id,
            grounding_quotes=[
                line
                for line in item.grounding_surface
                if line.startswith("requested_term=")
                or line.startswith("effective_term=")
                or line.startswith("term_mode=")
            ],
            exactness="exact",
            supports_claims=["interpretation_anchor"],
            limitations=[
                _t("Dieses Ergebnis darf nicht als unverändertes "
                "Oberflächenform-Profil beschrieben werden.", 'This result must not be described as an unchanged surface-form profile.')
            ],
        )
        if mismatch_fact is not None:
            facts.append(mismatch_fact)
    return facts


def _collocation_comparison_facts(
    contract: AnalysisContract,
    evidence_items: Sequence[EvidenceItem],
) -> List[ObservedFact]:
    """Expose the one shared-method comparison selected for reporting."""

    if contract.analysis_family != "collocation":
        return []
    requested_terms = same_corpus_collocation_terms(
        contract.question_scope
    )
    if len(requested_terms) < 2:
        return []
    profiles, comparable = _selected_collocation_profiles(
        contract.question_scope,
        evidence_items,
    )
    if not comparable or len(profiles) != len(requested_terms):
        return []

    count_items = _matching_collocation_count_items(
        requested_terms,
        profiles,
        evidence_items,
    )
    if any(term.casefold() not in count_items for term in requested_terms):
        return []

    profile_records: List[Tuple[str, EvidenceItem, int]] = []
    for term, item in zip(requested_terms, profiles):
        rows_seen = item.raw_surface.get("rows_seen")
        if rows_seen in (None, ""):
            rows_seen = item.raw_surface.get("result_count")
        if rows_seen in (None, "") and isinstance(
            item.raw_surface.get("rows"), list
        ):
            rows_seen = len(item.raw_surface["rows"])
        try:
            visible_rows = int(rows_seen)
        except (TypeError, ValueError):
            return []
        profile_records.append((term, item, visible_rows))

    first_record = _collocation_profile_record(profiles[0])
    if first_record is None:
        return []
    first_signature = first_record[1]
    method_values = {
        "attribute": first_signature.attribute,
        "window": first_signature.window,
        "within_sentence": first_signature.within_sentence,
        "min_freq": first_signature.min_freq,
        "sort_by": first_signature.sort_by,
        "corpus_id": first_signature.corpus_id,
        "docset_id": first_signature.docset_id,
    }
    method_values = {
        key: value for key, value in method_values.items() if value not in (None, "")
    }

    source_items = [
        *profiles,
        *[count_items[term.casefold()] for term in requested_terms],
    ]
    source_ids = _dedupe_ordered_strs([item.id for item in source_items])
    quotes = _dedupe_ordered_strs(
        [
            line
            for item in source_items
            for line in item.grounding_surface
            if line.startswith(
                (
                    "tool_args=",
                    "rows_seen=",
                    "result_count=",
                    "total=",
                    "query=",
                    "analysis_input=",
                    "window=",
                    "within_sentence=",
                    "min_freq=",
                    "sort_by=",
                    "scope:",
                    "method:",
                )
            )
        ]
    )[:16]
    if not quotes:
        return []

    result_parts: List[str] = []
    for term, _profile, rows_seen in profile_records:
        total = count_items[term.casefold()].raw_surface.get("total")
        result_parts.append(
            f"{term}: node_total={total}; rows_seen={rows_seen}"
        )
    statement = _compact_text(
        _t("Die direkt vergleichbaren Kollokationsprofile ", 'The directly comparable collocation profiles ')
        + "("
        + "; ".join(
            f"{key}={value}" for key, value in method_values.items()
        )
        + _t(") ergeben ", ') yield ')
        + _t(" und ", ' and ').join(result_parts)
        + ".",
        280,
    )
    return [
        ObservedFact(
            id=_compact_id(
                "collocation_comparison_"
                + "_".join(term.casefold() for term in requested_terms),
                96,
            ),
            statement=statement,
            fact_kind="distribution",
            source_evidence_ids=source_ids,
            grounding_quotes=quotes,
            exactness="derived",
            supports_claims=[
                "counts",
                "comparisons",
                "interpretation_anchor",
            ],
            limitations=[
                _t("Dieselbe absolute Mindestfrequenz ist relativ zum kleineren "
                "Knoten strenger; der Zeilenunterschied trennt Schwellenwirkung "
                "und Gebrauchsmuster deshalb nicht.", 'The same absolute minimum frequency is relatively stricter for the less frequent node. The row difference therefore does not separate threshold effects from usage patterns.')
            ],
        )
    ]


def _collocation_floor_facts(
    contract: AnalysisContract,
    evidence_items: Sequence[EvidenceItem],
) -> List[ObservedFact]:
    """Linguistic floor fact for a collocation whose reliability floor thinned
    out every candidate (Haertung r4, Fix 4).

    Replaces the raw method/row-count parameters with a sentence about the
    node and the min_freq floor. The node frequency N is only stated when a
    matching same-term ``query_count`` / ``run_cqlf_query`` total is in the
    turn evidence (grounded, never fabricated); otherwise the sentence is
    phrased without it.
    """
    facts: List[ObservedFact] = []
    # H5, Fix 4: EIN Floor-Fakt je Knoten. Ruft das Modell collocate_stats
    # mehrfach mit Schreibvarianten desselben Worts auf (Arbeit / Arbeit /
    # arbeit), duennt der Floor jede Variante aus. Ohne Dedup wiederholt die
    # Antwort denselben Floor-Satz je Variante. Der Knoten wird casefold-
    # normalisiert verglichen, damit Varianten desselben Worts kollabieren.
    seen_terms: set[str] = set()
    for item in evidence_items:
        if not _is_floor_thinned_collocation(item):
            continue
        term = _normalise_example_text(
            item.raw_surface.get("requested_term")
            or item.raw_surface.get("effective_term")
        )
        if not term:
            continue
        term_key = term.casefold()
        if term_key in seen_terms:
            continue
        min_freq = item.raw_surface.get("min_freq")
        floor_quote = next(
            (
                line
                for line in item.grounding_surface
                if line == f"min_freq={min_freq}"
            ),
            "",
        )
        zero_quote = next(
            (
                line
                for line in item.grounding_surface
                if line in {"result_count=0", "rows_seen=0"}
            ),
            "",
        )
        # A quote that carries the node term so the quoted `'{term}'` segment
        # in the statement resolves against the evidence surface.
        term_quote = next(
            (
                line
                for line in item.grounding_surface
                if line.startswith(("requested_term=", "effective_term="))
                and _normalise_example_text(line.split("=", 1)[1]).casefold()
                == term.casefold()
            ),
            "",
        )
        # The emptiness/floor anchor must be present; the term quote alone is
        # not enough grounding for the finding.
        if not floor_quote and not zero_quote:
            continue
        quotes = [quote for quote in (term_quote, floor_quote, zero_quote) if quote]
        source_ids = [item.id]
        node_total: Any = None
        count_items = _matching_collocation_count_items(
            [term], [item], evidence_items
        )
        count_item = count_items.get(term.casefold())
        if count_item is not None:
            candidate_total = count_item.raw_surface.get("total")
            total_quote = next(
                (
                    line
                    for line in count_item.grounding_surface
                    if line == f"total={candidate_total}"
                ),
                "",
            )
            if total_quote and candidate_total not in (None, ""):
                node_total = candidate_total
                quotes.append(total_quote)
                source_ids.append(count_item.id)
        floor_text = (
            str(min_freq) if min_freq not in (None, "") else ""
        )
        floor_clause = (
            f" (min_freq={floor_text})" if floor_text else ""
        )
        # NULL TREFFER ist keine verfehlte Schwelle.
        #
        # Die beiden Saetze unten behaupten, kein Kollokat habe die
        # Reliabilitaetsschwelle erreicht. Bei node_frequency 0 wurde gar
        # nichts gemessen, und die Schwelle hat nie gebunden. Genau diesen
        # Satz hat eine Professorin-Subagentin am 2026-08-29 als frei
        # erfunden und toedlich gewertet, und er ist DETERMINISTISCH
        # erzeugt, nicht vom Modell geschrieben.
        #
        # Das Werkzeug meldet solche Laeufe seit finding_substance als
        # "empty" mit Diagnose. Der Ausloeser HIER ist aber result_count=0,
        # und den traegt ein leerer Lauf genauso. Ein Fix nur am Werkzeug
        # haette den Satz stehen lassen: zweite Naht derselben Klasse.
        knoten_frequenz = item.raw_surface.get("node_frequency")
        try:
            ohne_treffer = (
                knoten_frequenz is not None and int(knoten_frequenz) <= 0
            )
        except (TypeError, ValueError):
            ohne_treffer = False
        if ohne_treffer:
            statement = (
                _t(f"Der Knoten '{term}' hat null Treffer. Es wurde nichts "
                f"gemessen, und die Schwelle{floor_clause} hat nicht "
                "gebunden: die leere Liste belegt keine Seltenheit.", f"""The node '{term}' has zero hits. Nothing was measured, and the threshold{floor_clause} excluded no observations. The empty list does not establish rarity.""")
            )
        elif node_total not in (None, ""):
            statement = (
                _t(f"Der Kollokationsknoten '{term}' kommt {node_total}-mal vor. "
                "Im sichtbaren Suchlauf erreicht kein Kollokat die "
                f"Reliabilitaetsschwelle{floor_clause}, die Kollokationsliste "
                "bleibt leer.", f"""The collocation node '{term}' occurs {node_total} times. No collocate reaches the reliability threshold{floor_clause} in the visible run, so the collocation list is empty.""")
            )
        else:
            statement = (
                _t(f"Fuer den Knoten '{term}' erreicht im sichtbaren Suchlauf "
                "kein Kollokat die Reliabilitaetsschwelle"
                f"{floor_clause}. Die Kollokationsliste bleibt leer.", f"""No collocate for '{term}' reaches the reliability threshold{floor_clause} in the visible run. The collocation list is empty.""")
            )
        # H6 (B6): Der Floor wird inzwischen deterministisch an der
        # Knotenfrequenz kalibriert. Traegt der Tool-Output node_frequency
        # und war der effektive Floor bereits adaptiv gesenkt (<5), sagt
        # die Limitation das ehrlich, statt eine weitere Senkung zu
        # verhandeln. Fehlen die Felder (aeltere Tool-Version): Alt-Text.
        node_frequency = item.raw_surface.get("node_frequency")
        try:
            node_frequency_int = int(node_frequency)
        except (TypeError, ValueError):
            node_frequency_int = None
        try:
            effective_floor = int(min_freq)
        except (TypeError, ValueError):
            effective_floor = None
        if (
            node_frequency_int is not None
            and effective_floor is not None
            and effective_floor < 5
        ):
            limitation_text = (
                _t(f"Der Floor war bereits adaptiv auf {effective_floor} "
                f"gesenkt (Knotenfrequenz {node_frequency_int}). Auswege: "
                "haeufigeres Zielwort oder weiteres Fenster.", f"""The adaptive threshold was already reduced to {effective_floor} (node frequency {node_frequency_int}). Options: choose a more frequent target or widen the window.""")
            )
            node_frequency_quote = next(
                (
                    line
                    for line in item.grounding_surface
                    if line == f"node_frequency={node_frequency}"
                ),
                "",
            )
            if node_frequency_quote and node_frequency_quote not in quotes:
                quotes.append(node_frequency_quote)
        elif ohne_treffer:
            limitation_text = (
                _t("Der Ausdruck steht so nicht im Korpus. Eine niedrigere "
                "Schwelle aendert daran nichts. Mehrwortausdruecke ueber "
                "eine CQL-Sequenz suchen, sonst den Kopf allein.", 'This expression does not occur in this form in the corpus. A lower threshold cannot change that. Search multiword expressions with a CQL sequence, or search the head alone.')
            )
        else:
            limitation_text = (
                _t("Auswege: ein haeufigeres Zielwort waehlen oder das Fenster "
                "weiten. min_freq bewusst zu senken liefert nur unsichere "
                "Paare und ist kein belastbarer Befund.", 'Options: choose a more frequent target or widen the window. Reducing min_freq admits pairs with fewer observations and does not by itself establish a reliable finding.')
            )
        fact = _make_fact(
            fact_id=f"{item.id}_floor",
            statement=statement,
            fact_kind="count",
            source_evidence_id=item.id,
            grounding_quotes=quotes,
            exactness="exact",
            supports_claims=["counts", "interpretation_anchor"],
            limitations=[limitation_text],
        )
        if fact is not None:
            if len(source_ids) > 1:
                fact.source_evidence_ids = _dedupe_ordered_strs(source_ids)
            facts.append(fact)
            seen_terms.add(term_key)
    return facts


def _annotation_sensitive_cqlf_query(query: Any) -> bool:
    return bool(
        re.search(
            r"\b(?:pos|tag|lemma|morph|ner)\s*(?:!?=|(?:not_)?in\b)",
            str(query or ""),
            re.IGNORECASE,
        )
    )


def _kwic_annotation_risk_rows(
    query: Any,
    rows: Sequence[Any],
) -> List[tuple[int, Dict[str, Any]]]:
    """Find visibly non-lexical spans in annotation-constrained results."""

    if not _annotation_sensitive_cqlf_query(query):
        return []
    risky: List[tuple[int, Dict[str, Any]]] = []
    for index, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            continue
        raw_tokens = row.get("match_tokens")
        tokens = (
            [str(token) for token in raw_tokens]
            if isinstance(raw_tokens, list)
            else _normalise_example_text(
                row.get("match") or row.get("kw")
            ).split()
        )
        if any(
            token.startswith(("@", "#"))
            or token == "#"
            or "|" in token
            or bool(re.search(r"[A-Za-zÀ-ÖØ-öø-ÿ]\.[(]", token))
            for token in tokens
            if token
        ):
            risky.append((index, row))
    return risky


def _kwic_facts(item: EvidenceItem) -> List[ObservedFact]:
    rows = item.raw_surface.get("rows")
    facts: List[ObservedFact] = []
    query_provenance = [
        line
        for line in item.grounding_surface
        if line.startswith(
            (
                "query=",
                "query_mode=",
                "attribute=",
                "case_insensitive=",
                "analysis_input=",
            )
        )
    ]
    if isinstance(rows, list):
        for index, row in enumerate(rows, start=1):
            if not isinstance(row, dict):
                continue
            kwic_line = _kwic_quote(index, row)
            if not kwic_line:
                continue
            quotes = [
                line
                for line in (
                    kwic_line,
                    (
                        _compact_text(
                            f'match[{index}]="{_normalise_example_text(row.get("match"))}"',
                            KWIC_GROUNDING_QUOTE_LIMIT,
                        )
                        if _normalise_example_text(row.get("match"))
                        else ""
                    ),
                    _row_quote("row", index, row),
                    *query_provenance,
                )
                if line
            ]
            example = kwic_line.split('"', 1)[1].rsplit('"', 1)[0]
            match_span = _normalise_example_text(row.get("match"))
            fact = _make_fact(
                fact_id=f"{item.id}_kwic_{index}",
                statement=(
                    _t(f'Sichtbares KWIC-Beispiel: "{example}".', f"""Visible concordance example: "{example}".""")
                    + (
                        _t(f' Vollständige Matchspanne: "{match_span}".', f' Complete match span: "{match_span}".')
                        if match_span
                        else ""
                    )
                ),
                fact_kind="kwic_example",
                source_evidence_id=item.id,
                grounding_quotes=quotes,
                exactness=_item_exactness(item, sample_only=True),
                supports_claims=["examples", "interpretation_anchor"],
                limitations=(
                    [_t("Es sind nur sichtbare Beispielzeilen belegt, keine Vollverteilung.", 'Only the visible example lines are established, rather than a full distribution.')]
                    if item.truncated
                    else []
                ),
                statement_limit=KWIC_GROUNDING_QUOTE_LIMIT + 64,
                quote_limit=KWIC_GROUNDING_QUOTE_LIMIT,
            )
            if fact is not None:
                facts.append(fact)
    query = _normalise_example_text(item.raw_surface.get("query"))
    total = item.raw_surface.get("total")
    if total not in (None, ""):
        count_statement = (
            _t(f"Die ausgeführte CQLF-Abfrage '{query}' hat total={total}.", f"""The executed CQLF query '{query}' has total={total}.""")
            if query
            else _t(f"Die sichtbare Trefferzahl ist total={total}.", f"""The visible hit count is total={total}.""")
        )
        sample = item.raw_surface.get("sample")
        population_partial = bool(
            isinstance(sample, dict)
            and sample.get("population_partial") is True
        )
        count_quotes = [
            _compact_text(f"total={total}", 220),
            *query_provenance,
        ]
        # H10/G2 Term-Provenienz: das total gehoert GENAU zu dieser Query.
        # Fehlt die query=-Zeile in der Surface, wird sie synthetisiert,
        # damit die Paarbindung (claim_rules.term_binding) das Paar
        # total=/query= aus den Zitaten lesen kann.
        if query and not any(
            str(line).startswith("query=") for line in query_provenance
        ):
            count_quotes.append(_compact_text(f"query={query}", 220))
        count_fact = _make_fact(
            fact_id=f"{item.id}_total",
            statement=count_statement,
            fact_kind="count",
            source_evidence_id=item.id,
            grounding_quotes=count_quotes,
            # Sampling limits the visible rows, not an independently computed
            # population total. Only an explicitly partial population makes
            # the total itself partial.
            exactness=(
                "partial" if item.partial or population_partial else "exact"
            ),
            supports_claims=["counts"],
        )
        if count_fact is not None:
            facts.append(count_fact)
    elif item.raw_surface.get("rows_seen") not in (None, ""):
        rows_seen = item.raw_surface.get("rows_seen")
        display = str(rows_seen).strip()
        if display:
            count_fact = _make_fact(
                fact_id=f"{item.id}_rows_seen",
                statement=_t(f"Der sichtbare CQLF-Suchlauf lieferte {display} Trefferzeilen.", f"""The visible CQLF run returned {display} concordance lines."""),
                fact_kind="count",
                source_evidence_id=item.id,
                grounding_quotes=[_compact_text(f"rows_seen={display}", 220)],
                exactness=_item_exactness(item, top_n_only=item.truncated),
                supports_claims=["counts"],
                limitations=[_t("rows_seen belegt die sichtbare Rueckgabe, nicht zwingend eine separate Korpus-Gesamtzahl.", 'rows_seen describes the visible return, which need not be a separate corpus-wide total.')],
            )
            if count_fact is not None:
                facts.append(count_fact)
    sample = item.raw_surface.get("sample")
    if isinstance(sample, dict):
        sample_parts = [
            f"{key}={sample[key]}"
            for key in (
                "requested",
                "drawn",
                "seed",
                "population",
                "population_partial",
                "method",
            )
            if sample.get(key) not in (None, "")
        ]
        sample_quote = next(
            (
                line
                for line in item.grounding_surface
                if line.startswith("sample:")
            ),
            "",
        )
        if sample_parts and sample_quote:
            sample_fact = _make_fact(
                fact_id=f"{item.id}_sample",
                statement=(
                    _t("Die sichtbaren KWIC-Zeilen wurden mit ", 'The visible concordance lines were retrieved with ')
                    + "; ".join(sample_parts)
                    + _t(" ausgewählt.", '.')
                ),
                fact_kind="metadata",
                source_evidence_id=item.id,
                grounding_quotes=[sample_quote, *query_provenance],
                exactness="exact",
                supports_claims=["interpretation_anchor"],
            )
            if sample_fact is not None:
                facts.append(sample_fact)
    if query and query_provenance:
        scope_fact = _make_fact(
            fact_id=f"{item.id}_query_scope",
            statement=_cqlf_query_scope_statement(item, query),
            fact_kind="limitation",
            source_evidence_id=item.id,
            grounding_quotes=query_provenance,
            exactness="exact",
            supports_claims=["interpretation_anchor"],
        )
        if scope_fact is not None:
            facts.append(scope_fact)
    annotation_risks = _kwic_annotation_risk_rows(
        query,
        rows if isinstance(rows, list) else [],
    )
    if annotation_risks:
        risk_quotes: List[str] = []
        for index, row in annotation_risks[:4]:
            risk_quotes.extend(
                quote
                for quote in (
                    _kwic_quote(index, row),
                    (
                        _compact_text(
                            f'match[{index}]="{_normalise_example_text(row.get("match"))}"',
                            KWIC_GROUNDING_QUOTE_LIMIT,
                        )
                        if _normalise_example_text(row.get("match"))
                        else ""
                    ),
                )
                if quote
            )
        quality_fact = _make_fact(
            fact_id=f"{item.id}_annotation_quality",
            statement=(
                _t("Die Attributabfrage trifft die im Index gespeicherte "
                "Annotation. In der sichtbaren Stichprobe treten "
                "Matchspannen mit Handle-, Hashtag- oder angebundener "
                "Interpunktionsoberfläche auf; diese Zeilen sind mögliche "
                "Tagging- oder Tokenisierungsartefakte und keine unabhängig "
                "validierten grammatischen Belege.", 'The attribute query matches annotations stored in the index. The visible sample contains handles, hashtags or attached punctuation in matching spans. These may reflect tagging or tokenisation artefacts and are not independently validated grammatical evidence.')
            ),
            fact_kind="limitation",
            source_evidence_id=item.id,
            grounding_quotes=[*risk_quotes, *query_provenance],
            exactness=_item_exactness(item, sample_only=True),
            supports_claims=["interpretation_anchor"],
        )
        if quality_fact is not None:
            facts.append(quality_fact)
    return facts


def _expanded_kwic_context_facts(item: EvidenceItem) -> List[ObservedFact]:
    kwic_line = _kwic_quote(1, item.raw_surface)
    if not kwic_line:
        return []
    example = kwic_line.split('"', 1)[1].rsplit('"', 1)[0]
    pos = item.raw_surface.get("pos")
    doc_id = item.raw_surface.get("doc_id")
    scope_bits = [
        f"{key}={value}"
        for key, value in (("pos", pos), ("doc_id", doc_id))
        if value not in (None, "")
    ]
    quotes = [
        kwic_line,
        *[
            _compact_text(f"{key}={value}", 220)
            for key, value in (("pos", pos), ("doc_id", doc_id))
            if value not in (None, "")
        ],
    ]
    fact = _make_fact(
        fact_id=f"{item.id}_expanded_context",
        statement=(
            _t("Der erweiterte, an Dokumentgrenzen beschnittene Kontext", 'The expanded context, clipped at document boundaries')
            + (f" ({', '.join(scope_bits)})" if scope_bits else "")
            + f' lautet: "{example}".'
        ),
        fact_kind="kwic_example",
        source_evidence_id=item.id,
        grounding_quotes=quotes,
        exactness="sample_only",
        supports_claims=["examples", "interpretation_anchor"],
        limitations=[
            _t("Der erweiterte Kontext belegt diesen einzelnen Treffer, keine "
            "Verteilung über sämtliche Treffer.", 'The expanded context documents this individual hit, rather than the distribution across all hits.')
        ],
    )
    return [fact] if fact is not None else []


def _lexical_diversity_facts(item: EvidenceItem) -> List[ObservedFact]:
    metric_keys = (
        "ttr",
        "sttr",
        "sttr_window",
        "sttr_n_windows",
        "mattr",
        "mattr_window",
        "guiraud",
        "n_tokens",
        "n_types",
        "corpus_raw_token_count",
        "analyst_tokens_only",
        "analyst_token_policy",
    )
    metrics = [
        f"{key}={item.raw_surface.get(key)}"
        for key in metric_keys
        if item.raw_surface.get(key) not in (None, "")
    ]
    if not metrics:
        return []
    quotes = [
        line
        for line in item.grounding_surface
        if any(line.startswith(f"{key}=") for key in metric_keys)
    ]
    quotes.extend(
        [
            (
                "method_reference=raw_ttr_is_length_sensitive; "
                "sttr_uses_equal_non_overlapping_windows; "
                "mattr_uses_every_overlapping_window"
            ),
            (
                "method_comparison=size_robustness_prefers_sttr_or_mattr_"
                "over_raw_ttr; at_equal_window_mattr_is_less_sensitive_to_"
                "arbitrary_segment_boundaries; values_from_different_window_"
                "sizes_are_not_a_metric_ranking"
            ),
        ]
    )
    fact = _make_fact(
        fact_id=f"{item.id}_diversity",
        statement=(
            _t("Das sichtbare lexikalische Diversitätsprofil weist ", 'The visible lexical diversity profile reports ')
            + "; ".join(metrics)
            + _t(" aus.", '.')
        ),
        fact_kind="distribution",
        source_evidence_id=item.id,
        grounding_quotes=quotes,
        exactness=_item_exactness(item),
        supports_claims=["counts", "comparisons", "interpretation_anchor"],
        limitations=[
            _t("Rohe TTR ist längensensitiv; Vergleiche unterschiedlich großer "
            "Scopes benötigen eine fensterstandardisierte Kennzahl wie STTR "
            "oder MATTR. MATTR mittelt über alle gleitenden Fenster und ist "
            "bei gleicher Fenstergröße weniger von willkürlichen "
            "Segmentgrenzen abhängig als die hier verwendete STTR über "
            "nicht überlappende Fenster. Unterschiedliche Fenstergrößen "
            "erlauben dennoch keine Rangfolge der ausgegebenen Messwerte.", 'Raw TTR is sensitive to text length. Comparing scopes of different sizes requires a fixed-window measure such as STTR or MATTR. MATTR averages over all sliding windows and is less dependent on arbitrary segment boundaries than the non-overlapping STTR windows used here. Values calculated with different window sizes still cannot be directly ranked.')
        ],
    )
    return [fact] if fact is not None else []


def _trend_facts(item: EvidenceItem) -> List[ObservedFact]:
    from .view_row_selection import ohne_pfad

    periods = item.raw_surface.get("periods")
    if not isinstance(periods, list):
        return []
    facts: List[ObservedFact] = []
    for index, period in enumerate(periods, start=1):
        if not isinstance(period, dict):
            continue
        label = _normalise_example_text(period.get("period"))
        metrics = [
            f"{key}={period.get(key)}"
            for key in (
                "documents",
                "hits",
                "tokens",
                "per_million",
                "ci_low",
                "ci_high",
            )
            if period.get(key) not in (None, "")
        ]
        if not label or not metrics:
            continue
        quote = _row_quote("period", index, ohne_pfad(period))
        fact = _make_fact(
            fact_id=f"{item.id}_period_{index}",
            statement=(
                _t(f"Die sichtbare Periode '{label}' weist ", f"""The visible period '{label}' reports """)
                + "; ".join(metrics)
                + _t(" aus.", '.')
            ),
            fact_kind="distribution",
            source_evidence_id=item.id,
            grounding_quotes=[quote],
            exactness=_item_exactness(item, top_n_only=True),
            supports_claims=["counts", "comparisons", "interpretation_anchor"],
        )
        if fact is not None:
            facts.append(fact)
    # P1 (Runde 2): lange Reihen duerfen nicht nur als Einzelfakten leben.
    # Die 64er-Synthesekappe mit Prioritaet-Spread zerschneidet eine
    # Zeitachse (Messung diachronie-1: 302 von 366 Fakten verworfen, der
    # Bruch 1999-2001 war datiert und fiel wieder raus). Ein kompakter
    # Serien-Fakt ueberlebt als interpretation_anchor jede Kappe.
    if len(facts) > 24:
        werte = []
        for period in periods:
            if not isinstance(period, dict):
                continue
            label = _normalise_example_text(period.get("period"))
            rate = period.get("per_million")
            if rate in (None, ""):
                rate = period.get("hits")
            if label and rate not in (None, ""):
                werte.append(f"{label}:{rate}")
        if len(werte) > 24:
            serie = _make_fact(
                fact_id=f"{item.id}_serie",
                statement=(
                    f"Kompakter Verlauf ueber {len(werte)} Perioden: "
                    + "; ".join(werte)
                ),
                statement_limit=3200,
                fact_kind="series",
                source_evidence_id=item.id,
                grounding_quotes=[_row_quote("period", 1, ohne_pfad(periods[0]))],
                exactness=_item_exactness(item, top_n_only=True),
                supports_claims=["interpretation_anchor", "counts", "comparisons"],
            )
            if serie is not None:
                facts.append(serie)
    return facts


def _keyness_nenner_fakt(item: EvidenceItem) -> List[ObservedFact]:
    """P5 (Runde 3): beide Keyness-Nenner als eigener metadata-Fakt.

    A3/A6 (Runde 3): Raten standen auf Analysten-Nennern und der Wechsel
    blieb unsichtbar (0,434 statt 0,393) — die Nenner stehen im
    diagnostics-Block, aber kein Extraktor machte sie zu Fakten.
    """
    diag = item.raw_surface.get("diagnostics")
    if not isinstance(diag, dict):
        return []
    werte = [
        f"{schluessel}={diag[schluessel]}"
        for schluessel in (
            "target_tokens", "target_tokens_roh",
            "reference_tokens", "reference_tokens_roh",
            "target_docs", "reference_docs",
        )
        if diag.get(schluessel) not in (None, "")
    ]
    if not werte:
        return []
    quote = next(
        (
            line
            for line in item.grounding_surface
            if "token" in line.casefold() or "nenner" in line.casefold()
        ),
        "",
    )
    if not quote:
        return []
    fakt = _make_fact(
        fact_id=f"{item.id}_nenner",
        statement=_t("Die Keyness-Nenner lauten: ", 'The keyness denominators are: ') + "; ".join(werte) + ".",
        fact_kind="metadata",
        source_evidence_id=item.id,
        grounding_quotes=[quote],
        exactness="exact",
        supports_claims=["counts", "interpretation_anchor"],
    )
    return [fakt] if fakt is not None else []


def _metric_row_facts(
    item: EvidenceItem,
    *,
    direction_context: Dict[str, Any] | None = None,
) -> List[ObservedFact]:
    rows = item.raw_surface.get("rows")
    if not isinstance(rows, list):
        return []
    try:
        query_args = json.loads(item.query) if item.query else {}
    except (TypeError, ValueError, json.JSONDecodeError):
        query_args = {}
    if not isinstance(query_args, dict):
        query_args = {}
    scope_bits: List[str] = []
    query_quotes: List[str] = []
    kompakt: List[str] = []
    if item.tool == "collocate_stats":
        raw_method = item.raw_surface.get("method")
        raw_attribute = (
            raw_method.get("attribute")
            if isinstance(raw_method, dict)
            else None
        )
        scope = item.raw_surface.get("scope")
        scope = scope if isinstance(scope, dict) else {}
        scope_bits = [
            f"{key}={value}"
            for key, value in (
                ("term", item.raw_surface.get("requested_term") or query_args.get("term")),
                ("attribute", raw_attribute),
                ("window", item.raw_surface.get("window")),
                ("within_sentence", item.raw_surface.get("within_sentence")),
                ("min_freq", item.raw_surface.get("min_freq")),
                ("sort_by", item.raw_surface.get("sort_by")),
                ("corpus_id", scope.get("corpus_id")),
                ("docset_id", scope.get("docset_id")),
            )
            if value not in (None, "")
        ]
        query_quotes = [
            line
            for line in item.grounding_surface
            if line.startswith(
                (
                    "requested_term=",
                    "window=",
                    "within_sentence=",
                    "min_freq=",
                    "sort_by=",
                    "scope:",
                    "method:",
                )
            )
        ]
    elif item.tool == "keyness" and direction_context:
        target_label = _normalise_example_text(
            direction_context.get("target_label")
        )
        reference_label = _normalise_example_text(
            direction_context.get("reference_label")
        )
        scope_bits = [
            f"target={target_label}",
            f"reference={reference_label}",
        ]
        grounding_selection = _normalise_example_text(
            direction_context.get("grounding_selection")
        )
        if grounding_selection:
            scope_bits.append(f"selection={grounding_selection}")
    scope_suffix = f" ({', '.join(scope_bits)})" if scope_bits else ""
    facts: List[ObservedFact] = []
    for index, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            continue
        metric_line = _metric_quote(index, row)
        if not metric_line:
            continue
        label = _normalise_example_text(
            row.get("word")
            or row.get("kw")
            or row.get("ngram")
            or row.get("label")
        )
        if not label:
            continue
        metrics = [
            f"{key}={row.get(key)}"
            for key in (
                "direction",
                "target_freq",
                "reference_freq",
                "target_per_million",
                "reference_per_million",
                "diff_per_million",
                "logdice",
                "mi3",
                "score",
                "score_key",
                "mi",
                "t",
                "ll",
                "ll_signed",
                "q_value",
                "low_reliability",
                "dice",
                "chi2_cell",
                "chi2_signed",
                "delta_p_nc",
                "delta_p_cn",
                "lmi",
                "npmi",
                "z",
                "f",
                "f2",
                "frequency",
                "freq",
                "n",
            )
            if row.get(key) not in (None, "")
        ]
        if not metrics:
            continue
        supports = ["comparisons", "examples", "ranks", "interpretation_anchor"]
        if any(
            row.get(key) not in (None, "")
            for key in (
                "f",
                "frequency",
                "freq",
                "target_freq",
                "reference_freq",
            )
        ):
            supports.append("counts")
        fact = _make_fact(
            fact_id=f"{item.id}_metric_{index}",
            statement=(
                _t(f"Die sichtbare Metrikzeile{scope_suffix} an Position {index} zeigt "
                f"'{label}' mit {'; '.join(metrics)}.", f"""The visible metric row{scope_suffix} at position {index} shows '{label}' with {', '.join(metrics)}.""")
            ),
            fact_kind="ranked_row",
            source_evidence_id=item.id,
            grounding_quotes=[
                line
                for line in (
                    _row_quote("row", index, row),
                    metric_line,
                    next(
                        (
                            value
                            for value in item.grounding_surface
                            if value == f"rank={index}"
                        ),
                        "",
                    ),
                    *query_quotes,
                    *list(
                        (direction_context or {}).get(
                            "grounding_quotes",
                            [],
                        )
                    ),
                )
                if line
            ],
            exactness=_item_exactness(item, top_n_only=True),
            supports_claims=supports,
            # Full collocation rows carry several association metrics. The
            # generic 280-character cap can cut the final decimal in half
            # (for example ``npmi=0...``), after which numeric provenance
            # correctly rejects the entire otherwise exact row.
            statement_limit=520,
        )
        if fact is not None:
            if direction_context:
                fact.source_evidence_ids = list(
                    direction_context.get(
                        "source_evidence_ids",
                        fact.source_evidence_ids,
                    )
                )
            facts.append(fact)
            kompakt.append(
                label + ": " + ", ".join(metrics[:2])
            )
    # P2 (Runde 2): gerankte Tabellen leiden unter derselben Kappe wie
    # Zeitreihen (diachronie-3: 24 von 24 Zellen einer Richtung gestrichen,
    # weil ihre Fakten das 64er-Fenster nicht ueberlebten). Der kompakte
    # Tabellen-Fakt traegt die Kopfzeilen jeder Richtung als series-Fakt
    # durch jede Kappe. Die Schwelle stand bis zum 2026-09-18 bei 24 und
    # war deshalb TOT: die rohen Zeilen sind oberhalb auf 20 gekappt
    # (DEFAULT_GROUNDING_ROW_LIMIT), 20 < 25 — der Traeger sprang nie an
    # (Diagnose GOAL-Defekt 3, Lauf 4: die Tabelle erreichte die
    # Verifikation nur als row[1] und row[2]). Eine Tabelle ab drei Zeilen
    # bekommt den Traeger, bevor das Fenster sie aushungert.
    if len(kompakt) > 2:
        erste_zeile = next(
            (row for row in rows if isinstance(row, dict)),
            {},
        )
        serie = _make_fact(
            fact_id=f"{item.id}_tabellen_serie",
            statement=(
                _t(f"Kompakte Rangliste, die ersten {min(len(kompakt), 48)} "
                "Zeilen: ", f"""Compact ranking, first {min(len(kompakt), 48)} rows: """) + " | ".join(kompakt[:48])
            ),
            statement_limit=2800,
            fact_kind="series",
            source_evidence_id=item.id,
            grounding_quotes=[
                quote
                for quote in (
                    _row_quote("row", 1, erste_zeile),
                    next(
                        (
                            value
                            for value in item.grounding_surface
                            if value == "rank=1"
                        ),
                        "",
                    ),
                )
                if quote
            ],
            exactness=_item_exactness(item, top_n_only=True),
            supports_claims=["interpretation_anchor", "ranks"],
        )
        if serie is not None:
            facts.append(serie)
    return facts


def _returned_metric_row_count_fact(
    item: EvidenceItem,
) -> List[ObservedFact]:
    # Fix 4: a floor-thinned collocation reports "rows_seen=0 zurückgegebene
    # Ergebniszeilen" as raw geplapper; the linguistic floor fact carries that
    # information instead.
    if _is_floor_thinned_collocation(item):
        return []
    rows_seen = item.raw_surface.get("rows_seen")
    if rows_seen in (None, ""):
        return []
    quote = next(
        (
            line
            for line in item.grounding_surface
            if line == f"rows_seen={rows_seen}"
        ),
        "",
    )
    if not quote:
        return []
    fact = _make_fact(
        fact_id=f"{item.id}_rows_seen",
        statement=(
            _t(f"Der sichtbare Tool-Output enthält rows_seen={rows_seen} "
            "zurückgegebene Ergebniszeilen.", f"""The visible tool output contains rows_seen={rows_seen} returned result rows.""")
        ),
        fact_kind="count",
        source_evidence_id=item.id,
        grounding_quotes=[quote],
        exactness="exact",
        supports_claims=["counts", "interpretation_anchor"],
        limitations=[
            _t("Die Zahl beschreibt die zurückgegebenen Ergebniszeilen, nicht "
            "automatisch sämtliche möglichen Kandidaten.", 'This count describes returned result rows, rather than necessarily all possible candidates.')
        ],
    )
    return [fact] if fact is not None else []


def _docset_scope_facts(item: EvidenceItem) -> List[ObservedFact]:
    """Expose the actual comparison populations created for an analysis."""

    label = _normalise_example_text(item.raw_surface.get("label"))
    doc_count = item.raw_surface.get("doc_count")
    token_count = item.raw_surface.get("token_count")
    if not label or doc_count in (None, "") or token_count in (None, ""):
        return []
    expected_quotes = {
        f"label={label}",
        f"doc_count={doc_count}",
        f"token_count={token_count}",
    }
    quotes = [
        line
        for line in item.grounding_surface
        if line in expected_quotes or line.startswith("tool_args=")
    ]
    if not expected_quotes.issubset(set(quotes)):
        return []
    fact = _make_fact(
        fact_id=f"{item.id}_scope",
        statement=(
            _t(f"Das erzeugte Teilkorpus '{label}' umfasst {doc_count} Dokumente "
            f"und {token_count} Tokens.", f"""The created subcorpus '{label}' contains {doc_count} documents and {token_count} tokens.""")
        ),
        fact_kind="distribution",
        source_evidence_id=item.id,
        grounding_quotes=quotes,
        exactness="exact",
        supports_claims=["counts", "comparisons", "interpretation_anchor"],
    )
    return [fact] if fact is not None else []


def _dispersion_facts(item: EvidenceItem) -> List[ObservedFact]:
    facts: List[ObservedFact] = []
    unit = _compact_text(item.raw_surface.get("unit", ""), 40)
    profile = _compact_text(item.raw_surface.get("profile", ""), 80)
    dp = item.raw_surface.get("dp")
    dpnorm = item.raw_surface.get("dpnorm")
    juilland_d = item.raw_surface.get("juilland_d")
    carroll_d2 = item.raw_surface.get("carroll_d2")
    range_value = item.raw_surface.get("range")
    range_prop = item.raw_surface.get("range_prop")
    vc = item.raw_surface.get("vc")
    total_hits = item.raw_surface.get("total_hits")
    n_documents = item.raw_surface.get("n_documents")
    coverage_ratio = item.raw_surface.get("coverage_ratio")
    nonzero_partitions = item.raw_surface.get("nonzero_partitions")
    peak_share = item.raw_surface.get("peak_share")
    nonzero_metric = (
        f"documents_with_hits={nonzero_partitions}"
        if unit == "documents" and nonzero_partitions not in (None, "")
        else (
            f"nonzero_partitions={nonzero_partitions}"
            if nonzero_partitions not in (None, "")
            else ""
        )
    )
    metrics = [
        f"unit={unit}" if unit else "",
        f"dp={dp}" if dp not in (None, "") else "",
        f"dpnorm={dpnorm}" if dpnorm not in (None, "") else "",
        f"juilland_d={juilland_d}" if juilland_d not in (None, "") else "",
        f"carroll_d2={carroll_d2}" if carroll_d2 not in (None, "") else "",
        f"range={range_value}" if range_value not in (None, "") else "",
        f"range_prop={range_prop}" if range_prop not in (None, "") else "",
        f"vc={vc}" if vc not in (None, "") else "",
        f"profile={profile}" if profile else "",
        f"total_hits={total_hits}" if total_hits not in (None, "") else "",
        f"n_documents={n_documents}" if n_documents not in (None, "") else "",
        f"coverage_ratio={coverage_ratio}" if coverage_ratio not in (None, "") else "",
        f"peak_share={peak_share}" if peak_share not in (None, "") else "",
        nonzero_metric,
    ]
    metrics = [metric for metric in metrics if metric]
    if not metrics:
        return facts
    quotes = [
        line
        for line in item.grounding_surface
        if line.startswith(
            (
                "unit=",
                "dp=",
                "dpnorm=",
                "juilland_d=",
                "carroll_d2=",
                "range=",
                "range_prop=",
                "vc=",
                "profile=",
                "total_hits=",
                "n_documents=",
                "coverage_ratio=",
                "nonzero_partitions=",
                "peak_share=",
            )
        )
    ]
    supports = ["comparisons", "interpretation_anchor"]
    if total_hits not in (None, "") or nonzero_partitions not in (None, ""):
        supports.append("counts")
    if coverage_ratio not in (None, ""):
        supports.append("percentages")
    fact = _make_fact(
        fact_id=f"{item.id}_dispersion",
        statement=_t(f"Das sichtbare Dispersionsprofil zeigt {'; '.join(metrics)}.", f"""The visible dispersion profile reports {', '.join(metrics)}."""),
        fact_kind="distribution",
        source_evidence_id=item.id,
        grounding_quotes=quotes[:16] or list(item.grounding_surface[:2]),
        exactness=_item_exactness(item, top_n_only=item.truncated),
        supports_claims=supports,
    )
    if fact is not None:
        facts.append(fact)
    if (
        unit == "documents"
        and total_hits not in (None, "")
        and n_documents not in (None, "")
        and nonzero_partitions not in (None, "")
    ):
        try:
            hit_count = int(total_hits)
            document_count = int(n_documents)
            hit_documents = int(nonzero_partitions)
        except (TypeError, ValueError):
            hit_count = document_count = hit_documents = 0
        maximum_distinct = min(hit_count, document_count)
        if hit_count > 0 and maximum_distinct > 0:
            repeated_hits = max(0, hit_count - hit_documents)
            range_saturation = hit_documents / maximum_distinct
            repeat_hit_share = repeated_hits / hit_count
            global_coverage = (
                hit_documents / document_count
                if document_count > 0
                else 0.0
            )
            calibration = _make_fact(
                fact_id=f"{item.id}_dispersion_calibration",
                statement=(
                    _t(f"Dokumentdiagnose: {hit_documents}/{document_count} "
                    f"Dokumente sind belegt ({global_coverage:.2%} global); "
                    f"zugleich {hit_documents}/{maximum_distinct} der bei "
                    f"{hit_count} Treffern maximal möglichen Trefferdokumente "
                    f"({range_saturation:.2%}). Nur "
                    f"{repeated_hits}/{hit_count} Treffer liegt über einer "
                    "Ein-Treffer-pro-Dokument-Basis; das belegt keine "
                    "ausgeprägte lokale Wiederholung.", f"""Document diagnostic: {hit_documents}/{document_count} documents have hits ({global_coverage:.2%} globally). This is {hit_documents}/{maximum_distinct} of the maximum distinct documents possible with {hit_count} hits ({range_saturation:.2%}). Only {repeated_hits}/{hit_count} hits exceed a one-hit-per-document baseline. This does not establish pronounced local repetition.""")
                ),
                fact_kind="limitation",
                source_evidence_id=item.id,
                grounding_quotes=[
                    *[
                        line
                        for line in quotes
                        if line.startswith(
                            (
                                "total_hits=",
                                "n_documents=",
                                "nonzero_partitions=",
                                "peak_share=",
                                "dp=",
                            )
                        )
                    ],
                    f"maximum_distinct_documents={maximum_distinct}",
                    f"documents_with_hits={hit_documents}",
                    f"global_document_coverage={global_coverage:.6g}",
                    f"global_document_coverage_percent={global_coverage:.2%}",
                    f"range_saturation={range_saturation:.6g}",
                    f"range_saturation_percent={range_saturation:.2%}",
                    f"repeated_hits={repeated_hits}",
                    f"repeat_hit_share={repeat_hit_share:.6g}",
                ],
                exactness="derived",
                supports_claims=[
                    "counts",
                    "percentages",
                    "comparisons",
                    "interpretation_anchor",
                ],
                limitations=[
                    _t("Die Dokumentdiagnose ist aus den sichtbaren Treffer- und "
                    "Dokumentzahlen abgeleitet.", 'The document diagnostic is derived from the visible hit and document counts.')
                ],
            )
            if calibration is not None:
                facts.append(calibration)
            metric_semantics = _make_fact(
                fact_id=f"{item.id}_dispersion_metric_semantics",
                statement=(
                    _t("Das Profil-Label ist eine Kurzklassifikation aus dp, "
                    "keine unabhängige Evidenz. Hohe dp/dpnorm bedeuten "
                    "stärkere Abweichung von der Längenerwartung; hohe "
                    "Juilland-/Carroll-Werte eine gleichmäßigere Verteilung. "
                    "DP ist daher als Abweichungsmaß zu benennen, nicht "
                    "mehrdeutig als hohe Dispersionsrate.", 'The profile label is a brief classification derived from dp. High dp/dpnorm indicates stronger deviation from the distribution expected by length. High Juilland/Carroll values indicate a more even distribution. DP is a deviation measure, rather than an ambiguous high dispersion rate.')
                ),
                fact_kind="limitation",
                source_evidence_id=item.id,
                grounding_quotes=[
                    line
                    for line in quotes
                    if line.startswith(
                        (
                            "dp=",
                            "dpnorm=",
                            "juilland_d=",
                            "carroll_d2=",
                            "profile=",
                        )
                    )
                ],
                exactness="derived",
                supports_claims=[
                    "comparisons",
                    "interpretation_anchor",
                ],
                limitations=[
                    _t("Die Dispersionsmaße haben unterschiedliche "
                    "Skalenrichtungen und dürfen nicht als unabhängige "
                    "Bestätigungen desselben Labels zusammengezählt werden.", 'The dispersion measures have different scale directions. They are not independent confirmations of the same label.')
                ],
            )
            if metric_semantics is not None:
                facts.append(metric_semantics)
            reliability = _make_fact(
                fact_id=f"{item.id}_dispersion_reliability",
                statement=(
                    _t("Die Kennwerte sind deskriptiv für den aktiven Index. Ohne "
                    "Resampling, Unsicherheitsintervalle oder frequenzgleiche "
                    "Referenz ist eine für die beobachtete Trefferzahl "
                    "ungewöhnliche Konzentration nicht belegt; ebenso keine "
                    "inferenzstatistische Stabilität über diesen Korpus hinaus.", 'These metrics describe the active index. Resampling, uncertainty intervals or a frequency-matched reference are needed to establish whether concentration is unusual for this hit count or statistically stable beyond this corpus.')
                ),
                fact_kind="limitation",
                source_evidence_id=item.id,
                grounding_quotes=[
                    line
                    for line in quotes
                    if line.startswith(
                        (
                            "total_hits=",
                            "n_documents=",
                            "unit=",
                        )
                    )
                ],
                exactness="derived",
                supports_claims=["interpretation_anchor"],
                limitations=[
                    _t("Deskriptive Korpuswerte und inferenzstatistische "
                    "Unsicherheit sind getrennte Aussageebenen.", 'Descriptive corpus values and inferential uncertainty concern different claims.')
                ],
            )
            if reliability is not None:
                facts.append(reliability)
    return facts


def _table_metric_facts(item: EvidenceItem) -> List[ObservedFact]:
    tables = item.raw_surface.get("tables")
    if not isinstance(tables, dict):
        return []
    facts: List[ObservedFact] = []
    seen_labels: set[str] = set()
    for table_name, entries in tables.items():
        if not isinstance(entries, list):
            continue
        for index, row in enumerate(entries, start=1):
            if not isinstance(row, dict):
                continue
            label = _normalise_example_text(row.get("word") or row.get("kw") or row.get("label"))
            metrics = [
                f"{key}={row.get(key)}"
                for key in (
                    "rank",
                    "f",
                    "f2",
                    "frequency",
                    "logdice",
                    "mi3",
                    "score",
                    "score_key",
                    "mi",
                    "t",
                    "ll",
                    "dice",
                    "chi2_cell",
                    "delta_p_nc",
                    "delta_p_cn",
                    "lmi",
                    "npmi",
                    "z",
                )
                if row.get(key) not in (None, "")
            ]
            dedupe_key = f"{table_name}:{label}:{'|'.join(metrics)}"
            if not label or not metrics or dedupe_key in seen_labels:
                continue
            seen_labels.add(dedupe_key)
            supports = ["comparisons", "examples", "ranks", "interpretation_anchor"]
            if row.get("f") not in (None, ""):
                supports.append("counts")
            fact = _make_fact(
                fact_id=f"{item.id}_table_metric_{table_name}_{index}",
                statement=(
                    _t(f"Die sichtbare Tabelle '{table_name}' zeigt an Position "
                    f"{index} die Partnerzeile '{label}' mit "
                    f"{'; '.join(metrics)}.", f"""The visible table '{table_name}' shows partner '{label}' at position {index} with {', '.join(metrics)}.""")
                    + (
                        _t(" Der f-Wert zählt indexierte Dependenzereignisse "
                        "dieser Partnerzeile.", ' The f value counts indexed dependency events for this partner row.')
                        if row.get("f") not in (None, "")
                        else ""
                    )
                    + (
                        _t(" Der f2-Wert ist die marginale Tokenhäufigkeit des "
                        "Partners auf der in f2_basis ausgewiesenen Basis.", ' The f2 value is the marginal token frequency of the partner on the basis reported by f2_basis.')
                        if row.get("f2") not in (None, "")
                        else ""
                    )
                ),
                fact_kind="ranked_row",
                source_evidence_id=item.id,
                grounding_quotes=[
                    line
                    for line in (
                        _row_quote(f"table[{table_name}]", index, row),
                        _metric_quote(index, row),
                    )
                    if line
                ],
                exactness=_item_exactness(item, top_n_only=True),
                supports_claims=supports,
                limitations=[
                    _t("Eine Word-Sketch-Partnerzeile ist weder ein "
                    "fortlaufender Phrasenbeleg noch ein POS-Tag.", 'A word-sketch partner row establishes neither a contiguous phrase example nor a POS tag.')
                ],
            )
            if fact is not None:
                facts.append(fact)
    return facts


def _relation_metadata_facts(item: EvidenceItem) -> List[ObservedFact]:
    relations = item.raw_surface.get("relations")
    if not isinstance(relations, dict):
        return []
    facts: List[ObservedFact] = []
    for index, (relation_name, metadata) in enumerate(
        relations.items(),
        start=1,
    ):
        if not isinstance(metadata, dict):
            continue
        label = _normalise_example_text(metadata.get("label"))
        if not label:
            continue
        metadata_bits: List[str] = []
        for key in (
            "row_limit",
            "total_candidates",
            "total_rows",
            "truncated",
            "min_freq",
            "basis",
            "coverage_scope",
        ):
            value = metadata.get(key)
            if value in (None, ""):
                continue
            if isinstance(value, bool):
                value = str(value).lower()
            metadata_bits.append(f"{key}={value}")
        quote = next(
            (
                line
                for line in item.grounding_surface
                if line.startswith(f"relation[{relation_name}]=")
            ),
            "",
        )
        fact = _make_fact(
            fact_id=f"{item.id}_relation_{index}",
            statement=(
                _t(f"Das Word Sketch beschreibt die Relation '{relation_name}' als "
                f"'{label}'", f"""The word sketch describes relation '{relation_name}' as '{label}'""")
                + (f"; {'; '.join(metadata_bits)}." if metadata_bits else ".")
            ),
            fact_kind="metadata",
            source_evidence_id=item.id,
            grounding_quotes=[quote] if quote else [],
            exactness="exact",
            supports_claims=[
                "examples",
                "interpretation_anchor",
                *(
                    ["counts"]
                    if any(
                        metadata.get(key) not in (None, "")
                        for key in (
                            "row_limit",
                            "total_candidates",
                            "total_rows",
                            "min_freq",
                        )
                    )
                    else []
                ),
            ],
            limitations=[
                _t("Gelistet werden Partnerzeilen mit f >= min_freq; die "
                "Schwelle filtert Partner, nicht Relationen. Einen "
                "Anteilsnenner über alle Vorkommen des Suchbegriffs "
                "gibt es nicht.", 'Partner rows meet f >= min_freq. This threshold filters partners, rather than relations. There is no denominator covering all occurrences of the search term.'),
                _t("total_rows zählt sichtbare Partnerzeilen dieser Relation; "
                "es ist keine Ereignisfrequenz.", 'total_rows counts visible partner rows for this relation. It is not an event frequency.'),
                *(
                    [
                    _t("Die ausgewiesene Kandidatenliste ist innerhalb der "
                    f"min_freq-Schwelle {metadata.get('min_freq')} vollständig; "
                    "Partnerkandidaten dieser Relation unterhalb der Schwelle "
                    "bleiben unbeobachtet. Daraus folgt keine Vollständigkeit "
                    "über nicht ausgegebene Relationstypen.", f"""The candidate list is complete within the min_freq threshold {metadata.get('min_freq')}. Partner candidates below the threshold remain unobserved. This does not establish completeness across relation types not returned.""")
                    ]
                    if (
                        metadata.get("truncated") is False
                        and metadata.get("total_rows") not in (None, "")
                        and metadata.get("total_candidates")
                        == metadata.get("total_rows")
                        and metadata.get("min_freq") not in (None, "")
                    )
                    else []
                ),
            ],
        )
        if fact is not None:
            facts.append(fact)
    return facts


def _document_row_facts(item: EvidenceItem, *, source_label: str) -> List[ObservedFact]:
    rows = item.raw_surface.get("rows")
    if not isinstance(rows, list):
        return []
    facts: List[ObservedFact] = []
    for index, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            continue
        snippet = _normalise_example_text(row.get("snippet") or row.get("kw") or row.get("text"))
        doc_id = row.get("doc_id")
        score = row.get("score")
        bits: List[str] = []
        # Long corpus file identifiers commonly contain many digits. Putting
        # them into the compact fact statement makes truncation split their
        # hash; the numeric grounding check then correctly rejects the broken
        # fragment and accidentally loses the entire document hit. The source
        # evidence id already preserves provenance, so keep the analytical
        # statement to the independently quoted document id, score and snippet.
        if doc_id not in (None, ""):
            bits.append(f"doc_id={doc_id}")
        if score not in (None, ""):
            bits.append(f"score={score}")
        if snippet:
            bits.append(f"snippet=\"{snippet}\"")
        if not bits:
            continue
        supports: List[str] = []
        if snippet:
            supports.extend(["examples", "interpretation_anchor"])
        quotes = [_row_quote("row", index, row)]
        if snippet:
            quotes.append(_compact_text(f'snippet="{snippet}"', 220))
        if doc_id not in (None, ""):
            quotes.append(_compact_text(f"doc_id={doc_id}", 220))
        if score not in (None, ""):
            quotes.append(_compact_text(f"score={score}", 220))
        fact = _make_fact(
            fact_id=f"{item.id}_{source_label}_{index}",
            statement=_t(f"Der sichtbare {source_label}-Treffer zeigt ", f"""The visible {source_label} match shows """) + ", ".join(bits) + ".",
            fact_kind="metadata",
            source_evidence_id=item.id,
            grounding_quotes=quotes,
            exactness="top_n_only",
            supports_claims=supports,
            limitations=[
                _t("Dokumentsuche belegt sichtbare Top-Treffer, keine vollständige Dokumentverteilung.", 'Document search establishes visible top matches, rather than a complete document distribution.')
            ],
        )
        if fact is not None:
            facts.append(fact)
    return facts


def _metadata_available_fields_fact(item: EvidenceItem) -> List[ObservedFact]:
    available_fields = item.raw_surface.get("available_fields")
    if not isinstance(available_fields, list):
        return []
    field_names = [
        _normalise_example_text(field)
        for field in available_fields
        if _normalise_example_text(field)
    ]
    if not field_names:
        return []
    grounding_quotes: List[str] = [
        _compact_text(f"available_fields={field_names}", 220)
    ]
    profile_bits: List[str] = []
    profile_complete = True
    supports = ["examples"]
    values = item.raw_surface.get("values")
    value_counts = item.raw_surface.get("value_counts")
    sampled_fields = {
        str(field)
        for field in item.raw_surface.get("sampled_value_fields", [])
        if str(field)
    }
    if isinstance(values, dict):
        if not isinstance(value_counts, dict):
            value_counts = {}
        partition_fields = [
            field_name
            for field_name in values
            if str(field_name).casefold() in _PARTITION_METADATA_FIELDS
        ]
        preferred_fields = [
            *_COMPARABLE_METADATA_FIELDS[:4],
            *partition_fields,
            *_COMPARABLE_METADATA_FIELDS[4:],
        ]
        profile_fields = list(
            dict.fromkeys(
                [
                    field_name
                    for field_name in preferred_fields
                    if field_name in values
                ]
                + [field_name for field_name in values]
            )
        )
        if len(profile_fields) > 10:
            profile_complete = False
        for field_name in profile_fields[:10]:
            entries = values.get(field_name)
            if not isinstance(entries, list):
                continue
            visible_values = [
                _normalise_example_text(entry)
                for entry in entries[:8]
                if _normalise_example_text(entry)
            ]
            if not visible_values:
                continue
            profile_bits.append(
                f"{field_name}=[" + ", ".join(f"'{value}'" for value in visible_values) + "]"
            )
            raw_count = value_counts.get(field_name)
            grounding_quotes.append(
                _compact_text(f"values[{field_name}]={visible_values}", 220)
            )
            if raw_count is not None:
                grounding_quotes.append(
                    _compact_text(f"value_count[{field_name}]={raw_count}", 220)
                )
            try:
                field_complete = (
                    field_name not in sampled_fields
                    and raw_count is not None
                    and int(raw_count) == len(visible_values)
                )
            except (TypeError, ValueError):
                field_complete = False
            profile_complete = profile_complete and field_complete
        if profile_bits:
            supports.append("interpretation_anchor")
    fact = _make_fact(
        fact_id=f"{item.id}_metadata_available_fields",
        statement=(
            (
                _t("Der Metadaten-Endpunkt weist folgende bereits sichtbare "
                "analytische Feldwerte aus: ", 'The metadata endpoint reports these already visible analytical field values: ')
                + "; ".join(profile_bits)
                + "."
                if profile_bits
                else (
                    _t("Der Metadaten-Endpunkt meldet folgende verfügbare "
                    "Feldnamen: ", 'The metadata endpoint reports these available field names: ')
                    + ", ".join(f"'{field}'" for field in field_names)
                    + "."
                )
            )
        ),
        fact_kind="metadata",
        source_evidence_id=item.id,
        grounding_quotes=grounding_quotes,
        exactness=(
            "partial"
            if (
                item.raw_surface.get("available_fields_truncated")
                or (profile_bits and not profile_complete)
            )
            else "exact"
        ),
        supports_claims=supports,
        limitations=(
            [_t("Das Feldinventar wurde für den Modellkontext gekürzt.", 'The field inventory was shortened for the model context.')]
            if item.raw_surface.get("available_fields_truncated")
            else []
        ),
    )
    return [fact] if fact is not None else []


def _metadata_value_facts(item: EvidenceItem) -> List[ObservedFact]:
    values = item.raw_surface.get("values")
    if not isinstance(values, dict):
        # H6 (B4): auch ohne sichtbare Wertelisten (z. B. wenn alle Felder
        # Identifier sind) muessen die count-only-Fakten fuer
        # identifier_value_fields entstehen koennen.
        values = {}
    value_counts = item.raw_surface.get("value_counts")
    if not isinstance(value_counts, dict):
        value_counts = {}
    sampled_fields = {
        str(field)
        for field in item.raw_surface.get("sampled_value_fields", [])
        if str(field)
    }
    facts: List[ObservedFact] = []
    candidates = [
        (raw_field_name, entries)
        for raw_field_name, entries in values.items()
        if _metadata_field_has_analytical_entries(raw_field_name, entries)
    ]
    for index, (raw_field_name, entries) in enumerate(candidates, start=1):
        field_name = _normalise_example_text(raw_field_name)
        if not field_name:
            continue
        if isinstance(entries, list):
            visible_values = [
                _normalise_example_text(entry)
                for entry in entries
                if _normalise_example_text(entry)
            ]
        else:
            compact = _compact_text(entries, 120)
            visible_values = [compact] if compact else []
        if visible_values and all(_looks_like_opaque_id(value) for value in visible_values):
            continue
        raw_count = value_counts.get(field_name)
        try:
            value_count = max(0, int(raw_count)) if raw_count is not None else None
        except (TypeError, ValueError):
            value_count = None
        if not visible_values:
            statement = _t(f"Das sichtbare Metadatenfeld '{field_name}' hat im aktuellen Output keine belegten Werte.", f"""The visible metadata field '{field_name}' has no established values in the current output.""")
            supports: List[str] = []
        elif value_count == 1 or (value_count is None and len(visible_values) == 1):
            statement = _t(f"Das Metadatenfeld '{field_name}' hat genau einen belegten Wert: '{visible_values[0]}'.", f"""The metadata field '{field_name}' has exactly one established value: '{visible_values[0]}'.""")
            supports = ["examples", "interpretation_anchor"]
        else:
            count_text = str(value_count if value_count is not None else len(visible_values))
            statement = (
                _t(f"Das Metadatenfeld '{field_name}' hat {count_text} belegte Werte; sichtbar sind: ", f"""The metadata field '{field_name}' has {count_text} established values. Visible values: """)
                + ", ".join(f"'{value}'" for value in visible_values[:12])
                + "."
            )
            supports = ["examples", "interpretation_anchor"]
            if field_name.casefold() not in _PARTITION_METADATA_FIELDS:
                supports.append("comparisons")
        field_is_complete = (
            field_name not in sampled_fields
            and value_count is not None
            and value_count == len(visible_values)
        )
        exactness = "exact" if field_is_complete else _item_exactness(item, top_n_only=False)
        grounding_quotes = [
            _compact_text(f"field={field_name}", 220),
            _compact_text(f"values[{field_name}]={visible_values}", 220),
        ]
        if value_count is not None:
            grounding_quotes.append(_compact_text(f"value_count[{field_name}]={value_count}", 220))
        fact = _make_fact(
            fact_id=f"{item.id}_metadata_{index}",
            statement=statement,
            fact_kind="metadata",
            source_evidence_id=item.id,
            grounding_quotes=grounding_quotes,
            exactness=exactness,
            supports_claims=supports,
        )
        if fact is not None:
            facts.append(fact)
        if (
            field_name.casefold() in _PARTITION_METADATA_FIELDS
            and (value_count or len(visible_values)) > 1
        ):
            limitation = _make_fact(
                fact_id=f"{item.id}_metadata_{index}_limitation",
                statement=(
                    _t(f"Das Feld '{field_name}' belegt eine technische Datenaufteilung. "
                    "Aus Feldname und sichtbaren Werten allein folgt keine fachlich "
                    "sinnvolle oder belastbare Subkorpusachse.", f"""The field '{field_name}' documents a technical data partition. Its name and visible values alone do not establish suitability as a corpus-linguistic comparison axis.""")
                ),
                fact_kind="limitation",
                source_evidence_id=item.id,
                grounding_quotes=grounding_quotes,
                exactness="derived",
                supports_claims=[],
                limitations=[
                    _t("Aus einer technischen Partition darf ohne Vergleichsdesign keine fachliche Vergleichseignung abgeleitet werden.", 'A technical partition requires a comparison design before its analytical suitability can be assessed.'),
                    _t("Der konkrete Zweck der technischen Partition ist nicht belegt.", 'The specific purpose of the technical partition is not established.'),
                ],
            )
            if limitation is not None:
                facts.append(limitation)
    # H6 (B4): count-only-Fakten fuer die vom Analytik-Filter entfernten
    # Identifier-Felder (doc_id, path, reference_hash, ...). Der Tool-Output
    # enthaelt fuer diese Felder reale Werte. Ohne diesen Fakt haette die
    # harte Regel metadata_values_are_falsely_absent keine Vergleichsbasis
    # und eine Antwort koennte die Felder folgenlos als leer bezeichnen.
    identifier_fields = [
        _normalise_example_text(field)
        for field in item.raw_surface.get("identifier_value_fields", [])
        if _normalise_example_text(field)
    ]
    for index, field_name in enumerate(dict.fromkeys(identifier_fields), start=1):
        raw_count = value_counts.get(field_name)
        try:
            value_count = int(raw_count)
        except (TypeError, ValueError):
            continue
        if value_count <= 0:
            continue
        fact = _make_fact(
            fact_id=f"{item.id}_metadata_idcount_{index}",
            statement=(
                _t(f"Das Metadatenfeld '{field_name}' ist belegt und weist "
                f"{value_count} distinkte Werte aus (ID-/Pfadfeld, "
                "Einzelwerte werden fuer den Kontext nicht aufgelistet).", f"""The metadata field '{field_name}' is established with {value_count} distinct values (ID or path field, individual values omitted from this context).""")
            ),
            fact_kind="metadata",
            source_evidence_id=item.id,
            grounding_quotes=[
                _compact_text(f"field={field_name}", 220),
                _compact_text(f"value_count[{field_name}]={value_count}", 220),
            ],
            exactness="exact",
            supports_claims=["counts", "interpretation_anchor"],
        )
        if fact is not None:
            facts.append(fact)
    return facts


def _metadata_contract_boundary_facts(
    contract: AnalysisContract,
    item: EvidenceItem,
) -> List[ObservedFact]:
    """Expose proven metadata absences as usable negative results."""

    facts: List[ObservedFact] = []
    available_fields = [
        _normalise_example_text(field)
        for field in item.raw_surface.get("available_fields", [])
        if _normalise_example_text(field)
    ]
    if _metadata_blocks_trend(contract, [item]):
        fact = _make_fact(
            fact_id=f"{item.id}_temporal_axis_absent",
            statement=(
                _t("Für die angeforderte Trendanalyse ist keine Zeitachse "
                "verfügbar: Das vollständige Metadateninventar enthält kein "
                "erkennbares Datums-, Jahres- oder Zeitfeld.", 'No time axis is available for the requested trend analysis. The complete metadata inventory contains no recognisable date, year or time field.')
            ),
            fact_kind="negative_result",
            source_evidence_id=item.id,
            grounding_quotes=[
                _compact_text(f"available_fields={available_fields}", 220)
            ],
            exactness="exact",
            supports_claims=["interpretation_anchor"],
            limitations=[
                _t("Ohne belegte zeitliche Ordnung ist kein Trendurteil zulässig.", 'A trend assessment requires an established temporal ordering.')
            ],
        )
        if fact is not None:
            facts.append(fact)

    requested_register = _requested_register_value(contract.question_scope)
    if requested_register and _metadata_blocks_requested_register(
        contract,
        [item],
    ):
        values = item.raw_surface.get("values")
        register_values = (
            [
                _normalise_example_text(value)
                for value in values.get("register", [])
                if _normalise_example_text(value)
            ]
            if isinstance(values, dict)
            and isinstance(values.get("register"), list)
            else []
        )
        fact = _make_fact(
            fact_id=f"{item.id}_requested_register_absent",
            statement=(
                _t(f"Der angefragte Registerwert {requested_register} fehlt "
                "im vollständig inventarisierten Metadatenfeld register; "
                "belegt sind: ", f"""The requested register value {requested_register} is absent from the complete register metadata inventory. Established values: """)
                + ", ".join(register_values)
                + "."
            ),
            fact_kind="metadata",
            source_evidence_id=item.id,
            grounding_quotes=[
                _compact_text(f"values[register]={register_values}", 220)
            ],
            exactness="exact",
            supports_claims=["interpretation_anchor"],
            limitations=[
                _t("Eine Suche darf nicht stillschweigend auf einen anderen "
                "Register- oder Korpus-Scope ausweichen.", 'A search must not silently switch to a different register or corpus scope.')
            ],
        )
        if fact is not None:
            facts.append(fact)
    return facts


_GOVERNANCE_METADATA_FIELD_PATTERN = re.compile(
    r"(?:licen[cs]e|lizenz|provenance|provenienz|copyright|"
    r"rights?|rechte?|access|zugang|reuse|nachnutzung)",
    re.IGNORECASE,
)
_UNRESOLVED_METADATA_VALUE_PATTERN = re.compile(
    r"(?:^|[_\s-])(?:unknown|pending|unresolved|unclassified|"
    r"not[_\s-]?set|tbd|unklar|ungeklärt|ungeklaert|offen)"
    r"(?:$|[_\s-])",
    re.IGNORECASE,
)


def _metadata_governance_limitation_facts(
    item: EvidenceItem,
) -> List[ObservedFact]:
    """Expose unresolved licence/provenance states as research constraints."""

    values = item.raw_surface.get("values")
    if not isinstance(values, dict):
        return []
    value_counts = item.raw_surface.get("value_counts")
    if not isinstance(value_counts, dict):
        value_counts = {}
    facts: List[ObservedFact] = []
    for raw_field, raw_entries in values.items():
        field_name = _normalise_example_text(raw_field)
        if not field_name or not _GOVERNANCE_METADATA_FIELD_PATTERN.search(
            field_name
        ):
            continue
        entries = (
            raw_entries
            if isinstance(raw_entries, list)
            else [raw_entries]
        )
        unresolved_values = [
            _normalise_example_text(entry)
            for entry in entries
            if _normalise_example_text(entry)
            and _UNRESOLVED_METADATA_VALUE_PATTERN.search(
                _normalise_example_text(entry)
            )
        ]
        if not unresolved_values:
            continue
        quotes = [
            f"field={field_name}",
            _compact_text(
                f"values[{field_name}]={unresolved_values}",
                220,
            ),
        ]
        if field_name in value_counts:
            quotes.append(
                _compact_text(
                    f"value_count[{field_name}]="
                    f"{value_counts[field_name]}",
                    220,
                )
            )
        status = ", ".join(
            f"'{value}'" for value in unresolved_values[:3]
        )
        fact = _make_fact(
            fact_id=f"{item.id}_metadata_governance_{field_name}",
            statement=(
                _t(f"Das Governance-Metadatenfeld '{field_name}' weist mit "
                f"{status} einen ausdrücklich ungeklärten Status aus. "
                "Vor einer belastbaren Freigabe-, Nachnutzungs- oder "
                "Publikationsentscheidung muss dieser Status geprüft werden; "
                "der sichtbare Wert belegt keine Freigabe.", f"""The governance metadata field '{field_name}' explicitly marks an unresolved status: {status}. This status needs examination before a permission, reuse or publication decision. The visible value does not establish clearance.""")
            ),
            fact_kind="limitation",
            source_evidence_id=item.id,
            grounding_quotes=quotes,
            exactness="derived",
            supports_claims=["interpretation_anchor"],
            limitations=[
                _t("Ein ungeklärter Governance-Status ist eine Nutzbarkeits- "
                "und Provenienzgrenze, keine inhaltliche Korpusdimension.", 'An unresolved governance status concerns usability and provenance, rather than a content dimension of the corpus.')
            ],
        )
        if fact is not None:
            facts.append(fact)
    return facts


def _semantic_row_facts(item: EvidenceItem) -> List[ObservedFact]:
    rows = item.raw_surface.get("rows")
    if not isinstance(rows, list):
        return []
    facts: List[ObservedFact] = []
    for index, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            continue
        snippet = _normalise_example_text(
            row.get("snippet") or row.get("kw") or row.get("label") or row.get("text")
        )
        score = row.get("score")
        score_kind = str(row.get("score_kind") or "").strip().lower()
        doc_id = row.get("doc_id")
        bits: List[str] = [f"rank={index}"]
        if doc_id not in (None, ""):
            bits.append(f"doc_id={doc_id}")
        if score not in (None, ""):
            bits.append(f"score={score}")
        if score_kind:
            bits.append(f"score_kind={score_kind}")
        if not bits:
            continue
        quotes = [f"row[{index}] " + " ".join(bits)]
        if snippet:
            # A shortened hit ceases to be a verbatim grounding quote and used
            # to make long, valid semantic rows disappear during validation.
            quotes.append(f'hit="{snippet}"')
        if doc_id not in (None, ""):
            quotes.append(_compact_text(f"doc_id={doc_id}", 220))
        if score not in (None, ""):
            quotes.append(_compact_text(f"score={score}", 220))
        if score_kind:
            quotes.append(_compact_text(f"score_kind={score_kind}", 220))
        if (
            score_kind == "lexical"
            and _semantic_candidate_generation_uses_vectors(
                item.raw_surface
            )
        ):
            row_label = (
                _t("Der sichtbar lexikalisch bewertete Treffer aus "
                "einbettungsbasierter Kandidatensuche zeigt ", 'The visible lexically scored match from embedding-based candidate retrieval shows ')
            )
        elif score_kind == "lexical":
            row_label = _t("Der sichtbare lexikalisch gerankte Dokumenttreffer zeigt ", 'The visible lexically ranked document match shows ')
        elif score_kind in {"cosine", "embedding", "semantic", "vector"}:
            row_label = _t("Der sichtbare semantische Treffer zeigt ", 'The visible semantic match shows ')
        else:
            row_label = _t("Der sichtbare Treffer des semantic_search-Tools zeigt ", 'The visible semantic_search match shows ')
        fact = _make_fact(
            fact_id=f"{item.id}_semantic_{index}",
            statement=row_label + ", ".join(bits) + ".",
            fact_kind="kwic_example",
            source_evidence_id=item.id,
            grounding_quotes=quotes,
            exactness=_semantic_item_exactness(item),
            supports_claims=["examples", "interpretation_anchor"] if snippet else [],
            limitations=_semantic_meta_limitations(item),
            quote_limit=max(220, *(len(quote) for quote in quotes)),
        )
        if fact is not None:
            facts.append(fact)
    return facts


def _semantic_visible_row_count_fact(item: EvidenceItem) -> List[ObservedFact]:
    rows = item.raw_surface.get("rows")
    if not isinstance(rows, list):
        return []
    visible_rows = sum(isinstance(row, dict) for row in rows)
    quote = f"visible_rows={visible_rows}"
    fact = _make_fact(
        fact_id=f"{item.id}_semantic_visible_rows",
        statement=(
            _t("Die für die semantische Auswertung sichtbare Ergebnisliste "
            f"enthält visible_rows={visible_rows} Treffer.", f"""The result list visible to this semantic analysis contains visible_rows={visible_rows} matches.""")
        ),
        fact_kind="count",
        source_evidence_id=item.id,
        grounding_quotes=[quote],
        exactness="exact",
        supports_claims=["counts", "interpretation_anchor"],
        limitations=[
            _t("visible_rows zählt die für diesen Grounding-Lauf sichtbaren "
            "Treffer, nicht automatisch alle semantisch ähnlichen Dokumente.", 'visible_rows counts matches visible to this grounding run, rather than necessarily all semantically similar documents.')
        ],
    )
    return [fact] if fact is not None else []


def _compare_row_facts(item: EvidenceItem) -> List[ObservedFact]:
    rows = item.raw_surface.get("rows")
    if not isinstance(rows, list):
        return []
    facts: List[ObservedFact] = []
    for index, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            continue
        label = _normalise_example_text(row.get("word") or row.get("kw"))
        if not label:
            continue
        metrics = [
            f"freq_human={row.get('freq_human')}" if row.get("freq_human") not in (None, "") else "",
            f"freq_ai={row.get('freq_ai')}" if row.get("freq_ai") not in (None, "") else "",
            f"chi2_cell_human={row.get('chi2_cell_human')}" if row.get("chi2_cell_human") not in (None, "") else "",
            f"chi2_cell_ai={row.get('chi2_cell_ai')}" if row.get("chi2_cell_ai") not in (None, "") else "",
            _format_log_ratio_metric(row),
        ]
        metrics = [metric for metric in metrics if metric]
        if not metrics:
            continue
        metric_quotes = [
            _compact_text(f"{key}={row.get(key)}", 220)
            for key in (
                "freq_human",
                "freq_ai",
                "chi2_cell_human",
                "chi2_cell_ai",
                "log_ratio",
                "one_sided",
            )
            if row.get(key) not in (None, "")
        ]
        fact = _make_fact(
            fact_id=f"{item.id}_contrast_{index}",
            statement=_t(f"Der sichtbare Kollokationsvergleich zeigt '{label}' mit {'; '.join(metrics)}.", f"""The visible collocation comparison shows '{label}' with {', '.join(metrics)}."""),
            fact_kind="ranked_row",
            source_evidence_id=item.id,
            grounding_quotes=[
                _row_quote("row", index, row),
                _compact_text(f"word={label}", 220),
                *metric_quotes,
            ],
            exactness=_item_exactness(item, top_n_only=True),
            supports_claims=[
                "comparisons",
                "counts",
                "examples",
                "ranks",
                "interpretation_anchor",
            ],
        )
        if fact is not None:
            facts.append(fact)
    return facts


def _contrast_row_facts(item: EvidenceItem) -> List[ObservedFact]:
    """Surface pairing-free ``contrast_collocates`` diff rows as evidence.

    Mirrors :func:`_compare_row_facts` but reads the generic
    ``freq_target``/``freq_reference``/``chi2_cell_target``/``chi2_cell_reference`` columns
    produced by ``CollocationEngine.compare_by_docset_masks`` (the unpaired
    subcorpus-A-vs-B contrast) instead of the human/ai column names.
    """
    rows = item.raw_surface.get("rows")
    if not isinstance(rows, list):
        return []
    facts: List[ObservedFact] = []
    for index, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            continue
        label = _normalise_example_text(row.get("word") or row.get("kw"))
        if not label:
            continue
        metrics = [
            f"freq_target={row.get('freq_target')}" if row.get("freq_target") not in (None, "") else "",
            f"freq_reference={row.get('freq_reference')}" if row.get("freq_reference") not in (None, "") else "",
            f"chi2_cell_target={row.get('chi2_cell_target')}" if row.get("chi2_cell_target") not in (None, "") else "",
            f"chi2_cell_reference={row.get('chi2_cell_reference')}" if row.get("chi2_cell_reference") not in (None, "") else "",
            _format_log_ratio_metric(row),
        ]
        metrics = [metric for metric in metrics if metric]
        if not metrics:
            continue
        metric_quotes = [
            _compact_text(f"{key}={row.get(key)}", 220)
            for key in (
                "freq_target",
                "freq_reference",
                "chi2_cell_target",
                "chi2_cell_reference",
                "log_ratio",
                "one_sided",
            )
            if row.get(key) not in (None, "")
        ]
        fact = _make_fact(
            fact_id=f"{item.id}_contrast_{index}",
            statement=_t(f"Der sichtbare Teilkorpus-Kontrast zeigt '{label}' mit {'; '.join(metrics)}.", f"""The visible subcorpus contrast shows '{label}' with {', '.join(metrics)}."""),
            fact_kind="ranked_row",
            source_evidence_id=item.id,
            grounding_quotes=[
                _row_quote("row", index, row),
                _compact_text(f"word={label}", 220),
                *metric_quotes,
            ],
            exactness=_item_exactness(item, top_n_only=True),
            supports_claims=[
                "comparisons",
                "counts",
                "examples",
                "ranks",
                "interpretation_anchor",
            ],
        )
        if fact is not None:
            facts.append(fact)
    return facts


def _cluster_facts(item: EvidenceItem) -> List[ObservedFact]:
    clusters = _informative_clusters(item.raw_surface)
    facts: List[ObservedFact] = []
    for index, cluster in enumerate(clusters, start=1):
        if not isinstance(cluster, dict):
            continue
        cluster_id = cluster.get("cluster_id")
        size = cluster.get("size")
        label = _normalise_example_text(cluster.get("label"))
        bits: List[str] = []
        if cluster_id not in (None, ""):
            bits.append(f"cluster_id={cluster_id}")
        if size not in (None, ""):
            bits.append(f"size={size}")
        if label:
            bits.append(f'label="{label}"')
        sample_values = _cluster_sample_values(cluster)
        samples = ", ".join(sample_values[:4])
        if samples:
            bits.append(f'samples="{samples}"')
        if not bits:
            continue
        supports: List[str] = []
        if size not in (None, ""):
            supports.append("counts")
        if samples:
            supports.append("examples")
        fact = _make_fact(
            fact_id=f"{item.id}_cluster_{index}",
            statement=_t("Der sichtbare Cluster-Eintrag zeigt ", 'The visible cluster entry shows ') + ", ".join(bits) + ".",
            fact_kind="metadata",
            source_evidence_id=item.id,
            grounding_quotes=[
                _compact_text(f"cluster[{index}] {cluster}", 220),
                *(
                    [_compact_text(f"cluster_id={cluster_id}", 220)]
                    if cluster_id not in (None, "")
                    else []
                ),
                *([_compact_text(f"size={size}", 220)] if size not in (None, "") else []),
                *([_compact_text(f"label={label}", 220)] if label else []),
                *([_compact_text(f"samples={samples}", 220)] if samples else []),
            ],
            exactness=_item_exactness(item, top_n_only=True),
            supports_claims=supports,
        )
        if fact is not None:
            facts.append(fact)
    return facts


def _cluster_label_fact(item: EvidenceItem) -> List[ObservedFact]:
    label = _normalise_example_text(item.raw_surface.get("label"))
    if not label:
        return []
    fact = _make_fact(
        fact_id=f"{item.id}_cluster_label",
        statement=_t(f'Das sichtbare Cluster-Label lautet "{label}".', f"""The visible cluster label is "{label}"."""),
        fact_kind="metadata",
        source_evidence_id=item.id,
        grounding_quotes=[_compact_text(f"label={label}", 220)],
        exactness="derived",
        supports_claims=["examples"],
    )
    return [fact] if fact is not None else []


def _plan_facts(item: EvidenceItem) -> List[ObservedFact]:
    plan = item.raw_surface.get("plan")
    if not isinstance(plan, dict) or not plan:
        return []
    fact = _make_fact(
        fact_id=f"{item.id}_plan",
        statement=_t(f"Der sichtbare Cluster-Plan ist: {_compact_text(plan, 220)}.", f"""The visible cluster plan is: {_compact_text(plan, 220)}."""),
        fact_kind="metadata",
        source_evidence_id=item.id,
        grounding_quotes=[_compact_text(f"plan={plan}", 220)],
        exactness="derived",
        supports_claims=[],
    )
    return [fact] if fact is not None else []


def _keyness_direction_contexts(
    evidence_items: Sequence[EvidenceItem],
) -> Dict[str, Dict[str, Any]]:
    """Bind keyness directions to their analytical and technical scopes."""

    docsets: Dict[str, Dict[str, Any]] = {}
    for item in evidence_items:
        if item.tool != "create_docset" or item.status == "error":
            continue
        docset_id = str(item.raw_surface.get("docset_id") or "").strip()
        label = _normalise_example_text(item.raw_surface.get("label"))
        if not docset_id or not label:
            continue
        try:
            query = json.loads(item.query) if item.query else {}
        except (TypeError, ValueError, json.JSONDecodeError):
            query = {}
        filters = query.get("filters") if isinstance(query, dict) else None
        scalar_filters: List[tuple[str, str]] = []
        if isinstance(filters, dict):
            for field_name, raw_value in filters.items():
                if isinstance(raw_value, (dict, list, tuple, set)):
                    continue
                field = _normalise_example_text(field_name)
                value = _normalise_example_text(raw_value)
                if field and value:
                    scalar_filters.append((field, value))
        analytical_label = (
            scalar_filters[0][1] if len(scalar_filters) == 1 else label
        )
        quotes = [
            line
            for line in item.grounding_surface
            if line in {f"docset_id={docset_id}", f"label={label}"}
            or line.startswith("tool_args=")
        ]
        if f"label={label}" not in quotes:
            continue
        docsets[docset_id] = {
            "analytical_label": analytical_label,
            "docset_label": label,
            "source_evidence_id": item.id,
            "grounding_quotes": quotes,
        }

    contexts: Dict[str, Dict[str, Any]] = {}
    for item in evidence_items:
        if item.tool != "keyness" or item.status == "error":
            continue
        try:
            query = json.loads(item.query) if item.query else {}
        except (TypeError, ValueError, json.JSONDecodeError):
            query = {}
        if not isinstance(query, dict):
            continue
        target = docsets.get(
            str(query.get("target_docset_id") or "").strip()
        )
        reference = docsets.get(
            str(query.get("reference_docset_id") or "").strip()
        )
        if not target or not reference:
            continue
        tool_args_quote = next(
            (
                line
                for line in item.grounding_surface
                if line.startswith("tool_args=")
            ),
            "",
        )
        grounding_selection = _normalise_example_text(
            item.raw_surface.get("grounding_selection")
        )
        contexts[item.id] = {
            "target_label": target["analytical_label"],
            "reference_label": reference["analytical_label"],
            "target_docset_label": target["docset_label"],
            "reference_docset_label": reference["docset_label"],
            "grounding_selection": grounding_selection,
            "source_evidence_ids": list(
                dict.fromkeys(
                    [
                        item.id,
                        target["source_evidence_id"],
                        reference["source_evidence_id"],
                    ]
                )
            ),
            "grounding_quotes": list(
                dict.fromkeys(
                    [
                        tool_args_quote,
                        *(
                            [f"grounding_selection={grounding_selection}"]
                            if grounding_selection
                            else []
                        ),
                        *target["grounding_quotes"],
                        *reference["grounding_quotes"],
                    ]
                )
            ),
        }
    return contexts


def deterministic_observed_facts(
    contract: AnalysisContract,
    evidence_items: Sequence[EvidenceItem],
) -> List[ObservedFact]:
    _ = contract
    facts: List[ObservedFact] = []
    validation_items: List[EvidenceItem] = []
    seen: set[str] = set()
    keyness_direction_contexts = _keyness_direction_contexts(
        evidence_items
    )
    for item in evidence_items:
        fact_surface = item.fact_surface or item.raw_surface
        if item.tool == "keyness" and isinstance(
            item.raw_surface.get("rows"), list
        ):
            # The model sees this direction-balanced window. Using the full,
            # globally sorted result would overflow the fact budget with only
            # its first direction and make the visible evidence unverifiable.
            fact_surface = item.raw_surface
        fact_item = (
            replace(item, raw_surface=fact_surface)
            if fact_surface
            else item
        )
        item_facts: List[ObservedFact] = []
        item_facts.extend(_limitation_facts_for_item(fact_item))
        item_facts.extend(_not_applicable_facts_for_item(fact_item))
        item_facts.extend(_query_error_facts(fact_item))
        if fact_item.tool == "frequency_list":
            item_facts.extend(_frequency_pos_scope_fact(fact_item))
            item_facts.extend(_frequency_scope_facts(fact_item))
            item_facts.extend(_frequency_row_facts(fact_item))
        elif fact_item.tool == "run_cqlf_query":
            item_facts.extend(_kwic_facts(fact_item))
        elif fact_item.tool == "kwic_context":
            item_facts.extend(_expanded_kwic_context_facts(fact_item))
        elif fact_item.tool == "query_count":
            item_facts.extend(_query_count_facts(fact_item))
        elif fact_item.tool in {"document_search", "documentation_search"}:
            item_facts.extend(
                _document_row_facts(
                    fact_item,
                    source_label=(
                        _t("Dokument", 'document')
                        if fact_item.tool == "document_search"
                        else _t("Dokumentations", 'documentation')
                    ),
                )
            )
        elif fact_item.tool == "metadata_values":
            item_facts.extend(_metadata_available_fields_fact(fact_item))
            item_facts.extend(_metadata_value_facts(fact_item))
            item_facts.extend(
                _metadata_contract_boundary_facts(contract, fact_item)
            )
            item_facts.extend(
                _metadata_governance_limitation_facts(fact_item)
            )
        elif fact_item.tool == "create_docset":
            item_facts.extend(_docset_scope_facts(fact_item))
        elif fact_item.tool == "semantic_search":
            item_facts.extend(_semantic_meta_limitation_facts(fact_item))
            item_facts.extend(_semantic_visible_row_count_fact(fact_item))
            item_facts.extend(_semantic_row_facts(fact_item))
        elif fact_item.tool in {
            "collocate_stats",
            "word_sketch",
            "keyness",
            "ngram_frequency",
        }:
            item_facts.extend(_returned_metric_row_count_fact(fact_item))
            item_facts.extend(_collocation_method_facts(fact_item))
            if fact_item.tool == "keyness":
                item_facts.extend(_keyness_nenner_fakt(fact_item))
            item_facts.extend(
                _metric_row_facts(
                    fact_item,
                    direction_context=keyness_direction_contexts.get(
                        fact_item.id
                    ),
                )
            )
            if fact_item.tool == "word_sketch":
                item_facts.extend(_relation_metadata_facts(fact_item))
                item_facts.extend(_table_metric_facts(fact_item))
        elif fact_item.tool == "lexical_diversity":
            item_facts.extend(_lexical_diversity_facts(fact_item))
        elif fact_item.tool == "trend_analysis":
            item_facts.extend(_trend_facts(fact_item))
        elif fact_item.tool == "compare_collocates":
            item_facts.extend(_returned_metric_row_count_fact(fact_item))
            item_facts.extend(_compare_row_facts(fact_item))
        elif fact_item.tool == "contrast_collocates":
            item_facts.extend(_contrast_row_facts(fact_item))
        elif fact_item.tool == "dispersion_offsets":
            item_facts.extend(_dispersion_facts(fact_item))
        elif fact_item.tool in {"semantic_cluster", "semantic_cluster_words"}:
            item_facts.extend(_cluster_facts(fact_item))
        elif fact_item.tool == "refine_cluster_label":
            item_facts.extend(_cluster_label_fact(fact_item))
        elif fact_item.tool == "semantic_recluster":
            item_facts.extend(_plan_facts(fact_item))
        analysis_input_quote = next(
            (
                line
                for line in item.grounding_surface
                if line.startswith("analysis_input=")
            ),
            "",
        )
        for fact in item_facts:
            if (
                analysis_input_quote
                and analysis_input_quote not in fact.grounding_quotes
            ):
                fact.grounding_quotes.append(analysis_input_quote)
            if fact.id in seen:
                continue
            seen.add(fact.id)
            facts.append(fact)
        # Deterministic extractors derive these quotes directly from the full
        # returned tool surface. Keep them available to the validator without
        # exposing every returned row to the model-facing grounding window.
        validation_items.append(
            replace(
                fact_item,
                grounding_surface=list(
                    dict.fromkeys(
                        [
                            *fact_item.grounding_surface,
                            *[
                                quote
                                for fact in item_facts
                                for quote in fact.grounding_quotes
                            ],
                        ]
                    )
                ),
            )
        )
    for fact in _collocation_comparison_facts(
        contract,
        validation_items,
    ):
        if fact.id in seen:
            continue
        seen.add(fact.id)
        facts.append(fact)
    for fact in _collocation_floor_facts(
        contract,
        validation_items,
    ):
        if fact.id in seen:
            continue
        seen.add(fact.id)
        facts.append(fact)
    return validate_observed_facts(
        facts,
        evidence_items=validation_items,
    )


def synthese_fenster_kappe(
    analysis_family: str,
    requested_sample_rows: int,
) -> int:
    """Wie viele Fakten die Synthese sieht.

    Erweiterte Kontextfragen brauchen die lokalisierte Passage, nicht jede
    Zeile, die ein Modell ohne KWIC-Limit zurueckbekommt. Deshalb kappt der
    kwic_context-Zweig enger als das Default-Fenster, ohne eine ausdruecklich
    angeforderte reproduzierbare Stichprobe zu beschneiden.

    Ohne angeforderte Stichprobe ergibt das 12. Genau diese Zahl war bis P8
    unsichtbar, weil die Meldung ueber der Konstanten 64 haengt.
    """
    if analysis_family != "kwic_context":
        return DEFAULT_SYNTHESIS_FACT_LIMIT
    return min(
        DEFAULT_SYNTHESIS_FACT_LIMIT,
        max(12, int(requested_sample_rows or 0) + 4),
    )


def select_synthesis_window(
    facts: Sequence[ObservedFact],
    *,
    analysis_family: str,
    requested_sample_rows: int = 0,
) -> List[ObservedFact]:
    """Kappe rechnen, auswaehlen und die Verdichtung melden.

    Die Meldung stand bis P8 im Orchestrator und prueste dort
    ``DEFAULT_SYNTHESIS_FACT_LIMIT`` (64) statt der wirksamen Kappe. Ein
    kwic_context-Turn ohne angeforderte Stichprobe kappt bei 12 und loggte
    deshalb nichts. Sie liegt jetzt hier, weil eine Meldung, die kein Test
    lesen kann, so gut wie keine ist: der Orchestrator-Zweig war eine innere
    Funktion in einer inneren Funktion einer async-Methode.
    """
    max_items = synthese_fenster_kappe(analysis_family, requested_sample_rows)
    selected = select_balanced_observed_facts(facts, max_items=max_items)
    omitted_count = len(facts) - len(selected)
    if len(facts) > max_items and omitted_count > 0:
        _LOGGER.info(
            "Grounding-Kontext intern verdichtet: %d von %d belegten Fakten "
            "nicht einzeln an die Synthese übergeben (Kappe %d).",
            omitted_count,
            len(facts),
            max_items,
        )
    return selected


def select_balanced_observed_facts(
    observed_facts: Sequence[ObservedFact],
    *,
    max_items: int = DEFAULT_SYNTHESIS_FACT_LIMIT,
) -> List[ObservedFact]:
    """Bound LLM context while retaining evidence from every tool result."""
    deduplicated_facts: List[ObservedFact] = []
    seen_limitations: set[tuple[str, tuple[str, ...]]] = set()
    for fact in observed_facts:
        if fact.fact_kind == "limitation":
            limitation_key = (
                " ".join(fact.statement.casefold().split()),
                tuple(
                    " ".join(item.casefold().split())
                    for item in fact.limitations
                ),
            )
            if limitation_key in seen_limitations:
                continue
            seen_limitations.add(limitation_key)
        deduplicated_facts.append(fact)

    if len(deduplicated_facts) <= max_items:
        return deduplicated_facts

    def spread_order(values: Sequence[ObservedFact]) -> List[ObservedFact]:
        """Cover a bounded ordered result without pretending to sample it."""

        if len(values) <= 2:
            return list(values)
        indices = [0, len(values) - 1]
        intervals = [(0, len(values) - 1)]
        while intervals:
            next_intervals: List[tuple[int, int]] = []
            for low, high in intervals:
                if high - low <= 1:
                    continue
                middle = (low + high) // 2
                if middle not in indices:
                    indices.append(middle)
                next_intervals.extend(((low, middle), (middle, high)))
            intervals = next_intervals
        return [values[index] for index in indices]

    source_order: List[str] = []
    by_source: Dict[str, List[ObservedFact]] = {}
    limitations: List[ObservedFact] = []
    for fact in deduplicated_facts:
        source_id = fact.source_evidence_ids[0] if fact.source_evidence_ids else ""
        if source_id not in by_source:
            source_order.append(source_id)
            by_source[source_id] = []
        if fact.fact_kind == "limitation":
            limitations.append(fact)
        else:
            by_source[source_id].append(fact)

    for source_id in source_order:
        by_source[source_id].sort(
            key=lambda fact: (
                0 if len(fact.source_evidence_ids) > 1 else 1,
                # Der series-Fakt steht VOR den Einzelzaehlungen (Diagnose
                # GOAL-Defekt 3): im alten Schlüssel wirkte seine Priorität
                # -1 nur im LETZTEN Kriterium, sodass die counts einer
                # Quelle vorgingen und das Fenster dem Traeger nie einen
                # Platz gab. Er ist das komprimierte Ergebnis eines ganzen
                # Werkzeugs und ueberlebt als erstes jede Kappe.
                0
                if fact.fact_kind == "series"
                else 1
                if fact.fact_kind == "negative_result"
                else 2
                if fact.fact_kind == "count"
                else 3,
                not bool(fact.supports_claims),
                fact.exactness != "exact",
                "interpretation_anchor" not in set(fact.supports_claims),
                {
                    "series": -1,
                    "metadata": 0,
                    "distribution": 1,
                    "ranked_row": 2,
                    "kwic_example": 2,
                }.get(fact.fact_kind, 3),
            )
        )
        kwic_positions = [
            index
            for index, fact in enumerate(by_source[source_id])
            if fact.fact_kind == "kwic_example"
        ]
        if len(kwic_positions) > 2:
            spread_kwic = spread_order(
                [by_source[source_id][index] for index in kwic_positions]
            )
            for index, fact in zip(kwic_positions, spread_kwic):
                by_source[source_id][index] = fact

    selected: List[ObservedFact] = []
    # Source coverage comes before limitations. Repeated generic bounds have
    # already been collapsed, so the remaining slots carry distinct caveats
    # instead of erasing an entire tool result.
    # P8: der feste Deckel 8 war fuer das Default-Fenster (64 Plaetze)
    # gedacht. Ein kwic_context-Turn ohne angeforderte Stichprobe kappt bei
    # 12, und dort nahmen die Limitationen 8 der 12 Plaetze, so dass fuer
    # KWIC-Zeilen 4 blieben. Ein Drittel des Fensters bindet den Deckel an die
    # wirksame Kappe: bei max_items=64 bleibt es beim alten Wert 8, bei
    # max_items=12 sind es 4 und die Belege behalten 8 Plaetze. Die Zahl der
    # Quellen ist die Untergrenze, damit jede Quelle ihre eigene Grenze
    # mitbringen kann (max_items=8 mit drei Quellen bleibt bei 3).
    limitation_budget = min(
        8,
        max(len(source_order), max_items // 3),
        len(limitations),
        max(0, max_items - len(source_order)),
    )
    content_budget = max_items - limitation_budget
    offset = 0
    while len(selected) < content_budget:
        added = False
        for source_id in source_order:
            source_facts = by_source[source_id]
            if offset < len(source_facts):
                selected.append(source_facts[offset])
                added = True
                if len(selected) >= content_budget:
                    break
        if not added:
            break
        offset += 1

    for fact in limitations:
        if len(selected) >= max_items:
            break
        selected.append(fact)
    return selected


# Numeric extraction must recognise grouped/thousands-separated numbers so that a
# claim's "1.234" / "1 234" / "1,234" all normalise to the SAME canonical token as
# the raw integer "1234" a tool renders into the grounding surface. Without this,
# a perfectly grounded count is false-rejected merely because the LLM rendered it
# with a German thousands dot while the evidence holds the bare integer. The
# pattern, longest-alternative-first:
#   1. German/space-grouped:  1.234  /  1 234  /  1.234.567  /  12 345,6
#   2. English-grouped:       1,234  /  1,234,567  /  1,234.56
#   3. plain decimal/integer: 42  /  3,14  /  3.14
# Group separators include the ASCII space plus U+00A0 (no-break space) and
# U+202F (narrow no-break space) that locale/UI formatters emit, so spaced
# thousands like "1 234" count as a single number, not two.
for _tens_word, _tens_value in _GERMAN_TENS.items():
    _COUNT_WORD_VALUES[_tens_word] = str(_tens_value)
    for _unit_word, _unit_value in _GERMAN_COMPOUND_NUMBER_UNITS.items():
        _COUNT_WORD_VALUES[f"{_unit_word}und{_tens_word}"] = str(
            _tens_value + _unit_value
        )


# Quoted-segment extraction covers every quote pair a German answer can use to
# present a corpus example: the internal ``<<...>>`` marker, the ASCII straight
# double quote, and the full set of Unicode/German typographic pairs
# („ … “ low-high, » … « German guillemets, « … » French guillemets, “ … ”
# English curly doubles, ‚ … ‘ German curly singles, ‘ … ’ English curly
# singles). ASCII *single* quotes are
# deliberately excluded so apostrophes ("Müller's", "geht's") do not register
# as fabricated examples — only genuine typographic single quotes are matched.
# Each alternative keeps its inner text in its own capture group; the extractor
# picks the first non-empty group, so adding a pair never reshuffles indices.
# Tokens that, on their own, are too weak/ambiguous to demand an interpretation
# anchor: "eher", "klar", "deutlich", "offenbar", "wirkt" appear constantly in
# honest hedged prose ("eher selten", "deutlich sichtbar in den Belegen") and
# produced false positives in the envelope gate. The dominance/category gate
# below uses the tightened _CATEGORY_PATTERN; the legacy weak tokens are kept
# only for the exactness-downgrade heuristic (_stronger_than_exactness).
def validate_observed_facts(
    observed_facts: Sequence[ObservedFact],
    *,
    evidence_items: Sequence[EvidenceItem],
) -> List[ObservedFact]:
    evidence_index = {
        str(item.id): item
        for item in evidence_items
        if str(item.id).strip()
    }
    result: List[ObservedFact] = []
    seen: set[str] = set()
    for fact in observed_facts:
        if not fact.source_evidence_ids:
            continue
        if any(source_id not in evidence_index for source_id in fact.source_evidence_ids):
            continue
        if not fact.grounding_quotes:
            continue
        referenced_items = [evidence_index[source_id] for source_id in fact.source_evidence_ids]
        if not all(_is_authoritative_evidence_item(item) for item in referenced_items):
            continue
        allowed_quotes = {
            quote
            for item in referenced_items
            for quote in item.grounding_surface
        }
        if any(quote not in allowed_quotes for quote in fact.grounding_quotes):
            continue
        joined_quotes = _joined_surface_text(fact.grounding_quotes)
        # Set membership, NOT substring: a substring check passes a fabricated "42"
        # whenever the evidence happens to contain "1429" / "0.42" etc.
        allowed_numbers = set(_extract_numeric_tokens(joined_quotes))
        numeric_tokens = _extract_numeric_tokens(fact.statement)
        if numeric_tokens and any(
            not _numeric_token_is_supported(token, allowed_numbers)
            for token in numeric_tokens
        ):
            continue
        allowed_ranges = set(_extract_ranges(joined_quotes))
        ranges = _extract_ranges(fact.statement)
        if ranges and any(range_token not in allowed_ranges for range_token in ranges):
            continue
        quoted_segments = _extract_grounding_example_segments(fact.statement)
        if quoted_segments and any(
            not any(
                _quoted_segment_is_supported(segment, grounding_quote)
                for grounding_quote in fact.grounding_quotes
            )
            for segment in quoted_segments
        ):
            continue
        if _unsupported_model_fact_terms(fact):
            continue
        if not _model_fact_has_atomic_quote_support(fact):
            continue
        _sanitise_model_fact_contract(fact, referenced_items)
        if fact.id in seen:
            continue
        seen.add(fact.id)
        result.append(fact)
    return result




# --------------------------------------------------------------------------- #
# Lexical-search / question-text helpers (moved verbatim from the facade
# tail; they sit in this layer because the observed-fact builders above
# read them).
# --------------------------------------------------------------------------- #
_SINGLE_LEXICAL_CQLF_QUERY_PATTERN = re.compile(
    r"^\s*\[\s*(?P<attribute>word|lemma)\s*=\s*"
    r"([\"'])(?P<term>[^\"']+)\2(?:\s+%(?:c|d))?\s*\]\s*$",
    re.IGNORECASE,
)
_CQLF_SEQUENCE_DESCRIPTION_PATTERN = re.compile(
    r"\b(?:gefolgt\s+von|darauf\s+folgend|danach|anschließend|"
    r"anschliessend|tokenfolge|sequenz|followed\s+by|then|subsequent)\b",
    re.IGNORECASE,
)
_CQLF_QUERY_DESCRIPTION_PATTERN = re.compile(
    r"\b(?:cqlf(?:-abfrage)?|query|abfrage|suchlauf|suche|treffer|"
    r"ergebnis\w*)\b",
    re.IGNORECASE,
)


def _fact_cqlf_queries(facts: Sequence[ObservedFact]) -> List[str]:
    queries: List[str] = []
    for fact in facts:
        for surface in [fact.statement, *fact.grounding_quotes]:
            match = re.search(r"(?:^|\s)query=(.+)$", str(surface or ""))
            if match:
                query = _normalise_example_text(match.group(1))
                if query:
                    queries.append(query)
            for quoted in re.findall(
                r"CQLF-Abfrage\s+['\"]([^'\"]+)['\"]",
                str(surface or ""),
                re.IGNORECASE,
            ):
                query = _normalise_example_text(quoted)
                if query:
                    queries.append(query)
    return _normalise_text_list(queries, max_items=8, item_limit=500)


def _misdescribed_multi_token_cqlf_query(
    claim_text: str,
    facts: Sequence[ObservedFact],
) -> str:
    """Catch a token sequence flattened into one attribute/value lookup."""

    claim_surface = " ".join(str(claim_text or "").casefold().split())
    if _CQLF_QUERY_DESCRIPTION_PATTERN.search(claim_surface) is None:
        return ""
    claim_tokens = set(re.findall(r"\w+", claim_surface, re.UNICODE))
    for query in _fact_cqlf_queries(facts):
        query_surface = " ".join(query.casefold().split())
        if query_surface and query_surface in claim_surface:
            continue
        units = re.findall(r"\[[^\[\]]+\]", query)
        if len(units) < 2:
            continue
        unit_tokens = [
            {
                token.casefold()
                for token in re.findall(r"[\wÄÖÜäöüß]+", unit, re.UNICODE)
                if len(token) >= 3
            }
            for unit in units
        ]
        mentioned_units = sum(
            bool(tokens.intersection(claim_tokens))
            for tokens in unit_tokens
        )
        if (
            mentioned_units >= 2
            and _CQLF_SEQUENCE_DESCRIPTION_PATTERN.search(claim_text or "")
            is None
        ):
            return query
    return ""


def _exact_lexical_search(item: EvidenceItem) -> Tuple[str, str]:
    """Return the lexical attribute and term for one exact-token lookup."""

    if (
        item.tool not in {"run_cqlf_query", "query_count"}
        or str(item.status or "").strip().casefold() == "error"
    ):
        return "", ""
    try:
        parsed_args = json.loads(item.query) if item.query else {}
    except (TypeError, ValueError, json.JSONDecodeError):
        parsed_args = {}
    query = _normalise_example_text(
        item.raw_surface.get("query")
        or (
            parsed_args.get("query")
            if isinstance(parsed_args, dict)
            else ""
        )
    )
    query_mode = _normalised_question_text(
        item.raw_surface.get("query_mode")
    )
    if query_mode == "plain_word":
        return (
            ("word", query)
            if query and not re.search(r"\s", query)
            else ("", "")
        )
    match = _SINGLE_LEXICAL_CQLF_QUERY_PATTERN.fullmatch(query)
    if not match:
        return "", ""
    return (
        str(match.group("attribute") or "").casefold(),
        _normalise_example_text(match.group("term")),
    )


def _cqlf_query_scope_statement(item: EvidenceItem, query: str) -> str:
    """Describe what the executed query did not test, at the right granularity."""

    attribute, term = _exact_lexical_search(item)
    escaped_term = term.replace("'", "’")
    if attribute == "word":
        case_insensitive = item.raw_surface.get("case_insensitive")
        case_variants = (
            _t(" Groß- und Kleinschreibung wurden dabei nicht unterschieden.", ' Case was ignored.')
            if case_insensitive is True
            or str(case_insensitive or "").strip().casefold()
            in {"1", "true", "yes"}
            else ""
        )
        return (
            _t(f"Das sichtbare Ergebnis gilt nur für die ausgeführte "
            f"Wortformenabfrage '{escaped_term}'.{case_variants} Andere "
            "Flexions- oder Lemmaformen, Komposita, Synonyme und semantisch "
            "verwandte Formulierungen wurden damit nicht geprüft.", f"""The visible result applies to the executed word-form query '{escaped_term}'.{case_variants} Other inflections, lemma forms, compounds, synonyms and semantically related expressions were not tested.""")
        )
    if attribute == "lemma":
        return (
            _t(f"Das sichtbare Ergebnis gilt nur für die ausgeführte "
            f"Lemmaabfrage '{escaped_term}'. Komposita, andere Lemmata oder "
            "Synonyme und semantisch verwandte Formulierungen wurden damit "
            "nicht geprüft. Sie prüft die Indexannotation, nicht deren "
            "linguistische Richtigkeit.", f"""The visible result applies to the executed lemma query '{escaped_term}'. Compounds, other lemmas, synonyms and semantically related expressions were not tested. It tests the index annotation, rather than its linguistic correctness.""")
        )
    annotation_boundary = (
        _t(" Die Query prüft Indexannotationen, nicht deren fehlerfreie "
        "linguistische Klassifikation.", ' The query tests index annotations, rather than validating their linguistic correctness.')
        if _annotation_sensitive_cqlf_query(query)
        else ""
    )
    return (
        _t(f"Das sichtbare Ergebnis gilt nur für die ausgeführte Query '{query}'; "
        "andere Tokenfolgen, Attributkombinationen und semantisch verwandte "
        "Formulierungen wurden damit nicht geprüft.", f"""The visible result applies to the executed query '{query}'. Other token sequences, attribute combinations and semantically related expressions were not tested.""")
        + annotation_boundary
    )


def _requested_frequency_result_count(question_text: str) -> int | None:
    text = _normalised_question_text(question_text)
    if not re.search(
        r"\b(?:frequenz(?:liste|rangliste)?|häufigst\w*|haeufigst\w*|"
        r"an\s+der\s+spitze)\b",
        text,
        re.IGNORECASE,
    ):
        return None
    count_token = (
        rf"\d+|{_COUNT_WORD_PATTERN_SOURCE}|"
        rf"{_LARGE_COUNT_WORD_PATTERN_SOURCE}"
    )
    patterns = (
        rf"\b(?:top[- ]?)?(?P<count>{count_token})\s+"
        r"(?:wortformen?|lemmata?|wörter?|woerter?|nomen|substantive?|"
        r"einträge?|eintraege?|positionen?)\b",
        rf"\btop[- ]?(?P<count>{count_token})\b",
        rf"\b(?P<count>{count_token})\s+(?:häufigst\w*|haeufigst\w*)\b",
    )
    match = next(
        (match for pattern in patterns if (match := re.search(pattern, text, re.IGNORECASE))),
        None,
    )
    if match is None:
        return None
    token = match.group("count")
    try:
        value = int(token)
    except ValueError:
        parsed = _number_word_value(token)
        value = int(parsed) if parsed is not None else 0
    return value if 1 <= value <= 50 else None


def _question_requests_kwic_table(question_text: str) -> bool:
    text = _normalised_question_text(question_text)
    return bool(
        re.search(
            r"\bkwic\b[^.!?\n]{0,100}\b(?:evidenz|belege?|zeilen?|"
            r"auswahl|stichprob\w*|sample\w*|zeigen?)\b",
            text,
            re.IGNORECASE,
        )
        or re.search(
            r"\b(?:stichprob\w*|sample\w*|reproduzier\w*)\b"
            r"[^.!?\n]{0,100}\bkwic\b",
            text,
            re.IGNORECASE,
        )
    )


def _question_term(text: str) -> str:
    raw = str(text or "")
    parsed = _extract_json(raw)
    if isinstance(parsed, dict):
        for key in ("term", "query", "word", "lemma"):
            value = _normalise_example_text(parsed.get(key))
            if value:
                return value
    quoted = re.search(r"[\"'`„“‚‘]([^\"'`„“‚‘]{2,80})[\"'`„“‚‘]", raw)
    if quoted:
        return _normalise_example_text(quoted.group(1))
    return ""


_COMPARABLE_METADATA_FIELDS = ("source", "register", "model", "text_type", "variant", "reference_kind")
