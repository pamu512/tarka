$ErrorActionPreference = "Stop"

$repoPath = "C:\Users\Pamu\Documents\fraud-stack"
$targetCommit = "8f6459e"
$remote = "origin"
$branch = "master"

Set-Location $repoPath

# Ensure the target commit exists locally before pushing.
git rev-parse --verify "$targetCommit^{commit}" | Out-Null

# Ensure the current branch contains the target commit.
$containsCommit = git branch --contains $targetCommit | Out-String
if ($containsCommit -notmatch "\b$branch\b") {
    throw "Branch '$branch' does not contain commit $targetCommit."
}

# Push the branch that includes the target commit.
git push $remote $branch
