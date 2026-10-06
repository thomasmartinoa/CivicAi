"""The officer chat request.

There is no response model: the endpoint streams Server-Sent Events, so what a client
receives is a sequence of framed events rather than one JSON body. The event names
and their payloads are documented on the route.
"""

from pydantic import BaseModel, Field


class ChatTurn(BaseModel):
    """One earlier turn, replayed by the client.

    The conversation lives in the browser, not on the server. That is a deliberate
    limit for this phase and not an oversight: a server-side session store is worth
    building once a screen exists that needs one, and until then the simplest thing
    that cannot leak one officer's conversation into another's is to keep it client
    side.

    A role the agent does not recognise is dropped rather than guessed at, so a
    client cannot smuggle a system turn in here — see
    `app/ai/agents/officer_chat.py::_history_to_messages`.
    """

    role: str
    content: str


class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    """Capped because it is sent to a model on every turn along with the whole
    history, and an unbounded question is an unbounded bill."""

    history: list[ChatTurn] = Field(default_factory=list, max_length=40)
