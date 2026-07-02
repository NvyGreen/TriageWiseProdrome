# TriageWiseProdrome


## Branching Strategy
**GitHub Flow**
- `main` always stays working
- Make a branch per requirement/task: `feature/scoring-engine`, `fix/esi-refinement`
- Open a PR to merge back
- Protect `main`: no merge unless CI passes (Pytest green + lint clean)


## Commit Message Format
    type(scope): short summary

    optional body explaining why

- **Types:** feat, fix, test, docs, refactor, chore
- **Subject:** imperative mood, ~50 chars, lowercase, no trailing period
- **Body:** only when the *why* isn't obvious; may reference requirement IDs

Ex: `feat(scoring): add ESI-3 resource refinement`