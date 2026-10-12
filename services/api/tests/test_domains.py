"""Domain packs are curated data; these checks keep them internally consistent.

The offline model and the evaluation generator share one matcher (``textmatch``), so a pack whose
hints overlap or whose examples classify elsewhere silently produces weaker evaluation suites.
"""

from __future__ import annotations

import pytest

from app.compiler import compile_requirement
from app.compiler.domains import ALL_PACKS, PACKS, DomainPack
from app.compiler.templates import TEMPLATES
from app.generator.engine import generate_repository
from app.generator.shared import textmatch
from app.generator.shared.injection import scan

IDS = [pack.key for pack in ALL_PACKS]


def _example_id(pack: DomainPack) -> str:
    return f"{pack.entity.id_prefix}-1001"


@pytest.mark.parametrize("pack", ALL_PACKS, ids=IDS)
def test_names_are_unique_identifiers(pack: DomainPack) -> None:
    for group in (pack.labels, pack.levels, pack.tools, pack.sources):
        names = [item.name for item in group]
        assert len(names) == len(set(names)), names
        assert all(name.isidentifier() and name == name.lower() for name in names)
    assert len(pack.labels) >= 2
    assert pack.levels == () or len(pack.levels) >= 2
    assert (pack.assess_step is None) == (pack.dimension is None)


@pytest.mark.parametrize("pack", ALL_PACKS, ids=IDS)
def test_label_hints_are_disjoint_and_normalized(pack: DomainPack) -> None:
    for group in (pack.labels, pack.levels):
        owners: dict[str, str] = {}
        for label in group:
            for hint in textmatch.label_hints(label.name, label.hints):
                normalized = textmatch.normalize(hint)
                assert normalized, f"{pack.key}/{label.name}: empty hint {hint!r}"
                previous = owners.setdefault(normalized, label.name)
                assert previous == label.name, (
                    f"{pack.key}: hint {hint!r} used by {previous} and {label.name}"
                )


@pytest.mark.parametrize("pack", ALL_PACKS, ids=IDS)
def test_examples_classify_to_their_own_label(pack: DomainPack) -> None:
    labels = [(label.name, label.hints) for label in pack.labels]
    for label in pack.labels:
        for example in label.examples:
            text = example.replace("{id}", _example_id(pack))
            computed, confidence, score = textmatch.classify(text, labels)
            assert computed == label.name, f"{pack.key}: {text!r} -> {computed}"
            assert score > 0 and confidence > 0
            assert not scan(text).suspicious, f"{pack.key}: example trips the injection guard: {text!r}"


@pytest.mark.parametrize("pack", [pack for pack in ALL_PACKS if pack.levels], ids=lambda pack: pack.key)
def test_level_hints_select_their_level(pack: DomainPack) -> None:
    levels = [(level.name, level.hints) for level in pack.levels]
    for level in pack.levels:
        if not level.hints:
            continue
        text = f"Update on {pack.entity.noun} {_example_id(pack)}: {level.hints[0]} reported."
        assert textmatch.assess(text, levels)[0] == level.name, text


@pytest.mark.parametrize("pack", ALL_PACKS, ids=IDS)
def test_tools_cover_the_workflow(pack: DomainPack) -> None:
    defaults = [tool for tool in pack.tools if tool.default]
    assert any(tool.mode == "read" for tool in defaults), (
        "every pack needs a default read tool for its lookup step"
    )
    if any(tool.mode == "execute" for tool in pack.tools):
        # Executing anything requires a reviewable draft first.
        assert any(tool.mode == "draft" for tool in pack.tools)
    entity_records = pack.entity.records
    assert entity_records and all(
        record[pack.entity.id_param].startswith(pack.entity.id_prefix) for record in entity_records
    )


def test_every_curated_pack_has_a_template() -> None:
    assert {pack.key for pack in PACKS} == {template.domain for template in TEMPLATES}


@pytest.mark.parametrize("template", TEMPLATES, ids=lambda template: template.id)
def test_generated_suites_keep_every_curated_example(template) -> None:
    repository = generate_repository(compile_requirement(template.requirement).spec)
    skipped = [
        note for note in repository.notes if note.startswith(("Skipped", "Dropped", "No label-specific"))
    ]
    assert skipped == []
