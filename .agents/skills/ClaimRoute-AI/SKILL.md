```markdown
# ClaimRoute-AI Development Patterns

> Auto-generated skill from repository analysis

## Overview
This skill teaches the core development patterns, coding conventions, and collaborative workflows used in the ClaimRoute-AI Python codebase. You'll learn how to contribute new features, fix bugs, manage provider integrations, and document or test your work according to the repository's established standards. The guide also introduces the main commands and step-by-step approaches for each common workflow.

## Coding Conventions

**File Naming**
- Use `snake_case` for all Python files.
  - Example: `claim_router.py`, `test_local_workspace.py`

**Import Style**
- Use relative imports within modules.
  - Example:
    ```python
    from .utils import validate_claim
    ```

**Export Style**
- Use named exports (explicitly define what is exported).
  - Example:
    ```python
    def route_claim(...):
        ...
    __all__ = ["route_claim"]
    ```

**Commit Messages**
- Follow [Conventional Commits](https://www.conventionalcommits.org/) with these prefixes: `feat`, `docs`, `fix`, `merge`, `test`, `release`.
- Keep commit messages concise (~51 characters on average).
  - Example: `feat: add support for new provider escalation`

## Workflows

### Feature Development with Tests and Docs
**Trigger:** When adding a new feature to the application  
**Command:** `/new-feature`

1. Implement the new feature in one or more files under `app/` or `engine/`.
2. Add or update corresponding tests in the `tests/` directory.
3. Update or add relevant documentation in `docs/` or `README.md`.

**Example:**
```python
# app/new_feature.py
def new_feature_logic(...):
    ...

# tests/test_new_feature.py
def test_new_feature_logic():
    ...
```
Update documentation:
```markdown
# docs/new_feature.md
## New Feature
Description of the new feature...
```

---

### Integration or Merge Feature Branches
**Trigger:** When merging two or more developed features into the main branch  
**Command:** `/merge-feature`

1. Merge code files from both branches (resolve conflicts if any).
2. Merge or reconcile test files to ensure all features are tested.
3. Merge or update documentation to reflect integrated features.

---

### Manual or Integration Testing Documentation Update
**Trigger:** After completing manual or integration testing and needing to document results  
**Command:** `/record-test-results`

1. Perform manual or integration testing as needed.
2. Update or add documentation files (e.g., runbooks, validation evidence) in:
    - `docs/submission/manual_testing_runbook.md`
    - `docs/development/`
    - `docs/submission/`

---

### Add or Update Provider Adapter
**Trigger:** When supporting a new provider or updating provider logic  
**Command:** `/add-provider`

1. Implement provider logic in `engine/escalation/providers/`.
2. Update or add configuration in `configs/`.
3. Update or add client/contract logic in `engine/escalation/`.
4. Add or update tests for the provider in `tests/`.
5. Update `.env.example` if new environment variables are needed.

**Example:**
```python
# engine/escalation/providers/new_provider.py
class NewProviderAdapter:
    ...
```
```yaml
# configs/new_provider.yaml
provider_config:
  ...
```
```python
# tests/test_new_provider.py
def test_new_provider_adapter():
    ...
```

---

### Fix or Enhance Workspace or Intake
**Trigger:** When fixing bugs or enhancing workspace/intake logic  
**Command:** `/fix-workspace`

1. Modify `app/workspace.py` or `app/intake.py` to fix or enhance logic.
2. Update or add tests in:
    - `tests/test_local_workspace.py`
    - `tests/test_local_intake.py`

**Example:**
```python
# app/workspace.py
def improved_workspace_logic(...):
    ...
```
```python
# tests/test_local_workspace.py
def test_improved_workspace_logic():
    ...
```

---

## Testing Patterns

- **Framework:** Not explicitly detected; likely uses `pytest` or standard Python testing.
- **Test File Naming:** Use `test_*.py` for Python tests.
  - Example: `test_local_workspace.py`, `test_new_provider.py`
- **Test Placement:** Place tests in the `tests/` directory, mirroring the structure of the codebase.
- **Test Example:**
    ```python
    # tests/test_sample.py
    def test_sample_function():
        assert sample_function(2) == 4
    ```

## Commands

| Command           | Purpose                                                      |
|-------------------|--------------------------------------------------------------|
| /new-feature      | Start a new feature with tests and documentation             |
| /merge-feature    | Merge/integrate feature branches and update docs/tests        |
| /record-test-results | Document results of manual or integration testing         |
| /add-provider     | Add or update a provider adapter and related configuration   |
| /fix-workspace    | Fix or enhance workspace/intake logic and update tests       |
```
