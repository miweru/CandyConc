# CandyConc

CandyConc is an application for corpus analysis on your own computer. It
imports your texts into its own index, searches them with plain searches or a
CQP-style query language, shows every hit in its document, and computes
frequency lists, collocations, dispersion, keyness, trends, n-grams, and word
sketches on the same index, each with the method that produced it. An
optional copilot answers research questions by calling the same analyses. It
runs as a local server with a web interface in your browser.

This package contains the complete application: the server, the web
interface, the import tools, and the compiled query engine.

## Install

The [platform status](https://github.com/miweru/CandyConc/blob/main/docs/reference/supported-platforms.md)
lists the built artifacts and configured build targets. Choose the wheel
for your platform and Python version from the
[releases of the repository](https://github.com/miweru/CandyConc/releases)
and install it into a virtual environment:

```bash
python -m pip install WHEEL_FILE
```

Replace `WHEEL_FILE` with the path or the address of the wheel. Then start
CandyConc:

```bash
candy
```

The web interface is at the address that `candy` prints, by default
`http://127.0.0.1:8010/`. Import a corpus with `candy import --help`, and
install an annotation pipeline with `candy pipeline en_core_web_sm`.

For an application bundle with its own Python, and for all other
details, see the
[installation guide](https://github.com/miweru/CandyConc/blob/main/docs/get-started/install-python-package.md).

## Documentation

The documentation is in the
[docs folder of the repository](https://github.com/miweru/CandyConc/tree/main/docs):
installation, tutorials, guides, concepts, the statistical methods, and the
reference of the query language, the command line, the HTTP API, and the
configuration.

## License

MIT. Corpus data keeps the license of its source. See
[Licenses](https://github.com/miweru/CandyConc/blob/main/docs/help/license.md).
