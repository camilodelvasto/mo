"""The fold: log -> flat description. THE shared primitive."""
import pytest
from shapes.corpus.engine.errors import ContractError, SidecarError
from shapes.corpus.engine.fold import fold, fold_with_provenance


def test_scalar_last_write_wins():
    entries = [
        {"id": "a", "fields": {"language": "de"}},
        {"id": "b", "fields": {"language": "en"}},
    ]
    assert fold(entries) == {"language": "en"}


def test_set_union_minus_removes_in_log_order():
    entries = [
        {"id": "a", "fields": {"tags": {"add": ["housing", "berlin"]}}},
        {"id": "b", "fields": {"tags": {"add": ["displacement"], "remove": ["berlin"]}}},
    ]
    assert fold(entries) == {"tags": ["housing", "displacement"]}


def test_bare_list_means_add():
    entries = [
        {"id": "a", "fields": {"tags": ["housing"]}},
        {"id": "b", "fields": {"tags": ["housing", "tenancy-law"]}},
    ]
    assert fold(entries) == {"tags": ["housing", "tenancy-law"]}


def test_proposed_is_invisible_to_the_fold():
    entries = [
        {"id": "a", "fields": {}, "proposed": {"tags": {"add": ["x"]}, "participants": {"add": ["A"]}}},
    ]
    assert fold(entries) == {}


def test_entries_without_fields_are_fine():
    assert fold([{"id": "received-duplicate"}]) == {}


def test_remove_before_add_is_a_noop_then_add_lands():
    entries = [
        {"id": "a", "fields": {"tags": {"remove": ["x"]}}},
        {"id": "b", "fields": {"tags": {"add": ["x"]}}},
    ]
    assert fold(entries) == {"tags": ["x"]}


def test_set_op_on_scalar_field_throws():
    entries = [
        {"id": "a", "fields": {"status": "open"}},
        {"id": "b", "fields": {"status": {"add": ["reviewed"]}}},
    ]
    with pytest.raises(ContractError):
        fold(entries)


def test_non_dict_entry_throws_typed():
    with pytest.raises(SidecarError):
        fold(["garbage"])


def test_fields_null_throws():
    with pytest.raises(SidecarError):
        fold([{"id": "a", "fields": None}])


def test_provenance_returns_contributing_entry_per_scalar():
    entries = [
        {"id": "normalize", "fields": {"language": "de"}},
        {"id": "assert", "by": "operator", "fields": {"language": "en"}},
    ]
    prov = fold_with_provenance(entries)
    assert prov["language"]["value"] == "en"
    assert prov["language"]["entry"]["id"] == "assert"
    assert prov["language"]["entry"]["by"] == "operator"


def test_provenance_for_set_is_last_contributor():
    entries = [
        {"id": "datasheet", "fields": {"tags": {"add": ["housing", "berlin"]}}},
        {"id": "assert", "by": "operator",
         "fields": {"tags": {"add": ["displacement"], "remove": ["berlin"]}}},
    ]
    prov = fold_with_provenance(entries)
    assert prov["tags"]["value"] == ["housing", "displacement"]
    assert prov["tags"]["entry"]["id"] == "assert"


def test_provenance_value_matches_plain_fold():
    entries = [
        {"id": "classify", "fields": {"doc_type": "interview"}},
        {"id": "datasheet", "fields": {"summary": "x"}},
    ]
    prov = fold_with_provenance(entries)
    flat = fold(entries)
    assert {k: v["value"] for k, v in prov.items()} == flat
