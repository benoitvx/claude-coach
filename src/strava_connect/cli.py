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
    get_athlete,
    get_last_sync,
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
        profile = get_athlete(conn, tokens.athlete_id)
    if profile is None:
        click.echo("  profil athlète : aucun en DB (à saisir en Lot 4)")
    else:
        click.echo(
            f"  profil athlète : poids={profile.weight_kg} kg, "
            f"FTP={profile.ftp_watts}, FCmax={profile.fc_max}"
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
