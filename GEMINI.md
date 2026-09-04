# GEMINI.md - Project Guidelines & Context

## Package Manager & Tooling
- **Default Package Manager:** `uv` is used as the default package/environment manager for this project (`uv run`, `uv add`, `uv sync`, etc.).
- **External CLI Tools Reference:** Always read [`Utils/tools-info.md`](file:///home/avijit/workSpace/Code/ta-patterns-book/Utils/tools-info.md) to discover, inspect, and understand the list of available project CLI tools (e.g. `DuckDB Explorer CLI` and `Tradebook & SmartGrid CLI`), their flag contracts, and operational guidelines.

## Directory Structure & File Placement
- Refer to [`DOCs/agents/dir-tree.md`](file:///home/avijit/workSpace/Code/ta-patterns-book/DOCs/agents/dir-tree.md) for the authoritative project directory tree, path descriptions, and file routing rules.
- Project path mappings are also configured in [`Shared/cnf.yaml`](file:///home/avijit/workSpace/Code/ta-patterns-book/Shared/cnf.yaml).
- Always place newly created files, datasets, notes, plans, or artifacts into their designated paths according to [`dir-tree.md`](file:///home/avijit/workSpace/Code/ta-patterns-book/DOCs/agents/dir-tree.md).
