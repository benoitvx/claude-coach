from __future__ import annotations

import xml.etree.ElementTree as ET

import pytest

from claude_coach.zwo import (
    Block,
    blocks_from_json,
    blocks_to_json,
    generate_zwo,
    is_bike,
    parse_blocks,
)


def test_is_bike() -> None:
    assert is_bike("Ride")
    assert is_bike("VirtualRide")
    assert is_bike("GravelRide")
    assert not is_bike("Run")
    assert not is_bike("Swim")


def test_parse_steady() -> None:
    blocks = parse_blocks("40m@65")
    assert blocks == [Block(kind="steady", duration_s=2400, power=0.65)]


def test_parse_seconds_duration() -> None:
    blocks = parse_blocks("90s@110")
    assert blocks[0].duration_s == 90
    assert blocks[0].power == 1.1


def test_parse_warmup_and_cooldown() -> None:
    blocks = parse_blocks("warmup:10m:50-65; cooldown:8m:65-50")
    assert blocks[0] == Block(kind="warmup", duration_s=600, power_from=0.5, power_to=0.65)
    assert blocks[1] == Block(kind="cooldown", duration_s=480, power_from=0.65, power_to=0.5)


def test_parse_intervals() -> None:
    blocks = parse_blocks("3x[12m@95;4m@60]")
    assert blocks == [
        Block(
            kind="intervals",
            repeat=3,
            on_duration_s=720,
            on_power=0.95,
            off_duration_s=240,
            off_power=0.6,
        )
    ]


def test_parse_full_session() -> None:
    dsl = "warmup:10m:50-65; 3x[12m@95;4m@60]; 10m@65; cooldown:8m:65-50"
    kinds = [b.kind for b in parse_blocks(dsl)]
    assert kinds == ["warmup", "intervals", "steady", "cooldown"]


@pytest.mark.parametrize(
    "dsl",
    [
        "",
        "   ",
        "60x@65",  # durée invalide
        "10m@0",  # puissance sous la borne
        "10m@201",  # puissance au-dessus de la borne
        "10h@65",  # unité de durée invalide
        "3x[12m@95]",  # un seul sous-bloc
        "3x[12m@95;4m@60;2m@50]",  # trois sous-blocs
        "0x[12m@95;4m@60]",  # zéro répétition
        "3x[12m@95;4m@60",  # crochet non fermé
        "n'importe quoi",
    ],
)
def test_parse_invalid_raises(dsl: str) -> None:
    with pytest.raises(ValueError):
        parse_blocks(dsl)


def test_json_round_trip() -> None:
    dsl = "warmup:10m:50-65; 3x[12m@95;4m@60]; 10m@65; cooldown:8m:65-50"
    blocks = parse_blocks(dsl)
    restored = blocks_from_json(blocks_to_json(blocks))
    assert restored == blocks


def test_blocks_from_json_rejects_non_list() -> None:
    with pytest.raises(ValueError):
        blocks_from_json('{"kind": "steady"}')


def test_generate_zwo_structure() -> None:
    dsl = "warmup:10m:50-65; 3x[12m@95;4m@60]; 10m@65; cooldown:8m:65-50"
    xml = generate_zwo(name="Seuil 3x12", description="bloc build", blocks=parse_blocks(dsl))

    assert xml.startswith('<?xml version="1.0" encoding="UTF-8"?>')
    root = ET.fromstring(xml.split("?>", 1)[1])
    assert root.tag == "workout_file"
    assert root.findtext("sportType") == "bike"
    assert root.findtext("name") == "Seuil 3x12"
    assert root.findtext("author") == "claude-coach"

    workout = root.find("workout")
    assert workout is not None
    children = list(workout)
    assert [c.tag for c in children] == ["Warmup", "IntervalsT", "SteadyState", "Cooldown"]

    warmup = children[0]
    assert warmup.attrib == {"Duration": "600", "PowerLow": "0.5", "PowerHigh": "0.65"}

    intervals = children[1]
    assert intervals.attrib["Repeat"] == "3"
    assert intervals.attrib["OnDuration"] == "720"
    assert intervals.attrib["OffPower"] == "0.6"

    # Le cooldown descend : PowerHigh (départ) > PowerLow (arrivée).
    cooldown = children[3]
    assert cooldown.attrib == {"Duration": "480", "PowerLow": "0.5", "PowerHigh": "0.65"}


def test_generate_zwo_empty_raises() -> None:
    with pytest.raises(ValueError):
        generate_zwo(name="x", description=None, blocks=[])
