import json
import os
import random
import shutil
import subprocess
import tempfile
import time
from dataclasses import asdict, fields
from typing import IO, Any, Dict, List

import jinja2
from packaging.version import Version

from jmeslog import model
from jmeslog.constants import DEFAULT_TEMPLATE, VALID_CHARS
from jmeslog.errors import NoChangesFoundError, ValidationError


class EditorRetriever:
    def prompt_entry_values(self, entry: model.JMESLogEntry) -> None:
        with tempfile.NamedTemporaryFile('w') as f:
            self._write_template_to_tempfile(f, entry)
            self._open_tempfile_in_editor(f.name)
            contents = self._read_tempfile(f.name)
            return self._parse_filled_in_contents(contents, entry)

    def _open_tempfile_in_editor(self, filename: str) -> None:
        env = os.environ
        editor = env.get('VISUAL', env.get('EDITOR', 'vim'))
        subprocess.run([editor, filename], check=True)

    def _write_template_to_tempfile(
        self, f: IO[str], entry: model.JMESLogEntry
    ) -> None:
        contents = DEFAULT_TEMPLATE.format(
            type=entry.type,
            category=entry.category,
            description=entry.description,
        )
        f.write(contents)
        f.flush()

    def _read_tempfile(self, filename: str) -> str:
        with open(filename) as f:
            filled_in_contents = f.read()
            return filled_in_contents

    def _parse_filled_in_contents(
        self, contents: str, entry: model.JMESLogEntry
    ) -> None:
        parsed_entry = EntryFileParser().parse_contents(contents)
        self._update_values_from_new_entry(entry, parsed_entry)

    def _update_values_from_new_entry(
        self, entry: model.JMESLogEntry, new_entry: model.JMESLogEntry
    ) -> None:
        for key, value in asdict(new_entry).items():
            if value:
                setattr(entry, key, value)


class EntryFileParser:
    def parse_contents(self, contents: str) -> model.JMESLogEntry:
        entry = model.JMESLogEntry.empty()
        if not contents.strip():
            return entry
        field_names = [f.name for f in fields(entry)]
        line_starts = tuple([f'{name}:' for name in field_names])
        for line in contents.splitlines():
            line = line.lstrip()
            if line.startswith('#') or not line:
                continue
            if line.startswith(line_starts):
                field_name, remaining = line.split(':', 1)
                setattr(entry, field_name, remaining.strip())
        return entry


class EntryGenerator:
    def __init__(self, entry: model.JMESLogEntry, retriever: EditorRetriever):
        self._entry = entry
        self._retriever = retriever

    def complete_entry(self) -> None:
        if not self._entry.is_completed():
            self._retriever.prompt_entry_values(self._entry)

    @property
    def change_entry(self) -> model.JMESLogEntry:
        return self._entry


class EntryFileWriter:
    def write_next_release_entry(
        self, entry: model.JMESLogEntry, change_dir: str
    ) -> str:
        self._create_next_release_dir(change_dir)
        abs_filename = self._generate_random_file(entry, change_dir)
        with open(abs_filename, 'w') as f:
            f.write(entry.to_json())
            f.write('\n')
        return abs_filename

    def _create_next_release_dir(self, change_dir: str) -> None:
        next_release = os.path.join(change_dir, 'next-release')
        if not os.path.isdir(next_release):
            os.mkdir(next_release)

    def _generate_random_file(
        self, entry: model.JMESLogEntry, change_dir: str
    ) -> str:
        next_release = os.path.join(change_dir, 'next-release')
        # Need to generate a unique filename for this change.
        short_summary = ''.join(
            ch for ch in entry.category if ch in VALID_CHARS
        )
        filename = f'{entry.type}-{short_summary}'
        possible_filename = self._random_filename(next_release, filename)
        while os.path.isfile(possible_filename):
            possible_filename = self._random_filename(next_release, filename)
        return possible_filename

    def _random_filename(self, next_release: str, filename: str) -> str:
        return os.path.join(
            next_release,
            '%s-%s-%s.json'
            % (time.monotonic_ns(), filename, str(random.randint(1, 100000))),
        )


class EntryRecorder:
    def __init__(
        self,
        entry_gen: EntryGenerator,
        schema: model.EntrySchema,
        file_writer: EntryFileWriter,
        output_dir: str = '.changes',
    ):
        self._entry_gen = entry_gen
        self._schema = schema
        self._file_writer = file_writer
        self._output_dir = output_dir

    def write_change_file_entry(self) -> str:
        self._entry_gen.complete_entry()
        entry = self._entry_gen.change_entry
        validate_change_entry(entry, self._schema)
        filename = self._file_writer.write_next_release_entry(
            entry, change_dir=self._output_dir
        )
        return filename


def validate_change_entry(
    entry: model.JMESLogEntry, schema: model.EntrySchema
) -> None:
    entry_dict = asdict(entry)
    schema_dict = asdict(schema)
    errors = []
    for schema_field in fields(schema):
        value = entry_dict[schema_field.name]
        allowed_values = schema_dict[schema_field.name]
        if allowed_values and value not in allowed_values:
            errors.append(
                f'The "{schema_field.name}" value must be one of: '
                f'{", ".join(allowed_values)}, received: "{value}"'
            )
    for key, value in entry_dict.items():
        if not value:
            errors.append(f'The "{key}" value cannot be empty.')
    if errors:
        raise ValidationError(errors)


def consolidate_next_release(
    next_version: str, change_dir: str, changes: model.JMESLogEntryCollection
) -> str:
    # Creates a new x.y.x.json file in .changes/ with the changes in
    # .changes/next-release.
    # It'll then remove the .changes/next-release directory.
    release_file = os.path.join(change_dir, f'{next_version}.json')
    with open(release_file, 'w') as f:
        f.write(json.dumps(changes.to_dict(), indent=2))
        f.write('\n')
    next_release_dir = os.path.join(change_dir, 'next-release')
    shutil.rmtree(next_release_dir)
    return release_file


def find_last_released_version(change_dir: str) -> str:
    results = sorted_versioned_releases(change_dir)
    if results:
        return results[-1]
    return '0.0.0'


def sorted_versioned_releases(change_dir: str) -> List[str]:
    # Strip off the '.json' suffix.
    files = [f[:-5] for f in os.listdir(change_dir) if f.endswith('.json')]
    return sorted(files, key=lambda x: Version(x))


def determine_next_version(
    last_released_version: str, version_bump_type: model.VersionBump
) -> str:
    parts = last_released_version.split('.')
    if version_bump_type == model.VersionBump.PATCH_VERSION:
        parts[2] = str(int(parts[2]) + 1)
    elif version_bump_type == model.VersionBump.MINOR_VERSION:
        parts[1] = str(int(parts[1]) + 1)
        parts[2] = '0'
    elif version_bump_type == model.VersionBump.MAJOR_VERSION:
        parts[0] = str(int(parts[0]) + 1)
        parts[1] = '0'
        parts[2] = '0'
    return '.'.join(parts)


def load_next_changes(change_dir: str) -> model.JMESLogEntryCollection:
    next_release = os.path.join(change_dir, 'next-release')
    if not os.path.isdir(next_release):
        raise NoChangesFoundError()
    changes = []
    for change in sorted(os.listdir(next_release)):
        entry = parse_entry(os.path.join(next_release, change))
        changes.append(entry)
    return model.JMESLogEntryCollection(changes=changes)


def parse_entry(filename: str) -> model.JMESLogEntry:
    with open(filename) as f:
        data = json.load(f)
        return model.JMESLogEntry(**data)


def create_entry_recorder(
    entry: model.JMESLogEntry, change_dir: str
) -> EntryRecorder:
    recorder = EntryRecorder(
        entry_gen=EntryGenerator(
            entry=entry,
            retriever=EditorRetriever(),
        ),
        schema=model.EntrySchema(),
        file_writer=EntryFileWriter(),
        output_dir=change_dir,
    )
    return recorder


def render_changes(
    changes: Dict[str, model.JMESLogEntryCollection],
    out: IO[str],
    template_contents: str,
) -> None:
    context = {
        'releases': reversed(list(changes.items())),
    }
    template = jinja2.Template(template_contents)
    result = template.render(**context)
    out.write(result)


def load_all_changes(
    change_dir: str,
) -> Dict[str, model.JMESLogEntryCollection]:
    releases = {}
    for version_number in sorted_versioned_releases(change_dir):
        filename = os.path.join(change_dir, f'{version_number}.json')
        with open(filename) as f:
            data = json.load(f)
            releases[version_number] = model.JMESLogEntryCollection.from_dict(
                data
            )
    return releases


def render_single_release_changes(
    change_collection: model.JMESLogEntryCollection, out: IO[str]
) -> None:
    for change in change_collection.changes:
        description = '\n  '.join(change.description.splitlines())
        out.write(f'* {change.type}:{change.category}:{description}\n')
    out.write('\n\n')


class ChangeQuery:
    def __init__(self, change_dir: str) -> None:
        self._change_dir = change_dir

    def run_query(self, query_for: str) -> Any:
        try:
            handler = getattr(self, f'query_{query_for.replace("-", "_")}')
        except AttributeError:
            raise RuntimeError(f"Unknown query type: {query_for}")
        return handler()

    def query_last_release_version(self) -> str:
        return find_last_released_version(self._change_dir)

    def query_next_version(self) -> str:
        changes = load_next_changes(self._change_dir)
        last_released_version = find_last_released_version(self._change_dir)
        next_version = determine_next_version(
            last_released_version, changes.version_bump_type
        )
        return next_version

    def query_next_release_type(self) -> str:
        changes = load_next_changes(self._change_dir)
        return changes.version_bump_type.value
