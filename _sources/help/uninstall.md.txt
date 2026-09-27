# Uninstall CandyConc

Removing CandyConc removes the program. Your data directory stays until you
delete it yourself, so you decide separately whether your corpora and project
files go too.

## Remove the program

### Application bundle

In the bundle folder, run:

```bash
./candyconc uninstall
```

The launcher shows the folder it will remove and the data directory it keeps,
and asks for confirmation. `./candyconc uninstall --yes` skips the question.
You can also delete the bundle folder directly, the result is the same.

### Python package

In the Python environment of CandyConc, run:

```bash
python -m pip uninstall candyconc
```

This removes the package and the command `candy`. If you created the
environment only for CandyConc, you can delete the environment directory
instead, which also removes the dependencies and the spaCy pipelines
installed into it.

## Decide about your data

After removing the program, these locations remain:

| Location | Content | To remove it |
| --- | --- | --- |
| `~/.candyconc` (or `CANDYCONC_HOME`) | corpora, project file, saved analyses, preferences, logs, pipelines installed with `./candyconc pipeline` | delete the directory |
| the configuration file, if you created one | settings | delete the file (`candy paths` showed its location) |
| `proj.ccproj` and `config/projects` in a working directory, if an older version created them there | project file and saved analyses | delete them |
| the browser | search history and preferences of the interface for the address of CandyConc | clear the site data of `127.0.0.1` in the browser |

Run `candy paths` before you remove the program if you are not sure where
these locations are on your computer.

To keep your work for later, leave the data directory in place. A new
installation of CandyConc finds it again. To keep it elsewhere, copy it and
set `CANDYCONC_HOME` to the copy when you install CandyConc again.
