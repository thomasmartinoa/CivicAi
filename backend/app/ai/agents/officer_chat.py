"""The officer chat agent.

A ReAct loop over the read-only tools in `app/ai/tools/officer.py`. Built on
LangChain's `create_agent` rather than hand-rolled, because the tool-call plumbing is
the boring part and the interesting decisions are elsewhere. (Not LangGraph's
`create_react_agent`, which is the same thing deprecated since LangGraph 1.0 and due
for removal in 2.0.)

**The step bound is a quota control, not a safety rail.** A confused agent will keep
calling tools, and at the free tier's 0.2 requests per second every step is five
seconds of an officer's time and one of 500 daily calls. `MAX_AGENT_STEPS` caps it,
and hitting the cap produces an answer saying so rather than an exception — an
officer who asked a hard question should be told the agent gave up, not shown a 500.

**The agent never constructs its model or its tools.** Both arrive as arguments, the
same rule the graph nodes follow, because a loop that built its own model could not
be tested: a scripted fake is the only way to drive the branch where the model calls
three tools and then answers.

**Nothing here is persisted by this module.** The caller records the conversation, so
a test can run the loop without a database.
"""

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

MAX_AGENT_STEPS = 6
"""Model turns before the loop is cut off.

Six is enough for the questions these tools were built for — the worst realistic case
is "who should take CIV-X" which needs `get_complaint` then `contractor_options`,
possibly with a `search_policy` to justify it — and it bounds a runaway at roughly
thirty seconds and six calls rather than an open-ended spend."""

# create_react_agent counts every node visit, and one model turn that calls a tool is
# two visits. The +1 admits the final model turn that answers without a tool call.
RECURSION_LIMIT = MAX_AGENT_STEPS * 2 + 1

STEP_LIMIT_MESSAGE = (
    "I could not answer that within my step limit. Try asking about one thing at a "
    "time, or give me a tracking id."
)


@dataclass
class ToolCall:
    """One tool invocation, for the transcript and the SSE stream."""

    name: str
    args: dict
    result: Any = None


@dataclass
class ChatResult:
    answer: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    hit_step_limit: bool = False
    """True when the loop was cut off. The answer is then STEP_LIMIT_MESSAGE, and a
    caller showing this to an officer should make the difference visible rather than
    presenting a surrender as a conclusion."""


def system_text(prompt) -> str:
    """The system message out of a registered ChatPromptTemplate.

    `create_agent` wants a plain string, while the registry holds templates so every
    prompt in the project is versioned the same way. Rendering with no messages and
    reading the first message is the public-API way to bridge the two — poking at
    `.messages[0].prompt.template` would break on any template restructure.
    """
    return prompt.invoke({"messages": []}).to_messages()[0].content


def build_officer_agent(model, tools, *, prompt=None):
    """Compile the ReAct graph.

    `model` must support `bind_tools`, which is why tests need a scripted fake chat
    model rather than the `RunnableLambda` the graph nodes take.
    """
    from langchain.agents import create_agent

    from app.ai.prompts import get_prompt

    return create_agent(
        model=model,
        tools=tools,
        system_prompt=system_text(prompt if prompt is not None
                                  else get_prompt("officer_chat")),
    )


def _history_to_messages(history: list[dict] | None) -> list:
    """Turn the client's `[{role, content}]` into LangChain messages.

    Anything that is not a recognised role is dropped rather than guessed at. The
    history arrives over HTTP from a browser, so a malformed entry is a bad request
    and not something to improvise a role for.
    """
    from langchain_core.messages import AIMessage, HumanMessage

    messages = []
    for entry in history or []:
        role = (entry.get("role") or "").lower()
        content = entry.get("content") or ""
        if not content:
            continue
        if role in ("user", "human"):
            messages.append(HumanMessage(content))
        elif role in ("assistant", "ai"):
            messages.append(AIMessage(content))
    return messages


def _message_text(message) -> str:
    """The text of an AI message, whatever shape the provider used.

    Gemini 3 returns `content` as a list of content blocks — `[{"type": "text",
    "text": "...", "extras": {...}}]` — not a string. An `isinstance(content, str)`
    check therefore discards the answer silently, which is exactly what the first
    live conversation did: the agent searched the corpus, got four passages, and
    reported "I ran the tools but did not produce an answer."

    `.text` is LangChain's own accessor and handles both shapes. A property, not a
    method — calling it is deprecated.
    """
    try:
        return (message.text or "").strip()
    except Exception:  # noqa: BLE001 - an exotic content shape must not end a turn
        content = message.content
        return content.strip() if isinstance(content, str) else ""


def _collect(messages: list) -> tuple[str, list[ToolCall]]:
    """The final answer and the tool calls that produced it.

    Tool results are matched to their calls by `tool_call_id`, not by order: a model
    may request several tools in one turn and LangGraph does not promise the results
    come back in the order they were asked for.
    """
    from langchain_core.messages import AIMessage, ToolMessage

    calls: dict[str, ToolCall] = {}
    order: list[str] = []
    answer = ""

    for message in messages:
        if isinstance(message, AIMessage):
            for requested in message.tool_calls or []:
                call_id = requested.get("id") or f"{requested['name']}:{len(order)}"
                calls[call_id] = ToolCall(name=requested["name"],
                                          args=dict(requested.get("args") or {}))
                order.append(call_id)
            # The last AI message with text is the answer. An AI message that only
            # requests tools has no text and is not one.
            text = _message_text(message)
            if text:
                answer = text
        elif isinstance(message, ToolMessage):
            existing = calls.get(message.tool_call_id)
            if existing is not None:
                existing.result = message.content

    return answer, [calls[cid] for cid in order]


async def run_officer_chat(question: str, *, agent, history: list[dict] | None = None) -> ChatResult:
    """Answer one question. Returns the answer and the tool calls behind it.

    A step-limit overrun is a result, not an exception: `hit_step_limit` is set and
    the answer says the agent gave up.
    """
    from langchain_core.messages import HumanMessage
    from langgraph.errors import GraphRecursionError

    messages = [*_history_to_messages(history), HumanMessage(question)]
    try:
        final = await agent.ainvoke(
            {"messages": messages},
            config={"recursion_limit": RECURSION_LIMIT},
        )
    except GraphRecursionError:
        logger.info("the officer agent hit its step limit on: %s", question[:120])
        return ChatResult(answer=STEP_LIMIT_MESSAGE, hit_step_limit=True)

    answer, calls = _collect(final["messages"])
    if not answer:
        # The loop ended without the model saying anything — a tool-call turn with no
        # follow-up. Reporting an empty bubble would look like a hung screen.
        answer = ("I ran the tools but did not produce an answer. Please ask again.")
    return ChatResult(answer=answer, tool_calls=calls)


async def stream_officer_chat(question: str, *, agent, history: list[dict] | None = None):
    """Yield `(event, payload)` pairs as the agent works.

    Events: `tool_call`, `tool_result`, `answer`, `error`. The SSE endpoint maps these
    onto the wire; keeping the mapping out of here is what lets a test assert the
    sequence without HTTP.

    Tool calls are surfaced *as they happen* because that is what the spec asks for —
    an officer watching "searching the roads SOP…" understands a four-second pause,
    where a spinner does not.
    """
    from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
    from langgraph.errors import GraphRecursionError

    messages = [*_history_to_messages(history), HumanMessage(question)]
    answered = False
    try:
        async for chunk in agent.astream(
            {"messages": messages},
            config={"recursion_limit": RECURSION_LIMIT},
            stream_mode="updates",
        ):
            for update in chunk.values():
                for message in (update or {}).get("messages", []):
                    if isinstance(message, AIMessage):
                        for requested in message.tool_calls or []:
                            yield "tool_call", {"name": requested["name"],
                                                "args": dict(requested.get("args") or {})}
                        text = _message_text(message)
                        if text:
                            answered = True
                            yield "answer", {"text": text}
                    elif isinstance(message, ToolMessage):
                        yield "tool_result", {"name": message.name,
                                              "result": message.content}
    except GraphRecursionError:
        yield "answer", {"text": STEP_LIMIT_MESSAGE, "hit_step_limit": True}
        return
    except Exception as exc:  # noqa: BLE001 - the stream is the only error channel
        # The connection is already open, so raising would drop it with no
        # explanation. A terminal error event is the only way the screen learns.
        logger.warning("the officer agent failed mid-stream: %s", exc)
        yield "error", {"message": "The assistant is unavailable. Please try again."}
        return

    if not answered:
        yield "answer", {"text": "I ran the tools but did not produce an answer. "
                                 "Please ask again."}
