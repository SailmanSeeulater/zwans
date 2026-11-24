import type { Metadata } from "next";

export const metadata: Metadata = { title: "Wtf is Zwans" };

/** What each part of Zwans is for, in a sentence or two. */
const PARTS: { name: string; about: string }[] = [
  {
    name: "An agent loop",
    about:
      "Calls the model, runs the tools it asks for and sends back the results, until the task is done. Built from scratch, no agent framework.",
  },
  {
    name: "Three ways in",
    about:
      "A terminal chat (zwans), one-shot tasks (zwans run), and this web UI, which zwans serve starts. There is also a macOS desktop app.",
  },
  {
    name: "Any model",
    about:
      "Claude by default (Opus 5.5 at medium effort), or any OpenAI-compatible API: OpenRouter, rented GPUs, or local models through Ollama. Switch in the middle of a chat with /model.",
  },
  {
    name: "Permissions",
    about:
      "Each tool call runs, asks you first, or is refused. In read-only mode nothing changes; in ask mode (the default) edits and commands wait for a yes; in auto mode only network commands, and ones Zwans can't classify, do. Before an edit, you see its diff.",
  },
  {
    name: "Sandboxes",
    about:
      "Commands run on your machine, in a Docker container whose only network is a proxy for package indexes and GitHub, in a jail on Linux, or under Seatbelt on macOS.",
  },
  {
    name: "Checkpoints",
    about:
      "Before each turn, the workspace is snapshotted to a git repository of its own, so /undo and /rewind put the files back. The project's .git is never touched.",
  },
  {
    name: "Sessions that last",
    about:
      "Saved, resumed and rewound by turn. A long conversation is compacted into handoff notes, and prompts are cached so later turns cost less.",
  },
  {
    name: "Extensions",
    about:
      "Hooks run your scripts before and after tool calls. Skills are loadable instructions, MCP servers add tools, and subagents take on part of a task in a fresh conversation. Instructions come from ZWANS.md, CLAUDE.md or AGENTS.md.",
  },
  {
    name: "Rooms",
    about:
      "Several agents, each on its own model, talk about a topic one at a time. Mention @Name to pick who goes next. Rooms in the sidebar sets one up.",
  },
  {
    name: "Evals",
    about:
      "Real coding tasks with hidden tests, in starter, hard and expert tiers. Zwans is measured against Claude Code and Codex on pass rate and cost, and the leaderboard ranks them.",
  },
];

/** The 49 built-in tools the model can call, grouped by what they're for. */
const TOOLS: { group: string; tools: [string, string][] }[] = [
  {
    group: "Files",
    tools: [
      ["Read", "A file with line numbers, or an image to look at"],
      ["Video", "A video's frames on one image, and its transcript"],
      ["NotebookEdit", "Replace, insert or delete a notebook cell"],
      ["Logs", "A long log grouped into its kinds of line, errors first"],
      ["Database", "Tables and read-only SQL, for SQLite and Postgres"],
      ["Data", "A CSV, JSON, Excel or Parquet file summarized: types, empties, ranges, per-group sums and means"],
      ["Chart", "Numbers drawn as a chart in the conversation, with a table of them"],
      ["ImageDiff", "Two images compared, with what changed outlined"],
      ["Archive", "Extract a zip or tar archive safely (Read lists one)"],
      ["Write", "Create a file, or replace all of one"],
      ["Edit", "Replace exact text in a file"],
      ["MultiEdit", "Several replacements at once, all made or none"],
      ["Glob", "Find files by name pattern"],
      ["Grep", "Search file contents with a regular expression"],
    ],
  },
  {
    group: "Understanding code",
    tools: [
      ["Outline", "What a file or folder defines, without the bodies"],
      ["References", "Every place a name is used"],
      ["Rename", "Rename an identifier everywhere it's used"],
      ["Diagnostics", "Run the project's linters and type checkers"],
      ["Docs", "Signature and docs of an installed Python module or function"],
      ["Imports", "The import graph: cycles, unused modules, what uses what"],
      ["OpenAPI", "An API's endpoints and their shapes, from its spec"],
      ["History", "Why code is the way it is: blame, line history and commit messages"],
    ],
  },
  {
    group: "Running things",
    tools: [
      ["Bash", "Run a shell command in the workspace"],
      ["BashOutput", "Read what a background command has printed"],
      ["KillBash", "Stop a background command"],
      ["Python", "A Python session that keeps its state between calls"],
      ["RunTests", "Run the project's tests and report the failures, and coverage"],
      ["Profile", "Run Python under cProfile and list where the time went"],
      ["Benchmark", "Time a command over many runs, and compare two, or before and after"],
      ["Bisect", "Find the commit that broke something by testing across history"],
      ["ShowChanges", "Everything changed since the session began, as a diff"],
    ],
  },
  {
    group: "This machine and CI",
    tools: [
      ["Env", "Which environment variables the project needs, and which are missing"],
      ["Ports", "What is listening on which port, and which of it is this project's"],
      ["Containers", "Docker containers' state, health and logs"],
      ["CI", "Why a GitHub Actions run failed, from its failed steps' logs"],
      ["Cron", "A cron expression in words, and its next run times"],
      ["Notify", "A desktop notification when a long task finishes"],
    ],
  },
  {
    group: "Planning and help",
    tools: [
      ["TodoWrite", "A to-do list you see as a checklist"],
      ["Task", "Hand part of the work to a subagent"],
      ["Skill", "Load instructions for a kind of task"],
      ["ToolSearch", "Load a tool that isn't offered yet; only the everyday ones start out loaded"],
      ["AskUser", "Ask you a question and wait for the answer"],
      ["Memory", "Keep a note for later sessions in this project"],
    ],
  },
  {
    group: "The web",
    tools: [
      ["WebSearch", "Search the web"],
      ["WebFetch", "Fetch a page's content, or just the answer to a question about it"],
      ["Packages", "A package's latest versions, release notes and known vulnerabilities"],
      ["Audit", "Every locked dependency checked for known vulnerabilities"],
      ["Http", "Send a request to a server on this machine, as your app's API"],
      ["Browser", "Use a page in a real browser, read as an outline, and audit it"],
    ],
  },
];

export default function AboutPage() {
  const count = TOOLS.reduce((n, g) => n + g.tools.length, 0);
  return (
    <main className="page about">
      <h1>Wtf is Zwans</h1>
      <p className="about-lede">
        Zwans is a coding agent built from scratch, to use alongside Claude Code or instead of it. Give it a task in a
        folder and it reads the code, makes the change, runs the tests and shows you the diff. It asks before it changes
        anything, unless you tell it not to.
      </p>

      <h2>What it has</h2>
      <div className="about-grid">
        {PARTS.map((p) => (
          <section key={p.name} className="panel glass">
            <h3>{p.name}</h3>
            <p className="muted">{p.about}</p>
          </section>
        ))}
      </div>

      <h2>Tools ({count})</h2>
      <p className="muted">
        The model can call these. Turn some off to save context, or add more with MCP servers.
      </p>
      <div className="about-grid">
        {TOOLS.map((g) => (
          <section key={g.group} className="panel glass">
            <h3>{g.group}</h3>
            <dl className="about-tools">
              {g.tools.map(([name, about]) => (
                <div key={name}>
                  <dt>
                    <code>{name}</code>
                  </dt>
                  <dd className="muted">{about}</dd>
                </div>
              ))}
            </dl>
          </section>
        ))}
      </div>

      <h2>Try it</h2>
      <pre className="about-try">
        <code>
          {`zwans                                   # chat in this folder
zwans run "make the tests pass" -w path/to/project
zwans --mode auto                       # edits without asking
zwans room "Monorepo or not?" -a ada=claude-haiku-5-5 -a bo=ollama/qwen3:8b
zwans eval run --tasks evals/tasks      # measure it`}
        </code>
      </pre>
      <p className="muted">
        Press <span className="kbd">⌘K</span> (<span className="kbd">Ctrl K</span> off a Mac) to search, or start the demo there: a scripted session with real tools and
        no API calls.
      </p>
    </main>
  );
}
