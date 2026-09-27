# Contributing to CandyConc

Thank you for considering a contribution. Bug reports, corrections of the
documentation, and changes to the code are all welcome.

## Report a problem or ask a question

Open an issue in the [issue tracker](https://github.com/miweru/CandyConc/issues).
For a problem, include the version (`candy --version`), your operating
system, the steps that lead to the problem, and the message you see. Do not
attach corpora that you may not share.

For security vulnerabilities, follow the [security policy](SECURITY.md).
All contributions follow the [code of conduct](CODE_OF_CONDUCT.md).

## Propose a change

1. Set up a development environment as described in
   [Set up a development environment](docs/contribute/development-setup.md).
2. Make your change on a branch, with tests. A fixed bug gets a test that
   fails without the fix.
3. Run the tests and the lint as described in [Run the tests](docs/contribute/tests.md).
4. If you changed an option, a route, or a setting, regenerate the reference
   pages as described in
   [Documentation maintenance](docs/contribute/documentation.md).
5. Open a pull request that says what the change does and why.

Where CandyConc is usually extended (analysis operations, import formats,
copilot tools, interface languages) is described in
[Architecture for contributors](docs/contribute/architecture-for-contributors.md).

## License of contributions

By contributing, you agree that your contribution is released under the
[MIT license](LICENSE) of the project.
