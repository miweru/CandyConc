# Back up your data

CandyConc keeps everything you create in one data folder, by default
`.candyconc` in your home folder. A backup of that folder, and of the
configuration file if you have one, keeps your corpora, subcorpora,
annotations, saved analyses, and settings. This guide lists what is where and
how to copy and restore it.

## Before you begin

- Know where your data folder is. Run `candy paths` (or `./candyconc paths`
  in the bundle folder). The line `data dir` names the folder, and
  `config file` the configuration file.

## What the data folder holds

| Path in the data folder | Content |
| --- | --- |
| `corpora/` | one folder for each imported corpus, the index files |
| `corpora.json` | the corpus catalog: registered corpora and the active corpus |
| `proj.ccproj` | the project file: subcorpora, line annotations, coding schemes |
| `projects/default/analysis_presets.json` | saved analyses with their settings and result rows |
| `prefs.json` | settings of the interface, such as the language, and bookmarks |
| `pipelines/` | spaCy pipelines downloaded with the application bundle |
| `logs/` | the audit log of the server |
| `tmp/` | temporary files, not needed in a backup |

Not in the data folder:

- the configuration file `config.toml`, whose location `candy paths` shows,
- corpora that you registered from other folders. The catalog stores their
  paths only,
- the search history and some view states, which the browser keeps in its
  local storage.

## Make a backup

1. Stop CandyConc with <kbd>Control</kbd>+<kbd>C</kbd> in its terminal, so
   that no file changes while you copy.
2. Copy the data folder to the backup location, for example:

   ```bash
   cp -R ~/.candyconc /Volumes/Backup/candyconc-backup
   ```

3. If you use a configuration file, copy it too.

The index files in `corpora/` make up most of the size. A corpus can also be
rebuilt from its input file with the same import command instead of being
backed up, see [Reproduce a result](reproduce-a-result.md).

## Restore a backup

1. Stop CandyConc.
2. Copy the backed-up folder back to `~/.candyconc`, or to another place and
   point CandyConc to it with the environment variable `CANDYCONC_HOME`.
3. Start CandyConc.

The corpus selector lists the corpora of `corpora/`, and the workspace shows
your subcorpora and saved analyses. Corpora that were registered from other
folders appear only if these folders exist at the same paths. Otherwise,
register them again, see [Switch, register, and remove corpora](../bring-in-texts/manage-corpora.md).

## Result

Your work is in a copy that you can restore on the same or another computer.
The data folder is not touched when you update or remove the application, see
[Upgrade CandyConc](../../help/upgrade.md) and
[Uninstall CandyConc](../../help/uninstall.md). All locations and the
environment variables that move them are described in
[Where your data lives](../../concepts/where-data-lives.md).
