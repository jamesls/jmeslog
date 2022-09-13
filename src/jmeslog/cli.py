import argparse
import os
import sys
from importlib import metadata
from typing import Callable, Optional

from jmeslog import core, model
from jmeslog.constants import DEFAULT_RENDER_TEMPLATE
from jmeslog.errors import NoChangesFoundError, ValidationError

SUB_CMD_FUNC = Callable[[argparse.Namespace], int]


def cmd_new_release(args: argparse.Namespace) -> int:
    # Parse the upcoming changes and determine the type of version
    # bump.
    # Apply the version bump to the last known release and figure out
    # the new version.
    # Create a new version file from the existing changes.
    # Delete the next changes folder.
    changes = core.load_next_changes(args.change_dir)
    if args.release_version is not None:
        next_version = args.release_version
    else:
        last_released_version = core.find_last_released_version(
            args.change_dir
        )
        next_version = core.determine_next_version(
            last_released_version, changes.version_bump_type
        )
    release_file = core.consolidate_next_release(
        next_version, args.change_dir, changes
    )
    print(f"New release file written: {release_file}")
    return 0


def cmd_new_change(args: argparse.Namespace) -> int:
    entry = model.JMESLogEntry(
        type=args.type, category=args.category, description=args.description
    )
    recorder = core.create_entry_recorder(entry, args.change_dir)
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
    changes = core.load_all_changes(args.change_dir)
    template_file = None
    if args.template:
        template_file = os.path.join(
            args.change_dir, 'templates', args.template
        )
        with open(template_file) as f:
            template_contents = f.read()
    else:
        template_contents = DEFAULT_RENDER_TEMPLATE
    core.render_changes(changes, sys.stdout, template_contents)
    return 0


def cmd_init(args: argparse.Namespace) -> int:
    if not os.path.isdir(args.change_dir):
        os.mkdir(args.change_dir)
    return 0


def cmd_query(args: argparse.Namespace) -> int:
    runner = core.ChangeQuery(args.change_dir)
    try:
        result = runner.run_query(args.query_for)
    except NoChangesFoundError as e:
        sys.stdout.write(str(e))
        sys.stdout.write("\n")
        return 1
    print(result)
    return 0


def cmd_pending(args: argparse.Namespace) -> int:
    pending_changes = core.load_next_changes(args.change_dir)
    sys.stdout.write('\n')
    core.render_single_release_changes(pending_changes, sys.stdout)
    return 0


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        '--version', action='version', version=metadata.version(__package__)
    )
    parser.add_argument(
        '--change-dir',
        default='.changes',
        help='The location of the .changes directory.',
    )
    subparser = parser.add_subparsers()

    init = subparser.add_parser('init')
    init.set_defaults(func=cmd_init)

    new_change = subparser.add_parser('new-change')
    new_change.set_defaults(func=cmd_new_change)
    new_change.add_argument(
        '-t',
        '--type',
        default='',
        choices=('bugfix', 'feature', 'enhancement'),
    )
    new_change.add_argument('-c', '--category', dest='category', default='')
    new_change.add_argument(
        '-d', '--description', dest='description', default=''
    )

    new_release = subparser.add_parser('new-release')
    new_release.set_defaults(func=cmd_new_release)
    new_release.add_argument(
        '-r', '--release-type', default='', choices=('patch', 'minor', 'major')
    )
    new_release.add_argument(
        '--release-version',
        help=(
            'Specify release version.  If not specified '
            'this value will be determined automatically.'
        ),
    )
    new_release.add_argument(
        '-d',
        '--description',
        dest='description',
        help=("Provide additional release notes for this " "release."),
    )

    render = subparser.add_parser('render')
    render.add_argument(
        '-t',
        '--template',
        help=(
            'The name of the template to use from the '
            '.changes/templates/ directory.'
        ),
    )
    render.set_defaults(func=cmd_render)

    query = subparser.add_parser('query')
    query.add_argument(
        'query_for',
        choices=('next-release-type', 'next-version', 'last-release-version'),
    )
    query.set_defaults(func=cmd_query)

    pending = subparser.add_parser('pending')
    pending.set_defaults(func=cmd_pending)

    return parser


def main(argv: Optional[list[str]] = None) -> int:
    parser = create_parser()
    if argv is None:
        argv = sys.argv[1:]
    args = parser.parse_args(argv)
    if not hasattr(args, 'func'):
        parser.print_help()
        return 0
    else:
        handler: SUB_CMD_FUNC = args.func
        return handler(args)


if __name__ == '__main__':
    sys.exit(main())
