from agentmaster.registry import COMMAND_REGISTRY, find_command


def test_every_registered_command_has_a_group_name_and_description():
    for entry in COMMAND_REGISTRY:
        assert entry.group
        assert entry.name
        assert entry.description


def test_registry_has_no_duplicate_group_name_pairs():
    pairs = [(entry.group, entry.name) for entry in COMMAND_REGISTRY]
    assert len(pairs) == len(set(pairs))


def test_find_command_returns_the_matching_entry():
    entry = find_command(group='ledger', name='doctor')

    assert entry is not None
    assert entry.description


def test_find_command_returns_none_for_an_unregistered_verb():
    assert find_command(group='ledger', name='no-such-command') is None
