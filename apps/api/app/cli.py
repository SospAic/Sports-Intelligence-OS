import argparse
import asyncio
import getpass
import os
from pathlib import Path

from sqlalchemy import select

from app.core.config import get_settings
from app.db.session import create_engine_and_session
from app.models.workspace import Workspace, WorkspaceMembership
from app.rules.parser import parse_v79_bytes
from app.services.automation_seed import seed_automation_examples
from app.services.bootstrap import bootstrap_admin
from app.services.editorial_rules import EditorialRuleService
from app.services.generation_seed import seed_generation_defaults
from app.services.platform_catalog_seed import seed_platform_catalog
from app.services.news_seed import seed_news_source_examples


async def run_bootstrap(args: argparse.Namespace) -> None:
    settings = get_settings()
    email = args.email or os.getenv("SIO_BOOTSTRAP_ADMIN_EMAIL")
    password = os.getenv("SIO_BOOTSTRAP_ADMIN_PASSWORD")
    workspace_name = os.getenv("SIO_BOOTSTRAP_WORKSPACE_NAME", "Sports Intelligence OS")

    if not email:
        email = (await asyncio.to_thread(input, "Administrator email: ")).strip()
    if not password:
        password = await asyncio.to_thread(getpass.getpass, "Administrator password: ")
    if not email or not password:
        raise SystemExit("administrator email and password are required")

    engine, session_factory = create_engine_and_session(settings)
    try:
        async with session_factory() as session:
            user = await bootstrap_admin(
                session,
                settings,
                email=email,
                password=password,
                display_name=args.display_name or "系统管理员",
                workspace_name=workspace_name,
            )
        print(
            f"Created administrator {user.email_display}. "
            "No password was printed or stored in code."
        )
    finally:
        await engine.dispose()


async def run_seed_platforms() -> None:
    settings = get_settings()
    engine, session_factory = create_engine_and_session(settings)
    try:
        async with session_factory() as session:
            created, updated = await seed_platform_catalog(session)
        print(
            f"Platform catalog ready; created {created} platform records, "
            f"updated {updated} existing records."
        )
    finally:
        await engine.dispose()


async def run_seed_news_sources() -> None:
    settings = get_settings()
    engine, session_factory = create_engine_and_session(settings)
    try:
        async with session_factory() as session:
            workspace_id = await session.scalar(
                select(Workspace.id).where(Workspace.status == "active").order_by(Workspace.id)
            )
            if workspace_id is None:
                raise SystemExit("create an administrator workspace before seeding news sources")
            created = await seed_news_source_examples(session, workspace_id)
        print(
            "News source examples ready; "
            f"created={created}. Network RSS examples remain disabled by default."
        )
    finally:
        await engine.dispose()


def read_rule_source(file_name: str) -> bytes:
    source_path = Path(file_name).resolve()
    if not source_path.is_file():
        raise SystemExit(f"rule source file does not exist: {source_path}")
    return source_path.read_bytes()


async def run_import_rules(args: argparse.Namespace) -> None:
    settings = get_settings()
    document = parse_v79_bytes(await asyncio.to_thread(read_rule_source, args.file))
    engine, session_factory = create_engine_and_session(settings)
    try:
        async with session_factory() as session:
            membership = await session.scalar(
                select(WorkspaceMembership)
                .where(
                    WorkspaceMembership.status == "active",
                    WorkspaceMembership.role.in_(("owner", "admin")),
                )
                .order_by(WorkspaceMembership.joined_at)
            )
            if membership is None:
                raise SystemExit("create an administrator workspace before importing rules")
            result = await EditorialRuleService(session).import_document(
                membership.workspace_id,
                membership.user_id,
                document,
                key="elite-sports-narration-v7-9",
                name="Elite Sports Faceless Narration Engine V7.9",
                description="完整 V7.9 原文及可编辑结构化规则",
                tags=["v7.9", "sports", "narration", "full-source"],
                changelog="导入完整 V7.9 原文并生成结构化规则",
                publish=True,
            )
        print(
            "Editorial rules import complete; "
            f"created={result.created}, version={result.version.version}, "
            f"source_hash={result.version.source_hash}, "
            f"sections={result.version.section_count}, rules={result.version.rule_count}, "
            f"warnings={result.validation.warnings}."
        )
    finally:
        await engine.dispose()


async def run_seed_generation() -> None:
    settings = get_settings()
    engine, session_factory = create_engine_and_session(settings)
    try:
        async with session_factory() as session:
            membership = await session.scalar(
                select(WorkspaceMembership)
                .where(
                    WorkspaceMembership.status == "active",
                    WorkspaceMembership.role.in_(("owner", "admin")),
                )
                .order_by(WorkspaceMembership.joined_at)
            )
            if membership is None:
                raise SystemExit("create an administrator workspace before seeding generation")
            try:
                result = await seed_generation_defaults(
                    session, membership.workspace_id, membership.user_id
                )
            except ValueError as exc:
                raise SystemExit(str(exc)) from exc
        print(
            "Generation defaults ready; "
            f"collection_created={result['collection_created']}, "
            f"version_created={result['version_created']}, "
            f"workflow_created={result['workflow_created']}."
        )
    finally:
        await engine.dispose()


async def run_seed_automations() -> None:
    settings = get_settings()
    engine, session_factory = create_engine_and_session(settings)
    try:
        async with session_factory() as session:
            membership = await session.scalar(
                select(WorkspaceMembership)
                .where(
                    WorkspaceMembership.status == "active",
                    WorkspaceMembership.role.in_(("owner", "admin")),
                )
                .order_by(WorkspaceMembership.joined_at)
            )
            if membership is None:
                raise SystemExit("create an administrator workspace before seeding automations")
            created = await seed_automation_examples(
                session, membership.workspace_id, membership.user_id
            )
        print(f"Disabled automation examples ready; created={created}.")
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="Sports Intelligence OS administrative CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)
    bootstrap_parser = subparsers.add_parser(
        "bootstrap-admin", help="Create the first administrator and owner membership"
    )
    bootstrap_parser.add_argument("--email")
    bootstrap_parser.add_argument("--display-name")
    subparsers.add_parser("seed-platforms", help="Create the idempotent platform catalog")
    subparsers.add_parser(
        "seed-news-sources",
        help="Create disabled official RSS examples and an empty manual source",
    )
    import_parser = subparsers.add_parser(
        "import-rules", help="Import the complete V7.9 source and structured rules"
    )
    import_parser.add_argument("--file", required=True)
    subparsers.add_parser(
        "seed-generation", help="Create the first published Prompt and generation workflow"
    )
    subparsers.add_parser("seed-automations", help="Create three disabled automation examples")
    args = parser.parse_args()

    if args.command == "bootstrap-admin":
        asyncio.run(run_bootstrap(args))
    elif args.command == "seed-platforms":
        asyncio.run(run_seed_platforms())
    elif args.command == "seed-news-sources":
        asyncio.run(run_seed_news_sources())
    elif args.command == "import-rules":
        asyncio.run(run_import_rules(args))
    elif args.command == "seed-generation":
        asyncio.run(run_seed_generation())
    elif args.command == "seed-automations":
        asyncio.run(run_seed_automations())


if __name__ == "__main__":
    main()
