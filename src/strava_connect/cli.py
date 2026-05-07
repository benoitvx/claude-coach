from __future__ import annotations

from contextlib import closing
from datetime import UTC, datetime

import click

from strava_connect.auth import (
    AuthError,
    ConfigError,
    load_config,
    load_tokens,
    start_oauth_flow,
    token_path_from_env,
)
from strava_connect.db import (
    GOAL_STATUSES,
    PLAN_STATUSES,
    SESSION_STATUSES,
    connect,
    count_activities,
    db_path_from_env,
    get_goal,
    get_last_sync,
    get_latest_metrics,
    get_metrics_history,
    get_training_plan,
    insert_athlete_metrics,
    insert_goal,
    insert_planned_session,
    insert_training_plan,
    list_goals,
    list_planned_sessions,
    list_training_plans,
    metrics_values_equal,
    migrate,
    stats_by_sport,
    update_goal_status,
    update_planned_session_status,
)
from strava_connect.sync import LOOKBACK_DAYS_DEFAULT, sync_full, sync_incremental


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


@main.command()
def status() -> None:
    """Affiche l'état de la DB, des tokens et de la dernière sync."""
    db_path = db_path_from_env()
    tokens_path = token_path_from_env()

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
    tokens = load_tokens(tokens_path) if tokens_path.exists() else None
    if tokens is None:
        click.echo("  absent — lance `strava-connect auth` pour démarrer.")
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
        click.echo("  profil athlète : aucun (saisis avec `strava-connect athlete set ...`)")
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
        raise click.ClickException("Aucun token stocké. Lance d'abord `strava-connect auth`.")
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
def athlete_show() -> None:
    """Affiche la dernière entrée de métriques."""
    athlete_id = _require_athlete_id()
    db_path = db_path_from_env()
    with closing(connect(db_path)) as conn:
        migrate(conn)
        metrics = get_latest_metrics(conn, athlete_id)

    if metrics is None:
        click.echo("Aucune métrique saisie. Utilise `strava-connect athlete set ...`")
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
def athlete_history(limit: int) -> None:
    """Affiche l'historique des métriques (chronologique inverse)."""
    athlete_id = _require_athlete_id()
    db_path = db_path_from_env()
    with closing(connect(db_path)) as conn:
        migrate(conn)
        history = get_metrics_history(conn, athlete_id, limit=limit)

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
def goal_list(status: str | None) -> None:
    """Liste les objectifs (triés par date cible)."""
    db_path = db_path_from_env()
    with closing(connect(db_path)) as conn:
        migrate(conn)
        goals = list_goals(conn, status=status)
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
def goal_show(goal_id: int) -> None:
    """Affiche le détail d'un objectif."""
    db_path = db_path_from_env()
    with closing(connect(db_path)) as conn:
        migrate(conn)
        g = get_goal(conn, goal_id)
    if g is None:
        raise click.ClickException(f"Aucun objectif #{goal_id}")
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
def plan_list(goal_id: int | None, status: str | None) -> None:
    """Liste les plans d'entraînement."""
    db_path = db_path_from_env()
    with closing(connect(db_path)) as conn:
        migrate(conn)
        plans = list_training_plans(conn, goal_id=goal_id, status=status)
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
def plan_show(plan_id: int) -> None:
    """Affiche un plan et toutes ses séances planifiées."""
    db_path = db_path_from_env()
    with closing(connect(db_path)) as conn:
        migrate(conn)
        p = get_training_plan(conn, plan_id)
        if p is None:
            raise click.ClickException(f"Aucun plan #{plan_id}")
        sessions = list_planned_sessions(conn, training_plan_id=plan_id)
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


@plan.group("session")
def plan_session() -> None:
    """Gestion des séances planifiées d'un plan."""


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
) -> None:
    """Ajoute une séance planifiée à un plan."""
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
        )
    click.echo(f"OK — séance #{s.id} créée le {s.planned_date.isoformat()} ({s.sport_type})")


@plan_session.command("list")
@click.option("--plan-id", "plan_id", required=True, type=int)
@click.option("--status", type=click.Choice(SESSION_STATUSES), default=None)
def plan_session_list(plan_id: int, status: str | None) -> None:
    """Liste les séances planifiées d'un plan."""
    db_path = db_path_from_env()
    with closing(connect(db_path)) as conn:
        migrate(conn)
        if get_training_plan(conn, plan_id) is None:
            raise click.ClickException(f"Aucun plan #{plan_id}")
        sessions = list_planned_sessions(conn, training_plan_id=plan_id, status=status)
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
    """Marque une séance comme réalisée (matching auto en lot 5b)."""
    db_path = db_path_from_env()
    with closing(connect(db_path)) as conn:
        migrate(conn)
        try:
            s = update_planned_session_status(conn, session_id, "done")
        except ValueError as exc:
            raise click.ClickException(str(exc)) from exc
    click.echo(f"OK — séance #{s.id} marquée 'done'")
