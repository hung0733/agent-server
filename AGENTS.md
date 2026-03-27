# AGENTS.MD

## Language and Framework Requirements
- **Primary Language**: Python 3.12
- **Virtual Environment**: Use `.venv` directory with activation via `source .venv/bin/activate`
- **Dependency Management**: Standard Python practices using `requirements.txt`, `pyproject.toml` or `setup.py` (to be created as needed)
- **Standard Library**: Use whenever possible; follow Python Enhancement Proposals (PEPs) where relevant

## Assistant Communication Language
- Respond to the user in Hong Kong Traditional Chinese (`zh-HK`) by default.
- Switch to another language only when the user explicitly requests it.

## Local Development Setup
- **Environment**: Python 3.12 environment located at `./.venv`
- **Dependencies**: Use `pip` within activated environment to manage packages
- **Configuration**: Standard Python packaging configuration files (to be added to the repository)

## Build Commands
- **Basic Build**: `python -m build` (after creating appropriate build configuration files like pyproject.toml)
- **Virtual Environment**: `python -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt` (requirements.txt to be created)
- **Install Dependencies**: `pip install -e .[dev]` (when setup.py/pyproject.toml includes dev extras)

## Test Commands
- **Single Test File**: `python -m pytest path/to/test_file.py -v`
- **Specific Test Method**: `python -m pytest path/to/test_file.py::TestClass::test_method -v`
- **Directory Tests**: `python -m pytest tests/ -v`
- **Unit Tests Only**: `python -m pytest tests/unit/ -v`
- **Integration Tests Only**: `python -m pytest tests/integration/ -v`
- **Coverage Report**: `python -m pytest --cov=src/ tests/ --cov-report=html` (ad-hoc coverage when tools are configured)

## Code Quality / Linting Commands
- **Linting**: `flake8 src/ --show-source` (when flake8 is configured)
- **Formatting**: `black src/ tests/` (when black is configured)
- **Import sorting**: `isort src/ tests/` (when isort is configured)
- **Static analysis**: `mypy src/ --strict` (when mypy is configured)

## Code Style Guidelines

### General Python Style:
- **Formatting**: Follow PEP 8 guidelines
- **Line Length**: 88-100 characters maximum
- **Documentation**: Use Google-style docstrings or NumPy docstring format for detailed API documentation
- **Imports**: Group standard library, third-party, and local modules; use absolute imports where practical
- **Naming**: Use descriptive names; prefix private attributes/functions with underscore
- **Comments**: Explain "why" not "what"; document complex logic thoroughly

### Imports Order:
1. Standard library imports
2. Third-party imports
3. Local application/library specific imports
Use blank lines to separate these groups.

### Error Handling:
- Use specific exception types rather than bare `except:` clauses
- Provide meaningful exceptions with helpful error messages
- Implement consistent error logging and reporting patterns
- Distinguish between user-caused errors and system errors in error handling

### Async/Await:
- Use async with caution; apply only when genuine parallelism benefits exist
- Manage async context properly with appropriate error handling
- Consider alternatives to async if complexity outweighs performance gains
- Document why async was preferred for complex operations

### Testing Style:
- Unit tests should be fast, focused on specific method/class behavior
- Integration tests to verify interaction between modules/components
- Use pytest fixtures for reusable test data/resources
- Apply AAA (Arrange, Act, Assert) pattern in test functions
- Maintain clear distinction between test methods (avoid shared mutable state)

## Specific Architectural Guidance for Agent Server:
- **Modularity**: Create well-isolated components with clear interfaces
- **Extensibility**: Design with plugin/module capability in mind where appropriate
- **API Consistency**: Maintain uniform patterns across endpoint handlers
- **Logging**: Structure logs for monitoring, debugging and observability
- **Security**: Validate inputs, manage authentication/authorization appropriately
- **Performance**: Profile during development to identify bottlenecks early

## Commit and Code Submission Standards
- **Commit Messages**: Use imperative tone: "Add feature", "Fix bug", "Refactor component"
- **Breaking Changes**: Tag clearly as "BREAKING:" with migration notes  
- **PR Guidelines**: Each PR should address one issue; include tests for functionality
- **Reviews**: Address feedback promptly; ensure changes pass all checks before merge
- **Documentation**: Update relevant docs alongside code changes

## Configuration and Deployment:
- **Settings**: Use environment variables or configuration files with default sensible values and override support
- **Environment separation**: Support development/staging/production configurations
- **Dependency specification**: Pin versions in deployment but allow flexibility in development where feasible

## Additional Notes:
- Follow Hong Kong style Traditional Chinese in comments/documentation where required
- Respect cultural norms and legal requirements if server operates internationally
- Use the virtual environment when running commands: `source .venv/bin/activate`
- Keep dependencies minimal and justified; regularly audit for security updates
- Add new tool recommendations and configurations as they become relevant to the project

## Internationalization (i18n) Requirements:
- All user-facing strings and system messages must be internationalized using i18n format
- Default language locale is `zh-HK` (Hong Kong Traditional Chinese) 
- Language/locale can be configured via environment variables through `.env` file
- All translatable content must be stored in appropriate language resource files
- Use appropriate i18n libraries such as `gettext` or similar frameworks

## Environment Variables Handling: 
- Load environment variables using proper configuration management tools
- When loading environment variables, DO NOT provide default values
- If environment variables are missing, raise/throw appropriate exceptions
- Ensure environment validation at application startup to prevent runtime issues
- Document all required environment variables for each deployment environment
