.PHONY: native wheel sdist lint demo demo-index

CHANNEL ?= stable
PYTHON ?= python3

# --- Demo ---------------------------------------------------------------------
# First-run convenience: import the synthetic English sample (four sentences,
# tokenized with blank:en, no pipeline download) and start the server with it.
# Override DEMO_SOURCE / DEMO_INDEX / DEMO_PORT / DEMO_SPACY_MODEL as needed.
REPO_ROOT ?= ..
DEMO_SOURCE ?= $(firstword $(wildcard $(REPO_ROOT)/packaging/sample/synthetic_en.csv ../repo_root/packaging/sample/synthetic_en.csv))
DEMO_INDEX ?= $(HOME)/.candyconc/corpora/demo
DEMO_SPACY_MODEL ?= blank:en
DEMO_HOST ?= 127.0.0.1
DEMO_PORT ?= 8010

# Build the demo index (rebuilds into DEMO_INDEX).
demo-index:
	@test -n "$(DEMO_SOURCE)" && test -f "$(DEMO_SOURCE)" || { \
		echo "Demo source not found. Set DEMO_SOURCE=/path/to/corpus.csv" >&2; exit 2; }
	rm -rf "$(DEMO_INDEX)"
	$(PYTHON) -m candyconc.entrypoints.cli import \
		--input "$(DEMO_SOURCE)" \
		--input-format csv \
		--id-column doc_id \
		--meta-columns genre \
		--spacy-model "$(DEMO_SPACY_MODEL)" \
		--output "$(DEMO_INDEX)"

# Build the demo index and start the server with it.
demo: demo-index
	CANDYCONC_INDEX_PATH="$(DEMO_INDEX)" $(PYTHON) -m candyconc.entrypoints.cli \
		--host $(DEMO_HOST) --port $(DEMO_PORT)

# Build all required Cython extensions in-place for local release smoke tests.
native:
	$(PYTHON) setup_native.py build_ext --inplace

# Build a platform wheel with native extensions via PEP 517.
wheel:
	$(PYTHON) -m build --wheel

# Build a source distribution that includes native build inputs.
sdist:
	$(PYTHON) -m build --sdist

# Run ruff as a non-mutating lint gate over the release-critical backend,
# packaging and import surface. Files missing in a checkout (the monorepo CI
# tests are not exported) are skipped by the wildcard.
LINT_FILES = $(wildcard \
	setup.py \
	setup_native.py \
	src/candyconc/config.py \
	src/candyconc/paths.py \
	src/candyconc/version.py \
	src/candyconc/entrypoints/cli.py \
	src/candyconc/ingest/*.py \
	src/candyconc/builders/*.py \
	src/candyconc/tools/install_smoke.py \
	src/candyconc/services/backend/server.py \
	src/candyconc/services/backend/startup.py \
	src/candyconc/services/backend/frontend_static.py \
	src/candyconc/services/backend/corpus_import_jobs.py \
	src/candyconc/services/backend/routes/corpora.py \
	src/candyconc/services/backend/routes/system.py \
	src/candyconc/core/native_extensions.py \
	tests/backend/test_active_corpus_registry_runtime.py \
	tests/backend/test_first_start_without_corpus.py \
	tests/infra/test_ci_lint.py \
	tests/infra/test_ci_setup.py \
	tests/infra/test_native_packaging.py \
	tests/infra/test_release_publish.py \
	tests/scripts/test_wheel_builder_dir.py \
	tests/unit/test_config_single_source.py \
	tests/unit/test_user_paths.py)

lint:
	$(PYTHON) -m ruff check \
		$(LINT_FILES)
