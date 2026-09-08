"""The price table, and what happens when it does not cover a model.

Every figure in ``runs.jsonl`` comes from here. The table this replaced was
hardcoded, priced Sonnet 5 at Sonnet 4.6's rate, and had no entry for the Gemini
model two calls actually went to — so the log overstated some calls by 50% and
silently stopped counting others. Both failures are pinned below.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from jobagent.adapters.prices import (
    PRICES_FILE,
    PriceError,
    clear_unpriced,
    load_prices,
    note_unpriced,
    unpriced_models,
)


@pytest.fixture(autouse=True)
def _clean_registry():
    clear_unpriced()
    yield
    clear_unpriced()


def write_prices(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "prices.yaml"
    path.write_text(body, encoding="utf-8")
    return path


# --------------------------------------------------------------------------- #
# The file that ships
# --------------------------------------------------------------------------- #


def test_the_shipped_table_loads() -> None:
    table = load_prices()

    assert table.checked_on
    assert table.models


def test_sonnet_5_is_priced_at_its_own_rate() -> None:
    """The bug this file exists for. Sonnet 5 is $2/$10; the hardcoded table
    carried Sonnet 4.6's $3/$15, overstating every call to it by half."""
    assert load_prices().lookup("claude-sonnet-5") == (2.0, 10.0)


def test_the_models_actually_configured_are_priced() -> None:
    """`.env` routes to these. A model the app is set up to call and cannot
    price is the failure being fixed, not a hypothetical."""
    table = load_prices()

    for model in ("claude-sonnet-5", "claude-haiku-4-5-20251001", "claude-opus-5"):
        assert table.lookup(model) is not None, model


def test_every_price_is_a_positive_pair() -> None:
    table = load_prices()

    assert all(
        inp > 0 and out > 0 for inp, out in table.models.values()
    ), table.models


def test_the_table_records_where_the_prices_came_from() -> None:
    """`checked_on` alone says the file was touched, not that anyone looked."""
    data = yaml.safe_load(PRICES_FILE.read_text(encoding="utf-8"))

    assert data["sources"]


# --------------------------------------------------------------------------- #
# Matching a model id to a row
# --------------------------------------------------------------------------- #


def test_a_dated_snapshot_resolves_to_its_family(tmp_path: Path) -> None:
    table = load_prices(
        write_prices(
            tmp_path,
            "checked_on: 2026-09-08\nmodels:\n"
            "  claude-haiku-4-5: {input: 1.0, output: 5.0}\n",
        )
    )

    assert table.lookup("claude-haiku-4-5-20251001") == (1.0, 5.0)


def test_the_longest_matching_key_wins(tmp_path: Path) -> None:
    """Opus 4.1 is three times the price of the rest of the Opus family. Under
    the old substring match, `claude-opus-4` matched it first and priced it at a
    third of what it costs."""
    table = load_prices(
        write_prices(
            tmp_path,
            "checked_on: 2026-09-08\nmodels:\n"
            "  claude-opus-4-1: {input: 15.0, output: 75.0}\n"
            "  claude-opus-4-8: {input: 5.0, output: 25.0}\n",
        )
    )

    assert table.lookup("claude-opus-4-1") == (15.0, 75.0)
    assert table.lookup("claude-opus-4-8") == (5.0, 25.0)


def test_a_key_matching_mid_id_does_not_count(tmp_path: Path) -> None:
    """Prefix, not substring. A key is a model family, and a family name in the
    middle of some other id is a coincidence."""
    table = load_prices(
        write_prices(
            tmp_path,
            "checked_on: 2026-09-08\nmodels:\n"
            "  gemini-2.5-flash: {input: 0.3, output: 2.5}\n",
        )
    )

    assert table.lookup("vendor-gemini-2.5-flash-proxy") is None


def test_an_uncovered_model_has_no_price() -> None:
    assert load_prices().lookup("some-model-nobody-has-heard-of") is None


# --------------------------------------------------------------------------- #
# A malformed table fails loudly
# --------------------------------------------------------------------------- #


def test_a_missing_file_is_reported(tmp_path: Path) -> None:
    with pytest.raises(PriceError, match="No price table"):
        load_prices(tmp_path / "nope.yaml")


def test_a_table_without_a_checked_on_date_is_rejected(tmp_path: Path) -> None:
    """An undated price table cannot be told from a stale one."""
    with pytest.raises(PriceError, match="checked_on"):
        load_prices(
            write_prices(
                tmp_path, "models:\n  claude-opus-5: {input: 5.0, output: 25.0}\n"
            )
        )


def test_a_yaml_error_names_the_line(tmp_path: Path) -> None:
    with pytest.raises(PriceError, match=r"prices\.yaml:\d+:\d+"):
        load_prices(
            write_prices(tmp_path, "checked_on: 2026-09-08\nmodels:\n  a: [unclosed\n")
        )


def test_a_half_written_row_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(PriceError, match="output"):
        load_prices(
            write_prices(
                tmp_path, "checked_on: 2026-09-08\nmodels:\n  m: {input: 5.0}\n"
            )
        )


def test_a_non_numeric_price_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(PriceError, match="non-numeric"):
        load_prices(
            write_prices(
                tmp_path,
                "checked_on: 2026-09-08\nmodels:\n  m: {input: free, output: 1.0}\n",
            )
        )


# --------------------------------------------------------------------------- #
# Reporting what could not be priced
# --------------------------------------------------------------------------- #


def test_unpriced_models_are_collected_and_deduplicated() -> None:
    note_unpriced("gemini-3.6-flash")
    note_unpriced("gemini-3.6-flash")
    note_unpriced("aardvark-1")

    assert unpriced_models() == ("aardvark-1", "gemini-3.6-flash")


def test_nothing_is_reported_when_everything_priced() -> None:
    assert unpriced_models() == ()


# --------------------------------------------------------------------------- #
# The run log, and the line at the end of the command
#
# A `cost_usd: null` on its own is ambiguous — a free call and a model nobody
# priced look identical. Two calls in `runs.jsonl` are exactly that, and nothing
# anywhere said so.
# --------------------------------------------------------------------------- #


def test_an_unpriced_call_is_marked_in_the_run_log(tmp_path: Path) -> None:
    import json

    from tests.test_llm import FakeClient

    log = tmp_path / "runs.jsonl"
    FakeClient(["a"], model="model-with-no-price", runs_log_path=log).complete(
        prompt="x", label="parse_jd"
    )

    record = json.loads(log.read_text(encoding="utf-8").strip())

    assert record["cost_usd"] is None
    assert record["price_unknown"] is True
    assert unpriced_models() == ("model-with-no-price",)


def test_a_priced_call_is_not_marked(tmp_path: Path) -> None:
    import json

    from tests.test_llm import FakeClient

    log = tmp_path / "runs.jsonl"
    FakeClient(["a"], model="claude-sonnet-5", runs_log_path=log).complete(prompt="x")

    record = json.loads(log.read_text(encoding="utf-8").strip())

    assert record["price_unknown"] is False
    assert record["cost_usd"] == pytest.approx((100 * 2.0 + 50 * 10.0) / 1_000_000)
    assert unpriced_models() == ()


def test_the_command_says_what_it_could_not_price() -> None:
    from typer.testing import CliRunner

    from jobagent.cli.main import app

    note_unpriced("gemini-3.6-flash")
    result = CliRunner().invoke(app, ["config", "check"])

    assert "no price for gemini-3.6-flash" in result.stderr
    assert "prices.yaml" in result.stderr


def test_a_fully_priced_run_says_nothing() -> None:
    """A note that appears when nothing is wrong is a note its reader learns to
    skip."""
    from typer.testing import CliRunner

    from jobagent.cli.main import app

    result = CliRunner().invoke(app, ["config", "check"])

    assert "no price for" not in result.stderr
