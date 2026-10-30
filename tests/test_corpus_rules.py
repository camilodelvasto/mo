import pytest
from shapes.corpus.engine.rules import due_rules, evaluate_condition
from shapes.corpus.engine.errors import ContractError


def test_equality():
    assert evaluate_condition("fields.consent == declined", {"consent": "declined"})
    assert not evaluate_condition("fields.consent == declined", {"consent": "given"})


def test_missing_field_is_false_not_an_error():
    # a projection without the field simply does not satisfy the condition
    assert not evaluate_condition("fields.consent == declined", {})


def test_inequality():
    assert evaluate_condition("fields.scan != infected", {"scan": "clean"})


def test_membership():
    cond = "fields.doc_type in [workshop, application, other]"
    assert evaluate_condition(cond, {"doc_type": "workshop"})
    assert not evaluate_condition(cond, {"doc_type": "interview"})


def test_unparseable_condition_throws():
    with pytest.raises(ContractError):
        evaluate_condition("fields.consent === declined", {})


def test_due_rules_returns_matching_rules():
    flow = {"rules": [{"when": "fields.consent == declined", "do": "retire"}]}
    assert due_rules(flow, {"consent": "declined"}) == [{"when": "fields.consent == declined", "do": "retire"}]
    assert due_rules(flow, {"consent": "given"}) == []
    assert due_rules({}, {"consent": "declined"}) == []


def test_inequality_missing_field_is_false():
    # absence is not a value: a never-declared field satisfies neither == nor !=
    assert not evaluate_condition("fields.scan != infected", {})


def test_membership_missing_field_is_false():
    assert not evaluate_condition("fields.doc_type in [a, b]", {})
