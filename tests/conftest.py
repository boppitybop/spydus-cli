import pytest
import requests
from unittest.mock import MagicMock

@pytest.fixture
def mock_session():
    session = MagicMock(spec=requests.Session)
    session.headers = {}
    session.cookies = requests.cookies.RequestsCookieJar()
    return session
