# GitHub wiki mirror

Markdown here is the **source of truth** for [github.com/pamu512/tarka/wiki](https://github.com/pamu512/tarka/wiki). The live wiki is a separate git repo; it does not auto-sync from `master`.

## Publish to GitHub wiki

From repo root (requires push access to `pamu512/tarka.wiki`):

```bash
./scripts/docs/sync-github-wiki.sh
```

Or manually:

```bash
git clone https://github.com/pamu512/tarka.wiki.git /tmp/tarka.wiki
for f in docs/wiki/*.md; do
  base="$(basename "$f")"
  [[ "$base" == "README.md" ]] && continue
  cp "$f" "/tmp/tarka.wiki/$base"
done
cd /tmp/tarka.wiki
git add -A
git status
git commit -m "docs: sync wiki from repo $(date -u +%Y-%m-%d)"
git push origin master
```

GitHub wiki uses `master` as default branch for the wiki repo.

## When to sync

After changing operator docs, compose profiles, or product surfaces referenced from wiki pages. Prefer linking to **`docs/INDEX.md`** and **`docs/docs/guides/`** in the main repo for depth; keep wiki pages as short entry points.

If wiki and [`docs/INDEX.md`](../INDEX.md) disagree, **trust the hub and the code**.
