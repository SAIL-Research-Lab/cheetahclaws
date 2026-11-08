"""Threaded sub-agent system for spawning nested agent loops."""
from __future__ import annotations

import inspect
import os
import uuid
import queue
import subprocess
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor, Future
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Any


# ── Agent definition ───────────────────────────────────────────────────────

@dataclass
class AgentDefinition:
    """Definition for a specialized agent type."""
    name: str
    description: str = ""
    system_prompt: str = ""   # extra instructions prepended to the base system prompt
    model: str = ""            # model override; "" = inherit from parent
    tools: list = field(default_factory=list)   # empty list = all tools
    source: str = "user"       # "built-in" | "user" | "project"


# ── Built-in agent definitions ─────────────────────────────────────────────

_BUILTIN_AGENTS: Dict[str, AgentDefinition] = {
    "general-purpose": AgentDefinition(
        name="general-purpose",
        description=(
            "General-purpose agent for researching complex questions, "
            "searching for code, and executing multi-step tasks."
        ),
        system_prompt="",
        source="built-in",
    ),
    "coder": AgentDefinition(
        name="coder",
        description="Specialized coding agent for writing, reading, and modifying code.",
        system_prompt=(
            "You are a specialized coding assistant. Focus on:\n"
            "- Writing clean, idiomatic code\n"
            "- Reading and understanding existing code before modifying\n"
            "- Making minimal targeted changes\n"
            "- Never adding unnecessary features, comments, or error handling\n"
        ),
        source="built-in",
    ),
    "reviewer": AgentDefinition(
        name="reviewer",
        description="Code review agent analyzing quality, security, and correctness.",
        system_prompt=(
            "You are a code reviewer. Analyze code for:\n"
            "- Correctness and logic errors\n"
            "- Security vulnerabilities (injection, XSS, auth bypass, etc.)\n"
            "- Performance issues\n"
            "- Code quality and maintainability\n"
            "Be concise and specific. Categorize findings as: Critical | Warning | Suggestion.\n"
        ),
        tools=["Read", "Glob", "Grep"],
        source="built-in",
    ),
    "researcher": AgentDefinition(
        name="researcher",
        description="Research agent for exploring codebases and answering questions.",
        system_prompt=(
            "You are a research assistant focused on understanding codebases.\n"
            "- Read and analyze code thoroughly before answering\n"
            "- Provide factual, evidence-based answers\n"
            "- Cite specific file paths and line numbers\n"
            "- Be concise and focused\n"
        ),
        tools=["Read", "Glob", "Grep", "WebFetch", "WebSearch"],
        source="built-in",
    ),
    "tester": AgentDefinition(
        name="tester",
        description="Testing agent that writes and runs tests.",
        system_prompt=(
            "You are a testing specialist. Your job:\n"
            "- Write comprehensive tests for the given code\n"
            "- Run existing tests and diagnose failures\n"
            "- Focus on edge cases and error conditions\n"
            "- Keep tests simple, readable, and fast\n"
        ),
        source="built-in",
    ),
}


# ── Loading agent definitions from .md files ──────────────────────────────

def _parse_agent_md(path: Path, source: str = "user") -> AgentDefinition:
    """Parse a .md file with optional YAML frontmatter into an AgentDefinition.

    File format:
        ---
        description: "Short description"
        model: claude-haiku-4-5-20251001
        tools: [Read, Write, Edit, Bash]
        ---

        System prompt body goes here...
    """
    content = path.read_text()
    name = path.stem
    description = ""
    model = ""
    tools: list = []
    system_prompt_body = content

    if content.startswith("---"):
        end = content.find("---", 3)
        if end != -1:
            fm_text = content[3:end].strip()
            system_prompt_body = content[end + 3:].strip()
            try:
                import yaml as _yaml
                fm = _yaml.safe_load(fm_text) or {}
            except ImportError:
                # Manual key: value parse (no yaml dependency required)
                fm: dict = {}
                for line in fm_text.splitlines():
                    if ":" in line:
                        k, _, v = line.partition(":")
                        fm[k.strip()] = v.strip()
            description = str(fm.get("description", ""))
            model = str(fm.get("model", ""))
            raw_tools = fm.get("tools", [])
            if isinstance(raw_tools, list):
                tools = [str(t) for t in raw_tools]
            elif isinstance(raw_tools, str):
                # Handle "[Read, Write]" or "Read, Write" format
                s = raw_tools.strip("[]")
                tools = [t.strip() for t in s.split(",") if t.strip()]

    return AgentDefinition(
        name=name,
        description=description,
        system_prompt=system_prompt_body,
        model=model,
        tools=tools,
        source=source,
    )


def load_agent_definitions() -> Dict[str, AgentDefinition]:
    """Load all agent definitions: built-ins → user-level → project-level.

    Search paths:
      ~/.cheetahclaws/agents/*.md   (user-level)
      .cheetahclaws/agents/*.md     (project-level, overrides user)
    """
    defs: Dict[str, AgentDefinition] = dict(_BUILTIN_AGENTS)

    # User-level
    user_dir = Path.home() / ".cheetahclaws" / "agents"
    if user_dir.is_dir():
        for p in sorted(user_dir.glob("*.md")):
            try:
                d = _parse_agent_md(p, source="user")
                defs[d.name] = d
            except Exception:
                pass

    # Project-level (overrides user)
    proj_dir = Path.cwd() / ".cheetahclaws" / "agents"
    if proj_dir.is_dir():
        for p in sorted(proj_dir.glob("*.md")):
            try:
                d = _parse_agent_md(p, source="project")
                defs[d.name] = d
            except Exception:
                pass

    return defs


def get_agent_definition(name: str) -> Optional[AgentDefinition]:
    """Look up an agent definition by name. Returns None if not found."""
    return load_agent_definitions().get(name)


# ── Sub-agent permission policy ────────────────────────────────────────────
#
# A sub-agent runs its own agent loop in a worker thread, so nobody is
# reading its event stream to answer a PermissionRequest.  Left unanswered,
# ``PermissionRequest.granted`` stays False and every write is silently
# "rejected by the user".  SubAgentPermissionPolicy answers instead:
#
#   1. parent session runs with auto-approve, or already granted this
#      signature ("s"/"!" at a prompt)            → allow
#   2. ``subagent_permission: "deny"``            → deny
#   3. ``"auto-edits"`` and a file-edit tool       → allow
#   4. ``"inherit"`` (default): what the parent would decide without asking —
#      read-only tools allowed (unless permission_mode is "manual"), and file
#      edits inside the sub-agent's own isolated worktree allowed
#   5. an interactive parent callback (config ``_permission_callback``,
#      ``fn(description, config[, signature]) -> bool``) is available
#                                                  → ask the user, labelled
#                                                    with the sub-agent name
#   6. otherwise                                   → deny, with a reason
#
# Every denial is recorded with its reason so the sub-agent's final result
# tells the parent what was blocked and how to unblock it.

SUBAGENT_PERMISSION_MODES = ("inherit", "auto-edits", "deny")
_EDIT_TOOLS = frozenset({"Write", "Edit", "MultiEdit", "ApplyPatch", "NotebookEdit"})
# Interactive prompts from concurrent sub-agents must not interleave.
_PROMPT_LOCK = threading.Lock()


def _edit_paths(req, name: str, path: str) -> list:
    """Every file an edit request touches (an ApplyPatch can touch several)."""
    inp = getattr(req, "tool_input", None) or {}
    if name == "ApplyPatch":
        try:
            from cheetahclaws.tools.patch import patch_paths
            return patch_paths(inp.get("patch") or inp.get("input") or "")
        except Exception:
            return []
    return [inp.get("file_path") or inp.get("notebook_path") or path]


def _tool_from_request(req) -> tuple:
    """Return (tool_name, path) recovered from a PermissionRequest."""
    if getattr(req, "tool_name", ""):
        inp = getattr(req, "tool_input", None) or {}
        return req.tool_name, inp.get("file_path") or inp.get("notebook_path") or ""
    sig = getattr(req, "signature", "") or ""
    name, _, rest = sig.partition(":")
    path = rest if name in _EDIT_TOOLS else ""
    if not name:
        desc = getattr(req, "description", "") or ""
        if desc.startswith("Run: "):
            name = "Bash"
        elif desc.startswith("Write to: "):
            name, path = "Write", desc[len("Write to: "):]
        elif desc.startswith("Edit: "):
            name, path = "Edit", desc[len("Edit: "):]
        else:
            name = desc.split("(", 1)[0].strip()
    return name, path


def _is_within(path: str, root: str) -> bool:
    if not path or not root:
        return False
    try:
        Path(path).expanduser().resolve().relative_to(Path(root).resolve())
        return True
    except (ValueError, OSError, RuntimeError):
        return False


def _tool_read_only(name: str) -> bool:
    try:
        from cheetahclaws.tool_registry import get_tool
        tool = get_tool(name)
        return bool(tool and tool.read_only)
    except Exception:
        return False


def _call_permission_callback(fn: Callable, desc: str, config: dict, sig: str) -> bool:
    """Invoke a 2- or 3-argument permission callback."""
    try:
        params = list(inspect.signature(fn).parameters.values())
        accepts_sig = (len(params) >= 3 or any(
            p.kind in (inspect.Parameter.VAR_POSITIONAL,
                       inspect.Parameter.VAR_KEYWORD) for p in params))
    except (TypeError, ValueError):
        accepts_sig = False
    if accepts_sig and sig:
        return bool(fn(desc, config, sig))
    return bool(fn(desc, config))


@dataclass
class SubAgentPermissionPolicy:
    """Decides PermissionRequests raised inside a sub-agent (see above)."""
    agent_name: str = ""
    mode: str = "inherit"
    permission_mode: str = "auto"
    callback: Optional[Callable] = None
    parent_grants: Any = field(default_factory=set)   # live set; read only
    parent_auto_approve: bool = False
    worktree_path: str = ""
    callback_config: dict = field(default_factory=dict)
    denials: list = field(default_factory=list)

    @classmethod
    def from_parent_config(cls, config: dict, agent_name: str = "",
                           worktree_path: str = "") -> "SubAgentPermissionPolicy":
        config = config or {}
        mode = str(config.get("subagent_permission") or "inherit").strip().lower()
        if mode not in SUBAGENT_PERMISSION_MODES:
            mode = "inherit"
        grants: Any = set()
        try:
            from cheetahclaws import runtime
            if config.get("_session_id"):
                grants = runtime.get_ctx(config).approved_sigs
        except Exception:
            pass
        auto = False
        try:
            from cheetahclaws.permissions import auto_approve_on
            auto = auto_approve_on(config)
        except Exception:
            pass
        cb = config.get("_permission_callback")
        return cls(
            agent_name=agent_name,
            mode=mode,
            permission_mode=str(config.get("permission_mode") or "auto"),
            callback=cb if callable(cb) else None,
            parent_grants=grants,
            parent_auto_approve=auto,
            worktree_path=worktree_path,
            callback_config=config,
        )

    def _deny(self, req, reason: str) -> bool:
        req.granted = False
        try:
            req.reason = reason
            req.deny_reason = reason   # the loop returns it as the tool result
            req.decided_by = "subagent_policy"
        except Exception:
            pass
        self.denials.append(f"{getattr(req, 'description', '')} — {reason}")
        return False

    def decide(self, req) -> bool:
        """Set ``req.granted`` (and ``req.reason`` on denial); return it."""
        sig = getattr(req, "signature", "") or ""
        desc = getattr(req, "description", "") or ""
        name, path = _tool_from_request(req)

        if self.permission_mode != "manual":
            if self.parent_auto_approve:
                req.granted = True
                return True
            if sig and sig in (self.parent_grants or ()):
                req.granted = True
                return True
        if self.mode == "deny":
            return self._deny(req, (
                "sub-agent escalations are disabled (subagent_permission="
                "\"deny\"); report what you need in your final answer"))
        if self.permission_mode != "manual":
            if self.mode == "auto-edits" and name in _EDIT_TOOLS:
                req.granted = True
                return True
            paths = _edit_paths(req, name, path) if name in _EDIT_TOOLS else []
            if paths and all(p and _is_within(p, self.worktree_path) for p in paths):
                req.granted = True
                return True
            if name and name not in _EDIT_TOOLS and name != "Bash" \
                    and _tool_read_only(name):
                req.granted = True
                return True
        if self.callback is not None:
            label = f"[sub-agent {self.agent_name}] {desc}" if self.agent_name else desc
            try:
                with _PROMPT_LOCK:
                    granted = _call_permission_callback(
                        self.callback, label, self.callback_config, sig)
            except Exception as e:
                return self._deny(req, f"permission prompt failed: {e}")
            if granted:
                req.granted = True
                return True
            return self._deny(req, "the user rejected this operation")
        hint = (
            "no interactive approver is available for sub-agents; the parent "
            "agent can perform this step itself, or the user can set "
            "subagent_permission=\"auto-edits\", run with /auto, or use "
            "isolation=\"worktree\" so edits stay in the sub-agent's worktree"
        )
        return self._deny(req, hint)

    def denial_report(self) -> str:
        if not self.denials:
            return ""
        lines = "\n".join(f"- {d}" for d in self.denials[:20])
        more = len(self.denials) - 20
        if more > 0:
            lines += f"\n- … and {more} more"
        return ("[Sub-agent permission denials — these operations did not "
                f"run:]\n{lines}")

    def system_note(self) -> str:
        """Up-front explanation for the sub-agent when escalations may be
        denied without a human in the loop."""
        if self.callback is not None or (
                self.parent_auto_approve and self.permission_mode != "manual"):
            return ""
        if self.mode == "auto-edits":
            return ""
        scope = ("file edits inside your worktree are allowed"
                 if self.worktree_path and self.mode != "deny"
                 else "file edits and non-read-only shell commands may be denied")
        return (
            "[Sub-agent permissions: you run without an interactive approver; "
            f"{scope}. If an operation is denied, do not retry it — finish "
            "what you can and list the blocked steps (with exact paths/"
            "commands and intended changes) in your final answer so the "
            "parent agent can apply them.]"
        )


# ── SubAgentTask ───────────────────────────────────────────────────────────

@dataclass
class SubAgentTask:
    """Represents a sub-agent task with lifecycle tracking."""
    id: str
    prompt: str
    status: str = "pending"       # pending | running | completed | failed | cancelled
    result: Optional[str] = None
    depth: int = 0
    name: str = ""                # optional human-readable name (addressable by SendMessage)
    worktree_path: str = ""       # set if isolation="worktree"
    worktree_branch: str = ""     # set if isolation="worktree"
    _cancel_flag: bool = False
    _future: Optional[Future] = field(default=None, repr=False)
    _inbox: Any = field(default_factory=queue.Queue, repr=False)  # for send_message
    _permission_policy: Any = field(default=None, repr=False)


# ── Worktree helpers ───────────────────────────────────────────────────────

def _git_root(cwd: str) -> Optional[str]:
    """Return the git root directory for cwd, or None if not in a git repo."""
    try:
        r = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=cwd, capture_output=True, text=True, check=True,
        )
        return r.stdout.strip()
    except Exception:
        return None


def _create_worktree(base_dir: str) -> tuple:
    """Create a temporary git worktree.

    Returns:
        (worktree_path, branch_name)
    Raises:
        subprocess.CalledProcessError or OSError on failure.
    """
    branch = f"nano-agent-{uuid.uuid4().hex[:8]}"
    # mkdtemp gives us a path; remove the empty dir so git can create it
    wt_path = tempfile.mkdtemp(prefix="nano-agent-wt-")
    os.rmdir(wt_path)
    subprocess.run(
        ["git", "worktree", "add", "-b", branch, wt_path],
        cwd=base_dir, check=True, capture_output=True, text=True,
    )
    return wt_path, branch


def _remove_worktree(wt_path: str, branch: str, base_dir: str) -> str:
    """Clean up a sub-agent worktree without destroying its work (best-effort).

    The sub-agent is told to commit before finishing, so its branch is the
    deliverable: it is deleted only when it holds no commits beyond the base
    HEAD, and the worktree is removed only when it has no uncommitted changes.
    Returns a note for the task result naming whatever was kept ("" if all
    of it was cleaned up).
    """
    def _git(*args, cwd=base_dir):
        return subprocess.run(["git", *args], cwd=cwd,
                              capture_output=True, text=True)

    kept = []
    try:
        dirty = bool(_git("status", "--porcelain", cwd=wt_path).stdout.strip())
    except Exception:
        dirty = False
    if dirty:
        kept.append(f"worktree {wt_path} (uncommitted changes)")
    else:
        try:
            _git("worktree", "remove", "--force", wt_path)
        except Exception:
            pass
    try:
        has_commits = bool(_git("rev-list", "--count", f"HEAD..{branch}")
                           .stdout.strip() not in ("", "0"))
    except Exception:
        has_commits = True   # unsure → keep it
    if has_commits or dirty:
        kept.append(f"branch {branch}")
    else:
        try:
            _git("branch", "-D", branch)
        except Exception:
            pass
    if not kept:
        return ""
    return ("\n\n[Sub-agent work kept for review: " + "; ".join(kept)
            + f". Merge with `git merge {branch}` or discard with "
            f"`git worktree remove --force {wt_path}; git branch -D {branch}`.]")


# ── Internal helpers ───────────────────────────────────────────────────────

def _agent_run(prompt, state, config, system_prompt, depth=0, cancel_check=None):
    """Lazy-import wrapper to avoid circular dependency with agent module.

    Uses absolute import so this works whether called from inside or outside
    the multi_agent package (sys.path includes the project root).
    """
    from cheetahclaws import agent as _agent_mod
    return _agent_mod.run(prompt, state, config, system_prompt, depth=depth, cancel_check=cancel_check)


def _extract_final_text(messages):
    """Walk backwards through messages, return first assistant content string."""
    for msg in reversed(messages):
        if msg.get("role") == "assistant" and msg.get("content"):
            return msg["content"]
    return None


# ── SubAgentManager ────────────────────────────────────────────────────────

class SubAgentManager:
    """Manages concurrent sub-agent tasks using a thread pool."""

    def __init__(self, max_concurrent: int = 5, max_depth: int = 5):
        self.tasks: Dict[str, SubAgentTask] = {}
        self._by_name: Dict[str, str] = {}   # name → task_id
        self.max_concurrent = max_concurrent
        self.max_depth = max_depth
        self._pool = ThreadPoolExecutor(max_workers=max_concurrent)

    def spawn(
        self,
        prompt: str,
        config: dict,
        system_prompt: str,
        depth: int = 0,
        agent_def: Optional[AgentDefinition] = None,
        isolation: str = "",     # "" | "worktree"
        name: str = "",
        parent_config: Optional[dict] = None,
    ) -> SubAgentTask:
        """Spawn a new sub-agent task.

        Args:
            prompt:       user message for the sub-agent
            config:       agent configuration dict (copied before modification)
            system_prompt: base system prompt
            depth:        current nesting depth (prevents infinite recursion)
            agent_def:    optional AgentDefinition with model/system_prompt/tools overrides
            isolation:    "" for normal, "worktree" for isolated git worktree
            name:         optional human-readable name (addressable via SendMessage)
            parent_config: the parent's full config (incl. private keys such
                          as ``_session_id``/``_permission_callback``) used to
                          answer the sub-agent's PermissionRequests; defaults
                          to ``config``.

        Returns:
            SubAgentTask tracking the spawned work.
        """
        task_id = uuid.uuid4().hex[:12]
        short_name = name or task_id[:8]
        task = SubAgentTask(id=task_id, prompt=prompt, depth=depth, name=short_name)
        self.tasks[task_id] = task
        if name:
            self._by_name[name] = task_id

        if depth >= self.max_depth:
            task.status = "failed"
            task.result = f"Max depth ({self.max_depth}) exceeded"
            return task

        # Build effective config and system prompt for this sub-agent
        eff_config = dict(config)
        eff_system = system_prompt

        if agent_def:
            if agent_def.model:
                eff_config["model"] = agent_def.model
            if agent_def.system_prompt:
                eff_system = agent_def.system_prompt.rstrip() + "\n\n" + system_prompt

        # Handle worktree isolation
        worktree_path = ""
        worktree_branch = ""
        base_dir = os.getcwd()

        if isolation == "worktree":
            git_root = _git_root(base_dir)
            if not git_root:
                task.status = "failed"
                task.result = "isolation='worktree' requires a git repository"
                return task
            try:
                worktree_path, worktree_branch = _create_worktree(git_root)
                task.worktree_path = worktree_path
                task.worktree_branch = worktree_branch
                notice = (
                    f"\n\n[Note: You are working in an isolated git worktree at "
                    f"{worktree_path} (branch: {worktree_branch}). "
                    f"Your changes are isolated from the main workspace at {git_root}. "
                    f"Commit your changes before finishing so they can be reviewed/merged.]"
                )
                prompt = prompt + notice
                # Pass the worktree path through config so tools (Bash/Glob/Grep)
                # use it as their working directory without touching the process-level
                # cwd (which is shared across all threads).
                eff_config["_worktree_cwd"] = worktree_path
            except Exception as e:
                task.status = "failed"
                task.result = f"Failed to create worktree: {e}"
                return task

        policy = SubAgentPermissionPolicy.from_parent_config(
            parent_config if parent_config is not None else config,
            agent_name=short_name, worktree_path=worktree_path,
        )
        task._permission_policy = policy
        _note = policy.system_note()
        if _note:
            eff_system = eff_system.rstrip() + "\n\n" + _note

        def _answer(event) -> None:
            # Duck-typed so tests and alternative loops need not import agent.
            if type(event).__name__ == "PermissionRequest" and \
                    hasattr(event, "granted"):
                try:
                    policy.decide(event)
                except Exception as e:   # never leave a request unanswered
                    policy._deny(event, f"permission policy error: {e}")

        def _with_denials(text):
            report = policy.denial_report()
            if not report:
                return text
            return f"{text}\n\n{report}" if text else report

        def _run():
            from cheetahclaws import agent as _agent_mod; AgentState = _agent_mod.AgentState
            task.status = "running"
            try:
                state = AgentState()
                gen = _agent_run(
                    prompt, state, eff_config, eff_system,
                    depth=depth + 1,
                    cancel_check=lambda: task._cancel_flag,
                )
                for _event in gen:
                    _answer(_event)
                    if task._cancel_flag:
                        break

                if task._cancel_flag:
                    task.status = "cancelled"
                    task.result = None
                else:
                    task.result = _with_denials(_extract_final_text(state.messages))
                    task.status = "completed"

                # Drain inbox: process any messages sent via SendMessage
                while not task._inbox.empty() and not task._cancel_flag:
                    inbox_msg = task._inbox.get_nowait()
                    task.status = "running"
                    gen2 = _agent_run(
                        inbox_msg, state, eff_config, eff_system,
                        depth=depth + 1,
                        cancel_check=lambda: task._cancel_flag,
                    )
                    for _ev in gen2:
                        _answer(_ev)
                        if task._cancel_flag:
                            break
                    if not task._cancel_flag:
                        task.result = _with_denials(_extract_final_text(state.messages))
                        task.status = "completed"

            except Exception as e:
                task.status = "failed"
                task.result = f"Error: {e}"
            finally:
                if worktree_path:
                    note = _remove_worktree(worktree_path, worktree_branch, base_dir)
                    if note:
                        task.result = (task.result or "") + note

        task._future = self._pool.submit(_run)
        return task

    def wait(self, task_id: str, timeout: float = None) -> Optional[SubAgentTask]:
        """Block until a task completes or timeout expires.

        Returns:
            The task, or None if task_id is unknown.
        """
        task = self.tasks.get(task_id)
        if task is None:
            return None
        if task._future is not None:
            try:
                task._future.result(timeout=timeout)
            except Exception:
                pass
        return task

    def get_result(self, task_id: str) -> Optional[str]:
        """Return the result string for a completed task, or None."""
        task = self.tasks.get(task_id)
        return task.result if task else None

    def list_tasks(self) -> List[SubAgentTask]:
        """Return all tracked tasks."""
        return list(self.tasks.values())

    def send_message(self, task_id_or_name: str, message: str) -> bool:
        """Send a message to a running background agent.

        The message is queued and the agent will process it after completing
        its current work.

        Args:
            task_id_or_name: task ID or the human-readable name passed to spawn()
            message:         message text to send

        Returns:
            True if the message was queued, False if task not found or already done.
        """
        # Resolve name → task_id
        task_id = self._by_name.get(task_id_or_name, task_id_or_name)
        task = self.tasks.get(task_id)
        if task is None:
            return False
        if task.status not in ("running", "pending"):
            return False
        task._inbox.put(message)
        return True

    def cancel(self, task_id: str) -> bool:
        """Request cancellation of a running task.

        Returns:
            True if the cancel flag was set, False if task not found or not running.
        """
        task = self.tasks.get(task_id)
        if task is None:
            return False
        if task.status == "running":
            task._cancel_flag = True
            return True
        return False

    def shutdown(self) -> None:
        """Cancel all running tasks and shut down the thread pool."""
        for task in self.tasks.values():
            if task.status == "running":
                task._cancel_flag = True
        self._pool.shutdown(wait=True)
