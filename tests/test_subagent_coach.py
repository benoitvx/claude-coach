"""Smoke tests structurels pour le subagent coach (lot 5d).

Pas de test comportemental (impossible sans appeler Claude). On vérifie juste
que le fichier existe, que le frontmatter est parsable et complet, et que
les marqueurs clés du brief sont présents dans le corps.
"""

from __future__ import annotations

from pathlib import Path

import pytest

COACH_PATH = Path(__file__).resolve().parent.parent / ".claude" / "agents" / "coach.md"


def _parse_frontmatter(content: str) -> dict[str, str]:
    """Parse un frontmatter YAML simple (clé: valeur, valeurs multi-lignes via indentation).

    On évite PyYAML pour ne pas ajouter de dépendance.
    """
    if not content.startswith("---\n"):
        raise ValueError("Pas de frontmatter délimité par '---'")
    end = content.find("\n---\n", 4)
    if end == -1:
        raise ValueError("Frontmatter non fermé")
    body = content[4:end]
    fields: dict[str, str] = {}
    current_key: str | None = None
    for raw_line in body.splitlines():
        if raw_line.startswith((" ", "\t")) and current_key is not None:
            fields[current_key] += " " + raw_line.strip()
            continue
        if ":" not in raw_line:
            continue
        key, value = raw_line.split(":", 1)
        current_key = key.strip()
        fields[current_key] = value.strip()
    return fields


def test_coach_subagent_file_exists() -> None:
    assert COACH_PATH.exists(), f"{COACH_PATH} manquant — lot 5d non livré"


def test_coach_frontmatter_has_required_fields() -> None:
    content = COACH_PATH.read_text(encoding="utf-8")
    fields = _parse_frontmatter(content)
    assert fields.get("name") == "coach"
    assert "description" in fields and len(fields["description"]) > 30
    assert fields.get("model") in {"haiku", "sonnet", "opus"}
    assert "tools" in fields
    # Bash est obligatoire (sans lui le coach ne peut rien lire/écrire).
    assert "Bash" in fields["tools"]


def test_coach_body_mentions_key_concepts() -> None:
    """Si l'un de ces marqueurs disparaît du prompt, on a sauté un brief important."""
    content = COACH_PATH.read_text(encoding="utf-8").lower()
    expected = [
        "strava-connect activity",
        "strava-connect plan",
        "--json",
        "polarisé",
        "périodisation",
        "swim&run",
        "70.3",
    ]
    missing = [m for m in expected if m.lower() not in content]
    assert not missing, f"Marqueurs absents du prompt coach : {missing}"


@pytest.mark.parametrize("forbidden_tool", ["Edit", "Write", "WebSearch", "WebFetch"])
def test_coach_does_not_grant_write_or_web_tools(forbidden_tool: str) -> None:
    """Le coach n'a pas besoin d'éditer de fichiers ni de surfer le web (en v1).

    Si on les ajoute plus tard, mettre à jour ce test consciemment.
    """
    content = COACH_PATH.read_text(encoding="utf-8")
    fields = _parse_frontmatter(content)
    msg = f"Outil `{forbidden_tool}` présent dans tools — non prévu en lot 5d"
    assert forbidden_tool not in fields["tools"], msg
