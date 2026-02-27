# Security Policy

## Supported Versions

| Version | Supported |
|---------|-----------|
| 1.0.x   | Yes       |
| < 1.0   | No        |

## Reporting a Vulnerability

**Email:** 64996768+mcp-tool-shop@users.noreply.github.com

Please include:
- Description of the vulnerability
- Steps to reproduce
- Potential impact

**Response timeline:**
- Acknowledgment: within 48 hours
- Assessment: within 7 days
- Fix (if confirmed): within 30 days

## Scope

Audiobooker is a **CLI tool** for converting EPUB/TXT books into narrated audiobooks.
- **Data accessed:** Reads EPUB/TXT files from local filesystem. Writes audio files (M4B/MP3) and cache manifests to output directories. Optionally uses voice-soundboard for TTS rendering and FFmpeg for audio assembly.
- **Data NOT accessed:** No network requests. No telemetry. No user data storage. No credentials or tokens.
- **Permissions required:** Read access to input book files. Write access to output directories. Optional: FFmpeg binary on PATH for audio assembly.
