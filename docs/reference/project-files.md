# Project files

The project file keeps the work you do on top of a corpus: saved subcorpora,
line annotations, and the coding schemes. Saved analyses and cluster lists are
kept next to it in the project directory. This page describes where both are,
the format of the project file, and how to migrate a project file of an older
version.

## Location

| What | Default location | Setting |
| --- | --- | --- |
| project file | `proj.ccproj` in the data directory (`~/.candyconc/proj.ccproj`) | `CANDYCONC_PROJECT_FILE` |
| project directory | `projects/` in the data directory | `CANDYCONC_PROJECTS_DIR` |

Earlier versions kept both in the working directory of the server. When the
working directory contains a `proj.ccproj` or a `config/projects` directory
and the setting is not set, CandyConc keeps using that file or directory.
`candy paths` prints the locations in effect. See
[Configuration reference](configuration.md#locations).

A server serves one project file, which all users of the server share. With
independent annotation by several coders switched on, the line annotations of
each coder are kept apart (see [Deployment](deployment.md)).

## Format

The project file is a JSON object with `"version": 2`. CandyConc writes it
completely on every change, into a temporary file that then replaces the old
one, so an interrupted write leaves the previous state.

| Key | Content |
| --- | --- |
| `version` | format version, `2` |
| `subcorpora` | saved subcorpora by name, see [Subcorpora](#subcorpora) |
| `row_annotations` | line annotations by corpus, line, and annotator, see [Line annotations](#line-annotations) |
| `coding_schemes` | the coding scheme of each corpus that has one: its categories and a revision number |
| `coding_scheme` | the project scheme: categories and revision number for every corpus without a scheme of its own. Project files of earlier versions kept their only scheme here |
| `settings` | project settings, such as independent annotation by several coders |
| `bookmarks`, `annotations`, `comments`, `timeline`, `metrics`, `filter_state`, `ai_outputs`, `analysis_tree`, `macros`, `jobs`, `project`, `span_annotations`, `annotation_progress` | further project records. `candy migrate-project` counts them and keeps them. |

### Subcorpora

Each saved subcorpus stores its definition, not a list of documents:

| Field | Content |
| --- | --- |
| `name` | the name, unique in the project |
| `corpus` | the corpus the subcorpus belongs to |
| `filter_spec` | the metadata filter, for example `{"party": "Republican"}` or a range |
| `query` | for a subcorpus from a search, the query whose documents it contains |
| `metadata_schema_hash` | the metadata schema hash of the corpus when the subcorpus was saved |
| `created_at`, `creator` | when and by whom it was saved |

When you use a saved subcorpus, CandyConc applies the definition to the corpus
again and gets a document set. If the metadata schema hash of the corpus has
changed since the subcorpus was saved, the result is marked `stale`: the
documents can differ from those at the time of saving.

### Line annotations

A line annotation belongs to one concordance line of one corpus. The line is
identified by its document and token position (`file:NAME|pos:N`). The
annotation has a category of the coding scheme, a note, the annotator, and the
time of the last change.

The identification contains the corpus name but no fingerprint of the index.
If you import a corpus again under the same name, check the annotations
before you rely on them, because token positions change when the text or the
annotation pipeline changes.

## Project directory

The project directory holds, for each project, a subdirectory `PROJECT/`
with `analysis_presets.json` (saved analyses) and `clusters.json` (cluster
lists), and a file `PROJECT.json` with the members of the project. The web
interface uses the project `default`.

## Migrate an older project file

Project files of older versions (SQLite, or JSON before version 2, or line
annotations in an older structure) are not changed automatically. CandyConc
refuses to open such a file and names the reason. Migrate it with
`candy migrate-project`:

1. Check the file without changing it:

   ```bash
   candy migrate-project OLD_FILE
   ```

   Replace `OLD_FILE` with the path of the old project file. The output lists
   how many records of each kind the file contains, for example
   `subcorpora=3, row_annotations=120`.

2. Write the migrated project to a new file:

   ```bash
   candy migrate-project OLD_FILE --output NEW_FILE
   ```

   Or replace the old file and keep a backup:

   ```bash
   candy migrate-project OLD_FILE --in-place --backup BACKUP_FILE
   ```

3. Point `CANDYCONC_PROJECT_FILE` to the new file, or copy it to the default
   location, and start CandyConc.

The migration keeps every record that it counts in step 1.
