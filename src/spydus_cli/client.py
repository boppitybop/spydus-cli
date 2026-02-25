# pyright: reportMissingImports=false, reportMissingModuleSource=false, reportUnknownVariableType=false, reportUnknownMemberType=false, reportUnknownArgumentType=false, reportUnknownLambdaType=false, reportUnknownParameterType=false
import base64
import getpass
import json
import os
import re
import sys
from datetime import date, datetime, timezone
from html import unescape
from pathlib import Path
from typing import Any, Callable, Optional
from urllib.parse import parse_qs, urlencode, urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import padding
from dotenv import load_dotenv

load_dotenv()

ANSI_RESET = "\033[0m"
ANSI_RED = "\033[31m"
ANSI_GREEN = "\033[32m"
ANSI_YELLOW = "\033[33m"
ANSI_CYAN = "\033[36m"

PUBLIC_KEY_PEM = """-----BEGIN PUBLIC KEY-----
MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQC82Gt72tYMWhZsxs79+VFHgFP2
kxeFvCuD/eg3NJOXAG9MMMDGzdQCCcbHDUXSHpwRE4ghacQrbr//JfBv+X5ZOeWU
fnw3GUdlC+1CiPLlGzK/5oAl/hoKwaVt8K6MKqZphFsm5ftJbnc8xGNrbVG+AXB0
bIAHZuvUILyfQV0+RwIDAQAB
-----END PUBLIC KEY-----"""


class SpydusClient:
    SESSION_CACHE_DIR = Path.home() / ".cache" / "spydus-cli"

    ITEM_TYPE_CODE_MAP: dict[str, set[str]] = {
        "book": {"BK"},
        "ebook": {"EBK"},
        "eaudiobook": {"EAUD"},
        "audiobook": {"EAUD", "AB"},
        "dvd": {"DVD", "VD"},
        "music-cd": {"CD", "MCD"},
        "cd": {"CD", "MCD"},
    }

    ITEM_TYPE_ALIASES: dict[str, str] = {
        "books": "book",
        "e-book": "ebook",
        "e-books": "ebook",
        "eaudio": "eaudiobook",
        "e-audio": "eaudiobook",
        "audio-book": "audiobook",
        "audio-books": "audiobook",
        "dvds": "dvd",
        "music": "music-cd",
        "musiccd": "music-cd",
        "music-cds": "music-cd",
    }

    def __init__(
        self,
        base_url: Optional[str] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
        library: Optional[str] = None,
        session: Optional[requests.Session] = None,
        verbose: bool = True,
    ):
        configured_library = (library or os.getenv("SPYDUS_LIBRARY") or "").strip().lower()
        if not configured_library:
            inferred_library = self._infer_library_from_env()
            configured_library = inferred_library or "default"

        self.library = configured_library
        self.profile_key = self._sanitize_profile_key(self.library)
        profile_prefix = self._profile_prefix()

        env_base_url = (
            os.getenv(f"{profile_prefix}BASE_URL")
            or os.getenv("SPYDUS_BASE_URL")
            or os.getenv("LIBRARY_BASE_URL")
        )
        resolved_base_url = (base_url or env_base_url or "").strip().rstrip("/")
        self.base_url = resolved_base_url

        self.login_url = f"{self.base_url}/cgi-bin/spydus.exe/PGM/OPAC/CCOPT/LB/2"
        self.dashboard_url = (
            f"{self.base_url}/cgi-bin/spydus.exe/PGM/OPAC/CCOPT/LB/1?ISGLB=0"
        )
        self.catalogue_url = f"{self.base_url}/cgi-bin/spydus.exe/ENQ/OPAC/ALLWRKENQ"

        self.username = (
            username
            or os.getenv(f"{profile_prefix}USER")
            or os.getenv("SPYDUS_USER")
            or os.getenv("LIBRARY_USER")
        )
        self.password = (
            password
            or os.getenv(f"{profile_prefix}PASSWORD")
            or os.getenv("SPYDUS_PASSWORD")
            or os.getenv("LIBRARY_PASSWORD")
        )

        self.session = session or requests.Session()
        default_cache_path = self.SESSION_CACHE_DIR / f"session-{self.profile_key}.json"
        self.session_cache_path = Path(
            os.getenv("SPYDUS_SESSION_CACHE", str(default_cache_path))
        ).expanduser()
        self.verbose = verbose

        self.session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                )
            }
        )

    @staticmethod
    def _sanitize_profile_key(name: str) -> str:
        normalized = re.sub(r"[^A-Za-z0-9]+", "_", name.strip().lower()).strip("_")
        return normalized or "default"

    @staticmethod
    def _discover_profile_keys_from_env() -> list[str]:
        discovered: set[str] = set()
        for key in os.environ:
            match = re.match(r"^SPYDUS_([A-Z0-9]+)_BASE_URL$", key)
            if not match:
                continue

            profile_token = match.group(1).strip().lower()
            if profile_token == "base":
                continue
            discovered.add(profile_token)

        return sorted(discovered)

    @classmethod
    def _infer_library_from_env(cls) -> str:
        discovered = cls._discover_profile_keys_from_env()
        if len(discovered) == 1:
            return discovered[0]
        return ""

    def _profile_prefix(self) -> str:
        profile_token = self.profile_key.upper()
        if profile_token == "DEFAULT":
            return "SPYDUS_"
        return f"SPYDUS_{profile_token}_"

    def _profile_env_key(self, suffix: str) -> str:
        return f"{self._profile_prefix()}{suffix}"

    def _ensure_base_url(self) -> bool:
        if self.base_url:
            return True

        profile_base_key = self._profile_env_key("BASE_URL")
        self._log(
            "Spydus base URL is not configured. "
            f"Set {profile_base_key} (or pass --base-url / --library)."
        )
        if self.profile_key == "default":
            available_profiles = self._discover_profile_keys_from_env()
            if available_profiles:
                self._log(
                    "Available profiles detected: "
                    f"{', '.join(available_profiles)}. Use --library <profile> or set SPYDUS_LIBRARY."
                )
        return False

    @staticmethod
    def _clean_text(text: str) -> str:
        cleaned = " ".join(text.split())
        cleaned = re.sub(r"\s+,", ",", cleaned)
        cleaned = re.sub(r"\s+;", ";", cleaned)
        cleaned = re.sub(r"\(\s+", "(", cleaned)
        cleaned = re.sub(r"\s+\)", ")", cleaned)
        return cleaned.strip()

    def _normalize_details_text(self, details_el: Any) -> str:
        if details_el is None:
            return ""

        top_level_spans = details_el.find_all("span", recursive=False)
        span_source = top_level_spans if top_level_spans else details_el.find_all("span")
        spans = [self._clean_text(span.get_text(" ", strip=True)) for span in span_source]
        parts = [part for part in spans if part]
        if parts:
            return " • ".join(parts)

        return self._clean_text(details_el.get_text(" ", strip=True))

    def _canonical_item_type(self, value: str) -> str:
        normalized = value.strip().lower()
        if not normalized:
            return ""
        return self.ITEM_TYPE_ALIASES.get(normalized, normalized)

    def resolve_item_type_codes(self, item_types: Optional[list[str]]) -> set[str]:
        if not item_types:
            return set()

        codes: set[str] = set()
        for item_type in item_types:
            canonical = self._canonical_item_type(item_type)
            if not canonical:
                continue

            mapped = self.ITEM_TYPE_CODE_MAP.get(canonical)
            if mapped:
                codes.update(mapped)
            else:
                codes.add(canonical.upper())

        return codes

    @staticmethod
    def _extract_format_codes_from_text(value: str) -> set[str]:
        if not value:
            return set()

        codes: set[str] = set()
        parsed = urlparse(value)
        query_params = parse_qs(parsed.query)
        recfmt_values = query_params.get("RECFMT", [])
        for recfmt in recfmt_values:
            cleaned = recfmt.strip().upper()
            if cleaned:
                codes.add(cleaned)

        for match in re.findall(r"03902\\([A-Za-z0-9]+)", value):
            cleaned = match.strip().upper()
            if cleaned:
                codes.add(cleaned)

        return codes

    def _matches_item_type_filter(
        self,
        details_text: str,
        format_codes: set[str],
        requested_codes: set[str],
    ) -> bool:
        if not requested_codes:
            return True

        if format_codes.intersection(requested_codes):
            return True

        details_lower = details_text.lower()
        keyword_map: dict[str, tuple[str, ...]] = {
            "BK": ("book",),
            "EBK": ("ebook", "e-book"),
            "EAUD": ("eaudiobook", "e audiobook", "e-audiobook", "audio book"),
            "AB": ("audiobook", "audio book"),
            "DVD": ("dvd",),
            "VD": ("dvd", "video"),
            "CD": ("music cd", "cd"),
            "MCD": ("music cd", "cd"),
        }
        for code in requested_codes:
            for keyword in keyword_map.get(code, (code.lower(),)):
                if keyword in details_lower:
                    return True

        return False

    @staticmethod
    def _extract_form_payload(form: Any) -> dict[str, str]:
        payload: dict[str, str] = {}
        for input_el in form.find_all("input"):
            name = input_el.get("name")
            if not name:
                continue

            input_type = (input_el.get("type") or "").lower()
            if input_type in {"checkbox", "radio"} and not input_el.has_attr("checked"):
                continue

            payload[name] = input_el.get("value", "")

        for text_el in form.find_all("textarea"):
            name = text_el.get("name")
            if name:
                payload[name] = text_el.get_text(strip=True)

        for select_el in form.find_all("select"):
            name = select_el.get("name")
            if not name:
                continue

            selected_option = select_el.find("option", selected=True)
            if selected_option is None:
                selected_option = select_el.find("option")
            payload[name] = selected_option.get("value", "") if selected_option else ""

        return payload

    def _log(self, message: str) -> None:
        if self.verbose:
            print(message, file=sys.stderr)

    def encrypt_password(self, password: str) -> str:
        public_key = serialization.load_pem_public_key(PUBLIC_KEY_PEM.encode())
        encrypted = public_key.encrypt(password.encode(), padding.PKCS1v15())
        return base64.b64encode(encrypted).decode()

    def _load_session_cache(self) -> bool:
        if not self.session_cache_path.exists():
            return False

        try:
            payload = json.loads(self.session_cache_path.read_text(encoding="utf-8"))
            cookies = payload.get("cookies", {})
            if not isinstance(cookies, dict) or not cookies:
                return False
            self.session.cookies.update(cookies)
            return True
        except (json.JSONDecodeError, OSError, TypeError, AttributeError):
            return False

    def _save_session_cache(self) -> None:
        try:
            self.session_cache_path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "saved_at": datetime.now(timezone.utc).isoformat(),
                "cookies": requests.utils.dict_from_cookiejar(self.session.cookies),
            }
            self.session_cache_path.write_text(json.dumps(payload), encoding="utf-8")
            os.chmod(self.session_cache_path, 0o600)
        except OSError:
            pass

    def clear_session_cache(self) -> None:
        try:
            if self.session_cache_path.exists():
                self.session_cache_path.unlink()
        except OSError:
            pass

    def _follow_meta_refresh(self, response: requests.Response) -> requests.Response:
        page_body = getattr(response, "text", "")
        if not isinstance(page_body, str):
            return response

        soup = BeautifulSoup(page_body, "html.parser")
        refresh_meta = soup.find(
            "meta", attrs={"http-equiv": lambda value: value and value.lower() == "refresh"}
        )
        if not refresh_meta:
            return response

        content = refresh_meta.get("content", "")
        match = re.search(r"url\s*=\s*(.+)$", content, flags=re.IGNORECASE)
        if not match:
            return response

        refresh_target = unescape(match.group(1)).strip().strip("\"'")
        refresh_url = urljoin(self.base_url, refresh_target)
        return self.session.get(refresh_url)

    def _session_is_authenticated(self) -> bool:
        try:
            response = self.session.get(self.dashboard_url)
        except requests.RequestException:
            return False

        if response.status_code != 200:
            return False

        response = self._follow_meta_refresh(response)
        page_body = getattr(response, "text", "")
        if not isinstance(page_body, str):
            return False

        page_text = page_body.lower()
        return (
            "log in" not in page_text
            and "login" not in response.url.lower()
            and (
                "dashboard" in page_text
                or "my account" in page_text
                or "current loans" in page_text
            )
        )

    def login(self, force: bool = False) -> bool:
        if not self._ensure_base_url():
            return False

        if not force and self._load_session_cache() and self._session_is_authenticated():
            self._log("Using cached session.")
            return True

        if not self.username or not self.password:
            self._log("Username and password are required for login.")
            return False

        self._log("Logging in...")

        login_page_url = f"{self.base_url}/cgi-bin/spydus.exe/MSGTRN/OPAC/LOGINB"
        response = self.session.get(login_page_url)
        if response.status_code != 200:
            self._log(f"Failed to load login page: {response.status_code}")
            return False

        encrypted_password = self.encrypt_password(self.password)
        payload = {
            "BRWLID": self.username,
            "BRWLPWD": encrypted_password,
            "RDT": "/cgi-bin/spydus.exe/PGM/OPAC/CCOPT/LB/1?ISGLB=0",
        }

        response = self.session.post(self.login_url, data=payload)
        response_text = getattr(response, "text", "")

        if (
            isinstance(response_text, str)
            and "log in" in response_text.lower()
            and "my library" not in response_text.lower()
        ):
            soup = BeautifulSoup(response_text, "html.parser")
            alert = soup.find("div", class_="alert")
            if alert:
                self._log(f"Login failed: {alert.get_text(strip=True)}")
            else:
                self._log("Login failed (credentials rejected or unknown error).")
            self.clear_session_cache()
            return False

        self._log("Login successful!")
        self._save_session_cache()
        return True

    def _load_dashboard_soup(self) -> Optional[BeautifulSoup]:
        if not self._ensure_base_url():
            return None

        response = self.session.get(self.dashboard_url)
        if response.status_code != 200:
            self._log(f"Failed to load dashboard: {response.status_code}")
            return None

        response = self._follow_meta_refresh(response)
        if response.status_code != 200:
            self._log(f"Failed to load dashboard: {response.status_code}")
            return None

        return BeautifulSoup(response.text, "html.parser")

    def _find_section_url(
        self,
        soup: BeautifulSoup,
        text_keywords: tuple[str, ...],
        href_keywords: tuple[str, ...] = (),
    ) -> Optional[str]:
        lowered_text_keywords = [keyword.lower() for keyword in text_keywords]
        lowered_href_keywords = [keyword.lower() for keyword in href_keywords]

        for anchor in soup.find_all("a", href=True):
            text = anchor.get_text(" ", strip=True).lower()
            href = anchor["href"].lower()

            text_match = any(keyword in text for keyword in lowered_text_keywords)
            href_match = any(keyword in href for keyword in lowered_href_keywords)

            if text_match or href_match:
                return urljoin(self.base_url, anchor["href"])

        return None

    def _fetch_soup(self, url: str) -> Optional[BeautifulSoup]:
        response = self.session.get(url)
        if response.status_code != 200:
            self._log(f"Failed to load section: {response.status_code}")
            return None
        return BeautifulSoup(response.text, "html.parser")

    def _extract_table_records(self, soup: BeautifulSoup) -> list[dict[str, str]]:
        table = soup.find("table")
        if not table:
            return []

        headers = [
            " ".join(cell.get_text(" ", strip=True).split()).lower()
            for cell in table.find_all("th")
        ]

        records: list[dict[str, str]] = []
        for row in table.find_all("tr"):
            cells = row.find_all("td")
            if not cells:
                continue

            values = [" ".join(cell.get_text(" ", strip=True).split()) for cell in cells]
            if headers and len(headers) >= len(values):
                record = {headers[index]: value for index, value in enumerate(values)}
            else:
                record = {f"col_{index + 1}": value for index, value in enumerate(values)}
            records.append(record)

        return records

    def _extract_reserve_count(self, status: str) -> int:
        match = re.search(r"(\d+)\s+reserve", status.lower())
        if not match:
            return 0
        return int(match.group(1))

    def _parse_due_date(self, value: str) -> Optional[date]:
        cleaned = " ".join(value.split())
        for pattern in ("%d %b %Y", "%d %B %Y"):
            try:
                return datetime.strptime(cleaned, pattern).date()
            except ValueError:
                continue
        return None

    def _is_overdue(self, item: dict[str, Any], today: Optional[date] = None) -> bool:
        current_date = today or date.today()
        due_date = self._parse_due_date(str(item.get("due_date", "")))
        status = str(item.get("status", "")).lower()
        return "overdue" in status or (due_date is not None and due_date < current_date)

    def _loan_sort_key(self, item: dict[str, Any]) -> date:
        due_date = self._parse_due_date(str(item.get("due_date", "")))
        return due_date or date.max

    def _parse_loans_table(self, soup: BeautifulSoup) -> list[dict[str, Any]]:
        table = soup.find("table")
        if not table:
            return []

        loans: list[dict[str, Any]] = []

        for row in table.find_all("tr"):
            cells = row.find_all("td")
            if len(cells) < 5:
                continue

            details_cell = cells[2] if len(cells) >= 6 else cells[1]
            due_cell = cells[-3]
            status_cell = cells[-2]
            options_cell = cells[-1]

            title_link = details_cell.find("a", href=True)
            title = (
                title_link.get_text(" ", strip=True)
                if title_link
                else details_cell.get_text(" ", strip=True)
            )

            details_text = details_cell.get_text(" ", strip=True)
            details = (
                details_text[len(title) :].strip(" -|")
                if details_text.startswith(title)
                else details_text
            )

            status_text = status_cell.get_text(" ", strip=True)
            reserve_count = self._extract_reserve_count(status_text)
            renew_text = options_cell.get_text(" ", strip=True).lower()

            loan: dict[str, Any] = {
                "title": title,
                "due_date": due_cell.get_text(" ", strip=True),
                "status": status_text,
                "renew_available": "renew" in renew_text,
                "reserved_by_others": reserve_count > 0,
                "reserves_count": reserve_count,
            }

            if details and details != title:
                loan["details"] = details

            renew_link = options_cell.find("a", href=True)
            if renew_link:
                loan["renew_url"] = urljoin(self.base_url, renew_link["href"])

            loans.append(loan)

        return loans

    def get_current_loans(self) -> list[dict[str, Any]]:
        self._log("Fetching current loans...")
        dashboard_soup = self._load_dashboard_soup()
        if dashboard_soup is None:
            return []

        loans_url = self._find_section_url(
            dashboard_soup,
            text_keywords=("current loans",),
            href_keywords=("/loanrenq/",),
        )

        if loans_url:
            loans_soup = self._fetch_soup(loans_url)
            if loans_soup is None:
                return []
        else:
            loans_soup = dashboard_soup

        loans = self._parse_loans_table(loans_soup)
        if not loans:
            self._log("No outstanding items found.")
        return loans

    def select_display_loans(
        self,
        loans: list[dict[str, Any]],
        mode: str = "auto",
        limit: int = 10,
    ) -> tuple[list[dict[str, Any]], str]:
        if not loans:
            return [], "none"

        sorted_loans = sorted(loans, key=self._loan_sort_key)
        if mode == "all":
            return sorted_loans, "all"

        if mode == "overdue":
            overdue = [loan for loan in sorted_loans if self._is_overdue(loan)]
            return overdue, "overdue"

        if mode == "top10":
            return sorted_loans[:limit], "top"

        overdue = [loan for loan in sorted_loans if self._is_overdue(loan)]
        if overdue:
            return overdue, "overdue"

        return sorted_loans[:limit], "top"

    def should_use_color(self, mode: str) -> bool:
        if mode == "always":
            return True
        if mode == "never":
            return False
        return sys.stdout.isatty() and os.getenv("TERM", "") != "dumb"

    def _style(self, text: str, ansi_color: str, enabled: bool) -> str:
        if not enabled:
            return text
        return f"{ansi_color}{text}{ANSI_RESET}"

    def _status_badge(self, status: str, use_color: bool) -> str:
        normalized = status.lower()
        if "overdue" in normalized:
            return self._style(f"🔴 {status}", ANSI_RED, use_color)
        if "due today" in normalized:
            return self._style(f"🟡 {status}", ANSI_YELLOW, use_color)
        if "due soon" in normalized:
            return self._style(f"🟠 {status}", ANSI_CYAN, use_color)
        return self._style(f"🟢 {status}", ANSI_GREEN, use_color)

    def _format_table(self, records: list[dict[str, Any]], columns: list[str]) -> str:
        if not records:
            return "No data found."

        rows: list[list[str]] = []
        for index, record in enumerate(records, start=1):
            row = [str(index)]
            for column in columns[1:]:
                value = str(record.get(column, ""))
                row.append(value)
            rows.append(row)

        headers = columns
        widths = [len(header) for header in headers]
        max_widths = [4, 50, 16, 28, 12]

        def clip(value: str, max_width: int) -> str:
            if len(value) <= max_width:
                return value
            return value[: max_width - 1] + "…"

        for row in rows:
            for idx, value in enumerate(row):
                capped = clip(value, max_widths[idx] if idx < len(max_widths) else 40)
                row[idx] = capped
                widths[idx] = max(widths[idx], len(capped))

        def render(values: list[str]) -> str:
            return "| " + " | ".join(
                value.ljust(widths[index]) for index, value in enumerate(values)
            ) + " |"

        separator = "+-" + "-+-".join("-" * width for width in widths) + "-+"
        lines = [separator, render(headers), separator]
        lines.extend(render(row) for row in rows)
        lines.append(separator)
        return "\n".join(lines)

    def format_loans_table(self, loans: list[dict[str, Any]]) -> str:
        return self._format_table(
            loans,
            ["#", "title", "due_date", "status", "reserves_count"],
        )

    def format_loans_compact(self, loans: list[dict[str, Any]], use_color: bool = False) -> str:
        if not loans:
            return "No outstanding items found."

        lines: list[str] = []
        for index, item in enumerate(loans, start=1):
            status = str(item.get("status", "N/A"))
            reserve_count = int(item.get("reserves_count", 0))
            reserve_info = f"reserves: {reserve_count}" if reserve_count else "reserves: 0"
            lines.append(
                f"{index:>2}. {item.get('title', 'Unknown title')}"
                f" | due {item.get('due_date', 'N/A')}"
                f" | {self._status_badge(status, use_color)}"
                f" | {reserve_info}"
            )
        return "\n".join(lines)

    def render_loans(
        self,
        loans: list[dict[str, Any]],
        output: str = "table",
        use_color: bool = False,
    ) -> str:
        if output == "json":
            return json.dumps(loans, indent=2, ensure_ascii=False)
        if output == "compact":
            return self.format_loans_compact(loans, use_color=use_color)
        return self.format_loans_table(loans)

    def renew_loan(self, loan: dict[str, Any]) -> dict[str, Any]:
        renew_url = loan.get("renew_url")
        if not renew_url:
            return {
                "title": loan.get("title", "Unknown title"),
                "success": False,
                "reason": "No renewal URL found",
            }

        response = self.session.get(str(renew_url))
        if response.status_code != 200:
            return {
                "title": loan.get("title", "Unknown title"),
                "success": False,
                "reason": f"Renew request failed ({response.status_code})",
            }

        body = response.text.lower()
        failure_patterns = [
            "unable",
            "cannot",
            "not renewed",
            "failed",
            "not possible",
            "max renew",
        ]
        failed = any(pattern in body for pattern in failure_patterns)

        return {
            "title": loan.get("title", "Unknown title"),
            "success": not failed,
            "reason": "" if not failed else "Renewal rejected by library system",
        }

    def renew_loans(
        self,
        loans: list[dict[str, Any]],
        confirm_each: bool = False,
        overdue_only: bool = False,
        input_fn: Callable[[str], str] = input,
    ) -> dict[str, Any]:
        results: list[dict[str, Any]] = []

        candidates = loans
        if overdue_only:
            candidates = [loan for loan in loans if self._is_overdue(loan)]

        for loan in candidates:
            if not loan.get("renew_available", False):
                results.append(
                    {
                        "title": loan.get("title", "Unknown title"),
                        "success": False,
                        "reason": "Not renewable",
                        "skipped": True,
                    }
                )
                continue

            if confirm_each:
                answer = input_fn(
                    f"Renew '{loan.get('title', 'Unknown title')}'? [y/N]: "
                ).strip().lower()
                if answer not in {"y", "yes"}:
                    results.append(
                        {
                            "title": loan.get("title", "Unknown title"),
                            "success": False,
                            "reason": "Skipped by user",
                            "skipped": True,
                        }
                    )
                    continue

            renewal_result = self.renew_loan(loan)
            renewal_result["skipped"] = False
            results.append(renewal_result)

        success_count = sum(1 for result in results if result.get("success"))
        skipped_count = sum(1 for result in results if result.get("skipped"))
        failed_count = len(results) - success_count - skipped_count

        return {
            "total_candidates": len(candidates),
            "attempted": len(results) - skipped_count,
            "succeeded": success_count,
            "failed": failed_count,
            "skipped": skipped_count,
            "results": results,
        }

    def _pick_value(self, record: dict[str, str], keys: tuple[str, ...]) -> str:
        lowered = {key.lower(): value for key, value in record.items()}
        for key in keys:
            if key in lowered and lowered[key]:
                return lowered[key]
        return ""

    def get_available_pickups(self) -> list[dict[str, Any]]:
        dashboard_soup = self._load_dashboard_soup()
        if dashboard_soup is None:
            return []

        section_url = self._find_section_url(
            dashboard_soup,
            text_keywords=("available for pickup", "pickup"),
            href_keywords=("/rsvcenq/",),
        )
        if not section_url:
            return []

        section_soup = self._fetch_soup(section_url)
        if section_soup is None:
            return []

        records = self._extract_table_records(section_soup)
        pickups: list[dict[str, Any]] = []
        for record in records:
            title = self._pick_value(record, ("details", "title", "item", "record", "col_2"))
            pickup_by = self._pick_value(
                record,
                (
                    "pickup by",
                    "pick-up by",
                    "pickup expiry",
                    "expires",
                    "expiry",
                    "col_4",
                ),
            )
            status = self._pick_value(record, ("status", "state", "availability", "col_5"))
            pickups.append(
                {
                    "title": title or "Unknown title",
                    "pickup_by": pickup_by or "unknown",
                    "status": status or "unknown",
                    "raw": record,
                }
            )

        return pickups

    def get_reservations(self, include_available: bool = False) -> list[dict[str, Any]]:
        dashboard_soup = self._load_dashboard_soup()
        if dashboard_soup is None:
            return []

        section_url = self._find_section_url(
            dashboard_soup,
            text_keywords=("requests", "reservations"),
            href_keywords=("/rsvcenq/",),
        )
        if not section_url:
            return []

        section_soup = self._fetch_soup(section_url)
        if section_soup is None:
            return []

        records = self._extract_table_records(section_soup)
        reservations: list[dict[str, Any]] = []
        for record in records:
            title = self._pick_value(record, ("details", "title", "item", "record", "col_2"))
            status = self._pick_value(record, ("status", "state", "availability", "col_5"))
            status_lower = status.lower()
            if not include_available and (
                "available" in status_lower or "pickup" in status_lower
            ):
                continue

            reservations.append(
                {
                    "title": title or "Unknown title",
                    "status": status or "unknown",
                    "raw": record,
                }
            )

        return reservations

    def get_requests(self) -> list[dict[str, Any]]:
        return self.get_reservations(include_available=True)

    def get_history(self) -> list[dict[str, Any]]:
        dashboard_soup = self._load_dashboard_soup()
        if dashboard_soup is None:
            return []

        history_url = self._find_section_url(
            dashboard_soup,
            text_keywords=("your history", "history"),
            href_keywords=("history", "/loanenq/"),
        )
        if not history_url:
            return []

        history_soup = self._fetch_soup(history_url)
        if history_soup is None:
            return []

        records = self._extract_table_records(history_soup)
        history_items: list[dict[str, Any]] = []
        for record in records:
            history_items.append(
                {
                    "date": self._pick_value(record, ("date", "transaction date", "col_1")),
                    "title": self._pick_value(record, ("details", "title", "item", "record", "col_2")),
                    "action": self._pick_value(record, ("status", "action", "event", "col_3")),
                    "raw": record,
                }
            )

        return history_items

    def check_new_items(self) -> list[dict[str, str]]:
        self._log("Checking new items...")
        if not self._ensure_base_url():
            return []

        new_items_url = (
            f"{self.base_url}/cgi-bin/spydus.exe/ENQ/OPAC/BIBENQ"
            "?QRY=BIBITM%3E%20(FILTER%3A%201%20%2B%20ITMFADTE%3A%20%22LASTMONTH%20-%20THISMONTH%22%20-%20MINOR%3A%20ITD16)"
            "%20-%20BIBITM%3E%20(FILTER%3A%201%20%2B%20ITMFADTE%3A%20%22%3C%20LASTMONTH%22)"
            "%20%2B%20BIBMTYP%3A%20BK&SORTS=DTE.DATE1.DESC%5DHBT.SOVR&QRYTEXT=New%20books&NRECS=20&ISGLB=0"
        )

        response = self.session.get(new_items_url)
        if response.status_code != 200:
            self._log(f"Failed to fetch new items: {response.status_code}")
            return []

        soup = BeautifulSoup(response.text, "html.parser")
        books: list[dict[str, str]] = []

        for card in soup.find_all("div", class_="card-body"):
            title_tag = card.find("h3", class_="card-title")
            details_div = card.find("div", class_="recdetails")
            if not title_tag or not title_tag.find("a"):
                continue

            spans = details_div.find_all("span") if details_div else []
            books.append(
                {
                    "title": title_tag.find("a").get_text(strip=True),
                    "author": spans[0].get_text(strip=True) if spans else "",
                    "year": spans[-1].get_text(strip=True) if len(spans) > 1 else "",
                }
            )

        return books

    def query_catalogue(
        self,
        query: str,
        limit: int = 10,
        item_types: Optional[list[str]] = None,
    ) -> list[dict[str, Any]]:
        self._log(f"Searching catalogue for: {query}")
        if not self._ensure_base_url():
            return []

        query = query.strip()
        if not query:
            return []

        requested_codes = self.resolve_item_type_codes(item_types)

        request_options = [
            (
                self.catalogue_url,
                {
                    "ENTRY": query,
                    "ENTRY_NAME": "BS",
                    "ENTRY_TYPE": "K",
                    "SORTS": "SQL_REL_GENWRK",
                    "GQ": query,
                    "NRECS": str(limit),
                    "QRY": "",
                    "QRYTEXT": "",
                    "_SPQ": "2",
                },
            ),
            (
                f"{self.base_url}/cgi-bin/spydus.exe/ENQ/OPAC/BIBENQ",
                {"QRY": query, "QRYTEXT": query, "NRECS": str(limit)},
            ),
        ]

        if len(requested_codes) == 1:
            selected_format = next(iter(requested_codes))
            request_options = [
                (base_url, {**params, "RECFMT": selected_format})
                for base_url, params in request_options
            ]

        def _parse_items(soup: BeautifulSoup) -> list[dict[str, Any]]:
            parsed: list[dict[str, Any]] = []
            seen_keys: set[str] = set()

            for link in soup.select("h3.card-title a[href]"):
                href_value = link.get("href", "")
                full_url = urljoin(self.base_url, href_value) if href_value else ""
                title = " ".join(link.get_text(" ", strip=True).split())
                item_key = full_url or title.lower()
                if not title or item_key in seen_keys:
                    continue
                seen_keys.add(item_key)

                container = link.find_parent("fieldset") or link.find_parent(
                    "div", class_="card-body"
                )
                details_text = ""
                hold_url = ""
                format_codes: set[str] = set()

                if container:
                    details_el = container.select_one(".card-text.recdetails, .recdetails")
                    if details_el:
                        details_text = self._normalize_details_text(details_el)

                    for tab_entry in container.select("[data-tab-href]"):
                        data_tab_href = tab_entry.get("data-tab-href", "")
                        format_codes.update(self._extract_format_codes_from_text(data_tab_href))

                    for anchor in container.select("a[href]"):
                        anchor_text = anchor.get_text(" ", strip=True).lower()
                        anchor_href_raw = anchor.get("href", "")
                        anchor_href = anchor_href_raw.lower()
                        format_codes.update(
                            self._extract_format_codes_from_text(anchor_href_raw)
                        )
                        if (
                            "place reservation" in anchor_text
                            or "view availability" in anchor_text
                            or "hold" in anchor_text
                            or "reserve" in anchor_text
                            or "request" in anchor_text
                            or "/ccopt/" in anchor_href
                            or "rsvc" in anchor_href
                            or "rsv" in anchor_href
                        ):
                            hold_url = urljoin(self.base_url, anchor_href_raw)
                            break

                if not self._matches_item_type_filter(
                    details_text=details_text,
                    format_codes=format_codes,
                    requested_codes=requested_codes,
                ):
                    continue

                parsed.append(
                    {
                        "title": title,
                        "details": details_text,
                        "url": full_url,
                        "hold_url": hold_url,
                        "formats": sorted(format_codes),
                    }
                )

            if parsed:
                return parsed

            for row in soup.find_all("tr"):
                cells = row.find_all("td")
                if len(cells) < 2:
                    continue
                anchor = row.find("a", href=True)
                title = (
                    anchor.get_text(" ", strip=True)
                    if anchor
                    else cells[1].get_text(" ", strip=True)
                )
                href = urljoin(self.base_url, anchor["href"]) if anchor else ""
                if not title:
                    continue
                parsed.append(
                    {
                        "title": self._clean_text(title),
                        "details": "",
                        "url": href,
                        "hold_url": "",
                        "formats": [],
                    }
                )

            return parsed

        for base_url, params in request_options:
            url = f"{base_url}?{urlencode(params)}"
            response = self.session.get(url)
            if response.status_code != 200:
                self._log(f"Failed to query catalogue endpoint {base_url}: {response.status_code}")
                continue

            soup = BeautifulSoup(response.text, "html.parser")
            items = _parse_items(soup)
            if items:
                return items[:limit]

        return []

    def discover_hold_url(self, item_url: str) -> str:
        if not item_url:
            return ""
        if not self._ensure_base_url():
            return ""

        response = self.session.get(item_url)
        if response.status_code != 200:
            return ""

        soup = BeautifulSoup(response.text, "html.parser")
        for anchor in soup.find_all("a", href=True):
            text = anchor.get_text(" ", strip=True).lower()
            href = anchor["href"].lower()
            if (
                "hold" in text
                or "reserve" in text
                or "request" in text
                or "rsvc" in href
                or "rsv" in href
            ):
                return urljoin(self.base_url, anchor["href"])

        return ""

    def _submit_hold_pickup_branch(
        self,
        response: requests.Response,
        hold_url: str,
        pickup_branch: str,
    ) -> tuple[Optional[requests.Response], str, list[str]]:
        soup = BeautifulSoup(response.text, "html.parser")
        form = soup.find("form")
        if form is None:
            return None, "No reservation form available for pickup branch selection", []

        payload = self._extract_form_payload(form)
        available_labels: list[str] = []
        selected_name = ""
        selected_value = ""

        selects = form.find_all("select")
        preferred_select = None
        for select in selects:
            select_name = (select.get("name") or "").lower()
            if any(keyword in select_name for keyword in ("pickup", "branch", "location", "library")):
                preferred_select = select
                break
        if preferred_select is None and selects:
            preferred_select = selects[0]

        if preferred_select is not None:
            select_name = preferred_select.get("name", "")
            options = preferred_select.find_all("option")
            target = pickup_branch.strip().lower()
            for option in options:
                option_value = option.get("value", "")
                option_text = option.get_text(" ", strip=True)
                if option_text:
                    available_labels.append(option_text)
                haystack = f"{option_value} {option_text}".lower()
                if target and target in haystack:
                    selected_name = select_name
                    selected_value = option_value
                    break

        if not selected_name:
            return None, f"Pickup branch not found: {pickup_branch}", available_labels

        payload[selected_name] = selected_value
        action = form.get("action") or hold_url
        submit_url = urljoin(hold_url, action)
        method = (form.get("method") or "post").lower()

        if method == "get":
            submit_response = self.session.get(submit_url, params=payload)
        else:
            submit_response = self.session.post(submit_url, data=payload)

        return submit_response, "", available_labels

    def place_hold(
        self,
        hold_url: str = "",
        item_url: str = "",
        pickup_branch: str = "",
    ) -> dict[str, Any]:
        if not self._ensure_base_url():
            return {
                "success": False,
                "reason": "Spydus base URL is not configured",
                "hold_url": "",
            }

        resolved_hold_url = hold_url or self.discover_hold_url(item_url)
        if not resolved_hold_url:
            return {
                "success": False,
                "reason": "No hold URL found for this item",
                "hold_url": "",
            }

        response = self.session.get(resolved_hold_url)
        if response.status_code != 200:
            return {
                "success": False,
                "reason": f"Hold request failed ({response.status_code})",
                "hold_url": resolved_hold_url,
            }

        final_response = response
        available_branches: list[str] = []
        pickup_value = pickup_branch.strip()
        if pickup_value:
            submitted_response, reason, available_branches = self._submit_hold_pickup_branch(
                response=response,
                hold_url=resolved_hold_url,
                pickup_branch=pickup_value,
            )
            if submitted_response is None:
                return {
                    "success": False,
                    "reason": reason,
                    "hold_url": resolved_hold_url,
                    "pickup_branch": pickup_value,
                    "available_pickup_branches": available_branches,
                }

            if submitted_response.status_code != 200:
                return {
                    "success": False,
                    "reason": f"Hold request failed ({submitted_response.status_code})",
                    "hold_url": resolved_hold_url,
                    "pickup_branch": pickup_value,
                }

            final_response = submitted_response

        body = final_response.text.lower()
        failure_patterns = ["unable", "cannot", "failed", "not permitted", "error"]
        failed = any(pattern in body for pattern in failure_patterns)

        return {
            "success": not failed,
            "reason": "" if not failed else "Hold request rejected by library system",
            "hold_url": resolved_hold_url,
            "pickup_branch": pickup_value,
        }

    def save_credentials(self, env_path: Path) -> None:
        env_values: dict[str, str] = {}
        if env_path.exists():
            for line in env_path.read_text(encoding="utf-8").splitlines():
                if "=" not in line or line.strip().startswith("#"):
                    continue
                key, value = line.split("=", 1)
                env_values[key.strip()] = value.strip()

        user_key = self._profile_env_key("USER")
        password_key = self._profile_env_key("PASSWORD")
        base_url_key = self._profile_env_key("BASE_URL")

        env_values["SPYDUS_LIBRARY"] = self.profile_key
        env_values[user_key] = self.username or ""
        env_values[password_key] = self.password or ""
        if self.base_url:
            env_values[base_url_key] = self.base_url

        if self.profile_key == "default":
            env_values["SPYDUS_USER"] = self.username or ""
            env_values["SPYDUS_PASSWORD"] = self.password or ""
            if self.base_url:
                env_values["SPYDUS_BASE_URL"] = self.base_url

        lines = [f"{key}={value}" for key, value in sorted(env_values.items())]
        env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        os.chmod(env_path, 0o600)

    def clear_credentials(self, env_path: Path) -> None:
        if env_path.exists():
            lines = env_path.read_text(encoding="utf-8").splitlines()
            profile_prefix = self._profile_prefix()
            filtered = [
                line
                for line in lines
                if not line.startswith(f"{profile_prefix}USER=")
                and not line.startswith(f"{profile_prefix}PASSWORD=")
                and not line.startswith("LIBRARY_USER=")
                and not line.startswith("LIBRARY_PASSWORD=")
            ]

            if self.profile_key == "default":
                filtered = [
                    line
                    for line in filtered
                    if not line.startswith("SPYDUS_USER=")
                    and not line.startswith("SPYDUS_PASSWORD=")
                ]

            env_path.write_text("\n".join(filtered).strip() + "\n", encoding="utf-8")
            os.chmod(env_path, 0o600)

        self.username = None
        self.password = None

    def prompt_for_credentials(
        self,
        input_fn: Callable[[str], str] = input,
        getpass_fn: Callable[[str], str] = getpass.getpass,
    ) -> bool:
        user_value = input_fn("Library username/card number: ").strip()
        password_value = getpass_fn("Library password: ").strip()

        if not user_value or not password_value:
            self._log("Credentials not provided.")
            return False

        self.username = user_value
        self.password = password_value
        return True