"""CLI for jbs — job board search."""

from __future__ import annotations

import csv
import io
import json
import os
import sys
import webbrowser
from pathlib import Path

import click
from dotenv import load_dotenv

load_dotenv()
from rich.console import Console
from rich.markdown import Markdown
from rich.table import Table

from jbs.config import Config, load_config


def _require_db(ctx: click.Context) -> "Store":
    """Get Store from context, failing with helpful message if DB doesn't exist."""
    from jbs.store import Store

    cfg: Config = ctx.obj["config"]
    if not Path(cfg.db_path).exists():
        click.echo(
            "No database found. Run `jbs init` to create the database and import tokens.\n"
            "  Quick start:\n"
            "    jbs init                # create DB + import tokens from tokens/*.txt\n"
            "    jbs scrape              # run all scrapers\n"
            "    jbs search --new        # browse what was found",
            err=True,
        )
        ctx.exit(1)
    return Store(cfg.db_path)


def _resolve_job_id(store: "Store", job_id: str) -> str:
    """Resolve a partial job ID to a full one. Exits with error if ambiguous or missing."""
    job = store.get_job(job_id)
    if job:
        return job_id
    # Partial match
    conn = store._conn()
    rows = conn.execute(
        "SELECT id FROM jobs WHERE id LIKE ?", (f"{job_id}%",)
    ).fetchall()
    if len(rows) == 1:
        return rows[0]["id"]
    if len(rows) > 1:
        click.echo(f"Ambiguous job ID '{job_id}'. Matches: {', '.join(r['id'] for r in rows[:5])}", err=True)
        raise SystemExit(1)
    click.echo(f"Job not found: {job_id}", err=True)
    raise SystemExit(1)


def _format_salary(row: dict) -> str:
    usd_min = row.get("salary_usd_min") or row.get("min_amount")
    usd_max = row.get("salary_usd_max") or row.get("max_amount")
    if not usd_min and not usd_max:
        return ""
    currency = row.get("currency") or "USD"
    parts = []
    if usd_min:
        parts.append(f"${usd_min:,.0f}")
    if usd_max:
        parts.append(f"${usd_max:,.0f}")
    return " - ".join(parts)


def _output_json(data: list[dict], keys: list[str] | None = None) -> None:
    if keys:
        data = [{k: row.get(k) for k in keys} for row in data]
    click.echo(json.dumps(data, indent=2, default=str))


def _output_csv(data: list[dict], keys: list[str]) -> None:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=keys, extrasaction="ignore")
    writer.writeheader()
    for row in data:
        writer.writerow({k: row.get(k, "") for k in keys})
    click.echo(buf.getvalue(), nl=False)


# -----------------------------------------------------------------------
# Main group
# -----------------------------------------------------------------------

@click.group()
@click.option("--db", default=None, help="SQLite database path")
@click.option("--format", "output_format", type=click.Choice(["table", "json", "csv"]), default=None)
@click.option("--no-color", is_flag=True)
@click.option("--verbose", is_flag=True)
@click.pass_context
def cli(ctx, db, output_format, no_color, verbose):
    cfg = load_config()
    if db:
        cfg.db_path = Path(db)

    # TTY detection: if not a TTY, default to JSON + no color
    if not sys.stdout.isatty():
        if output_format is None:
            output_format = "json"
        no_color = True

    if output_format is None:
        output_format = "table"

    ctx.ensure_object(dict)
    ctx.obj["config"] = cfg
    ctx.obj["format"] = output_format
    ctx.obj["verbose"] = verbose
    ctx.obj["no_color"] = no_color


# -----------------------------------------------------------------------
# jbs init
# -----------------------------------------------------------------------

@cli.command()
@click.pass_context
def init(ctx):
    """Create DB, import tokens from flat files."""
    from jbs.store import Store

    cfg: Config = ctx.obj["config"]
    db_path = Path(cfg.db_path)
    db_exists = db_path.exists()

    # Ensure parent dir
    db_path.parent.mkdir(parents=True, exist_ok=True)

    if db_exists:
        click.echo(f"Database already exists at {db_path}.")
    else:
        click.echo(f"Creating {db_path}... ", nl=False)

    store = Store(cfg.db_path)

    if not db_exists:
        click.echo("done.")

    # Import tokens
    click.echo("Importing tokens:")
    total_imported = 0

    token_files = [
        ("greenhouse", "tokens/greenhouse.txt", "tokens/greenhouse_raw.txt"),
        ("lever", "tokens/lever.txt", "tokens/lever_raw.txt"),
        ("ashby", "tokens/ashby.txt", None),
    ]

    for platform, validated, raw in token_files:
        filepath = validated if Path(validated).exists() else raw
        if filepath and Path(filepath).exists():
            count = store.import_tokens(platform, filepath)
            existing = len(store.get_all_tokens(platform))
            if count > 0:
                click.echo(f"  {platform:<12} {count} tokens from {filepath}")
            else:
                click.echo(f"  {platform:<12} 0 new ({existing} already in DB)")
            total_imported += count
        else:
            click.echo(f"  {platform:<12} no token file found")

    # Import 404 blocklists
    blocklist_total = 0
    blocklist_detail = []
    for platform in ("greenhouse", "lever", "ashby"):
        blocklist_path = f"tokens/{platform}_404.txt"
        if Path(blocklist_path).exists():
            with open(blocklist_path) as f:
                stale_tokens = [line.strip() for line in f if line.strip() and not line.startswith("#")]
            if stale_tokens:
                store.mark_tokens_stale(platform, stale_tokens)
                blocklist_total += len(stale_tokens)
                blocklist_detail.append(f"{len(stale_tokens)} {platform}")

    if blocklist_total:
        click.echo(f"  blocklists   {blocklist_total} tokens marked stale ({', '.join(blocklist_detail)})")

    if total_imported > 0:
        click.echo(f"Database initialized. {total_imported} tokens imported.")
    else:
        click.echo("Done. No new tokens to import.")

    store.close()


# -----------------------------------------------------------------------
# jbs scrape
# -----------------------------------------------------------------------

@cli.command()
@click.option("--sources", default=None, help="Comma-separated sources")
@click.option("--search-term", default=None, help="Filter by keyword")
@click.option("--hours-old", default=None, type=int, help="Only jobs posted within N hours")
@click.option("--classify", is_flag=True, help="Run enrichment after scraping")
@click.option("--dry-run", is_flag=True, help="Show what would be scraped")
@click.pass_context
def scrape(ctx, sources, search_term, hours_old, classify, dry_run):
    """Run scrapers, write results to the database."""
    from jbs.orchestrator import ScraperOrchestrator

    store = _require_db(ctx)
    cfg: Config = ctx.obj["config"]

    source_list = sources.split(",") if sources else cfg.default_sources

    # Check if any ATS sources have tokens
    ats_sources = {"greenhouse", "lever", "ashby"}
    skipped_ats = []
    for s in list(source_list):
        if s in ats_sources and not store.get_tokens(s):
            skipped_ats.append(s)

    if skipped_ats and not dry_run:
        active_sources = [s for s in source_list if s not in skipped_ats]
        if active_sources:
            click.echo(
                f"Scraping {len(active_sources)} sources "
                f"(no ATS tokens in DB — skipping {', '.join(skipped_ats)})..."
            )
        else:
            for s in skipped_ats:
                click.echo(f"  {s}: skipped (no tokens in DB)")
            click.echo(
                "  Tip: Run `jbs init` to import tokens from tokens/*.txt\n"
                "       or `jbs tokens add greenhouse <token>` to add one manually."
            )
            store.close()
            return
    else:
        click.echo(f"Scraping {len(source_list)} sources...")

    import logging
    if ctx.obj["verbose"]:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.INFO)

    orch = ScraperOrchestrator(cfg, store)
    result = orch.run(source_list, search_term, hours_old, dry_run)

    if not dry_run:
        click.echo(f"Run complete: {result['total']} new jobs inserted.")

    if classify and not dry_run:
        from jbs.enrich import EnrichmentPipeline
        click.echo("Running enrichment...")
        pipeline = EnrichmentPipeline(store)
        pipeline.run()
        click.echo("Enrichment complete.")

    store.close()


# -----------------------------------------------------------------------
# jbs search
# -----------------------------------------------------------------------

_SEARCH_JSON_KEYS = [
    "id", "title", "company_name", "location_raw", "work_arrangement",
    "min_amount", "max_amount", "currency", "salary_usd_min", "salary_usd_max",
    "site", "date_posted", "job_url", "ai_native", "seniority", "domain", "job_summary",
]

_SEARCH_CSV_KEYS = _SEARCH_JSON_KEYS


@cli.command()
@click.argument("query", required=False, default=None)
@click.option("--new", "new_only", is_flag=True, help="Jobs from latest run, not yet annotated")
@click.option("--company", default=None, help="Filter by company name")
@click.option("--location", default=None, help="Filter by location")
@click.option("--remote", "remote_flag", is_flag=True, help="Remote only")
@click.option("--onsite", is_flag=True, help="Onsite only")
@click.option("--source", default=None, help="Filter by source")
@click.option("--salary-min", default=None, type=float, help="Minimum salary")
@click.option("--days", default=None, type=int, help="Posted within N days")
@click.option("--ai-native", default=None, type=float, help="Minimum ai_native score")
@click.option("--seniority", default=None, help="Seniority level")
@click.option("--domain", default=None, help="Job domain")
@click.option("--industry", default=None, help="Company industry")
@click.option("--tag", multiple=True, help="Filter by tag")
@click.option("--interest", default=None, help="Filter by interest level")
@click.option("--engineering", is_flag=True, help="Only engineering roles")
@click.option("--vec", default=None, help="Semantic search query (requires embeddings)")
@click.option("--include-inactive", is_flag=True, help="Include deactivated jobs")
@click.option("--sort", default="date", type=click.Choice(["date", "salary", "company", "ai-native"]))
@click.option("--limit", default=50, type=int)
@click.option("--offset", default=0, type=int)
@click.pass_context
def search(ctx, query, new_only, company, location, remote_flag, onsite, source,
           salary_min, days, ai_native, seniority, domain, industry,
           tag, interest, engineering, vec, include_inactive, sort, limit, offset):
    """Query the job database."""
    from jbs.models import SearchQuery

    store = _require_db(ctx)

    if vec and not store.has_vec():
        click.echo("Warning: --vec requires sqlite-vec and mlx-embedding-models. Install: pip install -e '.[vector]'", err=True)

    work_arr = None
    if remote_flag:
        work_arr = ["remote"]
    elif onsite:
        work_arr = ["onsite"]

    sq = SearchQuery(
        text=query,
        new_only=new_only,
        companies=[company] if company else None,
        work_arrangement=work_arr,
        sites=[source] if source else None,
        min_salary=salary_min,
        hours_old=days * 24 if days else None,
        ai_native_min=ai_native,
        seniority=seniority.split(",") if seniority else None,
        domains=domain.split(",") if domain else None,
        industries=industry.split(",") if industry else None,
        tags=list(tag) if tag else None,
        engineering_only=engineering,
        include_inactive=include_inactive,
        vec_query=vec,
        limit=limit,
        offset=offset,
    )

    results = store.search(sq)

    # Get total count for footer
    total_count = len(results)

    fmt = ctx.obj["format"]
    if fmt == "json":
        _output_json(results, _SEARCH_JSON_KEYS)
    elif fmt == "csv":
        _output_csv(results, _SEARCH_CSV_KEYS)
    else:
        console = Console(no_color=ctx.obj["no_color"])
        table = Table(title=None)
        table.add_column("ID", style="cyan", no_wrap=True)
        table.add_column("Title")
        table.add_column("Company")
        table.add_column("Location")
        table.add_column("Salary", justify="right")
        table.add_column("Source")
        table.add_column("Posted")

        for row in results:
            table.add_row(
                row.get("id", ""),
                row.get("title", ""),
                row.get("company_name", ""),
                row.get("location_raw", ""),
                _format_salary(row),
                row.get("site", ""),
                str(row.get("date_posted", ""))[:10],
            )

        console.print(table)
        console.print(f"Showing {total_count} results.")

    store.close()


# -----------------------------------------------------------------------
# jbs show
# -----------------------------------------------------------------------

@cli.command()
@click.argument("job_id")
@click.option("--no-desc", is_flag=True, help="Hide the full description")
@click.option("--open", "open_url", is_flag=True, help="Open job URL in browser")
@click.pass_context
def show(ctx, job_id, no_desc, open_url):
    """Display full details for a single job."""
    store = _require_db(ctx)
    job_id = _resolve_job_id(store, job_id)
    job = store.get_job(job_id)

    if open_url and job.get("job_url"):
        webbrowser.open(job["job_url"])

    fmt = ctx.obj["format"]
    if fmt == "json":
        click.echo(json.dumps(job, indent=2, default=str))
        store.close()
        return

    console = Console(no_color=ctx.obj["no_color"])

    # Header
    title = job.get("title", "Unknown")
    company = job.get("company_name", "Unknown")
    location = job.get("location_raw", "")
    work_arr = job.get("work_arrangement", "")
    site = job.get("site", "")
    console.print(f"[bold]{title}[/bold]")
    console.print(f"{company}  ·  {location}  ·  {work_arr}  ·  {site}")
    console.rule()

    # Details
    salary = _format_salary(job)
    if salary:
        console.print(f"  Salary       {salary}")
    if job.get("seniority"):
        domain_str = job.get("domain", "")
        console.print(f"  Seniority    {job['seniority']:<16}Domain     {domain_str}")
    if job.get("date_posted"):
        console.print(f"  Posted       {str(job['date_posted'])[:10]}")
    if job.get("job_url"):
        console.print(f"  URL          {job['job_url']}")
    if job.get("company_name"):
        desc = job.get("company_description") or ""
        console.print(f"  Company      {job['company_name']}" + (f" — {desc}" if desc else ""))
    if job.get("ai_native") is not None:
        industry = job.get("industry") or ""
        console.print(f"  AI-Native    {job['ai_native']:<16}Industry   {industry}")
    if job.get("tags"):
        console.print(f"  Tags         {' '.join('#' + t for t in job['tags'])}")
    if job.get("annotation_interest"):
        console.print(f"  Interest     {job['annotation_interest']}")
    if job.get("annotation_note"):
        console.print(f'  Notes        "{job["annotation_note"]}"')
    if job.get("job_summary"):
        console.print(f"  Summary      {job['job_summary']}")

    # Description
    if not no_desc and job.get("description"):
        console.rule()
        console.print(Markdown(job["description"]))

    store.close()


# -----------------------------------------------------------------------
# jbs enrich
# -----------------------------------------------------------------------

@cli.command()
@click.option("--stage", type=click.Choice(["rules", "jobs", "companies", "embeddings"]), default=None)
@click.option("--dry-run", is_flag=True)
@click.option("--source", default=None)
@click.option("--force", is_flag=True)
@click.pass_context
def enrich(ctx, stage, dry_run, source, force):
    """Run the classification/enrichment pipeline."""
    import logging

    from jbs.enrich import EnrichmentPipeline

    store = _require_db(ctx)

    if ctx.obj["verbose"]:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.INFO)

    pipeline = EnrichmentPipeline(store)
    pipeline.run(stage=stage, force=force, source=source, dry_run=dry_run)

    store.close()


# -----------------------------------------------------------------------
# jbs annotate
# -----------------------------------------------------------------------

@cli.command()
@click.argument("job_id")
@click.option("--tag", multiple=True, help="Add a tag")
@click.option("--untag", multiple=True, help="Remove a tag")
@click.option("--note", default=None, help="Free-text note")
@click.option("--rating", default=None, type=click.IntRange(1, 5), help="Rating 1-5")
@click.option("--pros", multiple=True, help="Add a pro")
@click.option("--cons", multiple=True, help="Add a con")
@click.pass_context
def annotate(ctx, job_id, tag, untag, note, rating, pros, cons):
    """Tag, rate, note a job."""
    store = _require_db(ctx)
    job_id = _resolve_job_id(store, job_id)
    job = store.get_job(job_id)

    # Build annotation kwargs
    ann_kwargs: dict = {}
    if rating is not None:
        ann_kwargs["rating"] = rating
    if note is not None:
        ann_kwargs["note"] = note
    if pros:
        ann_kwargs["pros"] = json.dumps(list(pros))
    if cons:
        ann_kwargs["cons"] = json.dumps(list(cons))

    if ann_kwargs:
        store.annotate(job_id, **ann_kwargs)

    # Tags
    for t in tag:
        store.add_tag(job_id, t)
    for t in untag:
        store.remove_tag(job_id, t)

    title = job.get("title", "")
    company = job.get("company_name", "")
    click.echo(f"Updated {job_id} ({title} @ {company})")
    for t in tag:
        click.echo(f"  + tag: {t}")
    for t in untag:
        click.echo(f"  - tag: {t}")
    if rating is not None:
        click.echo(f"  rating: {rating}")
    if note is not None:
        click.echo(f"  note: {note}")

    store.close()


# -----------------------------------------------------------------------
# jbs apply
# -----------------------------------------------------------------------

_INTEREST_STAGES = [
    "interested", "applied", "phone-screen", "take-home",
    "onsite", "offer", "rejected", "withdrawn",
]


@cli.command(name="apply")
@click.argument("job_id", required=False, default=None)
@click.option("--stage", default="applied", type=click.Choice(_INTEREST_STAGES))
@click.option("--note", default=None)
@click.option("--list", "list_all", is_flag=True, help="Show all jobs with active interest")
@click.pass_context
def apply_cmd(ctx, job_id, stage, note, list_all):
    """Track application status."""
    store = _require_db(ctx)

    if list_all:
        conn = store._conn()
        rows = conn.execute(
            """SELECT a.interest, j.id, j.title, COALESCE(c.name, j.company_raw) AS company_name
               FROM job_annotations a
               JOIN jobs j ON j.id = a.job_id
               LEFT JOIN companies c ON c.id = j.company_id
               WHERE a.interest IS NOT NULL
               ORDER BY a.interest, j.title"""
        ).fetchall()

        fmt = ctx.obj["format"]
        if fmt == "json":
            _output_json([dict(r) for r in rows])
        else:
            console = Console(no_color=ctx.obj["no_color"])
            table = Table(title="Application Pipeline")
            table.add_column("Status")
            table.add_column("ID", style="cyan")
            table.add_column("Title")
            table.add_column("Company")
            for row in rows:
                table.add_row(row["interest"], row["id"], row["title"], row["company_name"])
            console.print(table)
            if not rows:
                click.echo("No applications tracked yet.")
        store.close()
        return

    if not job_id:
        click.echo("Usage: jbs apply <job-id> [--stage ...] or jbs apply --list", err=True)
        store.close()
        raise SystemExit(1)

    job_id = _resolve_job_id(store, job_id)
    job = store.get_job(job_id)

    # Normalize stage for DB (hyphens to underscores)
    db_stage = stage.replace("-", "_")
    store.set_interest(job_id, db_stage, note)

    title = job.get("title", "")
    company = job.get("company_name", "")
    click.echo(f"Applied to {job_id} ({title} @ {company})")
    click.echo(f"  interest: {stage}")

    store.close()


# -----------------------------------------------------------------------
# jbs stats
# -----------------------------------------------------------------------

@cli.command()
@click.option("--runs", default=5, type=int, help="Number of recent runs to show")
@click.pass_context
def stats(ctx, runs):
    """Database statistics, scrape history."""
    store = _require_db(ctx)
    data = store.get_stats()

    fmt = ctx.obj["format"]
    if fmt == "json":
        click.echo(json.dumps(data, indent=2, default=str))
        store.close()
        return

    console = Console(no_color=ctx.obj["no_color"])
    console.print(f"[bold]Jobs:[/bold] {data['jobs_total']} total, {data['jobs_active']} active")
    console.print(f"[bold]Companies:[/bold] {data['companies']}")

    if data["by_site"]:
        table = Table(title="Jobs by Source")
        table.add_column("Source")
        table.add_column("Count", justify="right")
        for site, count in sorted(data["by_site"].items()):
            table.add_row(site, str(count))
        console.print(table)

    # Token counts
    if data.get("token_counts"):
        _print_token_table(console, data["token_counts"])

    # Recent runs
    conn = store._conn()
    recent = conn.execute(
        "SELECT * FROM runs ORDER BY started_at DESC LIMIT ?", (runs,)
    ).fetchall()
    if recent:
        table = Table(title="Recent Runs")
        table.add_column("Run ID")
        table.add_column("Sources")
        table.add_column("Jobs", justify="right")
        table.add_column("Status")
        table.add_column("Started")
        for row in recent:
            table.add_row(
                row["run_id"],
                row["sources"] or "",
                str(row["total_jobs"] or 0),
                row["status"] or "",
                str(row["started_at"] or "")[:19],
            )
        console.print(table)

    store.close()


# -----------------------------------------------------------------------
# jbs tokens (group)
# -----------------------------------------------------------------------

@cli.group()
def tokens():
    """Token management subcommands."""
    pass


def _print_token_table(console: Console, counts: dict) -> None:
    table = Table(title="Tokens")
    table.add_column("Platform")
    table.add_column("Valid", justify="right")
    table.add_column("Stale", justify="right")
    table.add_column("Unchecked", justify="right")
    table.add_column("Total", justify="right")
    grand = {"valid": 0, "stale": 0, "unchecked": 0}
    for platform in sorted(counts):
        c = counts[platform]
        total = c.get("valid", 0) + c.get("stale", 0) + c.get("unchecked", 0)
        table.add_row(
            platform,
            str(c.get("valid", 0)),
            str(c.get("stale", 0)),
            str(c.get("unchecked", 0)),
            str(total),
        )
        for k in grand:
            grand[k] += c.get(k, 0)
    grand_total = sum(grand.values())
    table.add_row(
        "[bold]Total[/bold]",
        f"[bold]{grand['valid']}[/bold]",
        f"[bold]{grand['stale']}[/bold]",
        f"[bold]{grand['unchecked']}[/bold]",
        f"[bold]{grand_total}[/bold]",
    )
    console.print(table)


@tokens.command(name="list")
@click.pass_context
def tokens_list(ctx):
    """Show token counts by platform and status."""
    store = _require_db(ctx)
    counts = store.get_token_counts()

    fmt = ctx.obj["format"]
    if fmt == "json":
        click.echo(json.dumps(counts, indent=2))
    else:
        console = Console(no_color=ctx.obj["no_color"])
        if counts:
            _print_token_table(console, counts)
        else:
            click.echo("No tokens in database. Run `jbs init` to import.")

    store.close()


@tokens.command(name="add")
@click.argument("platform", type=click.Choice(["greenhouse", "lever", "ashby"]))
@click.argument("token")
@click.option("--name", default=None, help="Explicit company name")
@click.pass_context
def tokens_add(ctx, platform, token, name):
    """Add a single token manually."""
    store = _require_db(ctx)

    created = store.add_token(platform, token, company_name=name)
    display_name = name or token.replace("-", " ").replace("_", " ").title()

    if created:
        click.echo(f"Added {platform} token: {token} ({display_name})")
        click.echo("  Status: unchecked — run `jbs tokens validate` to verify.")
    else:
        # Already exists — look up status
        conn = store._conn()
        row = conn.execute(
            "SELECT name, token_status, token_checked_at FROM companies WHERE ats_platform = ? AND ats_token = ?",
            (platform, token),
        ).fetchone()
        status = row["token_status"] if row else "unknown"
        checked = row["token_checked_at"] if row else None
        existing_name = row["name"] if row else display_name
        msg = f"Token already exists: {platform}/{token} ({existing_name})"
        if checked:
            msg += f"\n  Status: {status} (last checked {checked[:10]})"
        else:
            msg += f"\n  Status: {status}"
        click.echo(msg)

    store.close()


@tokens.command(name="validate")
@click.option("--platform", type=click.Choice(["greenhouse", "lever", "ashby"]), default=None)
@click.option("--status", "check_status", type=click.Choice(["unchecked", "all"]), default="unchecked")
@click.pass_context
def tokens_validate(ctx, platform, check_status):
    """Validate ATS tokens against live APIs."""
    import concurrent.futures

    import requests

    store = _require_db(ctx)

    platforms = [platform] if platform else ["greenhouse", "lever", "ashby"]

    click.echo("Validating tokens...")
    total_valid = 0
    total_stale = 0

    for plat in platforms:
        if check_status == "unchecked":
            token_list = store.get_tokens_by_status(plat, "unchecked")
        else:
            token_list = store.get_all_tokens(plat)

        if not token_list:
            click.echo(f"  {plat:<12} no tokens to validate")
            continue

        valid, stale = _validate_tokens_concurrent(plat, token_list)
        store.mark_tokens_valid(plat, valid)
        store.mark_tokens_stale(plat, stale)

        click.echo(f"  {plat:<12} {len(token_list)} checked — {len(valid)} valid, {len(stale)} stale")
        total_valid += len(valid)
        total_stale += len(stale)

    click.echo(f"Validation complete. {total_valid} valid, {total_stale} stale.")
    store.close()


def _validate_tokens_concurrent(
    platform: str, tokens: list[str], max_workers: int = 10
) -> tuple[list[str], list[str]]:
    """Validate tokens against live APIs. Returns (valid, stale)."""
    import concurrent.futures

    import requests

    def check_one(token: str) -> tuple[str, bool]:
        url = _token_check_url(platform, token)
        try:
            resp = requests.get(url, timeout=15)
            if platform == "greenhouse":
                return token, resp.status_code == 200 and resp.json().get("jobs", []) is not None
            return token, resp.status_code == 200
        except Exception:
            return token, False

    valid = []
    stale = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(check_one, t): t for t in tokens}
        for future in concurrent.futures.as_completed(futures):
            token, is_valid = future.result()
            if is_valid:
                valid.append(token)
            else:
                stale.append(token)

    return valid, stale


def _token_check_url(platform: str, token: str) -> str:
    if platform == "greenhouse":
        return f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs"
    elif platform == "lever":
        return f"https://api.lever.co/v0/postings/{token}"
    elif platform == "ashby":
        return f"https://api.ashbyhq.com/posting-api/job-board/{token}"
    raise ValueError(f"Unknown platform: {platform}")


@tokens.command(name="discover")
@click.option("--phase", type=click.Choice(["harvest", "find-careers", "detect-ats"]), default=None)
@click.option("--status", "show_status", is_flag=True, help="Show discovery progress summary")
@click.pass_context
def tokens_discover(ctx, phase, show_status):
    """Discover ATS tokens from HN comments."""
    import logging

    from jbs.discover import run_discovery

    store = _require_db(ctx)

    if show_status:
        summary = store.get_hn_discovery_summary()
        fmt = ctx.obj["format"]
        if fmt == "json":
            click.echo(json.dumps(summary, indent=2))
        else:
            console = Console(no_color=ctx.obj["no_color"])
            console.print(f"[bold]Total HN URLs processed:[/bold] {summary['total']}")
            if summary.get("by_status"):
                for status, count in sorted(summary["by_status"].items()):
                    console.print(f"  {status:<12} {count}")
            if summary.get("by_platform"):
                console.print("[bold]ATS tokens found:[/bold]")
                for plat, count in sorted(summary["by_platform"].items()):
                    console.print(f"  {plat:<12} {count}")
        store.close()
        return

    if ctx.obj["verbose"]:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.INFO)

    run_discovery(store, phase=phase, verbose=ctx.obj["verbose"])
    store.close()


# -----------------------------------------------------------------------
# jbs models (group)
# -----------------------------------------------------------------------

@cli.group()
def models():
    """Embedding model management."""
    pass


@models.command(name="download")
@click.pass_context
def models_download(ctx):
    """Download all embedding models (run once before jbs enrich --stage embeddings)."""
    import logging

    from jbs.embeddings import download_models, get_model_status

    logging.basicConfig(level=logging.INFO)
    console = Console(no_color=ctx.obj["no_color"])

    console.print("Downloading embedding models...")
    results = download_models()

    for name, ok in results.items():
        status = "[green]OK[/green]" if ok else "[red]FAILED[/red]"
        console.print(f"  {name}: {status}")

    if all(results.values()):
        console.print("\nAll models ready.")
    else:
        console.print("\n[red]Some models failed to download.[/red]")
        raise SystemExit(1)


@models.command(name="list")
@click.pass_context
def models_list(ctx):
    """Show status of embedding models."""
    from jbs.embeddings import get_model_status

    console = Console(no_color=ctx.obj["no_color"])
    statuses = get_model_status()

    for m in statuses:
        icon = "[green]cached[/green]" if m["cached"] else "[red]missing[/red]"
        console.print(f"  {m['role']:<14} {m['name']:<45} {icon}")

    if not all(m["cached"] for m in statuses):
        console.print("\nRun [bold]jbs models download[/bold] to fetch missing models.")


# -----------------------------------------------------------------------
# Entry point
# -----------------------------------------------------------------------

def main():
    cli()
