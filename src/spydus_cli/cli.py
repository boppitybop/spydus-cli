import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .client import SpydusClient
from .output import format_records_table


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Spydus CLI")
    parser.add_argument(
        "--library",
        default=None,
        help="Library profile key (e.g. act, city, uni) for SPYDUS_<PROFILE>_* env vars",
    )
    parser.add_argument("--base-url", help="Spydus base URL", default=None)
    parser.add_argument("--user", help="Library username/card number")
    parser.add_argument("--password", help="Library password")

    parser.add_argument(
        "--setup-creds",
        action="store_true",
        help="Prompt for credentials and optionally save them",
    )
    parser.add_argument(
        "--clear-creds", action="store_true", help="Clear saved credentials from .env"
    )

    save_group = parser.add_mutually_exclusive_group()
    save_group.add_argument(
        "--save-creds", action="store_true", help="Save prompted credentials to .env"
    )
    save_group.add_argument(
        "--no-save-creds",
        action="store_true",
        help="Do not save prompted credentials",
    )

    parser.add_argument("--check-new", action="store_true", help="Check for new items")
    parser.add_argument("--check-loans", action="store_true", help="Check current loans")
    parser.add_argument(
        "--renew-all",
        action="store_true",
        help="Renew all overdue renewable loans automatically (default-safe mode)",
    )
    parser.add_argument(
        "--renew-overdue",
        action="store_true",
        help="Renew overdue renewable loans only",
    )
    parser.add_argument(
        "--renew-all-loans",
        action="store_true",
        help="Renew all renewable loans (including non-overdue)",
    )
    parser.add_argument(
        "--renew-confirm", action="store_true", help="Prompt before renewing each loan"
    )

    parser.add_argument("--check-account", action="store_true", help="Check account sections")
    parser.add_argument(
        "--account-sections",
        default="pickups,reservations,requests,history",
        help="Comma-separated sections: pickups,reservations,requests,history",
    )

    parser.add_argument("--catalogue-query", help="Search query for catalogue")
    parser.add_argument("--catalogue-limit", type=int, default=10, help="Catalogue result limit")
    _CATALOGUE_TYPES = ["book", "ebook", "audiobook", "eaudiobook", "dvd", "music-cd"]
    parser.add_argument(
        "--catalogue-type",
        default="",
        metavar="TYPE",
        help=(
            "Comma-separated item types to filter results. "
            f"Choices: {', '.join(_CATALOGUE_TYPES)}. "
            "Aliases also accepted (e.g. music, cd, books, e-book)."
        ),
    )
    parser.add_argument(
        "--place-hold-url",
        help="Place a hold using a direct Spydus hold/request URL",
    )
    parser.add_argument(
        "--place-hold-item",
        help="Alias for --catalogue-query when placing a hold (kept for backward compat)",
    )
    parser.add_argument(
        "--place-hold-item-index",
        type=int,
        metavar="N",
        help=(
            "Reserve the Nth catalogue result. "
            "Use with --catalogue-query (or --place-hold-item) to search and reserve in one step."
        ),
    )
    parser.add_argument(
        "--pickup-branch",
        help="Pickup branch name when submitting a reservation",
    )

    parser.add_argument(
        "--loans-view",
        choices=["auto", "overdue", "top10", "all"],
        default="auto",
        help="Loan selection mode: auto defaults to overdue, else top N by next due date",
    )
    parser.add_argument("--loans-limit", type=int, default=10, help="Number of loans for top mode")
    parser.add_argument(
        "--output",
        choices=["table", "compact", "json"],
        default="table",
        help="Output format",
    )
    parser.add_argument(
        "--color",
        choices=["auto", "always", "never"],
        default="auto",
        help="Color mode for compact output",
    )
    parser.add_argument("--verbose", action="store_true", help="Enable verbose logs")

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.loans_limit < 1:
        parser.error("--loans-limit must be >= 1")
    if args.catalogue_limit < 1:
        parser.error("--catalogue-limit must be >= 1")
    if args.place_hold_item_index is not None and args.place_hold_item_index < 1:
        parser.error("--place-hold-item-index must be >= 1")

    # --place-hold-item is an alias: merge into catalogue_query
    if args.place_hold_item and not args.catalogue_query:
        args.catalogue_query = args.place_hold_item

    if args.place_hold_item_index is not None and not args.catalogue_query:
        parser.error("--place-hold-item-index requires --catalogue-query (or --place-hold-item)")

    json_mode = args.output == "json"
    requested_catalogue_types = [
        value.strip()
        for value in args.catalogue_type.split(",")
        if value.strip()
    ]

    client = SpydusClient(
        library=args.library,
        base_url=args.base_url,
        username=args.user,
        password=args.password,
        verbose=args.verbose,
    )

    env_path = Path(".env")

    if args.clear_creds:
        client.clear_credentials(env_path)
        client.clear_session_cache()
        if not json_mode:
            print("Cleared saved credentials and local session cache.")
        else:
            print(json.dumps({"ok": True, "action": "clear_creds"}, indent=2))
        return

    if args.setup_creds:
        if not client.prompt_for_credentials():
            sys.exit(1)

        should_save = args.save_creds
        if not args.save_creds and not args.no_save_creds:
            answer = input("Save credentials to .env for future runs? [Y/n]: ").strip().lower()
            should_save = answer in {"", "y", "yes"}

        if should_save:
            client.save_credentials(env_path)
            if not json_mode:
                print("Credentials saved to .env")
        elif not json_mode:
            print("Credentials captured for this run only")

    requires_login = any(
        [
            args.check_loans,
            args.renew_all,
            args.renew_overdue,
            args.renew_all_loans,
            args.renew_confirm,
            args.check_account,
            bool(args.place_hold_url),
            args.place_hold_item_index is not None,
        ]
    )

    if requires_login and (not client.username or not client.password):
        if not client.prompt_for_credentials():
            sys.exit(1)

        if args.save_creds and not args.no_save_creds:
            client.save_credentials(env_path)

    payload: dict[str, Any] = {
        "schema_version": "1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "library": client.profile_key,
        "base_url": client.base_url,
        "data": {},
    }

    if args.check_new:
        new_items = client.check_new_items()
        payload["data"]["new_items"] = new_items
        if not json_mode:
            print("\n--- New Items ---")
            if not new_items:
                print("No new items found.")
            else:
                for item in new_items[:10]:
                    print(
                        f"{item.get('title', '')} ({item.get('year', 'N/A')}) "
                        f"by {item.get('author', 'N/A')}"
                    )

    loans: list[dict[str, Any]] = []
    if requires_login:
        if not client.login():
            sys.exit(1)

    if (
        args.check_loans
        or args.renew_all
        or args.renew_overdue
        or args.renew_all_loans
        or args.renew_confirm
    ):
        loans = client.get_current_loans()
        selected_loans, loans_mode = client.select_display_loans(
            loans,
            mode=args.loans_view,
            limit=args.loans_limit,
        )

        payload["data"]["loans"] = {
            "mode": loans_mode,
            "total": len(loans),
            "selected": selected_loans,
        }

        if not json_mode and args.check_loans:
            if loans_mode == "overdue":
                print("\n--- Current Loans (Overdue) ---")
            elif loans_mode == "top":
                print(f"\n--- Current Loans (Top {args.loans_limit} by Next Due Date) ---")
            elif loans_mode == "all":
                print("\n--- Current Loans (All, Ordered by Due Date) ---")
            else:
                print("\n--- Current Loans ---")
            print(f"Showing {len(selected_loans)} of {len(loans)} loans")
            print(
                client.render_loans(
                    selected_loans,
                    output=args.output,
                    use_color=client.should_use_color(args.color),
                )
            )

    if args.renew_all or args.renew_overdue or args.renew_all_loans or args.renew_confirm:
        overdue_only = (args.renew_all or args.renew_overdue) and not args.renew_all_loans
        renewal_result = client.renew_loans(
            loans,
            confirm_each=args.renew_confirm,
            overdue_only=overdue_only,
        )
        payload["data"]["renewals"] = renewal_result

        if not json_mode:
            print("\n--- Renewal Summary ---")
            print(
                f"Attempted: {renewal_result['attempted']} | "
                f"Succeeded: {renewal_result['succeeded']} | "
                f"Failed: {renewal_result['failed']} | "
                f"Skipped: {renewal_result['skipped']}"
            )
            result_rows = []
            for item in renewal_result["results"]:
                result_rows.append({
                    "title": item.get("title", "Unknown"),
                    "result": "Renewed" if item.get("success") else "Failed",
                    "reason": item.get("reason", ""),
                })
            if result_rows:
                print(format_records_table(result_rows, ["title", "result", "reason"]))

    if args.check_account:
        sections = [
            section.strip().lower()
            for section in args.account_sections.split(",")
            if section.strip()
        ]
        account_data: dict[str, list[dict[str, Any]]] = {}

        if "pickups" in sections:
            account_data["pickups"] = client.get_available_pickups()
        if "reservations" in sections:
            account_data["reservations"] = client.get_reservations(include_available=False)
        if "requests" in sections:
            account_data["requests"] = client.get_requests()
        if "history" in sections:
            account_data["history"] = client.get_history()

        payload["data"]["account"] = account_data

        if not json_mode:
            if "pickups" in account_data:
                print("\n--- Available for Pickup ---")
                print(format_records_table(account_data["pickups"], ["#", "title", "pickup_by", "status"]))
            if "reservations" in account_data:
                print("\n--- Reservations Not Yet Available ---")
                print(format_records_table(account_data["reservations"], ["#", "title", "status"]))
            if "requests" in account_data:
                print("\n--- Requests ---")
                print(format_records_table(account_data["requests"], ["#", "title", "status"]))
            if "history" in account_data:
                print("\n--- History ---")
                print(format_records_table(account_data["history"], ["#", "date", "title", "action"]))

    # ── Catalogue search (shared by display and hold) ──
    catalogue_items: list[dict[str, Any]] = []
    if args.catalogue_query:
        catalogue_items = client.query_catalogue(
            args.catalogue_query,
            limit=max(args.catalogue_limit, 10),
            item_types=requested_catalogue_types,
        )
        payload["data"]["catalogue"] = {
            "query": args.catalogue_query,
            "types": requested_catalogue_types,
            "exists": bool(catalogue_items),
            "count": len(catalogue_items),
            "items": catalogue_items,
        }

        if not json_mode:
            print(f"\n--- Catalogue Search: {args.catalogue_query} ---")
            if requested_catalogue_types:
                print(f"Types: {', '.join(requested_catalogue_types)}")
            if not catalogue_items:
                print("No catalogue items found.")
            else:
                printable_catalogue = []
                for item in catalogue_items:
                    printable_catalogue.append(
                        {
                            **item,
                            "formats": ",".join(item.get("formats", [])),
                        }
                    )
                print(
                    format_records_table(
                        printable_catalogue,
                        ["#", "title", "details", "formats", "url"],
                    )
                )

    # ── Hold / reservation ──
    if args.place_hold_url or (args.catalogue_query and args.place_hold_item_index is not None):
        hold_result: dict[str, Any] = {
            "success": False,
            "reason": "No hold action attempted",
            "hold_url": "",
        }

        if args.place_hold_url:
            hold_result = client.place_hold(
                hold_url=args.place_hold_url,
                pickup_branch=args.pickup_branch or "",
            )
        elif not catalogue_items:
            hold_result = {
                "success": False,
                "reason": "No catalogue match found",
                "hold_url": "",
            }
        else:
            selected_index = args.place_hold_item_index - 1
            if selected_index < 0 or selected_index >= len(catalogue_items):
                hold_result = {
                    "success": False,
                    "reason": (
                        f"Invalid --place-hold-item-index {args.place_hold_item_index}; "
                        f"expected 1..{len(catalogue_items)}"
                    ),
                    "hold_url": "",
                }
            else:
                selected_item = catalogue_items[selected_index]
                hold_result = client.place_hold(
                    hold_url=selected_item.get("hold_url", ""),
                    item_url=selected_item.get("url", ""),
                    pickup_branch=args.pickup_branch or "",
                )
                hold_result["selected_item"] = {
                    "index": args.place_hold_item_index,
                    "title": selected_item.get("title", ""),
                    "url": selected_item.get("url", ""),
                }

        payload["data"]["hold"] = hold_result
        if not json_mode:
            print("\n--- Hold Request ---")
            if hold_result.get("success"):
                print("Hold request submitted successfully.")
                if hold_result.get("verified") is True:
                    print("Verified: reservation confirmed in your account.")
                elif hold_result.get("verified") is False:
                    print("Warning: could not verify reservation in your account. Check manually.")
            else:
                print(f"Hold request failed: {hold_result.get('reason', 'Unknown issue')}")

    if json_mode:
        print(json.dumps(payload, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
