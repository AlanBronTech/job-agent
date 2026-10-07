"""SC-005: a four-question form with a limit, from the answer bank, no story twice."""

from __future__ import annotations

import pytest

from jobagent.core.generate import build_answers
from jobagent.core.profile import load_profile
from tests.quality_seed import PEOPLE, RoutedClient, northwind, northwind_assessment

QUESTIONS = [
    "Why do you want to work at Northwind Freight?",
    "Why this role?",
    "Tell us about a time you grew an engineer.",
    "What is your notice period?",
]


@pytest.fixture
def profile(example_dir):
    return load_profile(example_dir)


def s(text, *cites):
    return {"text": text, "cites": list(cites)}


def answer(question, kind, short, long):
    return {"question": question, "type": kind, "short": short, "long": long}


def clean_form():
    return {"answers": [
        answer(QUESTIONS[0], "why_company",
               [s("You build route planning for regional freight carriers.", "ad")],
               [s("You build route planning for regional freight carriers.", "ad"),
                s("The team of eight is the size I have grown before.", "ad")]),
        answer(QUESTIONS[1], "why_role",
               [s("It leads with coaching, which is the work I do best.", "ad")],
               [s("It leads with coaching.", "ad"),
                s("I ran performance and career development for a 15-person team.", "recent_manager.0")]),
        answer(QUESTIONS[2], "other",
               [s("I recruited, trained and led a distributed team of 6.", "startup_em.0")],
               [s("I recruited, trained and led a distributed team of 6.", "startup_em.0"),
                s("We delivered a full platform build in 8 months on budget.", "startup_em.0")]),
        answer(QUESTIONS[3], "notice_period",
               [s("Available to start within two weeks.", "notice_period")],
               [s("Available to start within two weeks.", "notice_period")]),
    ]}


def run(profile, *payloads, limit=600):
    client = RoutedClient({"generate_answers": list(payloads)})
    built = build_answers(QUESTIONS, northwind(), profile, northwind_assessment(),
                          client=client, kind=PEOPLE, limit=limit)
    return built, client.prompts["generate_answers"]


def test_four_answers_within_the_limit_with_both_variants(profile):
    built, prompts = run(profile, clean_form())
    assert built.issues == [] and len(prompts) == 1
    assert len(built.answers) == 4
    for a in built.answers:
        for variant in (a.short, a.long):
            assert len(" ".join(x.text for x in variant)) <= 600
    assert built.text.count("### ") == 4 and "**Short**" in built.text and "**Long**" in built.text


def test_the_bank_and_the_limit_reach_the_prompt(profile):
    _, prompts = run(profile, clean_form())
    assert "notice_period: Available to start within two weeks." in prompts[0]
    assert "600 characters" in prompts[0]
    assert "underperformer" not in prompts[0]  # excluded for people-focused


def test_over_the_limit_blocks_and_regenerates_once(profile):
    long_form = clean_form()
    long_form["answers"][1]["long"].append(s("x" * 700, "ad"))
    built, prompts = run(profile, long_form, clean_form())
    assert len(prompts) == 2 and "answer over limit" in prompts[1]
    assert built.issues == []


def test_a_story_in_two_answers_blocks(profile):
    form = clean_form()
    form["answers"][1]["long"].append(s("I recruited and led a team of 6.", "startup_em.1"))
    form["answers"][2]["long"].append(s("When overruled I committed.", "scope_disagreement"))
    built, _ = run(profile, form, form)
    assert any(i.rule == "story reused" for i in built.issues)


def test_why_company_citing_the_profile_blocks(profile):
    form = clean_form()
    form["answers"][0]["short"] = [s("I know freight from my last role.", "recent_manager.0")]
    built, _ = run(profile, form, form)
    assert any(i.rule == "company claim not from the ad" for i in built.issues)


def test_every_answer_sentence_is_traced(profile):
    form = clean_form()
    form["answers"][2]["short"] = [s("I coached a junior to a promotion.")]
    built, _ = run(profile, form, form)
    assert any(i.rule == "uncited claim" for i in built.issues)
