# Directory Tree & File Placement Guide

This document serves as the authoritative directory structure reference for AI Agents and developers. All new files, notes, datasets, and artifacts **must** be placed according to the routing rules defined below.

---

## Directory Hierarchy

```
ta-patterns-book/
├── __trash/                      # Discard area for temporary drafts / cleanups
├── .tmp/                         # Transient scratchpads & build cache
├── Core/                         # Core domain logic & Python source package
│   └── ta_patterns_book/         # Main package implementation namespace
├── DOCs/                         # All documentation, artifacts, notes & guides
│   ├── agents/                   # Agent operational docs & reference guides
│   │   └── dir-tree.md           # [This File] Directory tree & file routing guide
│   ├── Artifacts/                # Project management & system artifacts
│   │   ├── ADRs/                 # Architecture Decision Records (ADR-xxx.md)
│   │   ├── BUGs/                 # Bug reports & post-mortems
│   │   └── PLans/                # Task plans & implementation roadmaps
│   ├── GUIDs/                    # User guides, API references & manual docs
│   └── NOTEs/                    # Goal-oriented research & exploration notes
│       ├── GOAL-1/               # Goal 1 research workspace
│       │   ├── outcome.md        # Goal 1 final outcome summary
│       │   └── researches/       # Goal 1 research notes & benchmark logs
│       ├── GOAL-2/               # Goal 2 research workspace
│       └── GOAL-3/               # Goal 3 research workspace
├── Notebooks/                    # Marimo / Jupyter exploratory notebooks
├── Shared/                       # Shared configuration & data assets
│   ├── Data/                     # Shared static data fixtures & memory.duckdb
│   ├── INPs/                     # Raw input datasets (CSVs, Parquets, JSONs)
│   ├── OUTs/                     # Generated output datasets, plots & exported models
│   └── cnf.yaml                  # Project configuration file
├── Tests/                        # Unit, integration & regression test suites
├── Utils/                        # Registered CLI tools & helper utilities
│   ├── duckdb_explorer.py        # Interactive DuckDB explorer tool
│   └── utils.yaml                # Utility tooling specification
├── .python-version               # Python version specification
├── pyproject.toml                # Project package metadata & uv setup
├── GEMINI.md                     # Agent guidelines & context
└── Readme.md                     # Project overview README
```

---

## File Placement & Routing Rules

When creating or saving files, locate the appropriate directory using the table below:

| File Type / Artifact | Target Path | Example File |
| :--- | :--- | :--- |
| **Architecture Decisions** | `DOCs/Artifacts/ADRs/` | `ADR-001-data-pipeline.md` |
| **Bug Reports & Post-mortems** | `DOCs/Artifacts/BUGs/` | `BUG-01-indicator-mismatch.md` |
| **Execution / Task Plans** | `DOCs/Artifacts/PLans/` | `PLAN-goal1-implementation.md` |
| **Goal 1 Research Notes** | `DOCs/NOTEs/GOAL-1/researches/` | `pattern-matching-benchmarks.md` |
| **Goal Outcomes** | `DOCs/NOTEs/GOAL-<N>/outcome.md` | `outcome.md` |
| **User & Setup Guides** | `DOCs/GUIDs/` | `setup-guide.md` |
| **Agent Operational Docs** | `DOCs/agents/` | `dir-tree.md` |
| **Raw Input Datasets** | `Shared/INPs/` | `btc_1h_2023.csv` |
| **Generated Charts & Results** | `Shared/OUTs/` | `head_and_shoulders_plot.png` |
| **Static Reference Data & Memory** | `Shared/Data/` | `memory.duckdb` |
| **Jupyter / Marimo Notebooks** | `Notebooks/` | `01_candlestick_exploration.ipynb` |
| **Unit & Integration Tests** | `Tests/` | `test_head_and_shoulders.py` |
| **Core Library Code** | `Core/ta_patterns_book/` | `pattern_detector.py` |
| **Helper Utilities & Tools** | `Utils/` | `duckdb_explorer.py` |
