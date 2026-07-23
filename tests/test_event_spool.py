import json

from ledger.event_spool import read_events


def _write(path, record):
    path.write_text(json.dumps(record), encoding='utf-8')


def test_read_events_on_a_missing_directory_is_empty(tmp_path):
    result = read_events(tmp_path / 'no-such-dir')
    assert result.events == ()
    assert result.malformed == ()


def test_read_events_parses_valid_records_oldest_first(tmp_path):
    spool = tmp_path / 'events'
    spool.mkdir()
    _write(
        spool / '1-a.json',
        {
            'schema_version': 1,
            'kind': 'agent_session',
            'harness_session_id': 'h1',
            'x': 1,
        },
    )
    _write(
        spool / '2-b.json',
        {'schema_version': 1, 'kind': 'compaction', 'harness_session_id': 'h1', 'y': 2},
    )

    result = read_events(spool)

    assert [event.kind for event in result.events] == ['agent_session', 'compaction']
    assert result.events[0].harness_session_id == 'h1'
    assert result.events[0].fields == {'x': 1}
    assert result.malformed == ()


def test_read_events_reports_wrong_schema_version_as_malformed(tmp_path):
    spool = tmp_path / 'events'
    spool.mkdir()
    _write(
        spool / 'a.json', {'schema_version': 2, 'kind': 'x', 'harness_session_id': 'h'}
    )

    result = read_events(spool)

    assert result.events == ()
    assert len(result.malformed) == 1


def test_read_events_reports_invalid_json_as_malformed(tmp_path):
    spool = tmp_path / 'events'
    spool.mkdir()
    (spool / 'a.json').write_text('not json', encoding='utf-8')

    result = read_events(spool)

    assert result.events == ()
    assert len(result.malformed) == 1


def test_read_events_reports_non_dict_json_as_malformed(tmp_path):
    spool = tmp_path / 'events'
    spool.mkdir()
    (spool / 'a.json').write_text('[1, 2]', encoding='utf-8')

    result = read_events(spool)

    assert result.malformed == (spool / 'a.json',)


def test_read_events_reports_missing_required_fields_as_malformed(tmp_path):
    spool = tmp_path / 'events'
    spool.mkdir()
    _write(spool / 'a.json', {'schema_version': 1, 'kind': 'agent_session'})

    result = read_events(spool)

    assert result.malformed == (spool / 'a.json',)


def test_discard_removes_files(tmp_path):
    from ledger.event_spool import discard

    spool = tmp_path / 'events'
    spool.mkdir()
    path = spool / 'a.json'
    _write(path, {'schema_version': 1, 'kind': 'x', 'harness_session_id': 'h'})

    discard([path])

    assert not path.exists()
