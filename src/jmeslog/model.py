import enum
import json
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Union


class VersionBump(enum.Enum):
    PATCH_VERSION = 'patch'
    MINOR_VERSION = 'minor'
    MAJOR_VERSION = 'major'


@dataclass
class EntrySchema:
    type: List[str] = field(
        default_factory=lambda: ['feature', 'bugfix', 'enhancement']
    )
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
            'changes': [entry.to_dict() for entry in self.changes],
        }
        if self.summary:
            result['summary'] = self.summary
        return result

    @classmethod
    def from_dict(
        cls, release_info: Union[List[Any], Dict[str, Any]]
    ) -> 'JMESLogEntryCollection':
        if isinstance(release_info, list):
            return cls._load_old_format(release_info)
        return cls._load_new_format(release_info)

    @classmethod
    def _load_old_format(
        cls, release_info: List[Any]
    ) -> 'JMESLogEntryCollection':
        collection = cls(
            schema_version=cls._OLD_SCHEMA_VERSION,
            changes=[JMESLogEntry(**entry) for entry in release_info],
        )
        return collection

    @classmethod
    def _load_new_format(
        cls, release_info: Dict[str, Any]
    ) -> 'JMESLogEntryCollection':
        collection = cls(
            schema_version=release_info['schema-version'],
            changes=[
                JMESLogEntry(**entry) for entry in release_info['changes']
            ],
            summary=release_info.get('summary', ''),
        )
        return collection
