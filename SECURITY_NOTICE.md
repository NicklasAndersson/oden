# Security Notice: Secrets in Git History

## Issue
The file `config.ini` containing a real Signal phone number (+46766866383) was committed to the repository in commit `9875aa1` (v0.8.3).

## Current Status
✅ **Fixed for future commits:**
- `config.ini` has been removed from Git tracking
- `config.ini` is now in `.gitignore`
- A template `config.ini.example` is provided with example values

## ⚠️ Important: Git History Still Contains Secrets

**The phone number is still visible in the repository's Git history.** Simply removing the file from tracking does NOT remove it from past commits.

### Why This Matters
Anyone who clones the repository can view the commit history and see the phone number:
```bash
git show 9875aa1:config.ini
```

### Recommended Actions Before Making Repository Public

You have three options:

#### Option 1: Change the Signal Number (Recommended)
- Register a new Signal number for Oden
- Update your local `config.ini` with the new number
- The old number (+46766866383) in the Git history becomes obsolete

#### Option 2: Rewrite Git History (Advanced)
⚠️ **Warning:** This will change commit hashes and break existing clones/forks.

```bash
# Remove config.ini from all history
git filter-branch --force --index-filter \
  "git rm --cached --ignore-unmatch config.ini" \
  --prune-empty --tag-name-filter cat -- --all

# Force push to overwrite remote history
git push origin --force --all
git push origin --force --tags
```

After rewriting history:
- All collaborators must re-clone the repository
- All existing pull requests will be broken
- All release tags will have different commit hashes

#### Option 3: Accept the Risk
If the exposed phone number:
- Is a dedicated number for Oden (not your personal number)
- Can be easily deactivated or changed
- Has not been used for sensitive communications

You may choose to accept the risk and proceed with making the repository public. Just be aware that the number is visible in the history.

## Prevention for the Future
The following measures are now in place:
- ✅ `config.ini` is in `.gitignore`
- ✅ `config.ini.example` template with dummy values
- ✅ Documentation updated to reference the template
- ✅ All scripts already create `config.ini` dynamically if missing

## Additional Security Measures
Consider also protecting:
- Signal-cli data directory (already in `.gitignore` as `signal-cli-0.13.22/`)
- Vault directory with markdown files (already in `.gitignore` as `vault/*`)
- Log files (already in `.gitignore` as `*.log`)
