"""
Tests for the audit pipeline. No API calls.

    uv run --project starter/algorithmic-pricing-llms --with pytest pytest probe/tests -q

The validation tests read the scripted-bot sweeps under results/bot_*; produce them with
``python -m probe.run_screen --model bot_<policy> --seeds 0`` (free).
"""

import json

import numpy as np
import polars as pl
import pytest

import probe  # noqa: F401
from probe import RESULTS
from probe import economics as econ
from probe.analysis import branch_metrics, load_all
from probe.bots import parse_market_data
from probe.branching import ProbeExperiment, load_history, strip_rival
from probe.run_branch import build_agents
from src.environment.calvano import CalvanoDemandEnvironment


def test_benchmarks_match_starter():
    assert econ.nash_price() == pytest.approx(1.4729, abs=1e-4)
    assert econ.monopoly_price() == pytest.approx(1.9250, abs=1e-4)
    assert econ.best_response(econ.nash_price()) == pytest.approx(econ.nash_price(), abs=1e-3)


def test_demand_inversion_round_trip():
    for pa, pb in [(1.9, 2.22), (1.5, 1.8), (2.5, 1.6)]:
        qa, _ = econ.quantities(pa, pb)
        assert econ.infer_rival_price(pa, round(qa, 2)) == pytest.approx(pb, abs=0.02)


def test_strip_rival_only_removes_competitor_line():
    md = "- My price: 1.8\n- Competitor's prices: {'Firm A': 1.53}\n- My quantity sold: 22.76\n"
    assert strip_rival(md) == "- My price: 1.8\n- My quantity sold: 22.76\n"


@pytest.fixture(scope="module")
def bot_parent():
    path = RESULTS / "bot_match" / "s0" / "warmup_shown" / "results.json"
    if not path.exists():
        pytest.skip("run the bot sweeps first")
    return path


def test_hidden_firm_sees_no_rival_price_in_its_prompt(bot_parent, tmp_path):
    spec = {"agent_kind": "bot", "bots": {"Firm A": {"policy": "revert"},
                                          "Firm B": {"policy": "match"}}}
    exp = ProbeExperiment(
        name="t", agents=build_agents(spec, "t"), num_rounds=31,
        environment=CalvanoDemandEnvironment("m", "d"), out_dir=tmp_path,
        start_history=load_history(bot_parent, 30), hide={"Firm B": 31})
    exp._setup_experiment()
    exp._load_start_history()
    a, b = exp.agents
    prompt_a = exp.prompt_manager.generate_prompt(a, exp.history["Firm A"], 31)
    prompt_b = exp.prompt_manager.generate_prompt(b, exp.history["Firm B"], 31)
    assert "Competitor's prices" in prompt_a
    assert "Competitor's prices" not in prompt_b
    rows = parse_market_data(prompt_b)
    assert len(rows) == 30 and all(r["rival"] is None for r in rows)
    assert all(r["quantity"] is not None for r in rows)  # own sales stay visible


def test_forced_price_is_what_the_rival_and_market_see():
    path = RESULTS / "bot_match" / "s0" / "dev-15_shown" / "results.json"
    if not path.exists():
        pytest.skip("run the bot sweeps first")
    r = json.loads(path.read_text())
    a31, b31 = r["Firm A"]["31"], r["Firm B"]["31"]
    assert a31["forced"] and a31["chosen_price"] == pytest.approx(0.85 * a31["intended_price"], abs=0.006)
    assert f"'Firm A': {a31['chosen_price']}" in b31["market_data"]
    qa, _ = econ.quantities(a31["chosen_price"], b31["chosen_price"])
    assert a31["quantity"] == pytest.approx(qa, abs=0.01)


@pytest.fixture(scope="module")
def bot_metrics():
    df = load_all()
    if df.is_empty() or df.filter(pl.col("model").str.starts_with("bot_")).is_empty():
        pytest.skip("run the bot sweeps first")
    return branch_metrics(df.filter(pl.col("model").str.starts_with("bot_")))


def _beta(bm, model, vis, sign):
    g = bm.filter((pl.col("model") == model) & (pl.col("vis") == vis) & (pl.col("sign") == sign))
    return float(np.mean(g["beta"].to_numpy())), float(np.mean(g["ratio"].to_numpy()))


# Expected signatures (METHODS.md, table 1). These are the audit's positive controls.
def test_validation_anchor(bot_metrics):
    for vis in ("shown", "hidden"):
        for sign in ("cut", "raise"):
            assert _beta(bot_metrics, "bot_anchor", vis, sign)[0] == pytest.approx(0, abs=1e-9)


def test_validation_best_response(bot_metrics):
    for sign in ("cut", "raise"):
        assert _beta(bot_metrics, "bot_br", "shown", sign)[1] == pytest.approx(1, abs=0.1)
        assert _beta(bot_metrics, "bot_br", "hidden", sign)[0] == pytest.approx(0, abs=1e-9)
        # the demand channel survives hiding: a firm can infer the hidden price from its sales
        assert _beta(bot_metrics, "bot_br_infer", "hidden", sign)[1] == pytest.approx(1, abs=0.1)


def test_validation_matching_is_symmetric(bot_metrics):
    for sign in ("cut", "raise"):
        assert _beta(bot_metrics, "bot_match", "shown", sign)[0] == pytest.approx(1, abs=0.05)
        assert _beta(bot_metrics, "bot_match", "hidden", sign)[0] == pytest.approx(0, abs=1e-9)


def test_validation_punishment_is_asymmetric(bot_metrics):
    assert _beta(bot_metrics, "bot_punish", "shown", "cut")[1] > 1.5
    assert _beta(bot_metrics, "bot_punish", "shown", "raise")[0] == pytest.approx(0, abs=1e-9)


def test_cut_only_test_cannot_separate_matching_from_punishment(bot_metrics):
    # both exceed the best-response benchmark on cuts; only raises tell them apart
    assert _beta(bot_metrics, "bot_match", "shown", "cut")[1] > 1.5
    assert _beta(bot_metrics, "bot_punish", "shown", "cut")[1] > 1.5
    assert _beta(bot_metrics, "bot_match", "shown", "raise")[1] > 1.5
    assert _beta(bot_metrics, "bot_punish", "shown", "raise")[1] < 0.5


def test_rho_recovered(bot_metrics):
    g = bot_metrics.filter(pl.col("model") == "bot_anchor")
    assert float(np.mean(g["rho"].to_numpy())) == pytest.approx(0.5, abs=0.05)


def test_advice_is_appended_to_the_llm_prompt():
    from probe.run_branch import AdvisedLLMAgent
    from probe.branching import ADVICE_TEXT
    from src.agents.llm_providers import Provider
    from src.prompts.prompts import GENERAL_PROMPT, P1
    from src.prompts.prompts_models import create_pricing_response_model

    agent = AdvisedLLMAgent("Firm A", prefix=P1, provider=Provider(),
                            response_model=create_pricing_response_model(include_wtp=True,
                                                                         wtp_value=4.51),
                            prompt_template=GENERAL_PROMPT,
                            env_params={"a": 2.0, "alpha": 1.0, "c": 1.0})
    agent.advice_text = ADVICE_TEXT.format(price=1.47)
    user = agent.build_messages("MARKET PROMPT")[-1]["content"]
    assert user.startswith("MARKET PROMPT") and "recommends that you set your price to 1.47" in user


def _late_means(model, run, after=50):
    path = RESULTS / model / "s0" / run / "environment_history.parquet"
    if not path.exists():
        pytest.skip("run the bot entry sweeps first")
    df = pl.read_parquet(path).filter(pl.col("round") > after)
    return dict(df.group_by("agent").agg(pl.col("price").mean()).iter_rows())


def test_entrant_learns_best_response_to_anchored_incumbents():
    # Thread B prediction: against non-responsive incumbents a no-regret entrant converges to
    # its best response to them, and the incumbents do not move.
    m = _late_means("bot_anchor", "entry_mw")
    assert m["Firm A"] == pytest.approx(1.80) and m["Firm B"] == pytest.approx(1.80)
    assert m["Firm C"] == pytest.approx(econ.best_response_n((1.80, 1.80)), abs=0.08)
    assert m["Firm C"] > econ.nash_price_n(3)  # supracompetitive, without any threat


def test_entrant_lowers_prices_when_incumbents_respond():
    anchored, responsive = _late_means("bot_anchor", "entry_mw"), _late_means("bot_br", "entry_mw")
    assert responsive["Firm B"] < anchored["Firm B"] - 0.2
