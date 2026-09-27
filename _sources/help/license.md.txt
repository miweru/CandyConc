# Licenses

This page states the license of CandyConc, the licenses of the components it
ships, the licenses of the sample corpora of this documentation, and what
applies to your own corpora.

## CandyConc

CandyConc is released under the MIT license, copyright Michael Ruppert. The
license text is in the file `LICENSE` at the root of the repository and in
every wheel and application bundle. You may use, copy, change, and
redistribute the software, also commercially, as long as you keep the
copyright notice and the license text.

The license covers the software: the backend, the query engine, the web
interface, the import tools, and this documentation. It does not cover corpus
data, and no corpus data is part of the repository except the small sample
files named below.

## Components that CandyConc ships

| Component | Where the licenses are listed |
| --- | --- |
| Python packages that the wheel installs as dependencies | the metadata of each installed package |
| JavaScript libraries built into the web interface (for example Vue, D3, and Radix Vue) | `THIRD_PARTY_LICENSES.txt` next to `index.html` in the web interface of the package (`candyconc/web_dist/`), with the full license texts |
| everything in the application bundle: the Python interpreter (CPython from python-build-standalone), all Python packages, and the JavaScript libraries | `THIRD_PARTY_LICENSES.txt` in the bundle folder, with the full license texts |
| Mermaid (MIT) and MathJax (Apache 2.0), used to render diagrams and formulas in this documentation | the license files next to the copies in `docs/_static/` |

spaCy annotation pipelines are not part of CandyConc. Each pipeline that you
install with `candy pipeline` carries its own license, stated on its release
page at `explosion/spacy-models`.

## Sample corpora

| Corpus | Source | License |
| --- | --- | --- |
| synthetic English sample (`packaging/sample/synthetic_en.csv`, four sentences) | written for CandyConc | part of CandyConc, MIT |
| synthetic tea corpus (`docs/methods/data/tea_demo.jsonl`) | written for the worked examples | part of CandyConc, MIT |
| State of the Union sample corpus: 65 addresses, 1945 to 2006 | NLTK Data, package `state_union` (C-SPAN State of the Union Address Corpus, compiled by Kathleen Ahrens) | public domain. Addresses of the President of the United States are works of the US federal government (17 U.S.C. § 105). NLTK Data lists the package as public domain. |
| German DTA sample corpus: 30 texts, 1800 to 1899 | Deutsches Textarchiv, core corpus, normalized plain text version of 23 October 2020 | CC BY-SA 4.0. Name the source as "Deutsches Textarchiv". Every document keeps its DTA address in the metadata field `url`. |

The two corpora are in the folder `examples` of the repository, of the source
distribution, and of the application bundle, together with `README.md`,
`ATTRIBUTION.txt`, and the full text of CC BY-SA 4.0
(`LICENSE-CC-BY-SA-4.0.txt`).

The Deutsches Textarchiv asks to be cited as: <span lang="de">Deutsches Textarchiv. Grundlage
für ein Referenzkorpus der neuhochdeutschen Sprache. Herausgegeben von der
Berlin-Brandenburgischen Akademie der Wissenschaften, Berlin.</span>
<https://www.deutschestextarchiv.de/>

Results that you derive from the DTA sample and share must follow the terms of
CC BY-SA 4.0 where they contain its text.

## Your own corpora

CandyConc does not change the rights to the texts you import. The index,
exports, and evidence packages contain text from your corpus, so the license
and terms of its source apply to them as they apply to the corpus. In the
default setup your corpora stay on your computer. What the copilot sends to a
model endpoint is described in [Data and privacy](../concepts/data-and-privacy.md).
