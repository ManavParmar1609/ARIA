"""The SQL checkpointer and Store, exercised through real LangGraph graphs."""

from __future__ import annotations

import operator
from typing import Annotated, TypedDict

import pytest
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, Send, interrupt

from aria.db.engine import get_engine, init_db
from aria.graph.checkpoint import SqlCheckpointSaver
from aria.graph.store import SqlStore


class State(TypedDict, total=False):
    items: Annotated[list[str], operator.add]
    approved: bool
    big: list[str]


def _graph(saver: SqlCheckpointSaver):  # type: ignore[no-untyped-def]
    def fan(state: State) -> list[Send]:
        return [Send("work", {"items": [f"w{i}"]}) for i in range(3)]

    def work(state: State) -> State:
        return {"items": [f"done:{state['items'][0]}"]}

    def review(state: State) -> State:
        decision = interrupt({"question": "approve?", "count": len(state.get("items", []))})
        return {"approved": bool(decision)}

    builder = StateGraph(State)
    builder.add_node("work", work)
    builder.add_node("review", review)
    builder.add_conditional_edges(START, fan, ["work"])
    builder.add_edge("work", "review")
    builder.add_edge("review", END)
    return builder.compile(checkpointer=saver)


@pytest.fixture
def saver() -> SqlCheckpointSaver:
    engine = get_engine()
    init_db(engine)
    return SqlCheckpointSaver(engine)


def test_fan_out_interrupt_and_resume_survive_a_new_saver(saver: SqlCheckpointSaver) -> None:
    config: RunnableConfig = {"configurable": {"thread_id": "t1"}}
    paused = _graph(saver).invoke({"items": [], "big": ["x" * 100] * 50}, config)
    assert paused["__interrupt__"][0].value == {"question": "approve?", "count": 3}
    assert sorted(paused["items"]) == ["done:w0", "done:w1", "done:w2"]
    # A fresh saver on the same database stands in for a process restart.
    resumed = _graph(SqlCheckpointSaver(saver.engine)).invoke(Command(resume=True), config)
    assert resumed["approved"] is True


def test_history_replay_and_fork(saver: SqlCheckpointSaver) -> None:
    graph = _graph(saver)
    config: RunnableConfig = {"configurable": {"thread_id": "t2"}}
    graph.invoke({"items": []}, config)
    graph.invoke(Command(resume=False), config)
    history = list(graph.get_state_history(config))
    assert len(history) >= 3
    assert history[0].values["approved"] is False
    # Fork: copy the thread, then rewind the copy to before the review and decide differently.
    saver.copy_thread("t2", "t2-fork")
    fork_config: RunnableConfig = {"configurable": {"thread_id": "t2-fork"}}
    before_review = next(s for s in graph.get_state_history(fork_config) if s.next == ("review",))
    graph.invoke(None, before_review.config)  # replay to the interrupt
    forked = graph.invoke(Command(resume=True), fork_config)
    assert forked["approved"] is True
    assert graph.get_state(config).values["approved"] is False  # the original is untouched
    with pytest.raises(ValueError, match="already exists"):
        saver.copy_thread("t2", "t2-fork")


def test_large_values_are_stored_once_not_per_checkpoint(saver: SqlCheckpointSaver) -> None:
    from sqlalchemy import func, select

    from aria.db.engine import session_scope
    from aria.db.models import CheckpointBlobRow

    graph = _graph(saver)
    config: RunnableConfig = {"configurable": {"thread_id": "t3"}}
    graph.invoke({"items": [], "big": ["line"] * 5_000}, config)
    with session_scope(saver.engine) as session:
        big_versions = session.scalar(
            select(func.count())
            .select_from(CheckpointBlobRow)
            .where(CheckpointBlobRow.thread_id == "t3", CheckpointBlobRow.channel == "big")
        )
    assert big_versions == 1


def test_list_filters_and_limits(saver: SqlCheckpointSaver) -> None:
    graph = _graph(saver)
    config: RunnableConfig = {"configurable": {"thread_id": "t4"}}
    graph.invoke({"items": []}, config)
    everything = list(saver.list(config))
    assert len(list(saver.list(config, limit=2))) == 2
    loops = list(saver.list(config, filter={"source": "loop"}))
    assert loops
    assert all(c.metadata["source"] == "loop" for c in loops)
    before = list(saver.list(config, before=everything[0].config))
    assert len(before) == len(everything) - 1


def test_prune_keeps_only_the_latest_checkpoint(saver: SqlCheckpointSaver) -> None:
    graph = _graph(saver)
    config: RunnableConfig = {"configurable": {"thread_id": "t5"}}
    graph.invoke({"items": [], "big": ["x"] * 10}, config)
    latest = graph.get_state(config).values
    saver.prune(["t5"])
    assert len(list(saver.list(config))) == 1
    assert graph.get_state(config).values == latest
    saver.delete_thread("t5")
    assert saver.get_tuple(config) is None


async def test_async_api_matches_sync(saver: SqlCheckpointSaver) -> None:
    graph = _graph(saver)
    config: RunnableConfig = {"configurable": {"thread_id": "t6"}}
    paused = await graph.ainvoke({"items": []}, config)
    assert "__interrupt__" in paused
    done = await graph.ainvoke(Command(resume=True), config)
    assert done["approved"] is True
    assert [c async for c in saver.alist(config, limit=1)]


def test_store_put_get_search_and_namespaces() -> None:
    engine = get_engine()
    init_db(engine)
    store = SqlStore(engine)
    store.put(
        ("feedback", "bgl", "kernel_panic"),
        "run-1",
        {"from": "SEV3", "to": "SEV2", "reviewer": "ana"},
    )
    store.put(
        ("feedback", "bgl", "kernel_panic"),
        "run-2",
        {"from": "SEV3", "to": "SEV2", "reviewer": "raj"},
    )
    store.put(
        ("feedback", "hdfs", "block_serve"),
        "run-3",
        {"from": "SEV2", "to": "SEV3", "reviewer": "ana"},
    )
    item = store.get(("feedback", "bgl", "kernel_panic"), "run-1")
    assert item is not None
    assert item.value["to"] == "SEV2"
    assert len(store.search(("feedback", "bgl"))) == 2
    assert len(store.search(("feedback",), filter={"reviewer": "ana"})) == 2
    assert store.search(("feedback",), query="raj")[0].key == "run-2"
    assert ("feedback", "bgl", "kernel_panic") in store.list_namespaces(prefix=("feedback",))
    assert store.list_namespaces(prefix=("feedback",), max_depth=2) == [
        ("feedback", "bgl"),
        ("feedback", "hdfs"),
    ]
    store.delete(("feedback", "hdfs", "block_serve"), "run-3")
    assert store.get(("feedback", "hdfs", "block_serve"), "run-3") is None
