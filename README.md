# pr-status: command line pivot reporting of development meta-data

This is a command-line based tool, used to produce pivot reports based on data from Github, YouTrack and Timely.


## Installation

Install and set up dependencies:

```
$ brew install uv rlwrap gh
$ gh auth login
```

Create a minimal config file:

```
$ mkdir -p ~/.config/pr-status/
$ cp sample.config ~/.config/pr-status/config
```

Before running any report the config file needs to be edited in order to add a YouTrack authentication token.

- from YouTrack, click your avatar (top-right) → Profile.
- open the Account Security tab.
- under Authorization / Tokens, click "New token…" (sometimes labelled "Create new token").
- give it a name and, for scope, grant it access to YouTrack (read access to issues is sufficient — the tool only reads the issue State custom field via `GET /api/issues/{id}`).
- copy the token immediately (it's shown once) and paste it into the config file as `youtrack-token:XXXXXXX`

If `timely` reports are run, or regular reports using the `workdays` column, then Timely authentication details also need to be added to the config. Note that such reports can currently only be run by Timely users with admin access.

- account id — this is visible in the Timely URL after logging in, e.g. `https://app.timelyapp.com/<account-id>/...`
- access token — from Timely's API/developer settings. Create an application in order to obtain a token.
- paste these into the config file as `timely-account-id:XXXXXXX`, `timely-access-token:XXXXXX`

Finally, in order to use some of the report aliases in the sample config, e.g. `mine` or `to-review`, add your own name to the config:

- `this-author:<your name>`


## Running

To launch the repl itself, add this directory to `$PATH` and execute:

```
$ pr-status.sh
```

From here run one of the aliased reports, for example:

```
> all
```

If installation was done correctly, then this will show a pivot report of all outstanding PRs.

The main usage of this tool is to run such pivot reports. In general reports are run with the command:

```
> report <report columns> <sort options> <filters> <other options>
```


## Report columns

These should be written as a comma separated list of names or aliases. The available columns are:

| Name | Alias | Notes |
|------|-------|-------|
| pull-request | PR | PR number |
| title | T | |
| author | A | |
| loc | LOC | Scala lines added/removed |
| num-comments | NC | Comments since mark (or all if no mark) |
| creation-date | CD | Date PR was opened |
| last-comment-time | LCT | Time of most recent comment |
| my-last-comment-time | MCT | Time of your most recent comment |
| mark | MK | Your mark timestamp (see [Marking](#marking)) |
| comment | C | One row per comment; shows comment body |
| comment-time | CT | Timestamp of comment (use with C or CA) |
| comment-author | CA | Author of comment (use with C or CT) |
| reviewers | R | Reviewer names; `R=none` matches PRs with no reviewers. Names are shown in green/orange/red if the reviewer has approved/commented on/rejected the PR |
| review-outstanding | RO | Reviewers who have not yet approved or requested changes; `RO=none` matches PRs with none outstanding |
| unresolved (all) | UC | Unresolved review threads (all authors) |
| unresolved (human) | UH | Unresolved review threads (human authors only) |
| unresolved (ai) | UA | Unresolved review threads (AI authors only) |
| last-activity | LA | Days since most recent comment or review activity |
| age | AG | Days since the PR was opened |
| draft | D | Whether the PR is a draft (true/false) |
| branch | B | The PR's head (source) branch name |
| build | CI | CI state of the last build on the PR's head commit: `✓` full build passing, `✗` any build failing, `…` full build running, `_` no build or a passing/running partial build. A full build is one with 8 or more checks; a partial build (just scalafmt + CodeRabbit) is only surfaced when it fails |
| valid | V | Whether or not the PR is in a valid state (see [PR validity](#pr-validity)) |
| youtrack-ticket | YT | YouTrack ticket ID (e.g. PROJ-123); `none` if absent |
| youtrack-project | YP | YouTrack project name (e.g. PROJ); `none` if absent |
| youtrack-id | YI | YouTrack numeric ID (e.g. 123); `none` if absent |
| youtrack-state | YS | YouTrack ticket state |
| workdays | WD | Total workdays logged against the YT ticket in Timely (hours/8); blank if no YT ticket. Requires Timely admin access |

Unambiguous abbreviations of column names can be used, e.g. `last` for `last-activity`.

Note that if a column name is used, or if an alias is followed by an underscore, then long column names will be shown in the report heading, otherwise the alias is shown.


## Sort options

```
--sort col,col,...
```

- Sorts ascending by default: alphabetical for text, smallest-first for numbers, oldest-first for dates.
- Append `:R` to reverse a column's sort order, e.g. `--sort NC:R,author` sorts by NC descending, then author ascending.


## Filters

Any number of filters can be added to a report, each takes the form `--filter <predicate>`, where the predicate is one of:

**value predicates**

```
COL=v1,v2,..,vn    keeps only rows where COL's value is one of v1, ..., vn
COL!=v1,v2,..,vn   keeps only rows where COL's value is none of v1, ..., vn
```

**reviewer predicates**

```
R=v1,v2,..,vn   keeps PRs where at least one requested reviewer matches any of the values
R=none          keeps PRs with no requested reviewers at all
```

These can be combined: `R=none,bob` keeps PRs with no reviewers or where bob is a reviewer.

**timestamp predicates**

Boolean comparisons involving timestamp columns are supported. The following are all valid filters:

```
LCT > MCT         true if a comment was made after the user's last comment
LCT > yesterday   true if a comment was made after the start of day, yesterday
wed < LCT         true if a comment was made after the start of the previous wednesday
MCT = LCT         true if the last comment was made at exactly the same time as the user's last
```

- Blank timestamps, e.g. `LCT` when the user has never made a comment, are treated as epoch (1970-01-01).
- Day names resolve to the most recent occurrence strictly before today.


## Other report options

| Option | Description |
|--------|-------------|
| `--include-ai` | Include AI comments and reviewers (excluded by default) |
| `--include-drafts` | Include draft PRs (excluded by default) |
| `--include-pre-mark-commits` | Include comments before the mark timestamp (see [Marking](#marking)) |


## Marking

Marking simply records a timestamp against a specific PR, via:

```
> m, mark <PR id>
```

This allows timestamp predicates such as `LCT > MK` to be used, which could filter those PRs whose last comment was after the timestamp. The expected use case is that a developer feels they are up to date with some PR as of some timestamp, and wants to know if anything has happened to the PR since that point.

To remove the timestamp, enter:

```
> unmark <PR id>
```


## Focussing

```
> f, focus <PR id>
```

This in effect adds `--filter PR=<focused PR>` to subsequent reports. This can be useful if reports are displaying information on individual comments via any of the comment fields, as otherwise the report might be extremely long.

To remove the focus, enter:

```
> unfocus
```


## PR validity

A PR is invalid if any of the following are true:

- It has unresolved AI comments
- Its associated YouTrack ticket (if specified in the title) is not in 'review' state
- It has no reviewers


## Aliases

Command aliases can be set up in the config file. The sample config already has some examples. Aliases are defined as:

```
alias:name:command
```

The command will typically be a report.


## Other commands

| Command | Description |
|---------|-------------|
| `alias` | Displays the list of aliased reports |
| `rl`, `reload` | Reloads the config file |
| `quit`, `exit` | Exits the application |
| `rtc` | Refresh the Timely event cache (see [Timely reports](#timely-reports)) |


## Timely reports

These reports use the Timely API, which is only available to admins. Reports are run with:

```
> t, timely <columns> <month filter>
```

The available columns are:

| Name | Alias | Notes |
|------|-------|-------|
| developer | D, DEV | Person who logged the time |
| project | P | Timely project name |
| title | T | Log entry description (truncated to 50 chars) |
| hours | H | Hours logged (summed across matching entries) |
| workdays | W, WD | Hours divided by 8 |
| month | M | Month of the entry, e.g. Mar-26 |
| day | Y | Date of the entry, e.g. 2026-03-15 |
| youtrack-ticket | YT | YouTrack ticket ID extracted from title (e.g. PROJ-123); `none` if absent |
| youtrack-project | YP | YouTrack project part (e.g. PROJ); `none` if absent |
| youtrack-id | YI | YouTrack numeric part (e.g. 123); `none` if absent |

Rows with identical values across all displayed columns are merged and their hours summed. For example the following shows one row per developer + project:

```
> t developer,project,hours
```

The optional month filter can take the following:

| Filter | Meaning |
|--------|---------|
| `--filter month=mar-26` | Only March 2026 |
| `--filter month=mar` | Most recent March |
| `--filter month=1` | Current month only |
| `--filter month=3` | Current month plus 2 previous |
| (no month filter) | All cached data from 2025-01-01 onwards |

Projects listed in `timely-ignore-project` in the config are always excluded.

Timely events are cached locally. The cache is refreshed automatically when a timely report (or the `workdays` column) is run, but it can also be refreshed manually with the `rtc` command:

| Command | Description |
|---------|-------------|
| `rtc` | Refresh the last 7 days (default) |
| `rtc --num-days=N` | Refresh the last N days |
| `rtc --month=mmm-yy` | Refresh a single month, e.g. `rtc --month=mar-26` |
| `rtc --all` | Refresh everything from 2025-01-01 onwards |
