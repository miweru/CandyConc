# Release process

A release of CandyConc consists of application bundles, Python wheels, a
source distribution, the documentation as HTML pages in a ZIP file, and a
file of checksums, attached to a GitHub release. They are built and checked
by the workflow `.github/workflows/release.yml`.
This page describes what the workflow does and the steps around it.

## Version

The version is `version` in the `[project]` table of `app/pyproject.toml`.
The package metadata, `candy --version`, the API, and the footer of this
documentation read it from there. Change it there and nowhere else.

## What the release workflow builds

The workflow runs when a tag that starts with `v` is pushed, for example
`v0.1.0`, and on manual start (without creating a release).

| Job | What it does | Check |
| --- | --- | --- |
| `web` | builds the web interface with `npm ci` and `npm run build` (type check, Vite build, `THIRD_PARTY_LICENSES.txt` of the npm packages) | the build succeeds |
| `sdist` | copies the interface into the package, builds the documentation with the documented command into the package and as `candyconc-VERSION-docs-html.zip`, writes the release notes, and builds the source distribution. `CANDYCONC_REQUIRE_WEB_DIST=1` stops the build without the interface. | the documentation build ends without a warning and names its commit (`packaging/build_web.py --require-docs`), the section of the version in the release notes exists and every link in it points to a page of the documentation (`packaging/release_notes.py`), and the metadata of the source distribution contains no absolute path (`packaging/check_sdist.py`) |
| `wheels` | builds the wheels from the source distribution with cibuildwheel for CPython 3.11 to 3.14 on Linux x86_64, Linux aarch64 (emulated), macOS Intel, and macOS Apple silicon, without OpenMP and with macOS 11 as the deployment target | each wheel is installed with its dependencies and checked with `candy --version` and `python -m candyconc.tools.install_smoke --require-web` |
| `bundles` | builds an application bundle with CPython 3.12 from python-build-standalone and the wheels, for macOS Apple silicon, macOS Intel, and Linux x86_64 (`packaging/bundle/build_bundle.sh`) | the archive is unpacked in another place with a fresh application data directory, a sample is imported, the server starts, the interface and a search answer |
| `release` | only for a tag: computes `SHA256SUMS` over all files and creates a draft prerelease with them. The text of the release is the section of the version in [Release notes](../help/release-notes.md), written by the `sdist` job. | the tag is `v` followed by the version in `app/pyproject.toml` |

The workflow creates a draft marked as a prerelease. A person reviews and
publishes it.

State of this workflow for 0.1.0: the builds were run locally for macOS
arm64. The workflow itself has not yet run on GitHub.

## Steps for a release

1. Update the version in `app/pyproject.toml` and write the section
   `## CandyConc VERSION` of the [Release notes](../help/release-notes.md),
   and merge the change. This section is the text of the release page. Its
   relative links to other pages of the documentation become links to the
   same pages in the repository at the tag, where GitHub renders them.
2. Make sure the test workflow (`.github/workflows/test.yml`) passed on the
   commit.
3. Create and push the tag, for example `git tag v0.1.0` and
   `git push origin v0.1.0`.
4. Wait for the release workflow. Read the log of every job, including the
   checks of the wheels and bundles.
5. Download all files of the draft release, check them against
   `SHA256SUMS`, and install at least one bundle and one wheel from the
   downloaded files in a clean environment.
6. Publish the draft on the release page of the repository.
7. Download the published files again and compare their checksums.

Tags and release files are not overwritten. A corrected build gets a new
version.

## Build the artifacts locally

To build and check locally what the workflow builds for your platform, with
the documentation environment `.venv-docs` of
[Documentation maintenance](documentation.md):

```bash
export CANDYCONC_DOCS_COMMIT=$(git rev-parse --short=10 HEAD)
python packaging/build_web.py --require-docs --docs-python .venv-docs/bin/python --docs-zip dist
python packaging/release_notes.py --output dist/RELEASE_NOTES.md
CANDYCONC_REQUIRE_WEB_DIST=1 CANDYCONC_ENABLE_OPENMP=off python -m build app
python packaging/check_sdist.py app/dist/candyconc-*.tar.gz
python -m venv /tmp/candyconc-check
/tmp/candyconc-check/bin/python -m pip install app/dist/candyconc-*.whl
/tmp/candyconc-check/bin/python -m candyconc.tools.install_smoke --require-web
```

`CANDYCONC_DOCS_COMMIT` is the commit that the footer of every documentation
page names. In a tree without `.git`, for example an exported copy of the
repository, set it to the commit of the source by hand. Without it
`--require-docs` stops the build. The documentation ZIP and the release notes
land in `dist/`.

For a local macOS wheel build, set both the compiler target and the wheel
platform. For Apple silicon, prefix the build command with
`MACOSX_DEPLOYMENT_TARGET=11.0 _PYTHON_HOST_PLATFORM=macosx-11.0-arm64`.
This keeps an interpreter built for a newer macOS from assigning its own
platform requirement to CandyConc’s extensions. The complete runtime has
the separate requirements listed under
[Supported platforms](../reference/supported-platforms.md).

To build an application bundle from wheels:

```bash
sh packaging/bundle/build_bundle.sh --wheels app/dist --python 3.12 --out bundle
```

The script needs `uv`, downloads CPython from python-build-standalone, and
writes the archive and its checksum to `bundle/`. On macOS, it resolves
binary dependency wheels for macOS 13, independent of the build host’s
newer operating system. `CANDYCONC_BUNDLE_PLATFORM`
sets the platform name in the file name.

## Signing on macOS

The bundles are not signed with an Apple Developer ID and not notarized.
Users who download them with a browser remove the quarantine attribute once,
as described in [Troubleshooting](../help/troubleshooting.md#macos-refuses-to-run-the-bundle-after-a-browser-download).
Signing needs a Developer ID certificate in the secrets of the repository and
a signing and notarization step in the `bundles` job.
