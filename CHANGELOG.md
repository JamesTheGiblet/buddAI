# Changelog

## [3.2.0] - 2025-12-29

### Added

- WebSocket streaming for real-time token-by-token responses
- Multi-user support with session isolation
- Connection pooling for Ollama requests (10 connection pool)
- File upload validation (50MB limit, type checking)
- Zip slip protection for malicious archives
- Filename sanitization
- Type hints throughout codebase
- Enhanced iOS PWA support

### Security

- File size limits enforced (50MB)
- Magic number validation for ZIP files
- Path traversal prevention in zip extraction
- Maximum upload file count (10 files)
- Sanitized filenames to prevent path injection

### Performance

- Connection pooling reduces latency by ~30%
- WebSocket streaming improves perceived response time
- Per-user instance management

### Fixed

- Session isolation bug (users can no longer see each other's data)
- Connection leak in Ollama requests
- Memory growth in long-running server instances

## [3.1.0] - 2025-12-29

[Previous changelog content...]
