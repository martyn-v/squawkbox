from typing import get_args

from squawkbox.models.actions import Action, actions_to_prompt_text


def test_covers_every_action_in_union_order():
    output = actions_to_prompt_text()
    union, _ = get_args(Action)
    tags = [cls.model_fields["type"].default for cls in get_args(union)]
    positions = [output.index(f'- {tag} (type: "{tag}"):') for tag in tags]
    assert positions == sorted(positions)


def test_includes_docstrings():
    output = actions_to_prompt_text()
    union, _ = get_args(Action)
    for cls in get_args(union):
        assert cls.__doc__.strip() in output


def test_field_lines():
    output = actions_to_prompt_text()
    assert "  - path (required)" in output
    assert "  - reason (optional)" in output
    # the discriminator is vocabulary plumbing, not a field to describe
    assert "- type" not in output


def test_formatting_is_clean():
    output = actions_to_prompt_text()
    for line in output.splitlines():
        assert line == line.rstrip()
        assert not line.endswith(":") or line.endswith("Fields:")
