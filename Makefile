PR=poetry run

PHONY: install-dev
install-dev:
	poetry install --with=dev

PHONY: test
test:
	$(PR) coverage run --source=sandock -m unittest discover -s tests
	$(PR) coverage report
	$(PR) coverage html

PHONY: tidy
tidy:
	$(PR) black sandock tests

PHONY: lint
lint:
	$(PR) mypy .
	$(PR) flake8 sandock

PHONY: test-all
test-all: test lint