from __future__ import annotations

from conftest import first, kinds, only
from glasshouse import (
    ApprovalRequested,
    DryRunPlanned,
    FakeProvider,
    Gate,
    Policy,
    RunFinished,
    Session,
    Thinking,
    ToolFailed,
    ToolFinished,
    ToolProgress,
    ToolSkipped,
    ToolStarted,
    UndoFailed,
    Undone,
    calls,
    says,
)


def run(session: Session, prompt: str = "go", approve: bool = True) -> list:
    events = []
    for event in session.run(prompt):
        if isinstance(event, ApprovalRequested):
            (session.approve if approve else session.reject)(event.call_id)
        events.append(event)
    return events


# ---------------------------------------------------------------- basics


def test_a_run_with_no_tools_still_brackets_itself(registry):
    provider = FakeProvider([says("nothing to do")])
    events = run(Session(provider, registry))
    assert kinds(events) == ["run_started", "thinking", "run_finished"]
    assert first(events, RunFinished).text == "nothing to do"


def test_read_tools_run_without_asking(registry):
    provider = FakeProvider([calls(("list_files", {})), says("done")])
    events = run(Session(provider, registry))
    assert not only(events, ApprovalRequested)
    assert first(events, ToolFinished).result == ["a.txt", "b.txt"]


def test_tool_results_are_fed_back_in_one_message(registry):
    provider = FakeProvider(
        [calls(("read_file", {"path": "a.txt"}), ("read_file", {"path": "b.txt"})), says("ok")]
    )
    run(Session(provider, registry))
    # Second turn's history: user, assistant(tool_calls), user(tool_results)
    history = provider.calls[1]
    results = [m for m in history if m.get("tool_results")]
    assert len(results) == 1, "parallel results must arrive in a single message"
    assert len(results[0]["tool_results"]) == 2


def test_progress_callback_surfaces_as_events(registry):
    provider = FakeProvider([calls(("slow_count", {"n": 3})), says("ok")])
    events = run(Session(provider, registry))
    assert [e.message for e in only(events, ToolProgress)] == [
        "step 1/3",
        "step 2/3",
        "step 3/3",
    ]


def test_max_turns_stops_a_runaway_agent(registry):
    provider = FakeProvider([calls(("list_files", {}))] * 50)
    events = run(Session(provider, registry, max_turns=3))
    assert first(events, RunFinished).turns == 3


def test_unknown_tool_is_reported_not_raised(registry):
    provider = FakeProvider([calls(("does_not_exist", {})), says("ok")])
    events = run(Session(provider, registry))
    assert "unknown tool" in first(events, ToolFailed).error


# ---------------------------------------------------------------- gating


def test_mutation_is_gated_by_default(registry, world):
    provider = FakeProvider([calls(("delete_file", {"path": "a.txt"})), says("ok")])
    events = run(Session(provider, registry), approve=False)
    assert first(events, ApprovalRequested).effect == "destructive"
    assert only(events, ToolSkipped)
    assert "a.txt" in world["files"], "a rejected call must not run"


def test_approval_lets_it_through(registry, world):
    provider = FakeProvider([calls(("delete_file", {"path": "a.txt"})), says("ok")])
    run(Session(provider, registry), approve=True)
    assert "a.txt" not in world["files"]


def test_no_decision_means_no(registry, world):
    """Silence is not consent."""
    provider = FakeProvider([calls(("delete_file", {"path": "a.txt"})), says("ok")])
    events = [e for e in Session(provider, registry).run("go")]
    assert only(events, ToolSkipped)
    assert "a.txt" in world["files"]


def test_gate_never_runs_everything(registry, world):
    provider = FakeProvider([calls(("delete_file", {"path": "a.txt"})), says("ok")])
    events = run(Session(provider, registry, policy=Policy(gate=Gate.NEVER)))
    assert not only(events, ApprovalRequested)
    assert "a.txt" not in world["files"]


def test_gate_always_asks_even_for_reads(registry):
    provider = FakeProvider([calls(("list_files", {})), says("ok")])
    events = run(Session(provider, registry, policy=Policy(gate=Gate.ALWAYS)))
    assert first(events, ApprovalRequested).effect == "read"


def test_gate_on_destructive_lets_plain_writes_through(registry, world):
    provider = FakeProvider(
        [calls(("write_file", {"path": "c.txt", "content": "x"})), says("ok")]
    )
    events = run(Session(provider, registry, policy=Policy(gate=Gate.ON_DESTRUCTIVE)))
    assert not only(events, ApprovalRequested)
    assert world["files"]["c.txt"] == "x"


def test_irreversible_destructive_can_be_refused_outright(registry, world):
    provider = FakeProvider([calls(("shred_file", {"path": "a.txt"})), says("ok")])
    policy = Policy(gate=Gate.NEVER, require_undo_for_destructive=True)
    events = run(Session(provider, registry, policy=policy))
    assert "no undo handler" in first(events, ToolSkipped).reason
    assert "a.txt" in world["files"]


# ---------------------------------------------------------------- dry run


def test_dry_run_previews_instead_of_running(registry, world):
    provider = FakeProvider([calls(("delete_file", {"path": "a.txt"})), says("ok")])
    events = run(Session(provider, registry, dry_run=True))
    assert first(events, DryRunPlanned).preview == "would delete 'a.txt'"
    assert not only(events, ToolStarted)
    assert "a.txt" in world["files"], "dry run must not touch anything"


def test_dry_run_still_executes_reads(registry):
    """Reads are how the agent decides what to propose — they must happen."""
    provider = FakeProvider([calls(("list_files", {})), says("ok")])
    events = run(Session(provider, registry, dry_run=True))
    assert first(events, ToolFinished).result == ["a.txt", "b.txt"]
    assert not only(events, DryRunPlanned)


def test_dry_run_never_asks_for_approval(registry):
    provider = FakeProvider([calls(("delete_file", {"path": "a.txt"})), says("ok")])
    events = run(Session(provider, registry, dry_run=True, policy=Policy(gate=Gate.ALWAYS)))
    assert not only(events, ApprovalRequested)


def test_dry_run_reports_zero_applied(registry):
    provider = FakeProvider([calls(("delete_file", {"path": "a.txt"})), says("ok")])
    events = run(Session(provider, registry, dry_run=True))
    assert first(events, RunFinished).applied == 0


# ---------------------------------------------------------------- rollback


def test_failure_rolls_back_earlier_mutations(registry, world):
    provider = FakeProvider(
        [
            calls(("delete_file", {"path": "a.txt"})),
            calls(("delete_file", {"path": "gone.txt"})),  # raises
            says("unreachable"),
        ]
    )
    events = run(Session(provider, registry, policy=Policy(gate=Gate.NEVER)))
    assert only(events, ToolFailed)
    assert [e.tool for e in only(events, Undone)] == ["delete_file"]
    assert world["files"]["a.txt"] == "aaa", "the earlier delete must be undone"
    assert first(events, RunFinished).rolled_back == 1


def test_rollback_is_newest_first(registry, world):
    order: list[str] = []
    spec = registry.get("delete_file")
    original = spec.undo
    spec.undo = lambda path: (order.append(path), original(path))[1]

    provider = FakeProvider(
        [
            calls(("delete_file", {"path": "a.txt"})),
            calls(("delete_file", {"path": "b.txt"})),
            calls(("delete_file", {"path": "gone.txt"})),
            says("unreachable"),
        ]
    )
    run(Session(provider, registry, policy=Policy(gate=Gate.NEVER)))
    assert order == ["b.txt", "a.txt"]


def test_irreversible_effects_are_reported_not_silently_dropped(registry):
    provider = FakeProvider(
        [
            calls(("shred_file", {"path": "a.txt"})),
            calls(("delete_file", {"path": "gone.txt"})),  # raises
            says("unreachable"),
        ]
    )
    events = run(Session(provider, registry, policy=Policy(gate=Gate.NEVER)))
    assert "no undo handler" in first(events, UndoFailed).error


def test_auto_undo_can_be_switched_off(registry, world):
    provider = FakeProvider(
        [
            calls(("delete_file", {"path": "a.txt"})),
            calls(("delete_file", {"path": "gone.txt"})),
            says("unreachable"),
        ]
    )
    events = run(
        Session(provider, registry, policy=Policy(gate=Gate.NEVER), auto_undo=False)
    )
    assert not only(events, Undone)
    assert "a.txt" not in world["files"]


def test_reads_are_not_journalled(registry):
    provider = FakeProvider(
        [calls(("list_files", {})), calls(("delete_file", {"path": "gone.txt"})), says("x")]
    )
    events = run(Session(provider, registry, policy=Policy(gate=Gate.NEVER)))
    assert not only(events, Undone) and not only(events, UndoFailed)


# ---------------------------------------------------------------- events


def test_every_event_serialises(registry):
    provider = FakeProvider(
        [calls(("delete_file", {"path": "a.txt"})), calls(("slow_count", {"n": 1})), says("ok")]
    )
    for event in run(Session(provider, registry)):
        data = event.to_dict()
        assert data["kind"] == event.kind
        assert isinstance(data["at"], float)


def test_thinking_text_is_surfaced(registry):
    provider = FakeProvider([calls(("list_files", {}), text="let me look"), says("done")])
    events = run(Session(provider, registry))
    assert [e.text for e in only(events, Thinking)] == ["let me look", "done"]
