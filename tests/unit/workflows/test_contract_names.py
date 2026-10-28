"""The single owner names every catalog schema with a plain, direction-free name."""

import re

import pytest

from workflows.definition.catalog import CAPABILITIES, COLLECTION_CONTRACTS, CONTRACTS
from workflows.definition.contract_names import (
    SCHEMA_NAMES,
    adaptor_name,
    contract_name,
    contract_schema,
)

# Abbreviations a newcomer would have to decode; names use the plain words instead.
FORBIDDEN_ABBREVIATIONS = {
    "llm", "id", "ids", "ref", "refs", "impl", "cfg", "config", "interp", "ctx",
    "opt", "spec", "io", "api", "ml", "ai", "req", "resp", "dir", "info", "param",
    "params", "proto", "lit", "val",
}  # fmt: skip
# A name describes the schema, not which way it flows; sockets show direction.
DIRECTION_WORDS = {
    "input", "inputs", "output", "outputs", "in", "out", "incoming", "outgoing",
    "inbound", "outbound", "request", "response", "reply", "result", "source",
    "sink", "send", "sends", "receive", "receives", "from", "to",
}  # fmt: skip
# Module names; a schema shared by several modules must not be named after one.
MODULE_WORDS = {
    *CAPABILITIES,
    "interpreter", "proposer", "implementor", "implementer", "validator", "tuner",
}  # fmt: skip


def test_every_catalog_schema_has_one_plain_name_free_of_direction_and_module():
    """Fails if a catalog contract's schema has no name (the browser would fall back
    to an id-derived label), two schemas share a name or description, a name exceeds
    three words, uses punctuation, an abbreviation, a direction word or a module."""
    assert {contract_schema(contract) for contract in CONTRACTS} == set(SCHEMA_NAMES)
    names = [item.name.casefold() for item in SCHEMA_NAMES.values()]
    assert len(set(names)) == len(names)
    descriptions = [item.description for item in SCHEMA_NAMES.values()]
    assert len(set(descriptions)) == len(descriptions)
    for schema, item in SCHEMA_NAMES.items():
        assert re.fullmatch(r"[A-Z][a-z]*( [a-z]+){0,2}", item.name), (schema, item.name)
        words = set(item.name.casefold().split())
        assert not words & FORBIDDEN_ABBREVIATIONS, (schema, item.name)
        assert not words & DIRECTION_WORDS, (schema, item.name)
        assert not words & MODULE_WORDS, (schema, item.name)
        # One sentence: capitalised, ends with a full stop, no second sentence.
        assert re.fullmatch(r"[A-Z][^.]*\.", item.description), (schema, item.description)


def test_contract_ids_resolve_names_by_schema_not_by_id():
    """Fails if two ids carrying the same schema show different names, an optional
    wrapper renames its schema, ids with distinct schemas share a name, or the two
    ``str | None`` contracts (data folder vs language model name, kept separate)
    collapse into one bare ``str`` schema and one name."""
    by_schema: dict[str, set[str]] = {}
    for contract in CONTRACTS:
        by_schema.setdefault(contract_schema(contract), set()).add(contract_name(contract).name)
    assert all(len(names) == 1 for names in by_schema.values()), by_schema
    assert len({next(iter(names)) for names in by_schema.values()}) == len(by_schema)
    assert CONTRACTS["optional.text"] == CONTRACTS["optional.model-id"] == "str | None"
    assert contract_schema("optional.text") != contract_schema("optional.model-id")
    assert contract_name("optional.text").name == "Data folder"
    assert contract_name("optional.model-id").name == "Language model name"


def test_produced_schemas_are_exactly_those_capabilities_exchange():
    """Fails if a schema a capability receives or returns is not marked produced, or a
    schema only you provide (storage, settings, advice) claims to be produced."""
    exchanged = {
        contract_schema(contract)
        for capability in CAPABILITIES.values()
        for contract in (capability.input, capability.output)
    } | {contract_schema(contract) for contract in COLLECTION_CONTRACTS.values()}
    for schema, item in SCHEMA_NAMES.items():
        assert (item.kind == "produced") == (schema in exchanged), schema


def test_adaptor_name_joins_the_two_schema_names():
    """Fails if the future adaptor label stops using the owner's names in
    ``<from> → <to>`` order, or accepts a same-schema or unknown contract."""
    assert adaptor_name("interpretation.output", "literature.input") == (
        "Results analysis → Search evidence"
    )
    with pytest.raises(ValueError):
        adaptor_name("optional.text", "optional.text")
    with pytest.raises(KeyError):
        adaptor_name("proposal.output", "unknown.contract")
