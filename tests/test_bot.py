from datetime import date, timedelta
from io import StringIO
from pathlib import Path
from unittest.mock import MagicMock, patch

from spydus_cli.cli import SpydusClient, main


def test_encrypt_password(mock_session):
    client = SpydusClient(base_url="https://example.spydus.com", session=mock_session)
    encrypted = client.encrypt_password("MyPassword123")

    assert encrypted
    assert encrypted != "MyPassword123"


def test_login_success(mock_session, tmp_path: Path):
    client = SpydusClient(
        base_url="https://example.spydus.com",
        username="u",
        password="p",
        session=mock_session,
    )
    client.session_cache_path = tmp_path / "session.json"

    login_page = MagicMock()
    login_page.status_code = 200

    login_post = MagicMock()
    login_post.text = "<html><body><h1>My library</h1></body></html>"

    mock_session.get.return_value = login_page
    mock_session.post.return_value = login_post

    assert client.login() is True


def test_login_failure(mock_session, tmp_path: Path):
    client = SpydusClient(
        base_url="https://example.spydus.com",
        username="u",
        password="p",
        session=mock_session,
    )
    client.session_cache_path = tmp_path / "session.json"

    login_page = MagicMock()
    login_page.status_code = 200

    login_post = MagicMock()
    login_post.text = (
        "<html><body><h1>Log in</h1>"
        '<div class="alert alert-danger">Invalid credentials</div>'
        "</body></html>"
    )

    mock_session.get.return_value = login_page
    mock_session.post.return_value = login_post

    assert client.login() is False


def test_get_current_loans_parsing(mock_session):
    client = SpydusClient(base_url="https://example.spydus.com", session=mock_session)
    client.dashboard_url = "http://dashboard"

    dashboard = MagicMock()
    dashboard.status_code = 200
    dashboard.text = '<html><body><a href="/current-loans">Current loans</a></body></html>'

    loans_page = MagicMock()
    loans_page.status_code = 200
    loans_page.text = """
    <html><body>
      <table>
        <tr><th>#</th><th>A</th><th>Details</th><th>Date due</th><th>Status</th><th>Options</th></tr>
        <tr>
          <td>Select</td>
          <td>Meta</td>
          <td><a href="/bib/1">Example Book</a> Example Author 2025</td>
          <td>26 Feb 2026</td>
          <td>Due today 2 reserves</td>
          <td><a href="/renew/1">Renew loan</a></td>
        </tr>
      </table>
    </body></html>
    """

    mock_session.get.side_effect = [dashboard, loans_page]

    items = client.get_current_loans()

    assert len(items) == 1
    assert items[0]["title"] == "Example Book"
    assert items[0]["renew_available"] is True
    assert items[0]["reserved_by_others"] is True
    assert items[0]["reserves_count"] == 2


def test_select_display_loans_prefers_overdue(mock_session):
    client = SpydusClient(base_url="https://example.spydus.com", session=mock_session)
    loans = [
        {
            "title": "Book A",
            "due_date": (date.today() - timedelta(days=1)).strftime("%d %b %Y"),
            "status": "Due",
        },
        {
            "title": "Book B",
            "due_date": (date.today() + timedelta(days=1)).strftime("%d %b %Y"),
            "status": "Due soon",
        },
    ]

    selected, mode = client.select_display_loans(loans)

    assert mode == "overdue"
    assert len(selected) == 1
    assert selected[0]["title"] == "Book A"


def test_renew_loans_auto(mock_session):
    client = SpydusClient(base_url="https://example.spydus.com", session=mock_session)

    renew_ok = MagicMock()
    renew_ok.status_code = 200
    renew_ok.text = "Renewed"

    renew_fail = MagicMock()
    renew_fail.status_code = 200
    renew_fail.text = "Unable to renew"

    mock_session.get.side_effect = [renew_ok, renew_fail]

    result = client.renew_loans(
        [
            {
                "title": "Book A",
                "renew_available": True,
                "renew_url": "http://renew/a",
                "due_date": "26 Feb 2026",
                "status": "Due",
            },
            {
                "title": "Book B",
                "renew_available": True,
                "renew_url": "http://renew/b",
                "due_date": "26 Feb 2026",
                "status": "Due",
            },
        ]
    )

    assert result["attempted"] == 2
    assert result["succeeded"] == 1
    assert result["failed"] == 1


def test_renew_loans_confirm_skip(mock_session):
    client = SpydusClient(base_url="https://example.spydus.com", session=mock_session)

    result = client.renew_loans(
        [
            {
                "title": "Book A",
                "renew_available": True,
                "renew_url": "http://renew/a",
                "due_date": "26 Feb 2026",
                "status": "Due",
            }
        ],
        confirm_each=True,
        input_fn=lambda _prompt: "n",
    )

    assert result["attempted"] == 0
    assert result["skipped"] == 1


def test_query_catalogue_parsing(mock_session):
    client = SpydusClient(base_url="https://example.spydus.com", session=mock_session)

    response = MagicMock()
    response.status_code = 200
    response.text = """
    <html><body>
            <fieldset class="card card-list">
                <div class="card-body row d-flex flex-column">
                    <h3 class="card-title">
                        <a href="/cgi-bin/spydus.exe/FULL/OPAC/ALLWRKENQ/123/456,1">
                            <span><span class="highlight">Atomic</span> Habits</span>
                        </a>
                    </h3>
                    <div class="card-text recdetails"><span>Clear, James</span><span>2018</span></div>
                    <a href="/cgi-bin/spydus.exe/PGM/OPAC/CCOPT/123/0/V/0/R/9/ALLWRKENQ?SVL=456&amp;RECFMT=BK">
                        Place reservation
                    </a>
                </div>
            </fieldset>
            <fieldset class="card card-grid">
                <div class="card-body d-flex flex-column">
                    <h3 class="card-title">
                        <a href="/cgi-bin/spydus.exe/FULL/OPAC/ALLWRKENQ/123/456,1">Atomic Habits</a>
                    </h3>
                    <div class="card-text recdetails"><span>Clear, James</span><span>2018</span></div>
                </div>
            </fieldset>
    </body></html>
    """

    mock_session.get.return_value = response

    items = client.query_catalogue("Test")

    assert len(items) == 1
    assert items[0]["title"] == "Atomic Habits"
    assert items[0]["details"] == "Clear, James • 2018"
    assert "/FULL/OPAC/ALLWRKENQ/123/456,1" in items[0]["url"]
    assert "/PGM/OPAC/CCOPT/123/0/V/0/R/9/ALLWRKENQ" in items[0]["hold_url"]
    assert items[0]["formats"] == ["BK"]

    called_url = mock_session.get.call_args[0][0]
    assert "/ENQ/OPAC/ALLWRKENQ" in called_url
    assert "ENTRY=Test" in called_url


def test_query_catalogue_item_type_filter(mock_session):
        client = SpydusClient(base_url="https://example.spydus.com", session=mock_session)

        response = MagicMock()
        response.status_code = 200
        response.text = """
        <html><body>
            <fieldset class="card card-list">
                <div class="card-body row d-flex flex-column">
                    <h3 class="card-title">
                        <a href="/cgi-bin/spydus.exe/FULL/OPAC/ALLWRKENQ/123/456,1">Atomic Habits</a>
                    </h3>
                    <div class="card-text recdetails"><span>Clear, James</span><span>2018</span></div>
                    <a href="/cgi-bin/spydus.exe/PGM/OPAC/CCOPT/123/0/V/0/R/9/ALLWRKENQ?SVL=456&amp;RECFMT=BK">Place reservation</a>
                </div>
            </fieldset>
        </body></html>
        """

        mock_session.get.return_value = response

        dvd_items = client.query_catalogue("Atomic Habits", item_types=["dvd"])
        book_items = client.query_catalogue("Atomic Habits", item_types=["book"])

        assert dvd_items == []
        assert len(book_items) == 1
        assert book_items[0]["formats"] == ["BK"]


def test_profile_env_resolution(mock_session):
    with patch.dict(
        "os.environ",
        {
            "SPYDUS_LIBRARY": "act",
            "SPYDUS_ACT_BASE_URL": "https://librariesact.spydus.com",
            "SPYDUS_ACT_USER": "card123",
            "SPYDUS_ACT_PASSWORD": "pass123",
        },
        clear=True,
    ):
        client = SpydusClient(session=mock_session)

    assert client.profile_key == "act"
    assert client.base_url == "https://librariesact.spydus.com"
    assert client.username == "card123"
    assert client.password == "pass123"
    assert client.session_cache_path.name == "session-act.json"


def test_profile_env_auto_infer_single_profile(mock_session):
    with patch.dict(
        "os.environ",
        {
            "SPYDUS_ACT_BASE_URL": "https://librariesact.spydus.com",
            "SPYDUS_ACT_USER": "card123",
            "SPYDUS_ACT_PASSWORD": "pass123",
        },
        clear=True,
    ):
        client = SpydusClient(session=mock_session)

    assert client.profile_key == "act"
    assert client.base_url == "https://librariesact.spydus.com"
    assert client.username == "card123"
    assert client.password == "pass123"


def test_save_and_clear_credentials(mock_session, tmp_path: Path):
    client = SpydusClient(
        library="default",
        base_url="https://example.spydus.com",
        username="user1",
        password="pass1",
        session=mock_session,
    )
    env_path = tmp_path / ".env"

    client.save_credentials(env_path)

    content = env_path.read_text(encoding="utf-8")
    assert "SPYDUS_USER=user1" in content
    assert "SPYDUS_PASSWORD=pass1" in content

    client.clear_credentials(env_path)
    cleared = env_path.read_text(encoding="utf-8")
    assert "SPYDUS_USER" not in cleared
    assert "SPYDUS_PASSWORD" not in cleared


def test_main_json_output(mock_session):
    with patch("spydus_cli.cli.SpydusClient") as mock_client_cls:
        instance = mock_client_cls.return_value
        instance.base_url = "https://example.spydus.com"
        instance.profile_key = "default"
        instance.login.return_value = True
        instance.get_current_loans.return_value = []
        instance.select_display_loans.return_value = ([], "none")
        instance.should_use_color.return_value = False

        captured_stdout = StringIO()
        with patch("sys.stdout", new=captured_stdout):
            with patch("sys.argv", ["prog", "--check-loans", "--output", "json"]):
                main()

        output = captured_stdout.getvalue()
        assert "schema_version" in output
        assert '"data"' in output


def test_main_renew_all_overdue_only():
    with patch("spydus_cli.cli.SpydusClient") as mock_client_cls:
        instance = mock_client_cls.return_value
        instance.base_url = "https://example.spydus.com"
        instance.profile_key = "default"
        instance.login.return_value = True
        instance.get_current_loans.return_value = [
            {
                "title": "Book A",
                "renew_available": True,
                "due_date": "26 Feb 2026",
                "status": "Due",
            }
        ]
        instance.select_display_loans.return_value = ([], "none")
        instance.renew_loans.return_value = {
            "attempted": 0,
            "succeeded": 0,
            "failed": 0,
            "skipped": 0,
            "results": [],
        }

        with patch("sys.argv", ["prog", "--renew-all", "--output", "json"]):
            main()

        instance.renew_loans.assert_called_once()
        _, kwargs = instance.renew_loans.call_args
        assert kwargs["overdue_only"] is True


def test_main_renew_overdue_flag():
    with patch("spydus_cli.cli.SpydusClient") as mock_client_cls:
        instance = mock_client_cls.return_value
        instance.base_url = "https://example.spydus.com"
        instance.profile_key = "default"
        instance.login.return_value = True
        instance.get_current_loans.return_value = []
        instance.select_display_loans.return_value = ([], "none")
        instance.renew_loans.return_value = {
            "attempted": 0,
            "succeeded": 0,
            "failed": 0,
            "skipped": 0,
            "results": [],
        }

        with patch("sys.argv", ["prog", "--renew-overdue", "--output", "json"]):
            main()

        instance.renew_loans.assert_called_once()
        _, kwargs = instance.renew_loans.call_args
        assert kwargs["overdue_only"] is True


def test_main_renew_all_loans_flag():
    with patch("spydus_cli.cli.SpydusClient") as mock_client_cls:
        instance = mock_client_cls.return_value
        instance.base_url = "https://example.spydus.com"
        instance.profile_key = "default"
        instance.login.return_value = True
        instance.get_current_loans.return_value = []
        instance.select_display_loans.return_value = ([], "none")
        instance.renew_loans.return_value = {
            "attempted": 0,
            "succeeded": 0,
            "failed": 0,
            "skipped": 0,
            "results": [],
        }

        with patch(
            "sys.argv",
            ["prog", "--renew-all-loans", "--renew-overdue", "--output", "json"],
        ):
            main()

        instance.renew_loans.assert_called_once()
        _, kwargs = instance.renew_loans.call_args
        assert kwargs["overdue_only"] is False


def test_main_place_hold_item_requires_selection():
    with patch("spydus_cli.cli.SpydusClient") as mock_client_cls:
        instance = mock_client_cls.return_value
        instance.base_url = "https://example.spydus.com"
        instance.profile_key = "default"
        instance.login.return_value = True
        instance.query_catalogue.return_value = [
            {
                "title": "Book A",
                "details": "Author A • 2021",
                "url": "https://example/item/a",
                "hold_url": "https://example/hold/a",
                "formats": ["BK"],
            },
            {
                "title": "Book B",
                "details": "Author B • 2020",
                "url": "https://example/item/b",
                "hold_url": "https://example/hold/b",
                "formats": ["BK"],
            },
        ]

        captured_stdout = StringIO()
        with patch("sys.stdout", new=captured_stdout):
            with patch("sys.argv", ["prog", "--place-hold-item", "Atomic", "--output", "json"]):
                main()

        output = captured_stdout.getvalue()
        assert "selection_required" in output
        instance.place_hold.assert_not_called()


def test_main_place_hold_item_index_selection():
    with patch("spydus_cli.cli.SpydusClient") as mock_client_cls:
        instance = mock_client_cls.return_value
        instance.base_url = "https://example.spydus.com"
        instance.profile_key = "default"
        instance.login.return_value = True
        instance.query_catalogue.return_value = [
            {
                "title": "Book A",
                "details": "Author A • 2021",
                "url": "https://example/item/a",
                "hold_url": "https://example/hold/a",
                "formats": ["BK"],
            },
            {
                "title": "Book B",
                "details": "Author B • 2020",
                "url": "https://example/item/b",
                "hold_url": "https://example/hold/b",
                "formats": ["BK"],
            },
        ]
        instance.place_hold.return_value = {
            "success": True,
            "reason": "",
            "hold_url": "https://example/hold/b",
            "pickup_branch": "",
        }

        with patch(
            "sys.argv",
            [
                "prog",
                "--place-hold-item",
                "Atomic",
                "--place-hold-item-index",
                "2",
                "--output",
                "json",
            ],
        ):
            main()

        instance.place_hold.assert_called_once_with(
            hold_url="https://example/hold/b",
            item_url="https://example/item/b",
            pickup_branch="",
        )
