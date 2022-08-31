import os
import pytest
import json
from dataclasses import dataclass
from unittest import mock
from typing import Optional

import jmeslog
import jmeslog.cli
import jmeslog.core
import jmeslog.errors
from jmeslog import model


@dataclass
class CommandArgs:
    change_dir: Optional[str] = None
    release_version: Optional[str] = None


@dataclass
class NewChangeArgs:
    type: str
    category: str
    description: str
    change_dir: Optional[str] = None


def new_change(change_type, category='foo', description='bar'):
    return model.JMESLogEntry(type=change_type,
                                category=category, description=description)


def test_create_changelog_entry():
    entry = model.JMESLogEntry(type='feature',
                                 category='foo',
                                 description='My Feature')
    assert entry.to_json() == (
        '{\n'
        '  "type": "feature",\n'
        '  "category": "foo",\n'
        '  "description": "My Feature"\n'
        '}'
    )


def test_can_validate_allowed_values():
    schema = model.EntrySchema(type=['feature', 'bugfix'])
    entry = model.JMESLogEntry(type='feature', category='foo',
                                 description='My feature')
    assert jmeslog.core.validate_change_entry(entry=entry, schema=schema) is None
    err_msg = (
        'The "type" value must be one of: feature, bugfix, '
        'received: "notafeature"'
    )
    with pytest.raises(jmeslog.errors.ValidationError,
                       match=err_msg):
        jmeslog.core.validate_change_entry(
            schema=schema,
            entry=model.JMESLogEntry(
                type='notafeature',
                category='foo',
                description='bar')
        )


def test_no_values_can_be_empty():
    schema = model.EntrySchema(type=['feature', 'bugfix'])
    entry = model.JMESLogEntry(type='feature', category='foo',
                                 description='')
    err_msg = 'The "description" value cannot be empty.'
    with pytest.raises(jmeslog.errors.ValidationError,
                       match=err_msg):
        jmeslog.core.validate_change_entry(
            schema=schema,
            entry=entry,
        )


def test_no_prompt_if_entry_complete():
    completed = model.JMESLogEntry(
        type='feature',
        category='foo',
        description='My Feature'
    )
    retriever = mock.Mock(spec=jmeslog.core.EditorRetriever)
    gen = jmeslog.core.EntryGenerator(completed, retriever)
    gen.complete_entry()
    assert not retriever.prompt_entry_values.called


def test_prompt_in_editor_if_incomplete():
    incomplete = model.JMESLogEntry(
        type='feature',
        category='foo',
        # Missing a description.
        description='',
    )
    retriever = mock.Mock(spec=jmeslog.core.EditorRetriever)
    gen = jmeslog.core.EntryGenerator(incomplete, retriever)
    gen.complete_entry()
    retriever.prompt_entry_values.assert_called_with(incomplete)


def test_can_return_generated_entry():
    completed = model.JMESLogEntry(
        type='feature',
        category='foo',
        description='My Feature'
    )
    retriever = mock.Mock(spec=jmeslog.core.EditorRetriever)
    gen = jmeslog.core.EntryGenerator(completed, retriever)
    assert gen.change_entry.to_json() == (
        '{\n'
        '  "type": "feature",\n'
        '  "category": "foo",\n'
        '  "description": "My Feature"\n'
        '}'
    )


def test_can_record_entry(tmpdir):
    entry = model.JMESLogEntry(
        type='feature',
        category='foo',
        description='My Feature'
    )
    change_dir = tmpdir.join('.changes')
    change_dir.mkdir()
    recorder = jmeslog.core.EntryRecorder(
        entry_gen=jmeslog.core.EntryGenerator(
            entry=entry,
            retriever=mock.Mock(spec=jmeslog.core.EditorRetriever),
        ),
        schema=model.EntrySchema(),
        file_writer=jmeslog.core.EntryFileWriter(),
        output_dir=str(change_dir),
    )
    recorder.write_change_file_entry()
    contents = os.listdir(str(change_dir.join('next-release')))
    assert len(contents) == 1


def _assert_entry_file_parses_to(contents, expected):
    result = jmeslog.core.EntryFileParser().parse_contents(contents)
    assert result == expected


def test_can_parse_empty_file():
    _assert_entry_file_parses_to('', model.JMESLogEntry.empty())


def test_can_parse_single_fields():
    contents = (
        "# This is a comment\n"
        "type: bugfix\n"
        "category: foo\n"
        "# Another comment\n"
        "#description: ignore\n"
        "description: bar\n"
    )
    _assert_entry_file_parses_to(
        contents, model.JMESLogEntry(type='bugfix',
                                       category='foo',
                                       description='bar'))


def test_ignores_unknown_fields():
    contents = (
        "# This is a comment\n"
        "foo: bugfix\n"
        "bar: foo\n"
        "# Another comment\n"
        "#description: ignore\n"
        "baz: bar\n"
    )
    _assert_entry_file_parses_to(
        contents, model.JMESLogEntry.empty())


def test_last_entry_wins():
    contents = (
        "type: first\n"
        "type: last\n"
        "category: first\n"
        "category: last\n"
        "description: first\n"
        "description: last\n"
    )
    _assert_entry_file_parses_to(
        contents, model.JMESLogEntry(type='last',
                                       category='last',
                                       description='last'))


@pytest.mark.parametrize(
    'entry_types,bump_type', [
        (['bugfix', 'bugfix', 'bugfix'], model.VersionBump.PATCH_VERSION),
        (['enhancement', 'enhancement'], model.VersionBump.PATCH_VERSION),
        (['bugfix', 'enhancement'], model.VersionBump.PATCH_VERSION),
        (['feature'], model.VersionBump.MINOR_VERSION),
        (['feature', 'bugfix'], model.VersionBump.MINOR_VERSION),
        (['enhancement', 'feature', 'bugfix'],
         model.VersionBump.MINOR_VERSION),
    ]
)
def test_bugfix_is_patch_version(entry_types, bump_type):
    changes = model.JMESLogEntryCollection(
        changes=[
            new_change(entry_type) for entry_type in entry_types
        ]
    )
    assert changes.version_bump_type == bump_type


def test_collection_to_dict():
    changes = model.JMESLogEntryCollection(
        changes=[new_change('bugfix')],
        schema_version='1.0',
        summary='Summary of release.',
    )
    assert changes.to_dict() == {
        'schema-version': '1.0',
        'summary': 'Summary of release.',
        'changes': [{'type': 'bugfix', 'category': 'foo',
                     'description': 'bar'}],
    }

def write_change(change_type, change_dir):
    entry = new_change(change_type)
    jmeslog.core.create_entry_recorder(entry, change_dir).write_change_file_entry()
    return entry


def test_can_load_next_changes_dir_into_entries(tmpdir):
    change_dir = tmpdir.join('.changes')
    change_dir.mkdir()
    write_change('feature', str(change_dir))
    write_change('bugfix', str(change_dir))
    write_change('enhancement', str(change_dir))

    entries = jmeslog.core.load_next_changes(str(change_dir))
    assert entries == model.JMESLogEntryCollection(
        changes=[new_change('feature'),
                 new_change('bugfix'),
                 new_change('enhancement')]
    )


@pytest.mark.parametrize(
    'last_version,bump_type,new_version', [
        ('0.0.1', model.VersionBump.PATCH_VERSION, '0.0.2'),
        ('1.0.1', model.VersionBump.PATCH_VERSION, '1.0.2'),
        ('1.0.0', model.VersionBump.PATCH_VERSION, '1.0.1'),
        ('1.0.0', model.VersionBump.MINOR_VERSION, '1.1.0'),
        ('1.9.0', model.VersionBump.MINOR_VERSION, '1.10.0'),
        ('1.0.9', model.VersionBump.MINOR_VERSION, '1.1.0'),
        ('1.2.9', model.VersionBump.MINOR_VERSION, '1.3.0'),
        ('1.0.0', model.VersionBump.MAJOR_VERSION, '2.0.0'),
        ('1.1.0', model.VersionBump.MAJOR_VERSION, '2.0.0'),
        ('1.1.1', model.VersionBump.MAJOR_VERSION, '2.0.0'),
    ]
)
def test_determine_next_version(last_version, bump_type, new_version):
    assert jmeslog.core.determine_next_version(
        last_version, bump_type) == new_version


def test_can_find_last_released_version(tmpdir):
    change_dir = tmpdir.join('.changes')
    change_dir.mkdir()
    next_release = change_dir.join('next-release').mkdir()
    change_dir.join('0.0.1.json').write('{}')
    change_dir.join('0.1.1.json').write('{}')
    change_dir.join('0.1.10.json').write('{}')
    change_dir.join('1.2.3.json').write('{}')
    change_dir.join('1.2.30.json').write('{}')
    change_dir.join('1.10.0.json').write('{}')
    change_dir.join('1.20.0.json').write('{}')
    assert jmeslog.core.find_last_released_version(str(change_dir)) == '1.20.0'


def test_can_consolidate_next_release(tmpdir):
    change_dir = tmpdir.join('.changes')
    change_dir.mkdir()
    next_release = change_dir.join('next-release')
    next_release.mkdir()
    next_release_dir = str(next_release)
    changes = []
    changes.append(
        write_change('feature', next_release_dir)
    )
    changes.append(
        write_change('bugfix', next_release_dir)
    )
    changes.append(
        write_change('enhancement', next_release_dir)
    )
    jmeslog.core.consolidate_next_release(
        next_version='1.1.0', change_dir=str(change_dir),
        changes=model.JMESLogEntryCollection(changes=changes))
    assert os.path.isfile(str(change_dir.join('1.1.0.json')))
    assert not os.path.isdir(next_release_dir)
    with open(str(change_dir.join('1.1.0.json'))) as f:
        data = json.load(f)
    assert data == {
        'schema-version': '0.2',
        'changes': [
            {'type': 'feature', 'category': 'foo', 'description': 'bar'},
            {'type': 'bugfix', 'category': 'foo', 'description': 'bar'},
            {'type': 'enhancement', 'category': 'foo', 'description': 'bar'},
        ]
    }


def test_can_create_collection_from_dict():
    release_data = {
        'schema-version': '0.2',
        'changes': [
            {'type': 'feature', 'category': 'foo', 'description': 'bar'},
        ],
        'summary': 'Foo release.'
    }
    collection = model.JMESLogEntryCollection.from_dict(release_data)
    assert collection.schema_version == '0.2'
    assert collection.summary == 'Foo release.'
    assert collection.changes == [model.JMESLogEntry(type='feature',
                                                       category='foo',
                                                       description='bar')]


def test_can_create_collection_from_old_format():
    release_data = [
        {'type': 'feature', 'category': 'foo', 'description': 'bar'},
    ]
    collection = model.JMESLogEntryCollection.from_dict(release_data)
    assert collection.schema_version == '0.1'
    assert collection.summary == ''
    assert collection.changes == [model.JMESLogEntry(type='feature',
                                                       category='foo',
                                                       description='bar')]



def test_can_set_explicit_version(tmpdir):
    change_dir = os.path.join(str(tmpdir), '.changes')
    args = CommandArgs(change_dir=change_dir, release_version='1.2.3')
    jmeslog.cli.cmd_init(args)
    new_change_args = NewChangeArgs(
        type='enhancement',
        category='Foo',
        description='Changed foo',
        change_dir=change_dir,
    )
    jmeslog.cli.cmd_new_change(new_change_args)
    jmeslog.cli.cmd_new_release(args)
    assert os.listdir(change_dir)[0] == '1.2.3.json'
