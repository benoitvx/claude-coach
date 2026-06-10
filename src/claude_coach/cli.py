from __future__ import annotations

import json
import re
from contextlib import closing
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Literal, cast

import click

from claude_coach.auth import (
    AuthError,
    ConfigError,
    load_config,
    load_tokens,
    start_oauth_flow,
    token_path_from_env,
)
from claude_coach.coach import (
    KNOWN_FAMILIES,
    MatchResult,
    is_indoor_power_ride,
    match_all_planned_sessions,
    session_deltas,
    sport_types_in_family,
)
from claude_coach.db import (
    GOAL_STATUSES,
    PLAN_STATUSES,
    SESSION_STATUSES,
    aggregate_activities,
    connect,
    count_activities,
    db_path_from_env,
    delete_debrief,
    delete_planned_session,
    get_activity,
    get_debrief,
    get_goal,
    get_last_sync,
    get_latest_metrics,
    get_metrics_history,
    get_planned_session,
    get_training_plan,
    insert_athlete_metrics,
    insert_debrief,
    insert_goal,
    insert_planned_session,
    insert_training_plan,
    list_activities,
    list_debriefs,
    list_goals,
    list_laps,
    list_planned_sessions,
    list_streams,
    list_training_plans,
    metrics_values_equal,
    migrate,
    stats_by_sport,
    update_debrief,
    update_goal_status,
    update_planned_session_blocks,
    update_planned_session_status,
    update_training_plan_status,
)
from claude_coach.intervals import (
    IntervalsClient,
    IntervalsClientError,
    build_event_payload,
    intervals_sport_type,
    load_intervals_config,
    workout_doc_from_blocks,
    workout_doc_from_items,
)
from claude_coach.models import Activity, PlannedSession, SessionDebrief
from claude_coach.serializers import (
    activity_to_dict,
    athlete_metrics_to_dict,
    bucket_to_dict,
    debrief_to_dict,
    goal_to_dict,
    lap_to_dict,
    planned_session_to_dict,
    stream_to_dict,
    sync_log_to_dict,
    training_plan_to_dict,
)
from claude_coach.sync import LOOKBACK_DAYS_DEFAULT, sync_full, sync_incremental
from claude_coach.workout import parse_workout, workout_from_json, workout_to_json
from claude_coach.zwo import blocks_from_json, blocks_to_json, generate_zwo, parse_blocks


def _emit_json(data: object) -> None:
    """Écrit un objet en JSON stable (clés triées, indenté, UTF-8 non échappé)."""
    click.echo(json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False))


@click.group()
def main() -> None:
    """Connecteur CLI Strava."""


@main.command()
def auth() -> None:
    """Lance le flow OAuth2 (à exécuter une fois)."""
    try:
        config = load_config()
    except ConfigError as exc:
        raise click.ClickException(str(exc)) from exc

    tokens_path = token_path_from_env()
    try:
        tokens = start_oauth_flow(config, tokens_path)
    except AuthError as exc:
        raise click.ClickException(str(exc)) from exc

    click.echo(f"OK — tokens stockés dans {tokens_path} (athlete_id={tokens.athlete_id})")


@main.group("intervals")
def intervals_group() -> None:
    """Intégration intervals.icu (gratuit) : push de séances vers la montre Suunto.

    Auth = clé API perso (pas d'OAuth) : génère-la dans intervals.icu → Settings →
    Developer Settings, puis renseigne `intervals_api_key` et `intervals_athlete_id`
    dans data/config.json (ou les env vars INTERVALS_API_KEY / INTERVALS_ATHLETE_ID).
    Coche aussi « Upload planned workouts » dans /settings pour la synchro Suunto.
    """


@intervals_group.command("status")
@click.option("--json", "json_out", is_flag=True, help="Sortie JSON parseable")
def intervals_status(json_out: bool) -> None:
    """Affiche l'état de la config intervals.icu (clé API + athlete_id)."""
    try:
        config = load_intervals_config()
        config_present = True
        athlete_id: str | None = config.athlete_id
    except ConfigError:
        config_present = False
        athlete_id = None
    if json_out:
        _emit_json({"config_present": config_present, "athlete_id": athlete_id})
        return
    click.echo(f"Config intervals.icu : {'OK' if config_present else 'manquante'}")
    if config_present:
        click.echo(f"Athlete id           : {athlete_id}")
    else:
        click.echo("Renseigne intervals_api_key / intervals_athlete_id dans data/config.json")


@main.command()
@click.option("--json", "json_out", is_flag=True, help="Sortie JSON parseable")
def status(json_out: bool) -> None:
    """Affiche l'état de la DB, des tokens et de la dernière sync."""
    db_path = db_path_from_env()
    tokens_path = token_path_from_env()
    tokens = load_tokens(tokens_path) if tokens_path.exists() else None

    if json_out:
        payload: dict[str, object] = {
            "db_path": str(db_path),
            "db_exists": db_path.exists(),
            "db_size_kb": None,
            "activities_count": None,
            "by_sport": None,
            "last_sync": None,
            "tokens": None,
            "athlete_metrics": None,
        }
        if db_path.exists():
            payload["db_size_kb"] = round(db_path.stat().st_size / 1024, 1)
            with closing(connect(db_path)) as conn:
                migrate(conn)
                payload["activities_count"] = count_activities(conn)
                payload["by_sport"] = stats_by_sport(conn)
                last = get_last_sync(conn)
                payload["last_sync"] = sync_log_to_dict(last) if last else None
                if tokens is not None:
                    metrics = get_latest_metrics(conn, tokens.athlete_id)
                    payload["athlete_metrics"] = (
                        athlete_metrics_to_dict(metrics) if metrics else None
                    )
        if tokens is not None:
            remaining = tokens.expires_at - datetime.now(tz=UTC)
            payload["tokens"] = {
                "tokens_path": str(tokens_path),
                "athlete_id": tokens.athlete_id,
                "expires_at": tokens.expires_at.isoformat(),
                "expires_in_seconds": int(remaining.total_seconds()),
            }
        _emit_json(payload)
        return

    click.echo(f"DB           : {db_path}")
    if db_path.exists():
        size_kb = db_path.stat().st_size / 1024
        click.echo(f"  taille     : {size_kb:.1f} KB")
        with closing(connect(db_path)) as conn:
            migrate(conn)
            count = count_activities(conn)
            click.echo(f"  activités  : {count}")
            if count > 0:
                for sport, n in stats_by_sport(conn).items():
                    click.echo(f"    - {sport:<20} {n}")
            last = get_last_sync(conn)
            if last is None:
                click.echo("  dernière sync : jamais")
            else:
                click.echo(
                    f"  dernière sync : {last.started_at.isoformat()} "
                    f"({last.sync_type}, {last.status}, {last.activities_fetched} activités)"
                )
    else:
        click.echo("  fichier absent — aucune sync exécutée pour l'instant.")

    click.echo(f"\nTokens       : {tokens_path}")
    if tokens is None:
        click.echo("  absent — lance `claude-coach auth` pour démarrer.")
        return

    remaining = tokens.expires_at - datetime.now(tz=UTC)
    click.echo(f"  athlete_id : {tokens.athlete_id}")
    click.echo(
        f"  expire dans : {int(remaining.total_seconds() // 60)} min "
        f"(à {tokens.expires_at.astimezone(UTC).isoformat()})"
    )

    if not db_path.exists():
        return
    with closing(connect(db_path)) as conn:
        migrate(conn)
        metrics = get_latest_metrics(conn, tokens.athlete_id)
    if metrics is None:
        click.echo("  profil athlète : aucun (saisis avec `claude-coach athlete set ...`)")
    else:
        click.echo(
            f"  profil athlète : poids={metrics.weight_kg} kg, "
            f"FTP={metrics.ftp_watts}, FCmax={metrics.fc_max}, "
            f"FCrepos={metrics.fc_repos}, VMA={metrics.vma_kmh} km/h"
        )


@main.command()
@click.option(
    "--full",
    is_flag=True,
    help="Import complet (history_days = config). Sans ce flag : sync incrémentale.",
)
@click.option(
    "--limit",
    type=int,
    default=None,
    help="Limite N activités max (utile pour smoke test).",
)
@click.option(
    "--lookback-days",
    type=int,
    default=LOOKBACK_DAYS_DEFAULT,
    show_default=True,
    help="Sync incrémentale : nombre de jours à relire avant la dernière activité connue.",
)
def sync(full: bool, limit: int | None, lookback_days: int) -> None:
    """Synchronise les activités Strava dans la DB locale.

    Sans option : sync incrémentale (depuis la dernière activité connue,
    avec lookback configurable). Avec `--full` : import complet sur
    `history_days` jours.
    """
    try:
        config = load_config()
    except ConfigError as exc:
        raise click.ClickException(str(exc)) from exc

    db_path = db_path_from_env()
    tokens_path = token_path_from_env()

    def _on_progress(n: int, name: str) -> None:
        click.echo(f"  ↳ [{n}] {name}", err=True)

    def _on_warn(msg: str) -> None:
        click.echo(f"⚠ {msg}", err=True)

    try:
        if full:
            fetched, status = sync_full(
                config,
                db_path,
                tokens_path,
                history_days=config.history_days,
                limit=limit,
                on_progress=_on_progress,
                on_warn=_on_warn,
            )
        else:
            fetched, status = sync_incremental(
                config,
                db_path,
                tokens_path,
                lookback_days=lookback_days,
                history_days_fallback=config.history_days,
                limit=limit,
                on_progress=_on_progress,
                on_warn=_on_warn,
            )
    except AuthError as exc:
        raise click.ClickException(str(exc)) from exc

    click.echo(f"\n{fetched} activités importées (status={status})")
    if status == "partial":
        click.echo("→ Quota journalier atteint, relance demain pour finir.")


# --- Sous-commandes athlete (Lot 4) -----------------------------------------


def _require_athlete_id() -> int:
    tokens = load_tokens(token_path_from_env())
    if tokens is None:
        raise click.ClickException("Aucun token stocké. Lance d'abord `claude-coach auth`.")
    return tokens.athlete_id


@main.group()
def athlete() -> None:
    """Gestion des données athlète (poids, FTP, FCmax, FCrepos, VMA)."""


@athlete.command("set")
@click.option("--weight", type=float, default=None, help="Poids en kg")
@click.option("--ftp", type=int, default=None, help="FTP en watts")
@click.option("--fc-max", type=int, default=None, help="Fréquence cardiaque max")
@click.option("--fc-repos", type=int, default=None, help="Fréquence cardiaque au repos")
@click.option("--vma", type=float, default=None, help="VMA en km/h")
@click.option("--note", type=str, default=None, help="Note libre (max ~500 chars)")
def athlete_set(
    weight: float | None,
    ftp: int | None,
    fc_max: int | None,
    fc_repos: int | None,
    vma: float | None,
    note: str | None,
) -> None:
    """Enregistre une nouvelle entrée de métriques (avec timestamp)."""
    if all(v is None for v in (weight, ftp, fc_max, fc_repos, vma)) and note is None:
        raise click.ClickException("Aucune valeur fournie. Utilise --weight/--ftp/...")

    athlete_id = _require_athlete_id()
    db_path = db_path_from_env()
    with closing(connect(db_path)) as conn:
        migrate(conn)
        previous = get_latest_metrics(conn, athlete_id)
        effective_weight = (
            weight if weight is not None else (previous.weight_kg if previous else None)
        )
        effective_ftp = ftp if ftp is not None else (previous.ftp_watts if previous else None)
        effective_fc_max = fc_max if fc_max is not None else (previous.fc_max if previous else None)
        effective_fc_repos = (
            fc_repos if fc_repos is not None else (previous.fc_repos if previous else None)
        )
        effective_vma = vma if vma is not None else (previous.vma_kmh if previous else None)

        if note is None and metrics_values_equal(
            previous,
            weight_kg=effective_weight,
            ftp_watts=effective_ftp,
            fc_max=effective_fc_max,
            fc_repos=effective_fc_repos,
            vma_kmh=effective_vma,
        ):
            click.echo("Aucun changement par rapport à la dernière entrée.")
            return

        metrics = insert_athlete_metrics(
            conn,
            athlete_id,
            weight_kg=weight,
            ftp_watts=ftp,
            fc_max=fc_max,
            fc_repos=fc_repos,
            vma_kmh=vma,
            note=note,
        )
    click.echo(f"OK — entrée #{metrics.id} enregistrée à {metrics.recorded_at.isoformat()}")


@athlete.command("show")
@click.option("--json", "json_out", is_flag=True, help="Sortie JSON parseable")
def athlete_show(json_out: bool) -> None:
    """Affiche la dernière entrée de métriques."""
    athlete_id = _require_athlete_id()
    db_path = db_path_from_env()
    with closing(connect(db_path)) as conn:
        migrate(conn)
        metrics = get_latest_metrics(conn, athlete_id)

    if json_out:
        _emit_json(athlete_metrics_to_dict(metrics) if metrics else None)
        return

    if metrics is None:
        click.echo("Aucune métrique saisie. Utilise `claude-coach athlete set ...`")
        return

    click.echo(f"Dernière entrée ({metrics.recorded_at.isoformat()}) :")
    click.echo(f"  poids     : {metrics.weight_kg} kg")
    click.echo(f"  FTP       : {metrics.ftp_watts} W")
    click.echo(f"  FC max    : {metrics.fc_max} bpm")
    click.echo(f"  FC repos  : {metrics.fc_repos} bpm")
    click.echo(f"  VMA       : {metrics.vma_kmh} km/h")
    if metrics.note:
        click.echo(f"  note      : {metrics.note}")


@athlete.command("history")
@click.option("--limit", type=int, default=20, show_default=True, help="Max lignes affichées")
@click.option("--json", "json_out", is_flag=True, help="Sortie JSON parseable")
def athlete_history(limit: int, json_out: bool) -> None:
    """Affiche l'historique des métriques (chronologique inverse)."""
    athlete_id = _require_athlete_id()
    db_path = db_path_from_env()
    with closing(connect(db_path)) as conn:
        migrate(conn)
        history = get_metrics_history(conn, athlete_id, limit=limit)

    if json_out:
        _emit_json([athlete_metrics_to_dict(m) for m in history])
        return

    if not history:
        click.echo("Aucune métrique enregistrée.")
        return

    click.echo(f"{'Date':<28} {'poids':>7} {'FTP':>5} {'FCmax':>6} {'FCrep':>6} {'VMA':>6}  note")
    click.echo("-" * 80)
    for m in history:
        click.echo(
            f"{m.recorded_at.isoformat():<28} "
            f"{(str(m.weight_kg) if m.weight_kg is not None else '-'):>7} "
            f"{(str(m.ftp_watts) if m.ftp_watts is not None else '-'):>5} "
            f"{(str(m.fc_max) if m.fc_max is not None else '-'):>6} "
            f"{(str(m.fc_repos) if m.fc_repos is not None else '-'):>6} "
            f"{(str(m.vma_kmh) if m.vma_kmh is not None else '-'):>6}  "
            f"{m.note or ''}"
        )


# --- Sous-commandes goal / plan (Lot 5a) ------------------------------------

DISCIPLINES = ("run", "swim_run", "trail", "triathlon", "ride", "swim", "other")
SESSION_TYPES = (
    "endurance",
    "threshold",
    "intervals",
    "long",
    "race",
    "recovery",
    "renfo",
)
INTENSITIES = ("easy", "moderate", "threshold", "vo2max", "race")
DATE_TYPE = click.DateTime(formats=["%Y-%m-%d"])


@main.group()
def goal() -> None:
    """Gestion des objectifs sportifs (courses, événements cibles)."""


@goal.command("add")
@click.option("--name", required=True, help="Nom de l'objectif (ex: 'Swim&Run Sept 2026')")
@click.option(
    "--target-date", "target_date", type=DATE_TYPE, default=None, help="Date cible (YYYY-MM-DD)"
)
@click.option(
    "--discipline", type=click.Choice(DISCIPLINES), default=None, help="Discipline principale"
)
@click.option("--description", default=None, help="Description libre")
@click.option("--success-criteria", "success_criteria", default=None, help="Critères de réussite")
def goal_add(
    name: str,
    target_date: datetime | None,
    discipline: str | None,
    description: str | None,
    success_criteria: str | None,
) -> None:
    """Ajoute un objectif."""
    db_path = db_path_from_env()
    with closing(connect(db_path)) as conn:
        migrate(conn)
        g = insert_goal(
            conn,
            name=name,
            discipline=discipline,
            target_date=target_date.date() if target_date else None,
            description=description,
            success_criteria=success_criteria,
        )
    click.echo(f"OK — objectif #{g.id} créé : {g.name}")


@goal.command("list")
@click.option("--status", type=click.Choice(GOAL_STATUSES), default=None)
@click.option("--json", "json_out", is_flag=True, help="Sortie JSON parseable")
def goal_list(status: str | None, json_out: bool) -> None:
    """Liste les objectifs (triés par date cible)."""
    db_path = db_path_from_env()
    with closing(connect(db_path)) as conn:
        migrate(conn)
        goals = list_goals(conn, status=status)
    if json_out:
        _emit_json([goal_to_dict(g) for g in goals])
        return
    if not goals:
        click.echo("Aucun objectif.")
        return
    click.echo(f"{'#':>3}  {'Date':<10}  {'Statut':<10}  {'Discipline':<12}  Nom")
    click.echo("-" * 70)
    for g in goals:
        click.echo(
            f"{g.id:>3}  "
            f"{(g.target_date.isoformat() if g.target_date else '-'):<10}  "
            f"{g.status:<10}  "
            f"{(g.discipline or '-'):<12}  "
            f"{g.name}"
        )


@goal.command("show")
@click.argument("goal_id", type=int)
@click.option("--json", "json_out", is_flag=True, help="Sortie JSON parseable")
def goal_show(goal_id: int, json_out: bool) -> None:
    """Affiche le détail d'un objectif."""
    db_path = db_path_from_env()
    with closing(connect(db_path)) as conn:
        migrate(conn)
        g = get_goal(conn, goal_id)
    if g is None:
        raise click.ClickException(f"Aucun objectif #{goal_id}")
    if json_out:
        _emit_json(goal_to_dict(g))
        return
    click.echo(f"Objectif #{g.id} — {g.name}")
    click.echo(f"  statut       : {g.status}")
    click.echo(f"  discipline   : {g.discipline or '-'}")
    click.echo(f"  date cible   : {g.target_date.isoformat() if g.target_date else '-'}")
    if g.description:
        click.echo(f"  description  : {g.description}")
    if g.success_criteria:
        click.echo(f"  critères     : {g.success_criteria}")


@goal.command("complete")
@click.argument("goal_id", type=int)
def goal_complete(goal_id: int) -> None:
    """Marque l'objectif comme complété."""
    db_path = db_path_from_env()
    with closing(connect(db_path)) as conn:
        migrate(conn)
        try:
            g = update_goal_status(conn, goal_id, "completed")
        except ValueError as exc:
            raise click.ClickException(str(exc)) from exc
    click.echo(f"OK — objectif #{g.id} marqué '{g.status}'")


@goal.command("abandon")
@click.argument("goal_id", type=int)
def goal_abandon(goal_id: int) -> None:
    """Marque l'objectif comme abandonné (préserve l'historique, exclut des analyses)."""
    db_path = db_path_from_env()
    with closing(connect(db_path)) as conn:
        migrate(conn)
        try:
            g = update_goal_status(conn, goal_id, "abandoned")
        except ValueError as exc:
            raise click.ClickException(str(exc)) from exc
    click.echo(f"OK — objectif #{g.id} marqué '{g.status}'")


@main.group()
def plan() -> None:
    """Gestion des plans d'entraînement et des séances planifiées."""


@plan.command("add")
@click.option("--name", required=True, help="Nom du plan (ex: 'Prépa Swim&Run 12 sem')")
@click.option("--start", "start", required=True, type=DATE_TYPE, help="Début (YYYY-MM-DD)")
@click.option("--end", "end", required=True, type=DATE_TYPE, help="Fin (YYYY-MM-DD)")
@click.option("--goal-id", "goal_id", type=int, default=None, help="ID d'un objectif lié")
@click.option("--notes", default=None, help="Notes libres")
def plan_add(
    name: str,
    start: datetime,
    end: datetime,
    goal_id: int | None,
    notes: str | None,
) -> None:
    """Crée un plan d'entraînement."""
    if end.date() < start.date():
        raise click.ClickException("--end doit être >= --start")
    db_path = db_path_from_env()
    with closing(connect(db_path)) as conn:
        migrate(conn)
        if goal_id is not None and get_goal(conn, goal_id) is None:
            raise click.ClickException(f"Aucun objectif #{goal_id}")
        p = insert_training_plan(
            conn,
            name=name,
            start_date=start.date(),
            end_date=end.date(),
            goal_id=goal_id,
            notes=notes,
        )
    click.echo(f"OK — plan #{p.id} créé : {p.name}")


@plan.command("list")
@click.option("--goal-id", "goal_id", type=int, default=None)
@click.option("--status", type=click.Choice(PLAN_STATUSES), default=None)
@click.option("--json", "json_out", is_flag=True, help="Sortie JSON parseable")
def plan_list(goal_id: int | None, status: str | None, json_out: bool) -> None:
    """Liste les plans d'entraînement."""
    db_path = db_path_from_env()
    with closing(connect(db_path)) as conn:
        migrate(conn)
        plans = list_training_plans(conn, goal_id=goal_id, status=status)
    if json_out:
        _emit_json([training_plan_to_dict(p) for p in plans])
        return
    if not plans:
        click.echo("Aucun plan.")
        return
    click.echo(f"{'#':>3}  {'Début':<10}  {'Fin':<10}  {'Goal':>4}  {'Statut':<10}  Nom")
    click.echo("-" * 70)
    for p in plans:
        click.echo(
            f"{p.id:>3}  "
            f"{p.start_date.isoformat():<10}  "
            f"{p.end_date.isoformat():<10}  "
            f"{(str(p.goal_id) if p.goal_id is not None else '-'):>4}  "
            f"{p.status:<10}  "
            f"{p.name}"
        )


@plan.command("show")
@click.argument("plan_id", type=int)
@click.option("--json", "json_out", is_flag=True, help="Sortie JSON parseable")
def plan_show(plan_id: int, json_out: bool) -> None:
    """Affiche un plan et toutes ses séances planifiées."""
    db_path = db_path_from_env()
    with closing(connect(db_path)) as conn:
        migrate(conn)
        p = get_training_plan(conn, plan_id)
        if p is None:
            raise click.ClickException(f"Aucun plan #{plan_id}")
        sessions = list_planned_sessions(conn, training_plan_id=plan_id)
        # Charge les activités matchées (N+1 acceptable : ~20-30 sessions/plan).
        activities = {
            s.actual_activity_id: get_activity(conn, s.actual_activity_id)
            for s in sessions
            if s.actual_activity_id is not None
        }

    if json_out:
        plan_payload = training_plan_to_dict(p)
        sessions_payload: list[dict[str, object]] = []
        for s in sessions:
            sd = planned_session_to_dict(s)
            sd["realized"] = _realized_payload(s, activities.get(s.actual_activity_id or 0))
            sessions_payload.append(sd)
        plan_payload["sessions"] = sessions_payload
        _emit_json(plan_payload)
        return

    click.echo(f"Plan #{p.id} — {p.name}")
    click.echo(f"  période     : {p.start_date.isoformat()} → {p.end_date.isoformat()}")
    click.echo(f"  statut      : {p.status}")
    click.echo(f"  objectif    : {p.goal_id if p.goal_id is not None else '-'}")
    if p.notes:
        click.echo(f"  notes       : {p.notes}")

    if not sessions:
        click.echo("\nAucune séance planifiée.")
        return
    click.echo(f"\n{len(sessions)} séances planifiées :")
    click.echo(
        f"{'#':>4}  {'Date':<10}  {'Sport':<10}  {'Type':<10}  "
        f"{'Durée':>6}  {'Dist':>7}  {'Statut':<8}  Description"
    )
    click.echo("-" * 90)
    for s in sessions:
        dur = f"{s.target_duration_s // 60}min" if s.target_duration_s else "-"
        dist = f"{s.target_distance_m / 1000:.1f}km" if s.target_distance_m else "-"
        click.echo(
            f"{s.id:>4}  "
            f"{s.planned_date.isoformat():<10}  "
            f"{s.sport_type:<10}  "
            f"{(s.session_type or '-'):<10}  "
            f"{dur:>6}  "
            f"{dist:>7}  "
            f"{s.status:<8}  "
            f"{(s.description or '')[:40]}"
        )
        if s.actual_activity_id is not None:
            act = activities.get(s.actual_activity_id)
            if act is not None:
                click.echo(_format_realized_line(s, act))


def _realized_payload(s: PlannedSession, act: Activity | None) -> dict[str, object] | None:
    """Bloc 'realized' pour la sortie JSON de plan show — None si pas d'activité matchée."""
    if act is None:
        return None
    deltas = session_deltas(s, act)
    return {
        "activity_id": act.id,
        "moving_time_s": act.moving_time_s,
        "distance_m": act.distance_m,
        "average_heartrate": act.average_heartrate,
        "duration_delta_s": deltas["duration_delta_s"],
        "distance_delta_m": deltas["distance_delta_m"],
    }


def _format_realized_line(s: PlannedSession, act: Activity) -> str:
    """Ligne 'réalisé' pour une séance matchée : durée/distance/FC + écarts."""
    parts: list[str] = []
    if act.moving_time_s is not None:
        parts.append(f"{act.moving_time_s // 60} min")
    if act.distance_m is not None:
        parts.append(f"{act.distance_m / 1000:.1f} km")
    if act.average_heartrate is not None:
        parts.append(f"FCmoy {int(act.average_heartrate)}")

    deltas = session_deltas(s, act)
    delta_parts: list[str] = []
    dur_d = deltas["duration_delta_s"]
    if dur_d is not None:
        sign = "+" if dur_d >= 0 else ""
        delta_parts.append(f"Δdurée {sign}{int(dur_d) // 60} min")
    dist_d = deltas["distance_delta_m"]
    if dist_d is not None:
        sign = "+" if dist_d >= 0 else ""
        delta_parts.append(f"Δdist {sign}{dist_d / 1000:.1f} km")

    line = "        ↳ réalisé : " + ", ".join(parts) if parts else "        ↳ réalisé"
    if delta_parts:
        line += " (" + ", ".join(delta_parts) + ")"
    return line


@plan.command("match")
@click.option(
    "--plan-id",
    "plan_id",
    type=int,
    default=None,
    help="Limiter à un plan spécifique. Sans option : tous les plans actifs.",
)
@click.option("--dry-run", is_flag=True, help="Affiche sans écrire en DB")
@click.option("--json", "json_out", is_flag=True, help="Sortie JSON parseable")
def plan_match(plan_id: int | None, dry_run: bool, json_out: bool) -> None:
    """Apparie chaque séance planifiée à une activité Strava (par date + famille de sport)."""
    db_path = db_path_from_env()
    with closing(connect(db_path)) as conn:
        migrate(conn)
        if plan_id is not None and get_training_plan(conn, plan_id) is None:
            raise click.ClickException(f"Aucun plan #{plan_id}")
        results = match_all_planned_sessions(conn, plan_id=plan_id, dry_run=dry_run)

    matched = [r for r in results if r.activity is not None]
    unmatched = [r for r in results if r.activity is None]

    if json_out:
        _emit_json(
            {
                "plan_id": plan_id,
                "dry_run": dry_run,
                "matched": [_match_payload(r, matched=True) for r in matched],
                "unmatched": [_match_payload(r, matched=False) for r in unmatched],
            }
        )
        return

    prefix = "[dry-run] " if dry_run else ""
    if not results:
        click.echo(f"{prefix}Aucune séance à apparier.")
        return

    click.echo(f"{prefix}{len(matched)} séance(s) appariée(s), {len(unmatched)} sans match :")
    for r in matched:
        assert r.activity is not None  # narrow pour mypy
        click.echo(_format_match_line(r, matched=True))
    for r in unmatched:
        click.echo(_format_match_line(r, matched=False))


def _match_payload(r: MatchResult, *, matched: bool) -> dict[str, object]:
    base: dict[str, object] = {
        "session_id": r.session.id,
        "planned_date": r.session.planned_date.isoformat(),
        "sport_type": r.session.sport_type,
    }
    if not matched or r.activity is None:
        base["activity_id"] = None
        base["same_day"] = None
        base["moving_time_s"] = None
        return base
    act = r.activity
    same_day = act.start_date_local is not None and act.start_date_local.startswith(
        r.session.planned_date.isoformat()
    )
    base["activity_id"] = act.id
    base["same_day"] = same_day
    base["moving_time_s"] = act.moving_time_s
    return base


def _format_match_line(r: MatchResult, *, matched: bool) -> str:
    sym = "✓" if matched else "✗"
    sid = f"#{r.session.id}"
    base = f"  {sym} {sid:<5} {r.session.planned_date.isoformat()} {r.session.sport_type:<10}"
    if not matched or r.activity is None:
        return f"{base} → aucune activité dans la fenêtre"

    act = r.activity
    same_day = act.start_date_local is not None and act.start_date_local.startswith(
        r.session.planned_date.isoformat()
    )
    when = "même jour" if same_day else "J±1"
    dur = f"{act.moving_time_s // 60} min" if act.moving_time_s else "?"
    return f"{base} → activity {act.id} ({when}, {dur})"


@plan.command("complete")
@click.argument("plan_id", type=int)
def plan_complete(plan_id: int) -> None:
    """Marque le plan comme complété (fin de bloc, plan terminé)."""
    db_path = db_path_from_env()
    with closing(connect(db_path)) as conn:
        migrate(conn)
        try:
            p = update_training_plan_status(conn, plan_id, "completed")
        except ValueError as exc:
            raise click.ClickException(str(exc)) from exc
    click.echo(f"OK — plan #{p.id} marqué '{p.status}'")


@plan.command("pause")
@click.argument("plan_id", type=int)
def plan_pause(plan_id: int) -> None:
    """Met le plan en pause (blessure, voyage, etc. — peut être réactivé en DB)."""
    db_path = db_path_from_env()
    with closing(connect(db_path)) as conn:
        migrate(conn)
        try:
            p = update_training_plan_status(conn, plan_id, "paused")
        except ValueError as exc:
            raise click.ClickException(str(exc)) from exc
    click.echo(f"OK — plan #{p.id} marqué '{p.status}'")


@plan.command("abandon")
@click.argument("plan_id", type=int)
def plan_abandon(plan_id: int) -> None:
    """Marque le plan comme abandonné (préserve l'historique, distinct de 'completed')."""
    db_path = db_path_from_env()
    with closing(connect(db_path)) as conn:
        migrate(conn)
        try:
            p = update_training_plan_status(conn, plan_id, "abandoned")
        except ValueError as exc:
            raise click.ClickException(str(exc)) from exc
    click.echo(f"OK — plan #{p.id} marqué '{p.status}'")


@plan.group("session")
def plan_session() -> None:
    """Gestion des séances planifiées d'un plan."""


def _blocks_json_or_raise(sport_type: str, blocks_dsl: str | None) -> str | None:
    """Parse le DSL de blocs → JSON canonique. None si pas de DSL.

    Vélo home-trainer (VirtualRide) → blocs puissance %FTP (`zwo.py`, → Zwift).
    Tous les autres sports — course, natation, **vélo outdoor** — → blocs multi-cibles
    allure/FC/durée/distance (`workout.py`, → Suunto / Garmin via intervals.icu).
    """
    if blocks_dsl is None:
        return None
    try:
        if is_indoor_power_ride(sport_type):
            return blocks_to_json(parse_blocks(blocks_dsl))
        return workout_to_json(parse_workout(blocks_dsl))
    except ValueError as exc:
        raise click.ClickException(f"Blocs invalides : {exc}") from exc


def _slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.strip().lower()).strip("-")
    return slug or "seance"


@plan_session.command("add")
@click.option("--plan-id", "plan_id", required=True, type=int)
@click.option("--date", "date_", required=True, type=DATE_TYPE, help="Date prévue (YYYY-MM-DD)")
@click.option("--sport", required=True, help="Sport Strava (Run, Ride, Swim, TrailRun, ...)")
@click.option("--session-type", "session_type", type=click.Choice(SESSION_TYPES), default=None)
@click.option("--duration", type=int, default=None, help="Durée cible en secondes")
@click.option("--distance", type=float, default=None, help="Distance cible en mètres")
@click.option("--intensity", type=click.Choice(INTENSITIES), default=None)
@click.option("--description", default=None)
@click.option("--notes", default=None)
@click.option(
    "--blocks",
    default=None,
    help=(
        "Blocs structurés. Vélo home-trainer / VirtualRide (puissance %FTP → Zwift) : "
        "'warmup:10m:50-65; 3x[12m@95;4m@60]'. Course / natation / vélo outdoor "
        "(allure/FC/distance → Suunto ou Garmin) : "
        "'warmup:15min@h120-140; 6x[400m@p3:45;rest:90s@h130]'."
    ),
)
def plan_session_add(
    plan_id: int,
    date_: datetime,
    sport: str,
    session_type: str | None,
    duration: int | None,
    distance: float | None,
    intensity: str | None,
    description: str | None,
    notes: str | None,
    blocks: str | None,
) -> None:
    """Ajoute une séance planifiée à un plan."""
    blocks_json = _blocks_json_or_raise(sport, blocks)
    db_path = db_path_from_env()
    with closing(connect(db_path)) as conn:
        migrate(conn)
        if get_training_plan(conn, plan_id) is None:
            raise click.ClickException(f"Aucun plan #{plan_id}")
        s = insert_planned_session(
            conn,
            training_plan_id=plan_id,
            planned_date=date_.date(),
            sport_type=sport,
            session_type=session_type,
            target_duration_s=duration,
            target_distance_m=distance,
            target_intensity=intensity,
            description=description,
            notes=notes,
            blocks_json=blocks_json,
        )
    click.echo(f"OK — séance #{s.id} créée le {s.planned_date.isoformat()} ({s.sport_type})")


@plan_session.command("list")
@click.option("--plan-id", "plan_id", required=True, type=int)
@click.option("--status", type=click.Choice(SESSION_STATUSES), default=None)
@click.option("--json", "json_out", is_flag=True, help="Sortie JSON parseable")
def plan_session_list(plan_id: int, status: str | None, json_out: bool) -> None:
    """Liste les séances planifiées d'un plan."""
    db_path = db_path_from_env()
    with closing(connect(db_path)) as conn:
        migrate(conn)
        if get_training_plan(conn, plan_id) is None:
            raise click.ClickException(f"Aucun plan #{plan_id}")
        sessions = list_planned_sessions(conn, training_plan_id=plan_id, status=status)
    if json_out:
        _emit_json([planned_session_to_dict(s) for s in sessions])
        return
    if not sessions:
        click.echo("Aucune séance.")
        return
    for s in sessions:
        dur = f"{s.target_duration_s // 60}min" if s.target_duration_s else "-"
        click.echo(
            f"#{s.id:<4} {s.planned_date.isoformat()}  {s.sport_type:<10} "
            f"{(s.session_type or '-'):<10}  {dur:>6}  {s.status}"
        )


@plan_session.command("done")
@click.argument("session_id", type=int)
def plan_session_done(session_id: int) -> None:
    """Marque manuellement une séance comme réalisée (sans la lier à une activité Strava)."""
    db_path = db_path_from_env()
    with closing(connect(db_path)) as conn:
        migrate(conn)
        try:
            s = update_planned_session_status(conn, session_id, "done")
        except ValueError as exc:
            raise click.ClickException(str(exc)) from exc
    click.echo(f"OK — séance #{s.id} marquée 'done'")


@plan_session.command("skip")
@click.argument("session_id", type=int)
def plan_session_skip(session_id: int) -> None:
    """Marque une séance comme passée volontairement (substitution, repos, etc.)."""
    db_path = db_path_from_env()
    with closing(connect(db_path)) as conn:
        migrate(conn)
        try:
            s = update_planned_session_status(conn, session_id, "skipped")
        except ValueError as exc:
            raise click.ClickException(str(exc)) from exc
    click.echo(f"OK — séance #{s.id} marquée '{s.status}'")


@plan_session.command("delete")
@click.argument("session_id", type=int)
def plan_session_delete(session_id: int) -> None:
    """Supprime une séance non encore réalisée (report, replanification).

    Restreint aux séances en statut 'planned' : une séance aboutie
    (done/skipped/missed) fait partie de l'historique et n'est pas supprimable.
    """
    db_path = db_path_from_env()
    with closing(connect(db_path)) as conn:
        migrate(conn)
        try:
            s = delete_planned_session(conn, session_id)
        except ValueError as exc:
            raise click.ClickException(str(exc)) from exc
    click.echo(f"OK — séance #{s.id} ({s.sport_type} {s.planned_date.isoformat()}) supprimée")


@plan_session.command("set-blocks")
@click.argument("session_id", type=int)
@click.argument("blocks")
def plan_session_set_blocks(session_id: int, blocks: str) -> None:
    """Définit (ou remplace) les blocs structurés d'une séance.

    Vélo home-trainer / VirtualRide (puissance %FTP → Zwift) :
        claude-coach plan session set-blocks 12 "warmup:10m:50-65; 3x[12m@95;4m@60]"
    Course / natation / vélo outdoor (allure/FC/distance → Suunto ou Garmin) :
        claude-coach plan session set-blocks 12 "warmup:15min@h120-140; 6x[400m@p3:45;rest:90s]"
    """
    db_path = db_path_from_env()
    with closing(connect(db_path)) as conn:
        migrate(conn)
        existing = get_planned_session(conn, session_id)
        if existing is None:
            raise click.ClickException(f"Aucune séance #{session_id}")
        blocks_json = _blocks_json_or_raise(existing.sport_type, blocks)
        s = update_planned_session_blocks(conn, session_id, blocks_json)
    click.echo(f"OK — blocs définis pour la séance #{s.id} ({s.sport_type})")


@plan_session.command("export")
@click.argument("session_id", type=int)
@click.option(
    "--output",
    type=click.Path(dir_okay=False, path_type=Path),
    default=None,
    help="Chemin du .zwo (défaut: data/exports/<slug>.zwo)",
)
@click.option(
    "--stdout/--no-stdout",
    "to_stdout",
    default=True,
    help="Afficher aussi le XML sur la sortie standard (défaut: oui)",
)
def plan_session_export(session_id: int, output: Path | None, to_stdout: bool) -> None:
    """Exporte une séance vélo home-trainer en .zwo (Zwift) — fallback offline.

    Voie nominale : `push-intervals` (intervals.icu → Zwift). Ce `.zwo` reste un
    secours pour un import manuel dans Zwift.
    """
    db_path = db_path_from_env()
    with closing(connect(db_path)) as conn:
        migrate(conn)
        s = get_planned_session(conn, session_id)
        if s is None:
            raise click.ClickException(f"Aucune séance #{session_id}")
        if not is_indoor_power_ride(s.sport_type):
            raise click.ClickException(
                f"Export .zwo réservé au vélo home-trainer (VirtualRide), pas à "
                f"'{s.sport_type}'. Vélo outdoor / course : `push-intervals`."
            )
        if not s.blocks_json:
            raise click.ClickException(
                f"La séance #{session_id} n'a pas de blocs structurés. Ajoute-les via : "
                f'claude-coach plan session set-blocks {session_id} "warmup:10m:50-65; ..."'
            )
        plan = get_training_plan(conn, s.training_plan_id)
        blocks = blocks_from_json(s.blocks_json)

    plan_name = plan.name if plan else "Plan"
    name = f"{plan_name} — {s.planned_date.isoformat()}"
    xml = generate_zwo(name=name, description=s.description or s.notes, blocks=blocks)

    if output is None:
        filename = f"{_slugify(plan_name)}-{s.planned_date.isoformat()}-{s.sport_type.lower()}.zwo"
        output = db_path.parent / "exports" / filename
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(xml, encoding="utf-8")
    click.echo(f"OK — .zwo écrit : {output}")
    if to_stdout:
        click.echo(xml)


@plan_session.command("push-intervals")
@click.argument("session_id", type=int)
@click.option(
    "--dry-run",
    "dry_run",
    is_flag=True,
    help="Affiche le payload intervals.icu sans l'envoyer (debug)",
)
def plan_session_push_intervals(session_id: int, dry_run: bool) -> None:
    """Pousse une séance structurée vers intervals.icu — hub unique (gratuit).

    intervals.icu fan-oute la séance vers l'appareil selon le sport (connexions
    configurées dans son UI web, « Upload planned workouts » coché) :
    course / natation → Suunto, vélo outdoor → Garmin, vélo home-trainer (VirtualRide)
    → Zwift. La séance est créée comme événement « WORKOUT » dans le calendrier.
    """
    db_path = db_path_from_env()
    with closing(connect(db_path)) as conn:
        migrate(conn)
        s = get_planned_session(conn, session_id)
        if s is None:
            raise click.ClickException(f"Aucune séance #{session_id}")
        try:
            intervals_sport_type(s.sport_type)
        except ValueError as exc:
            raise click.ClickException(str(exc)) from exc
        if not s.blocks_json:
            example = (
                '"warmup:10m:50-65; 3x[12m@95;4m@60]; cooldown:8m:65-50"'
                if is_indoor_power_ride(s.sport_type)
                else '"warmup:15min@h120-140; 6x[400m@p3:45;rest:90s@h130]; cooldown:10min@h120"'
            )
            raise click.ClickException(
                f"La séance #{session_id} n'a pas de blocs structurés. Ajoute-les via : "
                f"claude-coach plan session set-blocks {session_id} {example}"
            )
        plan = get_training_plan(conn, s.training_plan_id)

        if is_indoor_power_ride(s.sport_type):
            # Vélo home-trainer → Zwift : puissance %FTP (pas de FCmax requise).
            blocks = blocks_from_json(s.blocks_json)
            workout_doc = workout_doc_from_blocks(blocks)
        else:
            # Course / natation / vélo outdoor : cibles allure/FC/distance.
            # FCmax pour convertir les cibles FC (bpm → %FCmax ; Suunto refuse les bpm).
            items = workout_from_json(s.blocks_json)
            tokens = load_tokens(token_path_from_env())
            metrics = get_latest_metrics(conn, tokens.athlete_id) if tokens else None
            max_hr = metrics.fc_max if metrics else None
            try:
                workout_doc = workout_doc_from_items(items, max_hr=max_hr)
            except ValueError as exc:
                raise click.ClickException(str(exc)) from exc

    plan_name = plan.name if plan else "Plan"
    payload = build_event_payload(
        s,
        plan_name=plan_name,
        sport_type=s.sport_type,
        workout_doc=workout_doc,
        description=s.description or s.notes,
    )

    if dry_run:
        _emit_json(payload)
        return

    try:
        config = load_intervals_config()
    except ConfigError as exc:
        raise click.ClickException(str(exc)) from exc
    try:
        with IntervalsClient(config) as client:
            created = client.upsert_event(payload)
    except (AuthError, IntervalsClientError) as exc:
        raise click.ClickException(str(exc)) from exc

    event_id = created.get("id") or "?"
    click.echo(
        f"OK — séance #{s.id} poussée sur intervals.icu (event id: {event_id}). "
        "Avec « Upload planned workouts » coché, elle part vers ta montre / Garmin / Zwift."
    )


# --- Sous-commandes activity (Lot 5c) ---------------------------------------


def _resolve_sport_types(sport: str | None, family: str | None) -> list[str] | None:
    if sport is not None:
        return [sport]
    if family is not None:
        return sport_types_in_family(family)
    return None


@main.group()
def activity() -> None:
    """Lecture des activités importées (filtres, agrégats)."""


@activity.command("list")
@click.option("--from", "since", type=DATE_TYPE, default=None, help="Date min (YYYY-MM-DD)")
@click.option("--to", "until", type=DATE_TYPE, default=None, help="Date max (YYYY-MM-DD)")
@click.option("--sport", default=None, help="Sport Strava exact (Run, Ride, ...)")
@click.option(
    "--family",
    type=click.Choice(KNOWN_FAMILIES),
    default=None,
    help="Famille de sports (run, ride, swim, ...)",
)
@click.option("--limit", type=int, default=None, help="Limite de lignes")
@click.option("--json", "json_out", is_flag=True, help="Sortie JSON parseable")
def activity_list(
    since: datetime | None,
    until: datetime | None,
    sport: str | None,
    family: str | None,
    limit: int | None,
    json_out: bool,
) -> None:
    """Liste les activités (les plus récentes en tête)."""
    sport_types = _resolve_sport_types(sport, family)
    db_path = db_path_from_env()
    with closing(connect(db_path)) as conn:
        migrate(conn)
        activities = list_activities(
            conn,
            since=since.date() if since else None,
            until=until.date() if until else None,
            sport_types=sport_types,
            limit=limit,
        )

    if json_out:
        _emit_json([activity_to_dict(a) for a in activities])
        return

    if not activities:
        click.echo("Aucune activité.")
        return
    click.echo(
        f"{'#':>10}  {'Date':<10}  {'Sport':<14}  {'Durée':>6}  "
        f"{'Dist':>7}  {'D+':>5}  {'FCmoy':>5}  Nom"
    )
    click.echo("-" * 90)
    for a in activities:
        date_local = (a.start_date_local or "")[:10] or "-"
        dur = f"{a.moving_time_s // 60}min" if a.moving_time_s else "-"
        dist = f"{a.distance_m / 1000:.1f}km" if a.distance_m else "-"
        elev = f"{int(a.total_elevation_gain_m)}m" if a.total_elevation_gain_m else "-"
        hr = f"{int(a.average_heartrate)}" if a.average_heartrate else "-"
        click.echo(
            f"{a.id:>10}  {date_local:<10}  {(a.sport_type or '-'):<14}  "
            f"{dur:>6}  {dist:>7}  {elev:>5}  {hr:>5}  {(a.name or '')[:50]}"
        )


@activity.command("show")
@click.argument("activity_id", type=int)
@click.option("--json", "json_out", is_flag=True, help="Sortie JSON parseable")
def activity_show(activity_id: int, json_out: bool) -> None:
    """Affiche une activité (sans streams ni laps)."""
    db_path = db_path_from_env()
    with closing(connect(db_path)) as conn:
        migrate(conn)
        a = get_activity(conn, activity_id)
    if a is None:
        raise click.ClickException(f"Aucune activité #{activity_id}")

    if json_out:
        _emit_json(activity_to_dict(a))
        return

    click.echo(f"Activité #{a.id} — {a.name or '(sans nom)'}")
    click.echo(f"  sport          : {a.sport_type or '-'}")
    click.echo(
        f"  date           : {a.start_date_local or '-'} (local) / {a.start_date or '-'} (UTC)"
    )
    if a.timezone:
        click.echo(f"  timezone       : {a.timezone}")
    if a.distance_m is not None:
        click.echo(f"  distance       : {a.distance_m / 1000:.2f} km")
    if a.moving_time_s is not None:
        click.echo(f"  durée mouvement: {a.moving_time_s // 60} min")
    if a.elapsed_time_s is not None:
        click.echo(f"  durée totale   : {a.elapsed_time_s // 60} min")
    if a.total_elevation_gain_m is not None:
        click.echo(f"  D+             : {a.total_elevation_gain_m:.0f} m")
    if a.average_speed_ms is not None:
        click.echo(f"  vitesse moy    : {a.average_speed_ms * 3.6:.2f} km/h")
    if a.max_speed_ms is not None:
        click.echo(f"  vitesse max    : {a.max_speed_ms * 3.6:.2f} km/h")
    if a.average_heartrate is not None:
        max_hr = int(a.max_heartrate) if a.max_heartrate is not None else "-"
        click.echo(f"  FC moy/max     : {int(a.average_heartrate)} / {max_hr}")
    if a.average_watts is not None:
        click.echo(f"  puissance moy  : {int(a.average_watts)} W")
    if a.calories is not None:
        click.echo(f"  calories       : {int(a.calories)}")
    if a.device_name:
        click.echo(f"  appareil       : {a.device_name}")
    if a.description:
        click.echo(f"  description    : {a.description}")


@activity.command("laps")
@click.argument("activity_id", type=int)
@click.option("--json", "json_out", is_flag=True, help="Sortie JSON parseable")
def activity_laps(activity_id: int, json_out: bool) -> None:
    """Affiche les laps d'une activité (utile pour débrief d'intervalles)."""
    db_path = db_path_from_env()
    with closing(connect(db_path)) as conn:
        migrate(conn)
        if get_activity(conn, activity_id) is None:
            raise click.ClickException(f"Aucune activité #{activity_id}")
        laps = list_laps(conn, activity_id)

    if json_out:
        _emit_json([lap_to_dict(lap) for lap in laps])
        return

    if not laps:
        click.echo("Aucun lap enregistré pour cette activité.")
        return

    click.echo(
        f"{'#':>3}  {'Dist':>7}  {'Durée':>6}  {'Allure':>8}  "
        f"{'FCmoy':>5}  {'FCmax':>5}  {'Wmoy':>5}"
    )
    click.echo("-" * 60)
    for lap in laps:
        dist = f"{lap.distance_m:.0f}m" if lap.distance_m is not None else "-"
        dur = f"{lap.moving_time_s}s" if lap.moving_time_s is not None else "-"
        if lap.average_speed_ms and lap.average_speed_ms > 0:
            pace_s_per_km = 1000.0 / lap.average_speed_ms
            pace = f"{int(pace_s_per_km // 60)}'{int(pace_s_per_km % 60):02d}/km"
        else:
            pace = "-"
        fc_moy = f"{int(lap.average_heartrate)}" if lap.average_heartrate else "-"
        fc_max = f"{int(lap.max_heartrate)}" if lap.max_heartrate else "-"
        watts = f"{int(lap.average_watts)}" if lap.average_watts else "-"
        click.echo(
            f"{lap.lap_index or '-':>3}  {dist:>7}  {dur:>6}  "
            f"{pace:>8}  {fc_moy:>5}  {fc_max:>5}  {watts:>5}"
        )


@activity.command("streams")
@click.argument("activity_id", type=int)
@click.option(
    "--type",
    "stream_types",
    multiple=True,
    help=(
        "Type(s) de stream à inclure (heartrate, watts, velocity_smooth, distance, "
        "altitude, cadence, temp, latlng, time, moving, grade_smooth). Répétable. "
        "Sans option : tous les streams."
    ),
)
@click.option("--json", "json_out", is_flag=True, help="Sortie JSON parseable")
def activity_streams(activity_id: int, stream_types: tuple[str, ...], json_out: bool) -> None:
    """Affiche les streams seconde-par-seconde d'une activité.

    Utile pour analyser un long Z2 (% temps en zone FC via le stream heartrate)
    ou la dérive cardio sur une séance longue. Volumineux en sortie : préférer
    `--type` pour filtrer.
    """
    db_path = db_path_from_env()
    types_list = list(stream_types) if stream_types else None
    with closing(connect(db_path)) as conn:
        migrate(conn)
        if get_activity(conn, activity_id) is None:
            raise click.ClickException(f"Aucune activité #{activity_id}")
        streams = list_streams(conn, activity_id, stream_types=types_list)

    if json_out:
        _emit_json([stream_to_dict(s) for s in streams])
        return

    if not streams:
        click.echo("Aucun stream pour cette activité.")
        return

    click.echo(f"{'Type':<18} {'Résolution':<11} {'Samples':>8}")
    click.echo("-" * 50)
    for s in streams:
        d = stream_to_dict(s)
        data = d["data"]
        n = len(data) if isinstance(data, list) else 0
        click.echo(f"{s.stream_type:<18} {(s.resolution or '-'):<11} {n:>8}")


@activity.command("stats")
@click.option("--from", "since", type=DATE_TYPE, default=None, help="Date min (YYYY-MM-DD)")
@click.option("--to", "until", type=DATE_TYPE, default=None, help="Date max (YYYY-MM-DD)")
@click.option("--sport", default=None, help="Sport Strava exact")
@click.option(
    "--family",
    type=click.Choice(KNOWN_FAMILIES),
    default=None,
    help="Famille de sports",
)
@click.option(
    "--by",
    "group_by",
    type=click.Choice(["sport", "week", "month"]),
    default="sport",
    show_default=True,
    help="Clé d'agrégation",
)
@click.option("--json", "json_out", is_flag=True, help="Sortie JSON parseable")
def activity_stats(
    since: datetime | None,
    until: datetime | None,
    sport: str | None,
    family: str | None,
    group_by: str,
    json_out: bool,
) -> None:
    """Agrège les activités par sport, semaine ou mois."""
    sport_types = _resolve_sport_types(sport, family)
    db_path = db_path_from_env()
    with closing(connect(db_path)) as conn:
        migrate(conn)
        buckets = aggregate_activities(
            conn,
            group_by=cast(Literal["sport", "week", "month"], group_by),
            since=since.date() if since else None,
            until=until.date() if until else None,
            sport_types=sport_types,
        )

    if json_out:
        total = {
            "count": sum(b.count for b in buckets),
            "distance_m": sum(b.distance_m for b in buckets),
            "moving_time_s": sum(b.moving_time_s for b in buckets),
            "elevation_gain_m": sum(b.elevation_gain_m for b in buckets),
        }
        _emit_json(
            {
                "group_by": group_by,
                "buckets": [bucket_to_dict(b) for b in buckets],
                "total": total,
            }
        )
        return

    if not buckets:
        click.echo("Aucune activité dans la fenêtre.")
        return
    click.echo(f"{'Bucket':<14}  {'Activités':>9}  {'Distance':>10}  {'Durée':>10}  {'D+':>7}")
    click.echo("-" * 60)
    for b in buckets:
        click.echo(
            f"{b.key:<14}  {b.count:>9}  "
            f"{b.distance_m / 1000:>7.1f} km  "
            f"{b.moving_time_s // 60:>7} min  "
            f"{int(b.elevation_gain_m):>5} m"
        )


# --- Sous-commandes debrief (Lot 7) -----------------------------------------


def _debrief_line(d: SessionDebrief) -> str:
    """Ligne résumé d'un débrief pour l'affichage `list`."""
    link = f"act #{d.activity_id}" if d.activity_id else ""
    if d.planned_session_id:
        link = (link + " / " if link else "") + f"séance #{d.planned_session_id}"
    rpe = f"RPE {d.rpe}" if d.rpe is not None else "RPE -"
    pain = f"  ⚠ {d.pain}" if d.pain else ""
    return f"#{d.id:<4} {d.debrief_date.isoformat()}  {rpe:<7}  {(link or '—'):<24}{pain}"


@main.group()
def debrief() -> None:
    """Débriefs subjectifs de séance (RPE, ressenti, douleurs)."""


@debrief.command("add")
@click.option("--activity", "activity_id", type=int, default=None, help="ID activité Strava liée")
@click.option("--session", "session_id", type=int, default=None, help="ID séance planifiée liée")
@click.option(
    "--date", "date_", type=DATE_TYPE, default=None, help="Date du débrief (défaut: aujourd'hui)"
)
@click.option("--rpe", type=click.IntRange(1, 10), default=None, help="Effort perçu 1-10")
@click.option("--feeling", default=None, help="Ressenti général (texte libre)")
@click.option("--pain", default=None, help="Signaux douleur (texte libre: mollet, genou, ...)")
def debrief_add(
    activity_id: int | None,
    session_id: int | None,
    date_: datetime | None,
    rpe: int | None,
    feeling: str | None,
    pain: str | None,
) -> None:
    """Consigne le ressenti d'une séance (RPE, sensations, douleurs).

    Au moins un de --rpe / --feeling / --pain est requis. Lier le débrief à une
    activité (--activity) et/ou une séance planifiée (--session) est optionnel.
    """
    if rpe is None and feeling is None and pain is None:
        raise click.ClickException("Un débrief doit contenir au moins --rpe, --feeling ou --pain.")
    debrief_date = date_.date() if date_ is not None else date.today()
    db_path = db_path_from_env()
    with closing(connect(db_path)) as conn:
        migrate(conn)
        if activity_id is not None and get_activity(conn, activity_id) is None:
            raise click.ClickException(f"Aucune activité #{activity_id}")
        if session_id is not None and get_planned_session(conn, session_id) is None:
            raise click.ClickException(f"Aucune séance #{session_id}")
        d = insert_debrief(
            conn,
            debrief_date=debrief_date,
            activity_id=activity_id,
            planned_session_id=session_id,
            rpe=rpe,
            feeling=feeling,
            pain=pain,
        )
    rpe_txt = f"RPE {d.rpe}" if d.rpe is not None else "sans RPE"
    click.echo(f"OK — débrief #{d.id} consigné ({d.debrief_date.isoformat()}, {rpe_txt})")


@debrief.command("list")
@click.option("--from", "since", type=DATE_TYPE, default=None, help="Date min (YYYY-MM-DD)")
@click.option("--to", "until", type=DATE_TYPE, default=None, help="Date max (YYYY-MM-DD)")
@click.option("--activity", "activity_id", type=int, default=None, help="Filtrer sur une activité")
@click.option("--session", "session_id", type=int, default=None, help="Filtrer sur une séance")
@click.option("--limit", type=int, default=None, help="Limite de lignes")
@click.option("--json", "json_out", is_flag=True, help="Sortie JSON parseable")
def debrief_list(
    since: datetime | None,
    until: datetime | None,
    activity_id: int | None,
    session_id: int | None,
    limit: int | None,
    json_out: bool,
) -> None:
    """Liste les débriefs (du plus récent au plus ancien)."""
    db_path = db_path_from_env()
    with closing(connect(db_path)) as conn:
        migrate(conn)
        debriefs = list_debriefs(
            conn,
            since=since.date() if since else None,
            until=until.date() if until else None,
            activity_id=activity_id,
            planned_session_id=session_id,
            limit=limit,
        )
    if json_out:
        _emit_json([debrief_to_dict(d) for d in debriefs])
        return
    if not debriefs:
        click.echo("Aucun débrief.")
        return
    for d in debriefs:
        click.echo(_debrief_line(d))


@debrief.command("show")
@click.argument("debrief_id", type=int)
@click.option("--json", "json_out", is_flag=True, help="Sortie JSON parseable")
def debrief_show(debrief_id: int, json_out: bool) -> None:
    """Affiche le détail d'un débrief."""
    db_path = db_path_from_env()
    with closing(connect(db_path)) as conn:
        migrate(conn)
        d = get_debrief(conn, debrief_id)
    if d is None:
        raise click.ClickException(f"Aucun débrief #{debrief_id}")
    if json_out:
        _emit_json(debrief_to_dict(d))
        return
    click.echo(f"Débrief #{d.id} — {d.debrief_date.isoformat()}")
    click.echo(f"  RPE         : {d.rpe if d.rpe is not None else '-'}/10")
    click.echo(f"  activité    : {d.activity_id or '-'}")
    click.echo(f"  séance      : {d.planned_session_id or '-'}")
    click.echo(f"  ressenti    : {d.feeling or '-'}")
    click.echo(f"  douleurs    : {d.pain or '-'}")
    click.echo(f"  créé le     : {d.created_at.isoformat()}")


@debrief.command("edit")
@click.argument("debrief_id", type=int)
@click.option("--activity", "activity_id", type=int, default=None)
@click.option("--session", "session_id", type=int, default=None)
@click.option("--date", "date_", type=DATE_TYPE, default=None)
@click.option("--rpe", type=click.IntRange(1, 10), default=None)
@click.option("--feeling", default=None)
@click.option("--pain", default=None)
def debrief_edit(
    debrief_id: int,
    activity_id: int | None,
    session_id: int | None,
    date_: datetime | None,
    rpe: int | None,
    feeling: str | None,
    pain: str | None,
) -> None:
    """Modifie un débrief. Seuls les champs fournis sont changés.

    Pour vider un champ (ex: retirer une note de douleur), supprime puis recrée.
    """
    db_path = db_path_from_env()
    with closing(connect(db_path)) as conn:
        migrate(conn)
        if activity_id is not None and get_activity(conn, activity_id) is None:
            raise click.ClickException(f"Aucune activité #{activity_id}")
        if session_id is not None and get_planned_session(conn, session_id) is None:
            raise click.ClickException(f"Aucune séance #{session_id}")
        try:
            d = update_debrief(
                conn,
                debrief_id,
                debrief_date=date_.date() if date_ else None,
                activity_id=activity_id,
                planned_session_id=session_id,
                rpe=rpe,
                feeling=feeling,
                pain=pain,
            )
        except ValueError as exc:
            raise click.ClickException(str(exc)) from exc
    click.echo(f"OK — débrief #{d.id} mis à jour")


@debrief.command("delete")
@click.argument("debrief_id", type=int)
def debrief_delete(debrief_id: int) -> None:
    """Supprime un débrief."""
    db_path = db_path_from_env()
    with closing(connect(db_path)) as conn:
        migrate(conn)
        try:
            d = delete_debrief(conn, debrief_id)
        except ValueError as exc:
            raise click.ClickException(str(exc)) from exc
    click.echo(f"OK — débrief #{d.id} ({d.debrief_date.isoformat()}) supprimé")
