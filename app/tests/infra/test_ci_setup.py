import os
import unittest

REQUIRED_DIRS = [
    # The runtime entrypoints package carries the CLI.
    "src/candyconc/entrypoints",
    "src/candyconc/services/backend",
    "src/candyconc/core",
]

REQUIRED_CORE_FILES = [
    # query_runtime is a module inside candyconc.core, not a top-level dir.
    "src/candyconc/core/query_runtime.py",
]

REQUIRED_FILES = [
    "pyproject.toml",
]

#: GitHub runs workflows only from the repository root. In the exported
#: repository that is the parent of app/, in the monorepo the future root
#: files live in repo_root next to app/ (plus the app-local ci.yml).
WORKFLOW_DIRS = [
    "../.github/workflows",
    "../repo_root/.github/workflows",
    ".github/workflows",
]


class TestCISetup(unittest.TestCase):
    def test_required_directories_exist(self):
        for path in REQUIRED_DIRS:
            self.assertTrue(os.path.isdir(path), f"Missing directory: {path}")

    def test_required_files_exist(self):
        for file in REQUIRED_FILES + REQUIRED_CORE_FILES:
            self.assertTrue(os.path.isfile(file), f"Missing file: {file}")

    def test_active_workflows_directory_exists(self):
        found = [path for path in WORKFLOW_DIRS if os.path.isdir(path)]
        self.assertTrue(found, f"No workflow directory among {WORKFLOW_DIRS}")
        self.assertTrue(
            any(name.endswith((".yml", ".yaml")) for path in found for name in os.listdir(path))
        )


if __name__ == "__main__":
    unittest.main()
