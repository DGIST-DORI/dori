# Contributing to DORI

Thanks for contributing to DORI!  
This guide explains the minimum workflow for code, docs, and issue contributions.

## 1) Before You Start

- Project overview: [`README.md`](./README.md)
- Security reporting: [`SECURITY.md`](./SECURITY.md)
- Community guidelines: [`CODE_OF_CONDUCT.md`](./CODE_OF_CONDUCT.md)
- Documentation index: [`docs/README.md`](./docs/README.md)

## 2) What Contributions Are Welcome?

- Bug reports with reproducible steps
- ROS2 node improvements
- Dashboard (web) improvements
- Documentation updates (`docs/`)
- Tooling improvements (`tools/`)

## 3) Repository Structure (Quick Map)

```text
.
├─ ros2_ws/src/            # ROS2 packages (dori_bringup, perception, stt, tts, navigation, ...)
├─ web/                    # Dashboard frontend (Vite/React)
├─ docs/
│  ├─ user/                # User docs (manual, config)
│  └─ dev/                 # Developer docs (architecture, topics, web-style, etc.)
├─ tools/                  # Parser/crawler/util scripts
├─ data/                   # Campus data (raw/processed/indexed)
└─ config/                 # Shared config files (e.g., ROS2 topic config)
```

### Where should I read/write docs?

- End-user usage/configuration → [`docs/user/`](docs/user/)
- Developer architecture/topics/style → [`docs/dev/`](docs/dev/)
- Entry point for all docs → [`docs/README.md`](docs/README.md)

## 4) General Development Rules

- All logger messages and code comments must be written in English.
- Keep changes small and focused.
- Never commit secrets, API keys, or machine-specific hardcoded paths.
- If behavior changes, update related documentation in the same PR.

## 5) Branch / Commit / PR Workflow

1. Create a branch from your issue/task
   - Example: `feature/perception-hand-landmark-fix`
2. Use clear commit messages that explain intent
   - Example: `fix(perception): handle missing hand_landmarker model path`
3. Include the following in your PR description:
   - Background
   - What changed
   - How to test
   - Scope/impact
   - Screenshots or short video for UI changes

## 6) Testing & Validation

Please validate what is relevant to your change:
- ROS2 changes: build and launch affected packages
- Web changes: build frontend and verify affected panels
- Docs changes: check broken links and file paths

## 7) Documentation Contribution Guidelines

When contributing docs:
- Start from [`docs/README.md`](docs/README.md)
- Put user-facing content in [`docs/user/`](docs/user/)
- Put engineering/architecture content in [`docs/dev/`](docs/dev/)
- If you add a new document, update related index links in the same PR
