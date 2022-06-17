"""Script for managing changelogs."""
# A couple of things to note here:
#
# This is meant to be a single file script.
# This makes it easier to package for those that don't want
# to go through pip.  This also means:
#
# * No runtime dependencies
# * It only needs to run on py3 (Specifically py37 is all we test)
# * It needs to run on windows, linux, and mac.
#
import os
import sys
import json
import string
import random
import argparse
import tempfile
import subprocess
import shutil
import time
import enum
from dataclasses import dataclass, asdict, field, fields
from typing import List, Dict, Any, IO, Union
from distutils.version import StrictVersion

import jinja2


__version__ = '0.1.1'


VALID_CHARS = set(string.ascii_letters + string.digits)
# TODO: Dynamically generate this template based on schema values.
# TODO: Support #123 and owner/repo#123 references
DEFAULT_TEMPLATE = """\
# Type should be one of: feature, bugfix, enhancement
# feature: A larger feature or change in behavior, usually resulting in a
#          minor version bump.
# bugfix: Fixing a bug in an existing code path.
# enhancement: Small change to an underlying implementation detail.
# api-change: Changes to a modeled API.
type: {type}

# Category is the high level feature area.
category: {category}

# A brief description of the change.  You can
# use github style references to issues such as
# "fixes #489", "owner/repo#100", etc.  These
# will get automatically replaced with the correct
# link.
description: {description}
"""

DEFAULT_RENDER_TEMPLATE = """\
=========
CHANGELOG
=========

{% for release, changes in releases %}
{{ release }}
{{ '=' * release|length }}
{%- if changes.summary %}
{{ changes.summary -}}
{% endif %}
{% for change in changes.changes %}
* {{ change.type }}:{{ change.category }}:{{ change.description -}}
{% endfor %}
{% endfor %}

"""


class VersionBump(enum.Enum):
    PATCH_VERSION = 'patch'
    MINOR_VERSION = 'minor'
    MAJOR_VERSION = 'major'


class ValidationError(Exception):
    def __init__(self, errors: List[str]) -> None:
        self.errors = errors

    def __str__(self) -> str:
        new_line = '\n'
        return (
            f"The change entry is invalid:{new_line}{new_line}"
            f"{new_line.join(self.errors)}"
        )


class NoChangesFoundError(Exception):
    def __init__(self) -> None:
        super().__init__("There are no pending changes.")


@dataclass
class EntrySchema:
    type: List[str] = field(default_factory=lambda: ['feature', 'bugfix',
                                                     'enhancement'])
    # An empty list means any string is valid.
    category: List[str] = field(default_factory=lambda: [])


@dataclass
class JMESLogEntry:
    type: str
    category: str
    description: str

    @classmethod
    def empty(cls) -> 'JMESLogEntry':
        return cls('', '', '')

    def to_json(self) -> str:
        entry_dict = self.to_dict()
        return json.dumps(entry_dict, indent=2)

    def to_dict(self) -> Dict[str, str]:
        return asdict(self)

    def is_completed(self) -> bool:
        """Check if all fields are non-empty."""
        for value in asdict(self).values():
            if not value:
                return False
        return True


@dataclass
class JMESLogEntryCollection:
    changes: List[JMESLogEntry]
    schema_version: str = '0.2'
    summary: str = ''

    _OLD_SCHEMA_VERSION = '0.1'

    @property
    def version_bump_type(self) -> VersionBump:
        bump_type = VersionBump.PATCH_VERSION
        for entry in self.changes:
            if entry.type == 'feature':
                bump_type = VersionBump.MINOR_VERSION
        return bump_type

    def to_dict(self) -> Dict[str, Any]:
        result = {
            'schema-version': self.schema_version,
            'changes': [entry.to_dict() for entry in self.changes]
        }
        if self.summary:
            result['summary'] = self.summary
        return result

    @classmethod
    def from_dict(cls,
                  release_info: Union[List[Any], Dict[str, Any]]
                  ) -> 'JMESLogEntryCollection':
        if isinstance(release_info, list):
            return cls._load_old_format(release_info)
        return cls._load_new_format(release_info)

    @classmethod
    def _load_old_format(cls,
                         release_info: List[Any]) -> 'JMESLogEntryCollection':
        collection = cls(
            schema_version=cls._OLD_SCHEMA_VERSION,
            changes=[JMESLogEntry(**entry) for entry in release_info],
        )
        return collection

    @classmethod
    def _load_new_format(cls,
                         release_info: Dict[str, Any]
                         ) -> 'JMESLogEntryCollection':
        collection = cls(
            schema_version=release_info['schema-version'],
            changes=[JMESLogEntry(**entry)
                     for entry in release_info['changes']],
            summary=release_info.get('summary', ''),
        )
        return collection


class EditorRetriever:
    def prompt_entry_values(self, entry: JMESLogEntry) -> None:
        with tempfile.NamedTemporaryFile('w') as f:
            self._write_template_to_tempfile(f, entry)
            self._open_tempfile_in_editor(f.name)
            contents = self._read_tempfile(f.name)
            return self._parse_filled_in_contents(contents, entry)

    def _open_tempfile_in_editor(self, filename: str) -> None:
        env = os.environ
        editor = env.get('VISUAL', env.get('EDITOR', 'vim'))
        subprocess.run([editor, filename], check=True)

    def _write_template_to_tempfile(self,
                                    f: IO[str],
                                    entry: JMESLogEntry) -> None:
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

    def _parse_filled_in_contents(self, contents: str,
                                  entry: JMESLogEntry) -> None:
        parsed_entry = EntryFileParser().parse_contents(contents)
        self._update_values_from_new_entry(entry, parsed_entry)

    def _update_values_from_new_entry(self, entry: JMESLogEntry,
                                      new_entry: JMESLogEntry) -> None:
        for key, value in asdict(new_entry).items():
            if value:
                setattr(entry, key, value)


class EntryFileParser:
    def parse_contents(self, contents: str) -> JMESLogEntry:
        entry = JMESLogEntry.empty()
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
    def __init__(self, entry: JMESLogEntry, retriever: EditorRetriever):
        self._entry = entry
        self._retriever = retriever

    def complete_entry(self) -> None:
        if not self._entry.is_completed():
            self._retriever.prompt_entry_values(self._entry)

    @property
    def change_entry(self) -> JMESLogEntry:
        return self._entry


class EntryFileWriter:
    def write_next_release_entry(self, entry: JMESLogEntry,
                                 change_dir: str) -> str:
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

    def _generate_random_file(self, entry: JMESLogEntry,
                              change_dir: str) -> str:
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
            next_release, '%s-%s-%s.json' % (
                time.monotonic_ns(), filename,
                str(random.randint(1, 100000)))
        )


class EntryRecorder:
    def __init__(self, entry_gen: EntryGenerator, schema: EntrySchema,
                 file_writer: EntryFileWriter, output_dir: str = '.changes'):
        self._entry_gen = entry_gen
        self._schema = schema
        self._file_writer = file_writer
        self._output_dir = output_dir

    def write_change_file_entry(self) -> str:
        self._entry_gen.complete_entry()
        entry = self._entry_gen.change_entry
        validate_change_entry(entry, self._schema)
        filename = self._file_writer.write_next_release_entry(
            entry, change_dir=self._output_dir)
        return filename


def validate_change_entry(entry: JMESLogEntry, schema: EntrySchema) -> None:
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
            errors.append(
                f'The "{key}" value cannot be empty.'
            )
    if errors:
        raise ValidationError(errors)


def cmd_new_release(args: argparse.Namespace) -> int:
    # Parse the upcoming changes and determine the type of version
    # bump.
    # Apply the version bump to the last known release and figure out
    # the new version.
    # Create a new version file from the existing changes.
    # Delete the next changes folder.
    changes = load_next_changes(args.change_dir)
    last_released_version = find_last_released_version(args.change_dir)
    next_version = determine_next_version(last_released_version,
                                          changes.version_bump_type)
    release_file = consolidate_next_release(
        next_version, args.change_dir, changes)
    print(f"New release file written: {release_file}")
    return 0


def consolidate_next_release(next_version: str, change_dir: str,
                             changes: JMESLogEntryCollection) -> str:
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
    return sorted(
        files, key=lambda x: StrictVersion(x))


def determine_next_version(last_released_version: str,
                           version_bump_type: VersionBump) -> str:
    parts = last_released_version.split('.')
    if version_bump_type == VersionBump.PATCH_VERSION:
        parts[2] = str(int(parts[2]) + 1)
    elif version_bump_type == VersionBump.MINOR_VERSION:
        parts[1] = str(int(parts[1]) + 1)
        parts[2] = '0'
    elif version_bump_type == VersionBump.MAJOR_VERSION:
        parts[0] = str(int(parts[0]) + 1)
        parts[1] = '0'
        parts[2] = '0'
    return '.'.join(parts)


def load_next_changes(change_dir: str) -> JMESLogEntryCollection:
    next_release = os.path.join(change_dir, 'next-release')
    if not os.path.isdir(next_release):
        raise NoChangesFoundError()
    changes = []
    for change in sorted(os.listdir(next_release)):
        entry = parse_entry(os.path.join(next_release, change))
        changes.append(entry)
    return JMESLogEntryCollection(changes=changes)


def parse_entry(filename: str) -> JMESLogEntry:
    with open(filename) as f:
        data = json.load(f)
        return JMESLogEntry(**data)


def create_entry_recorder(entry: JMESLogEntry,
                          change_dir: str) -> EntryRecorder:
    recorder = EntryRecorder(
        entry_gen=EntryGenerator(
            entry=entry,
            retriever=EditorRetriever(),
        ),
        schema=EntrySchema(),
        file_writer=EntryFileWriter(),
        output_dir=change_dir,
    )
    return recorder


def cmd_new_change(args: argparse.Namespace) -> int:
    entry = JMESLogEntry(
        type=args.type,
        category=args.category,
        description=args.description
    )
    recorder = create_entry_recorder(entry, args.change_dir)
    try:
        change_file = recorder.write_change_file_entry()
    except ValidationError as e:
        sys.stderr.write(str(e))
        sys.stderr.write("\n")
        return 1
    except Exception:
        sys.stderr.write("Unexpected error raised:\n\n")
        raise
    print(
        f"The change has been written to: {change_file}\n"
        f"You add this to your commit by running:\n\n"
        f"git add {change_file}\n"
    )
    return 0


def cmd_render(args: argparse.Namespace) -> int:
    changes = load_all_changes(args.change_dir)
    template_file = None
    if args.template:
        template_file = os.path.join(args.change_dir,
                                     'templates', args.template)
        with open(template_file) as f:
            template_contents = f.read()
    else:
        template_contents = DEFAULT_RENDER_TEMPLATE
    render_changes(changes, sys.stdout, template_contents)
    return 0


def render_changes(changes: Dict[str, JMESLogEntryCollection],
                   out: IO[str], template_contents: str) -> None:
    context = {
        'releases': reversed(list(changes.items())),
    }
    template = jinja2.Template(template_contents)
    result = template.render(**context)
    out.write(result)


def load_all_changes(change_dir: str) -> Dict[str, JMESLogEntryCollection]:
    releases = {}
    for version_number in sorted_versioned_releases(change_dir):
        filename = os.path.join(change_dir, f'{version_number}.json')
        with open(filename) as f:
            data = json.load(f)
            releases[version_number] = JMESLogEntryCollection.from_dict(data)
    return releases


def cmd_init(args: argparse.Namespace) -> int:
    if not os.path.isdir(args.change_dir):
        os.mkdir(args.change_dir)
    return 0


def cmd_query(args: argparse.Namespace) -> int:
    runner = ChangeQuery(args.change_dir)
    try:
        result = runner.run_query(args.query_for)
    except NoChangesFoundError as e:
        sys.stdout.write(str(e))
        sys.stdout.write("\n")
        return 1
    print(result)
    return 0


def cmd_pending(args: argparse.Namespace) -> int:
    pending_changes = load_next_changes(args.change_dir)
    sys.stdout.write('\n')
    _render_single_release_changes(pending_changes, sys.stdout)
    return 0


def _render_single_release_changes(change_collection: JMESLogEntryCollection,
                                   out: IO[str]) -> None:
    for change in change_collection.changes:
        description = '\n  '.join(change.description.splitlines())
        out.write(
            f'* {change.type}:{change.category}:{description}\n'
        )
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
            last_released_version, changes.version_bump_type)
        return next_version

    def query_next_release_type(self) -> str:
        changes = load_next_changes(self._change_dir)
        return changes.version_bump_type.value


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument('--version', action='version', version=__version__)
    parser.add_argument('--change-dir', default='.changes',
                        help='The location of the .changes directory.')
    subparser = parser.add_subparsers()

    init = subparser.add_parser('init')
    init.set_defaults(func=cmd_init)

    new_change = subparser.add_parser('new-change')
    new_change.set_defaults(func=cmd_new_change)
    new_change.add_argument('-t', '--type',
                            default='', choices=('bugfix', 'feature',
                                                 'enhancement'))
    new_change.add_argument('-c', '--category', dest='category',
                            default='')
    new_change.add_argument('-d', '--description', dest='description',
                            default='')

    new_release = subparser.add_parser('new-release')
    new_release.set_defaults(func=cmd_new_release)
    new_release.add_argument('-r', '--release-type',
                             default='', choices=('patch', 'minor', 'major'))
    new_release.add_argument('--release-version',
                             help=(
                                 'Specify release version.  If not specified '
                                 'this value will be determined automatically.'
                             ))
    new_release.add_argument('-d', '--description', dest='description',
                             help=("Provide additional release notes for this "
                                   "release."))

    render = subparser.add_parser('render')
    render.add_argument('-t', '--template',
                        help=('The name of the template to use from the '
                              '.changes/templates/ directory.'))
    render.set_defaults(func=cmd_render)

    query = subparser.add_parser('query')
    query.add_argument('query_for', choices=('next-release-type',
                                             'next-version',
                                             'last-release-version'))
    query.set_defaults(func=cmd_query)

    pending = subparser.add_parser('pending')
    pending.set_defaults(func=cmd_pending)

    return parser


def main() -> int:
    parser = create_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == '__main__':
    sys.exit(main())
