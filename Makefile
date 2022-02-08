check:
	flake8 jmeslog.py
	python -m mypy --disallow-untyped-defs --strict-optional --warn-no-return ./jmeslog.py

coverage:
	py.test --cov jmeslog --cov-report term-missing ./tests

prcheck: check coverage
