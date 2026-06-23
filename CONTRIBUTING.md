# Contributing to OptiCipher

Thank you for your interest in OptiCipher! This is an **open-source research and
education project**, and contributions from the community are genuinely welcomed —
whether you are a student, a developer, a security researcher, or simply curious.

## Ways to contribute

- **Code:** new features, bug fixes, performance improvements.
- **Cryptography:** hardening the scheme, adding an Argon2id KDF option, or
  performing and writing up independent security analysis.
- **Metrics & research:** new statistical tests (χ² histogram uniformity, local
  entropy, key-sensitivity), reproducible benchmark reports, sample datasets.
- **Documentation:** clarifications, translations, tutorials, diagrams.
- **Front-ends:** a GUI or web interface over the library.

## Ground rules

1. **Open an issue first** for anything substantial, so we can align on the
   approach before you invest time.
2. **Match the code style.** OptiCipher is deliberately, heavily commented and
   written to be read. New code should explain the *why*, not just the *what*.
3. **Add tests** for any new behaviour. The suite must stay green:
   ```bash
   pip install -e ".[dev]"
   pytest -v
   ```
4. **Keep dependencies minimal** and well-established. New third-party
   requirements should be justified in the PR.
5. **Be honest about security.** Do not overstate guarantees. If a change affects
   the threat model, update the README accordingly.

## Development setup

```bash
git clone https://github.com/bio-colab/OptiCipher.git
cd OptiCipher
pip install -e ".[dev]"
pytest -v
python examples/demo.py
```

## Pull request checklist

- [ ] Tests added/updated and passing (`pytest`).
- [ ] Public functions have docstrings; non-obvious logic is commented.
- [ ] README / docs updated if behaviour or the threat model changed.
- [ ] No secrets, no large binary blobs committed.

## Code of conduct

Be respectful, constructive, and welcoming. We want OptiCipher to be a friendly
place to learn about image encryption.

## License of contributions

By contributing, you agree that your contributions are licensed under the same
**MIT License** that covers the project.
