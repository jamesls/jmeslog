check:
	flake8 jmeslog
	python -m mypy --disallow-untyped-defs --strict-optional --warn-no-return jmeslog

coverage:
	py.test --cov jmeslog --cov-report term-missing ./tests

prcheck: check coverage
