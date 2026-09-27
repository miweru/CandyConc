# Upgrade CandyConc

A new version replaces the program and keeps your data. Corpora, the project
file, saved analyses, and preferences live in the data directory
(`~/.candyconc`), which an upgrade does not change. See
[Where your data lives](../concepts/where-data-lives.md).

CandyConc 0.1.0 is the first release. The steps on this page apply to later
versions.

## Before you begin

- Stop CandyConc (Control+C in the terminal where it runs).
- Optional: back up the data directory, see
  [Back up your data](../guides/keep-and-share/back-up-your-data.md).
- Read the [Release notes](release-notes.md) of the new version for changes
  that need a step from you, for example a migration of the project file.

## Upgrade the application bundle

1. Download the archive of the new version for your platform from the release
   page and check it against `SHA256SUMS`, as described in
   [Install CandyConc](../get-started/install.md).
2. Unpack it next to the old bundle folder. The folders have the version in
   their name, so they do not collide.
3. Start the new version:

   ```bash
   ./candyconc
   ```

   Run the command in the new bundle folder. CandyConc opens your corpora
   from the data directory.
4. Delete the old bundle folder, or run `./candyconc uninstall` in it.

spaCy pipelines that you installed with `./candyconc pipeline` are in the
data directory and stay available.

## Upgrade the Python package

1. Activate the Python environment in which CandyConc is installed.
2. Install the new wheel over the old one:

   ```bash
   python -m pip install --upgrade WHEEL_FILE
   ```

   Replace `WHEEL_FILE` with the path or the address of the wheel for your
   platform and Python version, see
   [Install the Python package](../get-started/install-python-package.md).
3. Check the version:

   ```bash
   candy --version
   ```

spaCy pipelines installed into the same environment stay installed.

## Corpora and project files from an older version

- **Corpora.** An index of an older version opens in a newer one. An index
  whose format is newer than the installed CandyConc is refused with a
  message to update CandyConc. See [Index format](../reference/index-format.md#versions).
- **Corpora built before 0.1.0.** Development versions before 0.1.0 wrote
  indexes with the builder revision `0`, which lack the morphological
  features of many tokens. Check such an index with
  `python -m candyconc.tools.check_index INDEX_DIRECTORY`, and import the
  corpus again if the check reports the defect. See
  [Troubleshooting](troubleshooting.md#an-index-lacks-morphological-features).
- **Project file.** A project file of an older format is not converted
  automatically. CandyConc refuses to open it and names the reason. Migrate
  it with `candy migrate-project`, see
  [Project files](../reference/project-files.md#migrate-an-older-project-file).
- **Project file in the working directory.** If you kept `proj.ccproj` in the
  directory where you started CandyConc, it keeps being used when you start
  CandyConc there. To move it to the data directory, stop CandyConc and move
  the file to `~/.candyconc/proj.ccproj`, and `config/projects` to
  `~/.candyconc/projects`.

After the upgrade, open a corpus, run a search, and open a saved subcorpus to
confirm that your work is there.
