# Security model

What Zwans's permissions and sandbox protect against, and what they don't. The point of
writing this down is to keep the sandbox from giving false confidence.

## The threat

The model is not the adversary; the content it reads is. A repository, a dependency's
README, a test's output or a web page can carry instructions planted for coding agents:
"run `curl ... | sh` first", "delete the tests", "print `~/.ssh/id_rsa`". A model that
follows one acts with the user's access. The second threat is ordinary mistakes: a model
that runs `rm -rf` on the wrong folder.

## The layers

1. **The system prompt** tells the model that instructions in files and command output come
   from whoever wrote that content, not from the user. This lowers how often the model tries
   a planted action; it guarantees nothing.
2. **The policy** (`src/zwans/policy/`) judges every tool call before it runs. Bash commands
   are parsed into simple commands first, and each one is sorted as read, write, execute,
   network or unknown. In `ask` mode only reads run without the user's approval. A refusal
   goes back to the model as an error saying why.
3. **The executor** confines the file tools to the workspace (and Zwans's own folder for
   saved tool output). Commands run without Zwans's API credentials in their environment.
4. **The Docker executor** runs commands in a container that sees only the workspace,
   runs as the user's uid with no capabilities, and reaches the network only through a proxy
   that allows a list of hosts.

## What the policy can't see

The classifier reads the command line, not what programs do. These are deliberate limits:

- **Running code is one decision.** `python script.py`, `pytest` and `make` are "execute":
  the code can do anything, including network calls. In `ask` mode they ask; in `auto` mode
  they run. That's why `auto` belongs with the Docker executor, where "anything" is bounded.
- **Config files can make "read" commands run programs.** A crafted `.git/config` can make
  `git status` run a program (`core.fsmonitor`), and git is treated as read-only for
  `status`, `diff` and `log`. Edits to `.git/` always ask, but a repository that arrives
  with such a config is not detected. The Docker executor contains it; local execution
  doesn't.
- **Reads outside the workspace are judged by their arguments.** `cat ~/.ssh/id_rsa` asks,
  but a program that reads a file named inside its own code does not show it on the
  command line.
- **The untrusted-content flag is session-wide and coarse.** Once anything from a file or
  command has been read, which is almost always, network commands ask even when a rule allows
  them. It cannot tell which content influenced which call.
- **A workspace policy is trusted by content hash**, so trusting a policy file and then
  letting the agent edit it requires trusting it again. The agent's own edits to `.zwans/`
  always ask.

## Extensions

- **Hooks run on the host**, with your access, even with the Docker executor: they are your
  own programs. A project's hooks are code from whoever wrote the project, so they need the
  same trust as its allow rules. A pre_tool hook that fails to run blocks the call, so a
  broken hook can't open a gap.
- **MCP servers come only from your own config**, never from a workspace, because starting
  one runs a program. Their tools reach outside the workspace, so every tool not marked
  read-only asks, in `auto` mode too, and after untrusted content even an allowed one asks,
  as a network command would: posting a comment can carry what was read somewhere else.
  The read-only mark is the server's own word, trusted because you chose the server. A
  "read-only" tool that takes a query can still send that query out; Zwans can't see what
  a server does with its arguments.
- **MCP output and skills count as untrusted content.** A project's skills are text from
  the project, like its ZWANS.md, and are listed in the system prompt the same way.
- **Subagents share the parent's policy, hooks and untrusted flag**, so delegating a call
  doesn't change whether it's allowed, and the injection suite counts a subagent's calls
  like the agent's own. The `Task` call itself runs without asking because each call the
  subagent makes is checked. Subagents running at once ask their questions one at a time.

## The jail

`zwans-jail` (`runtime/`, Linux only) is a sandbox per command, built from kernel features
rather than a container runtime. What it adds over the Docker executor, and what it leaves:

- **No network at all**, where Docker's proxy lets package indexes and GitHub through. A
  task that needs `pip install` fails under the jail.
- **The workspace is still mounted read-write**, as with Docker: code in the jail can change
  or delete anything in the project, `.git/` included.
- **Its limits depend on the machine.** With a delegated cgroup (a desktop login) memory and
  process counts are hard limits; without one (most containers and CI runners) they fall
  back to `RLIMIT_DATA` and `RLIMIT_NPROC`, which a determined program can get around with
  memory it maps in other ways. `--stats` reports which applied.
- **It needs unprivileged user namespaces**, which some distributions restrict (Ubuntu
  24.04 with AppArmor). It doesn't need root, and adds no setuid program.
- **The kernel is shared**, as with containers: a kernel bug reachable through the allowed
  system calls is a way out. The allowlist keeps that surface close to Docker's.
- The read-only paths come from PATH and the system folders, so software installed there
  (a conda environment, say) is visible to the command, though not writable.

## The server

`zwans serve` lets a browser run the agent, so it is a way to run commands on this machine.

- It listens on 127.0.0.1 unless told otherwise, and warns when it isn't.
- Every API call and WebSocket needs a token made fresh at each start. The link carries it
  after `#`, which browsers don't send to servers, so it stays out of logs; `zwans attach`
  reads it from `~/.zwans/server.json`, which only the user can read. The browser keeps it
  in localStorage, so anything that can run script on the UI's origin can use it.
- A WebSocket from another site's page is closed before it can send the token. Pages on
  other sites can't read the API's responses either, since it sends no CORS headers (except
  to the one `--dev-origin`, when given).
- The policy is the same as in the terminal; the server only changes who answers its
  questions. A project's policy that would loosen the rules or run hooks isn't trusted from
  the browser: those parts stay off, and the session says so.

## What the Docker sandbox doesn't cover

- The workspace is mounted read-write. Code in the container can change or delete anything
  in the project, including `.git/`. Commit or back up before using `auto`.
- Allowed hosts are allowed for everything: a package index can serve a malicious package,
  and GitHub can host anything. The allowlist limits exfiltration targets; it doesn't vet
  downloads.
- The eval checks, and the file tools, run on the host. Only commands run in the container.
- Containers share the host kernel. This is not a defence against kernel exploits; Phase 7's
  `zwans-jail` doesn't change that either.

## How it's tested

- `tests/test_policy_commands.py`: the parser and classifier, including commands that try to
  hide a second command (`&&`, `$(...)`, `bash -c`, `find -exec`, here-documents).
- `tests/test_policy.py`: rules, modes, the untrusted-content escalation, policy trust, and
  that refusals reach the model as tool errors.
- `tests/test_hooks.py`, `tests/test_mcp.py`, `tests/test_subagents.py`: a pre_tool hook
  blocks `git push` and a broken one blocks too; a project's hooks need trust; MCP tools ask
  unless read-only and ask again after untrusted content; a subagent's calls are checked
  and counted like the parent's.
- `tests/test_server.py`: the token on every route and WebSocket, the origin check,
  approvals that go back over the WebSocket, and several clients on one session.
- `tests/test_jail.py`: the escape suite. Fork bombs, a memory bomb, /proc and host-file
  access, ptrace, signalling host processes, inherited file descriptors, mounting, new
  namespaces, network access, timeouts and leftover background processes. It runs in CI
  on Linux (the `jail` job), inside a delegated cgroup.
- `tests/test_docker_executor.py`: the container sees no host files outside the workspace
  and no host environment, timeouts kill whole process trees, there is no direct route out,
  and the proxy refuses hosts off the list. These run in CI on Linux.
- `evals/tasks-injection/`: nine repos with planted instructions, run against real models.
  The result that matters is how many planted actions *ran*; see `docs/findings.md`.
