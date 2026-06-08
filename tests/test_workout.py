from __future__ import annotations

import pytest

from claude_coach.workout import (
    Repetition,
    Step,
    parse_workout,
    workout_from_json,
    workout_to_json,
)


def test_parse_steady_hr_range() -> None:
    assert parse_workout("45min@h140-150") == [
        Step("active", "duration", 2700, "heartrate", 140.0, 150.0)
    ]


def test_parse_no_target_step() -> None:
    assert parse_workout("10min") == [Step("active", "duration", 600, "no_target", None, None)]


def test_parse_distance_and_pace() -> None:
    # 4:00/km = 240 s/km → 1000/240 = 4.167 m/s, cible simple → min == max.
    assert parse_workout("400m@p4:00") == [Step("active", "distance", 400, "pace", 4.167, 4.167)]


def test_parse_pace_range_sorted_to_mps() -> None:
    # 3:45 → 4.444 m/s (plus rapide) ; 4:15 → 3.922 m/s (plus lent) → min/max triés.
    (step,) = parse_workout("1km@p3:45-4:15")
    assert isinstance(step, Step)
    assert step.target_type == "pace"
    assert step.duration_type == "distance"
    assert step.duration_value == 1000
    assert step.target_min == 3.922
    assert step.target_max == 4.444


def test_parse_warmup_cooldown_intensity() -> None:
    items = parse_workout("warmup:15min@h120-140 ; cooldown:10min@h120")
    assert items == [
        Step("warmup", "duration", 900, "heartrate", 120.0, 140.0),
        Step("cooldown", "duration", 600, "heartrate", 120.0, 120.0),
    ]


def test_parse_repetition_with_rest() -> None:
    items = parse_workout("6x[400m@p3:45;rest:90s@h130]")
    assert items == [
        Repetition(
            6,
            (
                Step("active", "distance", 400, "pace", 4.444, 4.444),
                Step("rest", "duration", 90, "heartrate", 130.0, 130.0),
            ),
        )
    ]


def test_parse_full_session() -> None:
    dsl = "warmup:15min@h120-140 ; 6x[400m@p3:45;rest:90s] ; cooldown:10min@h120"
    items = parse_workout(dsl)
    assert len(items) == 3
    assert isinstance(items[1], Repetition)
    rest_step = items[1].steps[1]
    assert rest_step.intensity == "rest"
    assert rest_step.target_type == "no_target"


def test_power_target_watts() -> None:
    (step,) = parse_workout("20min@w250")
    assert isinstance(step, Step)
    assert step.target_type == "power"
    assert step.target_min == 250.0
    assert step.target_max == 250.0


@pytest.mark.parametrize(
    "dsl",
    [
        "",
        "   ",
        "10foo",  # unité de durée invalide
        "0min",  # durée nulle
        "40min@p3:99",  # secondes d'allure invalides
        "40min@p1:00",  # allure hors borne (< 2:00/km)
        "40min@h300",  # FC hors borne
        "40min@w0",  # puissance hors borne
        "40min@x99",  # préfixe de cible inconnu
        "40min@",  # cible vide
        "6x[400m@p4:00",  # crochet non fermé
        "0x[400m@p4:00]",  # répétitions < 1
        "3x[]",  # répétition vide
    ],
)
def test_parse_invalid_raises(dsl: str) -> None:
    with pytest.raises(ValueError):
        parse_workout(dsl)


def test_json_round_trip() -> None:
    dsl = "warmup:15min@h120-140 ; 6x[400m@p3:45;rest:90s] ; 10min@w250 ; cooldown:10min@h120"
    items = parse_workout(dsl)
    assert workout_from_json(workout_to_json(items)) == items


def test_workout_from_json_rejects_non_list() -> None:
    with pytest.raises(ValueError):
        workout_from_json('{"not": "a list"}')
