# Contributing to Context Memory + LLM Gateway

Thank you for your interest in contributing to the Context Memory + LLM Gateway project! This document provides guidelines for contributing to the project.

## Development Setup

### Prerequisites

- Docker and Docker Compose
- Git
- OpenRouter API key ([get one here](https://openrouter.ai/keys))

### Local Development

1. **Fork and clone the repository**
   ```bash
   git clone https://github.com/your-username/context-memory-gateway.git
   cd context-memory-gateway
   ```

2. **Set up the development environment**
   ```bash
   ./scripts/dev.sh setup
   ```

3. **Configure environment variables**
   ```bash
   cp .env.example .env
   # Edit .env with your OpenRouter API key and other settings
   ```

4. **Start development services**
   ```bash
   ./scripts/dev.sh start
   ```

5. **Run tests**
   ```bash
   ./scripts/dev.sh test
   ```

## Development Workflow

### 1. Create a Feature Branch

```bash
git checkout -b feature/your-feature-name
# or
git checkout -b bugfix/issue-description
```

### 2. Make Your Changes

- Follow the existing code style and conventions
- Add tests for new functionality
- Update documentation as needed
- Ensure all tests pass

### 3. Run Quality Checks

```bash
# Run tests
./scripts/dev.sh test

# Run linting (if available)
# Add linting commands as needed

# Check code formatting
# Add formatting commands as needed
```

### 4. Commit Your Changes

```bash
git add .
git commit -m "feat: Add your feature description

- What was changed
- Why it was changed
- Any breaking changes
"
```

Use conventional commit format:
- `feat:` - New feature
- `fix:` - Bug fix
- `docs:` - Documentation changes
- `style:` - Code style changes
- `refactor:` - Code refactoring
- `test:` - Test additions
- `chore:` - Maintenance tasks

### 5. Push and Create Pull Request

```bash
git push origin feature/your-feature-name
```

Then create a pull request on GitHub.

## Code Guidelines

### Python Style

- Follow PEP 8 style guidelines
- Use type hints for function parameters and return types
- Write docstrings for all public functions and classes
- Keep functions small and focused on single responsibility
- Use meaningful variable and function names

### Async/Await Patterns

- Use async/await for I/O operations
- Avoid mixing sync and async code unnecessarily
- Use `asyncio.gather()` for concurrent async operations
- Add proper error handling for async functions

### Database Operations

- Use SQLAlchemy async patterns consistently
- Add proper indexes for frequently queried columns
- Use transactions for related operations
- Avoid N+1 queries by using proper joins and select_related

### API Design

- Follow RESTful principles
- Use consistent HTTP status codes
- Provide meaningful error messages
- Document all endpoints with OpenAPI specs
- Version API endpoints appropriately

### Testing

- Write unit tests for business logic
- Write integration tests for API endpoints
- Write end-to-end tests for critical workflows
- Mock external dependencies in unit tests
- Aim for high test coverage

### Error Handling

- Use custom exceptions for business logic errors
- Log errors with appropriate context
- Return consistent error responses
- Don't expose internal errors to clients in production

### Security

- Validate all input data
- Use parameterized queries to prevent SQL injection
- Hash sensitive data appropriately
- Follow principle of least privilege
- Keep dependencies updated

## Project Structure

```
server/
├── app/
│   ├── api/          # API endpoints
│   ├── core/         # Core functionality (config, security, etc.)
│   ├── db/           # Database models and session management
│   ├── services/     # Business logic services
│   └── workers/      # Background task workers
├── tests/            # Test files
└── alembic/          # Database migrations
```

## Database Migrations

When making database changes:

1. Create a migration:
   ```bash
   ./scripts/dev.sh create-migration "Add new field to user model"
   ```

2. Review the generated migration file
3. Apply migrations:
   ```bash
   ./scripts/dev.sh migrate
   ```

## Documentation

- Update README.md for significant changes
- Add docstrings to new functions
- Update API documentation
- Add examples for new features

## Pull Request Process

1. **Title**: Use descriptive, concise title
2. **Description**: Explain what was changed and why
3. **Tests**: Ensure all tests pass
4. **Review**: Request review from maintainers
5. **Merge**: Squash and merge approved changes

## Community

- Be respectful and inclusive
- Help others learn and grow
- Follow the code of conduct
- Participate in discussions

## Questions?

If you have questions about contributing, please:

1. Check the existing documentation
2. Search existing issues and discussions
3. Create a new issue with your question
4. Reach out to maintainers

Thank you for contributing! 🎉