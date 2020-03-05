check:
	flake8 jmeslog.py
	mypy --ignore-missing-imports --follow-imports=skip --disallow-untyped-defs --strict-optional --warn-no-return ./jmeslog.py

coverage:
	py.test --cov jmeslog --cov-report term-missing ./tests

