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
    connect,
    count_activities,
    db_path_from_env,
    get_last_sync,
    get_latest_metrics,
    get_metrics_history,
    insert_athlete_metrics,
    metrics_values_equal,
    migrate,
    stats_by_sport,
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
