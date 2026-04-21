Create a pull request for the current branch.

Usage: /pr [base-branch]
Default base branch: main

Follow these steps exactly:

1. **Check for uncommitted changes.** Run `git status --porcelain`. If there is any output, stop and tell the user to commit or stash changes first. Do not proceed.

2. **Get the current branch.** Run `git branch --show-current`. If the branch is `main`, stop and tell the user to create a feature branch first. Do not proceed.

3. **Determine the base branch.** If `$ARGUMENTS` is provided, use it as the base branch. Otherwise default to `main`.

4. **Gather changes.** Run these commands:
   - `git log <base>..HEAD --oneline` to get the commit list
   - `git diff <base>...HEAD --stat` to get the file change summary
   - `git diff <base>...HEAD` to get the full diff
   Read the diff carefully to understand every change.

5. **Categorize changes.** Classify the work into one primary category:
   - `feat:` — new functionality
   - `fix:` — bug fix
   - `docs:` — documentation only
   - `refactor:` — code restructuring without behavior change
   - `chore:` — maintenance, config, dependencies
   - `test:` — test additions or changes

6. **Generate the PR title.** Write a conventional-commit-style title:
   - Format: `<type>: <description>` (e.g., `feat: add PR template and slash command`)
   - Under 72 characters
   - Imperative mood (e.g., "add" not "added" or "adds")
   - Lowercase after the prefix

7. **Generate the PR body.** Use this exact structure:

   ```
   ## Summary
   <1-2 sentences: what changed and why>

   ## Changes
   <Bulleted list of changes, grouped by area if touching multiple areas>

   ## Testing
   <How changes were verified — tests run, manual checks, etc.>
   ```

8. **Create the PR.** Run:
   ```
   gh pr create --base <base> --title "<title>" --body "<body>"
   ```
   Use a HEREDOC for the body to preserve formatting.

9. **Print the result.** Show the PR URL returned by `gh pr create`.

Important:
- Use `gh` CLI, not MCP tools
- Do not push the branch — `gh pr create` handles that automatically
- If `gh pr create` fails because the branch has no upstream, push first with `git push -u origin HEAD`
- Keep the summary concise — the diff speaks for itself
