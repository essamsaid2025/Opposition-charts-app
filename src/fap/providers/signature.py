"""What a provider knows about how its own files look.

A provider declares evidence, never a decision: the intelligence engine
(fap.providers.intelligence) weighs the evidence of every candidate and picks a
winner. That is what keeps provider detection free of ``if provider == ...`` -
adding a vendor is one class with one signature, and the engine is untouched.

Every field is optional. A provider with no signature is still detected the way
it always was, through ``DataProvider.supports(filename)``.
"""
from __future__ import annotations

from dataclasses import dataclass, field

# Weighted evidence. Positive rules earn confidence, negative rules destroy it.
# The engine normalizes a provider's score by what its own signature could
# possibly earn, so a sparse signature is not punished for being sparse.
WEIGHT_FILENAME = 10
WEIGHT_METADATA = 20
WEIGHT_REQUIRED_COLUMNS = 30
WEIGHT_OPTIONAL_COLUMNS = 10
WEIGHT_JSON_STRUCTURE = 25
WEIGHT_SHEET_NAMES = 20
WEIGHT_VALUE_PATTERNS = 15
WEIGHT_FINGERPRINT = 40
PENALTY_MISSING_REQUIRED = -25
PENALTY_UNKNOWN_SCHEMA = -20


@dataclass(frozen=True, slots=True)
class ProviderSignature:
    """Recognition evidence for one provider.

    supported_extensions
        Hard gate, not a score: a file this provider cannot physically read is
        never a candidate. Empty means "any extension".
    filename_patterns
        Case-insensitive substrings of the file name ("statsbomb", "f24").
    sheet_names / metadata_patterns
        Workbook evidence: sheet titles, and text in the workbook's own
        properties (creator, title, company).
    required_columns
        Columns the format always has. Absent when other evidence exists ->
        penalty; this is what stops a near-miss from being declared a match.
    optional_columns
        Columns that are typical but not guaranteed.
    json_patterns
        Top-level JSON keys ("events", "matchPeriod").
    nested_object_patterns
        Dotted paths inside records ("type.name", "pass.end_location") - the
        shape that distinguishes vendor JSON from a flat export.
    provider_identifiers
        Strings that essentially only occur in this vendor's files
        ("statsbomb_xg", "qualifier_id"). The strongest single signal.
    known_value_patterns
        Regexes matched against sampled cell values, for formats whose columns
        are generic but whose values are not.
    schema_version
        Reported in the import summary; free text.
    priority
        Tie-break only, never a substitute for evidence. Generic catch-alls sit
        below zero so a vendor with equal evidence always wins.
    """
    supported_extensions: tuple[str, ...] = ()
    filename_patterns: tuple[str, ...] = ()
    sheet_names: tuple[str, ...] = ()
    required_columns: tuple[str, ...] = ()
    optional_columns: tuple[str, ...] = ()
    metadata_patterns: tuple[str, ...] = ()
    json_patterns: tuple[str, ...] = ()
    nested_object_patterns: tuple[str, ...] = ()
    provider_identifiers: tuple[str, ...] = ()
    known_value_patterns: tuple[str, ...] = ()
    schema_version: str = ""
    priority: int = 0
    generic: bool = False          # a catch-all: recognized, but never preferred

    def achievable_score(self) -> int:
        """The most this signature could earn, used to normalize confidence."""
        total = 0
        if self.filename_patterns:
            total += WEIGHT_FILENAME
        if self.metadata_patterns:
            total += WEIGHT_METADATA
        if self.required_columns:
            total += WEIGHT_REQUIRED_COLUMNS
        if self.optional_columns:
            total += WEIGHT_OPTIONAL_COLUMNS
        if self.json_patterns:
            total += WEIGHT_JSON_STRUCTURE
        if self.nested_object_patterns:
            total += WEIGHT_JSON_STRUCTURE
        if self.sheet_names:
            total += WEIGHT_SHEET_NAMES
        if self.known_value_patterns:
            total += WEIGHT_VALUE_PATTERNS
        if self.provider_identifiers:
            total += WEIGHT_FINGERPRINT
        return total
