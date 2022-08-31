import string

VALID_CHARS = set(string.ascii_letters + string.digits)
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
