# Contributing to audiobooker

Thank you for your interest in contributing to audiobooker! This is an AI audiobook generator that converts books to narrated audiobooks with multi-voice synthesis.

## How to Contribute

### Reporting Issues

If you find a bug or have a suggestion:

1. Check if the issue already exists in [GitHub Issues](https://github.com/mcp-tool-shop/audiobooker/issues)
2. If not, create a new issue with:
   - A clear, descriptive title
   - Steps to reproduce (for bugs)
   - Expected vs. actual behavior
   - Your environment (Python version, OS, book format tested)
   - Sample file or text snippet if relevant

### Contributing Code

1. **Fork the repository** and create a branch from `main`
2. **Make your changes**
   - Follow the existing code style
   - Maintain compatibility with voice-soundboard
   - Ensure EPUB/TXT parsing works correctly
3. **Test your changes**
   ```bash
   pytest tests/ -v
   ```
4. **Commit your changes**
   - Use clear, descriptive commit messages
   - Reference issue numbers when applicable
5. **Submit a pull request**
   - Describe what your PR does and why
   - Link to related issues

### Development Workflow

```bash
# Clone the repository
git clone https://github.com/mcp-tool-shop/audiobooker.git
cd audiobooker

# Create a virtual environment
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

# Install with dev dependencies
pip install -e ".[dev]"

# Install voice-soundboard (required)
pip install -e ../voice-soundboard

# Run tests
pytest tests/ -v

# Test CLI
audiobooker --help
audiobooker voices
```

### Adding Features

When adding new features:

1. Maintain the review-before-render workflow for audiobook compilation
2. Ensure dialogue detection heuristics remain robust
3. Test with various EPUB and TXT formats
4. Update README.md with new commands or options
5. Add tests for new functionality

### Code Organization

- `audiobooker/parser/` - EPUB/TXT parsing
- `audiobooker/casting/` - Dialogue detection, voice assignment
- `audiobooker/renderer/` - Audio synthesis and M4B assembly
- `audiobooker/review.py` - Review format export/import
- `audiobooker/cli.py` - Command-line interface

### Testing

- Test EPUB parsing with different formats
- Test TXT dialogue detection with various quotation styles
- Test voice assignment and emotion control
- Test review export/import cycle
- Test M4B output with chapter markers

### Testing Audiobooks

When testing with real books:

1. Use EPUB files with proper formatting
2. Verify dialogue detection accuracy
3. Check character attribution
4. Ensure chapter markers align with source
5. Test M4B playback in standard players

### Code Style

- Use type hints for all functions
- Follow PEP 8 conventions
- Keep functions small and focused
- Use descriptive variable names
- Add docstrings for public methods

### Release Process

(For maintainers)

1. Update version in `pyproject.toml`
2. Update CHANGELOG.md
3. Create git tag: `git tag v0.x.x`
4. Push tag: `git push origin v0.x.x`
5. GitHub Actions will publish to PyPI

## Code of Conduct

Please note that this project is released with a [Code of Conduct](CODE_OF_CONDUCT.md). By participating, you agree to abide by its terms.

## Questions?

Open an issue or start a discussion. We're here to help!

## Related Projects

- [voice-soundboard](https://github.com/mcp-tool-shop/voice-soundboard) - AI-powered voice synthesis engine
- [a11y-lint](https://github.com/mcp-tool-shop/a11y-lint) - Accessibility linter for CLI output
- [a11y-assist](https://github.com/mcp-tool-shop/a11y-assist) - Low-vision-first CLI assistant
