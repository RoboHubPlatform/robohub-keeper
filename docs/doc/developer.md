# The Developer section

The **Developer** section (`/developer`) shows and changes the requirements and
architecture decisions of the whole RoboHub workspace — every repository of the
family — and commits what it changed. It is the keeper's face of the
requirements process ({ref}`process/index`), and everything it reads or writes
goes through the `rho req` tool (the rho-req component, 0.3.0 or later): the
keeper never writes a requirements file or an ADR itself, so a change made here
is exactly the change `rho req` makes from a terminal, with the file's comments,
blank lines, quoting and key order kept.

## Pages

| Page | What it is for |
| --- | --- |
| **Requirements** `/developer/requirements` | Every requirement of the workspace, filtered by repository, level, status, tag and text; each row leads to its page. A maintainer has **New requirement** (`/developer/new`). |
| A requirement `/developer/requirements/<ID>` | Its statement and rationale, status, level, verification, file and line, owner, tags; what it satisfies (up the chain) and what satisfies it (down the tree), as links; its decisions; the code tagged `@req` and the tests tagged `@verifies`, with each test's latest result and the requirement's evidence. A maintainer has **Edit** and **Set status**. |
| **Architecture decisions** `/developer/adr` | The decisions of each repository with their status, date and requirements; a maintainer writes a new one from the repository's `0000-template.md`. |
| A decision `/developer/adr/<repository>/<ADR-NNNN>` | The decision, rendered, with its requirements and what it supersedes or is superseded by. A maintainer sets its status (proposed, accepted, rejected) or supersedes it. |
| **Traceability** `/developer/trace` | The matrix — each requirement against its children, decisions, code and tests, with its evidence — the gaps, and the release gate of `rho req trace --release`: releasable, or how many gaps block a release. |
| **Check** `/developer/check` | `rho req check --workspace`: every error and warning with its file and line. |
| **Export** `/developer/export` | `rho req render --workspace`, shown rendered and offered as Markdown (`/developer/export/requirements.md`). |
| **Commit** `/developer/commit` | Per repository, what the section changed, and a commit of exactly those files. |

| Action | `rho req` |
| --- | --- |
| New requirement | `rho req new --dir <repository> --level … --title … --statement …` |
| Edit | `rho req edit <ID> --set … --add … --remove …`, only the fields the form changed; a changed statement sends an approved requirement back to proposed unless **Keep the status** is ticked (`--keep-status`) |
| Set status | `rho req set-status <ID> <STATUS>`, without `--force`: the lifecycle decides |
| New decision | `rho req adr new --dir <repository> --title … --requirements …` |
| Decision status | `rho req adr set-status <ADR> <STATUS>` |
| Supersede | `rho req adr supersede <OLD> <NEW>` |

When the tool refuses a change — an unknown id, a `satisfies` to a level that is
not higher, a status the lifecycle does not allow — its own words are shown on
the form, with what was typed, and nothing is written.

The keeper reads the tool's answers as `--tsv` records (one per line, the
record's kind first), so a line of standard error in the same output is never
taken for data.

## The workspace

The workspace is the folder that holds the family's repositories:
`ROBOHUB_WORKSPACE` (or `RHO_WORKSPACE`) when it is set, else the folder the
orchestrator is in. `rho req` is started from the orchestrator, the root of the
family, with `ROBOHUB_WORKSPACE` set to that folder, and finds the other
repositories by their `requirements: { parent }` in module.yml. A repository a
request names is looked up among the ones `rho req` found, and its folder is the
one `rho req` gave; a requirement id must be `PREFIX-NNNN` and a decision
`ADR-NNNN` before either reaches the tool. Nothing a request carries becomes a
path.

When `rho req` is not installed the section says so and how to install it:

```sh
rho module install rho-req
# or, from a checkout of the Rho toolchain
rho module publish modules/components/rho-req --local
```

## Who may do what

Reading every page of the section needs a signed-in person. Every change — a new
requirement, an edit, a status, a decision, a commit — needs a **maintainer**, is
a POST with the form's CSRF token, and is refused with 403 otherwise; a person
who is not a maintainer sees no edit control.

A maintainer is:

- an **admin** (and a ticket that carries every scope, `*`), or
- a person granted **`keeper:maintainer`** — the **Maintainer** box under
  *Developer* in the person's inspector on **Users & access**.

The grant is read from the people store on every request, so taking it away
takes effect at once. A viewer or operator made a maintainer signs in again: a
session made of read-only scopes may not POST at all, and the session records
`keeper:maintainer` beside the role's scope at sign-in.

**Approvals.** Moving a requirement to approved, implemented or verified, and
accepting a decision, are approvals. In the keeper a maintainer may make them;
what makes them stand is CI: `rho req check --base` accepts an approval only from
a commit whose author is in the `MAINTAINERS.yml` that governs the repository.
The keeper does not tie its people to MAINTAINERS.yml — a keeper account is not a
git identity — but when the git identity a repository commits with (its
`user.name` and `user.email`) is not in MAINTAINERS.yml, the section says so
after an approval and on the Commit page, because CI will refuse that commit.

## Committing

The Commit page lists, for each repository, the files that differ under
`docs/requirements/` and `docs/architecture/` — the only two directories
`rho req` writes. The section never changes module.yml, so a commit never
carries it, nor any other file. **Commit** asks for a confirmation, and refuses
when the files are no longer the ones the page showed.

A commit is never pushed. Where it goes depends on the branch the repository is
on:

- **Another branch than the default one**: an ordinary commit on that branch,
  `git commit -- <the listed files>` (a new file is added first). What else was
  staged stays staged.
- **The default branch** (what `origin/HEAD` names, else `main` or `master`), or
  a detached HEAD: the working copy and the index are not touched. The commit is
  built on a temporary index — `git read-tree`, `git update-index --add --remove`
  of the listed files, `git write-tree`, `git commit-tree` — and the branch
  `requirements/<yyyy-mm-dd>` is created or advanced to it with `git update-ref`.
  The page says so: *committed to requirements/2026-11-19; the working copy is
  unchanged; push or merge it yourself*. A later commit the same day advances the
  same branch; a branch of that name that no longer contains HEAD is left alone
  and the next name (`-2`, `-3` …) is used. What is already on the day's branch is
  not offered again.

The author is the git identity configured in that repository. The message's
subject names the requirements and decisions the commit changes —
`requirements: GW-0004, GW-0001, ADR-0003` — and its body lists the files.
