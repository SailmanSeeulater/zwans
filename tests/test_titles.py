import asyncio

from zwans.messages import TextBlock
from zwans.providers.base import ModelResponse
from zwans.providers.fake import FakeProvider
from zwans.titles import clean_title, request, title_model, write_title


def test_a_claude_session_asks_haiku_and_others_ask_themselves() -> None:
    assert title_model(None, "claude-opus-5-5") == "claude-haiku-5-5"
    assert title_model(None, "ollama/qwen3-coder:30b") is None
    assert title_model("ollama/qwen3:8b", "claude-opus-5-5") == "ollama/qwen3:8b"


def test_titles_are_cleaned_of_what_models_add() -> None:
    assert clean_title('"Fix the CSV parser."') == "Fix the CSV parser"
    labelled = "Title: **Retry with backoff**\n\nThis names the task."
    assert clean_title(labelled) == "Retry with backoff"
    assert clean_title("  \n  Split   inventory module  ") == "Split inventory module"
    long = clean_title(
        "Rename parse amount to parse money everywhere in the billing code and its tests"
    )
    assert len(long) <= 60 and long.endswith("…") and " " in long
    assert clean_title("...") == ""


def test_the_request_holds_the_prompt_and_the_start_of_the_reply() -> None:
    (message,) = request("Fix the parser", "The bug is in tokenize." * 100)
    block = message.content[0]
    assert isinstance(block, TextBlock)
    text = block.text
    assert text.startswith("The task:\nFix the parser")
    assert "The start of the reply:" in text
    assert len(text) < 1_000


def test_writing_a_title_returns_it_with_the_response_for_its_cost() -> None:
    said = ModelResponse(
        content=[TextBlock(text="Fix the CSV parser.")], stop_reason="end_turn", input_tokens=40
    )
    title, response = asyncio.run(write_title(FakeProvider([said]), "Quoted commas break", ""))
    assert title == "Fix the CSV parser"
    assert response is not None and response.input_tokens == 40
