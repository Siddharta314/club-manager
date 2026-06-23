"""Tests for the matches app — DRF views.

Covers the HTTP layer for the match lifecycle endpoints:

- ``POST /api/v1/slots/{slot_id}/match/`` — create match from slot.
- ``GET  /api/v1/matches/{id}/`` — match detail.
- ``POST /api/v1/matches/{id}/join/`` — self-signup.
- ``POST /api/v1/matches/{id}/leave/`` — leave match.
- ``POST /api/v1/matches/{id}/cancel/`` — admin cancel.
- ``POST /api/v1/matches/{id}/override-add/`` — admin override-add.
"""
from __future__ import annotations

from datetime import timedelta
from unittest.mock import MagicMock

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from clubs.models import Club, Court
from match_slots.models import MatchSlot
from matches.models import Match
from players.models import User


# ---------------------------------------------------------------------------
# Helpers + fixtures
# ---------------------------------------------------------------------------
def _make_club_court_slot(
    start_offset_minutes: int = 60,
) -> tuple[Club, Court, MatchSlot]:
    """Create a Club + Court + future MatchSlot for view tests.

    The Club is set up with a creator that's added to its admins
    M2M so the IsClubAdmin M2M-based check passes for admin
    endpoints.
    """
    creator = User.objects.create(
        username="m_creator", email="m_creator@example.com"
    )
    club = Club.objects.create(name="MV", address="MV 1", created_by=creator)
    club.admins.add(creator)
    court = Court.objects.create(club=club, name="MV Court")
    start = timezone.now() + timedelta(minutes=start_offset_minutes)
    slot = MatchSlot.objects.create(
        court=court,
        start_time=start,
        end_time=start + timedelta(minutes=90),
    )
    return club, court, slot


@pytest.fixture
def auth_client(bypass_clerk_auth, make_clerk_state, db):
    """APIClient bound to a Clerk-authenticated user.

    Mirrors the fixture in clubs/tests/test_views.py — duplicated
    here so the matches test module is self-contained.
    """

    def _make(clerk_id: str, **user_kwargs):
        from django.contrib.auth import get_user_model

        UserModel = get_user_model()
        user, _ = UserModel.objects.get_or_create(
            clerk_user_id=clerk_id,
            defaults={
                "username": user_kwargs.pop("username", clerk_id),
                "email": user_kwargs.pop("email", f"{clerk_id}@example.com"),
            },
        )
        for field, value in user_kwargs.items():
            setattr(user, field, value)
        if user_kwargs:
            user.save()
        state = make_clerk_state(
            sub=clerk_id, email=user.email, name=user.username
        )
        bypass_clerk_auth(state)
        client = APIClient()
        client.defaults["HTTP_AUTHORIZATION"] = "Bearer test.jwt.token"
        return client, user

    return _make


# ---------------------------------------------------------------------------
# CreateMatchFromSlotView
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestCreateMatchFromSlotView:
    URL_TMPL = "/api/v1/slots/{slot_id}/match/"

    def test_first_signup_creates_match_and_host(self, auth_client) -> None:
        _, _, slot = _make_club_court_slot()
        client, user = auth_client("m_host", level=3.50)
        response = client.post(self.URL_TMPL.format(slot_id=slot.pk))
        assert response.status_code == 201, response.data
        match = Match.objects.get(pk=response.data["id"])
        assert match.host_id == user.pk
        # Range = 3.50 ± 0.25
        assert float(match.level_min) == 3.25
        assert float(match.level_max) == 3.75

    def test_already_booked_slot_returns_400(self, auth_client) -> None:
        _, _, slot = _make_club_court_slot()
        client, user = auth_client("m_host2", level=3.50)
        # First call succeeds.
        response = client.post(self.URL_TMPL.format(slot_id=slot.pk))
        assert response.status_code == 201
        # Second call on the same slot fails.
        response = client.post(self.URL_TMPL.format(slot_id=slot.pk))
        assert response.status_code == 400
        assert "booked" in str(response.data).lower()

    def test_past_slot_returns_400(self, auth_client) -> None:
        # Create a slot in the past directly.
        _, court, _ = _make_club_court_slot()
        past_start = timezone.now() - timedelta(hours=2)
        slot = MatchSlot.objects.create(
            court=court,
            start_time=past_start,
            end_time=past_start + timedelta(minutes=60),
        )
        client, _ = auth_client("m_late", level=3.50)
        response = client.post(self.URL_TMPL.format(slot_id=slot.pk))
        assert response.status_code == 400
        assert "passed" in str(response.data).lower()

    def test_unknown_slot_returns_404(self, auth_client) -> None:
        client, _ = auth_client("m_404", level=3.50)
        response = client.post(self.URL_TMPL.format(slot_id=999_999))
        assert response.status_code == 404

    def test_anonymous_user_returns_401(self) -> None:
        _, _, slot = _make_club_court_slot()
        client = APIClient()
        response = client.post(self.URL_TMPL.format(slot_id=slot.pk))
        assert response.status_code == 401


# ---------------------------------------------------------------------------
# MatchDetailView
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestMatchDetailView:
    URL_TMPL = "/api/v1/matches/{id}/"

    def test_returns_match_with_players_and_companions_and_capacity(
        self, auth_client
    ) -> None:
        from companions.models import Companion
        from matches.services import create_match_from_slot

        _, _, slot = _make_club_court_slot()
        client, host = auth_client("m_det", level=3.50)
        match = create_match_from_slot(slot=slot, host=host)
        Companion.objects.create(
            match=match, sponsored_by=host, name="Alex", level=3.40
        )
        response = client.get(self.URL_TMPL.format(id=match.pk))
        assert response.status_code == 200, response.data
        # Players: just the host.
        assert len(response.data["players"]) == 1
        # Companions: one.
        assert len(response.data["companions"]) == 1
        # Capacity totals.
        assert response.data["capacity"]["player_count"] == 1
        assert response.data["capacity"]["companion_count"] == 1
        assert response.data["capacity"]["total"] == 2
        assert response.data["capacity"]["is_full"] is False

    def test_unknown_match_returns_404(self, auth_client) -> None:
        client, _ = auth_client("m_det_404", level=3.50)
        response = client.get(self.URL_TMPL.format(id=999_999))
        assert response.status_code == 404


# ---------------------------------------------------------------------------
# JoinMatchView
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestJoinMatchView:
    URL_TMPL = "/api/v1/matches/{id}/join/"

    def test_join_in_range_returns_200(self, auth_client) -> None:
        from matches.services import create_match_from_slot

        _, _, slot = _make_club_court_slot()
        client, host = auth_client("m_jh", level=3.50)
        match = create_match_from_slot(slot=slot, host=host)
        client2, _ = auth_client("m_jp", level=3.40)
        response = client2.post(self.URL_TMPL.format(id=match.pk))
        assert response.status_code == 200, response.data
        assert len(response.data["players"]) == 2

    def test_join_out_of_range_returns_400(self, auth_client) -> None:
        from matches.services import create_match_from_slot

        _, _, slot = _make_club_court_slot()
        client, host = auth_client("m_jo_h", level=3.50)
        match = create_match_from_slot(slot=slot, host=host)
        client2, _ = auth_client("m_jo_p", level=4.50)
        response = client2.post(self.URL_TMPL.format(id=match.pk))
        assert response.status_code == 400
        assert "out of range" in str(response.data).lower()

    def test_join_cancelled_match_returns_400(self, auth_client) -> None:
        from matches.services import create_match_from_slot

        _, _, slot = _make_club_court_slot()
        client, host = auth_client("m_jc_h", level=3.50)
        match = create_match_from_slot(slot=slot, host=host)
        match.is_cancelled = True
        match.save()
        client2, _ = auth_client("m_jc_p", level=3.50)
        response = client2.post(self.URL_TMPL.format(id=match.pk))
        assert response.status_code == 400
        assert "cancelled" in str(response.data).lower()

    def test_join_unknown_match_returns_404(self, auth_client) -> None:
        client, _ = auth_client("m_ju", level=3.50)
        response = client.post(self.URL_TMPL.format(id=999_999))
        assert response.status_code == 404


# ---------------------------------------------------------------------------
# LeaveMatchView
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestLeaveMatchView:
    URL_TMPL = "/api/v1/matches/{id}/leave/"

    def test_leave_returns_204(self, auth_client) -> None:
        from matches.services import create_match_from_slot, join_match

        _, _, slot = _make_club_court_slot()
        # Host signs up via the API so the match gets created with
        # the right level range.
        client, host = auth_client("m_lh", level=3.50)
        match = create_match_from_slot(slot=slot, host=host)
        # Second player joins via the service so the test doesn't
        # depend on the level-range check.
        other = User.objects.create(
            username="m_lp", email="m_lp@example.com", level=3.40
        )
        join_match(match=match, user=other)
        # The second player calls leave. auth_client patches Clerk
        # state globally per test so we can only switch "users" by
        # calling auth_client again — but that re-binds a different
        # user. To exercise the leave path for `other`, we use a
        # third-user that the second call switches to.
        client_other, other_user = auth_client("m_lp_user", level=3.40)
        join_match(match=match, user=other_user)
        response = client_other.post(self.URL_TMPL.format(id=match.pk))
        assert response.status_code == 204

    def test_leave_host_returns_400(self, auth_client) -> None:
        from matches.services import create_match_from_slot

        _, _, slot = _make_club_court_slot()
        client, host = auth_client("m_lh2", level=3.50)
        match = create_match_from_slot(slot=slot, host=host)
        response = client.post(self.URL_TMPL.format(id=match.pk))
        assert response.status_code == 400
        assert "host" in str(response.data).lower()

    def test_leave_unknown_match_returns_404(self, auth_client) -> None:
        client, _ = auth_client("m_lu", level=3.50)
        response = client.post(self.URL_TMPL.format(id=999_999))
        assert response.status_code == 404


# ---------------------------------------------------------------------------
# CancelMatchView + AdminAddPlayerView
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestAdminMatchActions:
    def test_cancel_by_admin(self, auth_client) -> None:
        from matches.services import create_match_from_slot

        club, _, slot = _make_club_court_slot()
        # The auth_client user becomes a club admin of a NEW club so
        # they have admin rights on it.
        client, admin = auth_client("m_adm", role=User.Role.CLUB_ADMIN)
        new_club = Club.objects.create(name="MX", address="MX 1", created_by=admin)
        new_club.admins.add(admin)
        # Create the match on the new club's slot.
        from clubs.models import Court as _Court

        new_court = _Court.objects.create(club=new_club, name="MX Court")
        start = timezone.now() + timedelta(hours=1)
        new_slot = MatchSlot.objects.create(
            court=new_court,
            start_time=start,
            end_time=start + timedelta(minutes=90),
        )
        host = User.objects.create(
            username="m_ch", email="m_ch@example.com"
        )
        match = create_match_from_slot(slot=new_slot, host=host)
        response = client.post(f"/api/v1/matches/{match.pk}/cancel/")
        assert response.status_code == 200, response.data
        match.refresh_from_db()
        assert match.is_cancelled is True

    def test_cancel_by_non_admin_returns_403(self, auth_client) -> None:
        from matches.services import create_match_from_slot

        _, _, slot = _make_club_court_slot()
        # Player (not admin) tries to cancel the match.
        client, _ = auth_client("m_chn", level=3.50)
        host = User.objects.create(
            username="m_ch2", email="m_ch2@example.com"
        )
        match = create_match_from_slot(slot=slot, host=host)
        response = client.post(f"/api/v1/matches/{match.pk}/cancel/")
        assert response.status_code == 403

    def test_override_add_by_admin_accepts_out_of_range(
        self, auth_client
    ) -> None:
        from matches.services import create_match_from_slot

        # Create a match on a fresh club the admin owns.
        client, admin = auth_client("m_oa", role=User.Role.CLUB_ADMIN)
        new_club = Club.objects.create(name="MZ", address="MZ 1", created_by=admin)
        new_club.admins.add(admin)
        from clubs.models import Court as _Court

        new_court = _Court.objects.create(club=new_club, name="MZ Court")
        start = timezone.now() + timedelta(hours=1)
        new_slot = MatchSlot.objects.create(
            court=new_court,
            start_time=start,
            end_time=start + timedelta(minutes=90),
        )
        host = User.objects.create(
            username="m_oh", email="m_oh@example.com", level=3.50
        )
        match = create_match_from_slot(slot=new_slot, host=host)
        # Out-of-range user.
        target = User.objects.create(
            username="m_ot", email="m_ot@example.com", level=5.00
        )
        response = client.post(
            f"/api/v1/matches/{match.pk}/override-add/",
            {"user_id": target.pk},
            format="json",
        )
        assert response.status_code == 200, response.data
        assert match.players.filter(user=target).exists()

    def test_override_add_by_non_admin_returns_403(self, auth_client) -> None:
        from matches.services import create_match_from_slot

        _, _, slot = _make_club_court_slot()
        client, _ = auth_client("m_oa_p", level=3.50)
        host = User.objects.create(
            username="m_oa_h", email="m_oa_h@example.com"
        )
        match = create_match_from_slot(slot=slot, host=host)
        target = User.objects.create(
            username="m_oa_t", email="m_oa_t@example.com"
        )
        response = client.post(
            f"/api/v1/matches/{match.pk}/override-add/",
            {"user_id": target.pk},
            format="json",
        )
        assert response.status_code == 403

    def test_override_add_missing_user_id_returns_400(self, auth_client) -> None:
        from matches.services import create_match_from_slot

        client, admin = auth_client("m_oam", role=User.Role.CLUB_ADMIN)
        new_club = Club.objects.create(name="MW", address="MW 1", created_by=admin)
        new_club.admins.add(admin)
        from clubs.models import Court as _Court

        new_court = _Court.objects.create(club=new_club, name="MW Court")
        start = timezone.now() + timedelta(hours=1)
        new_slot = MatchSlot.objects.create(
            court=new_court,
            start_time=start,
            end_time=start + timedelta(minutes=90),
        )
        host = User.objects.create(
            username="m_omh", email="m_omh@example.com"
        )
        match = create_match_from_slot(slot=new_slot, host=host)
        response = client.post(
            f"/api/v1/matches/{match.pk}/override-add/",
            {},
            format="json",
        )
        assert response.status_code == 400
        assert "user_id" in str(response.data).lower()


# ---------------------------------------------------------------------------
# CancelMatchView — cancel-via-view integration (REQ-WIRE-009, REQ-WIRE-010)
# ---------------------------------------------------------------------------
@pytest.fixture
def patched_send_delay_view(monkeypatch):
    """Local copy of ``patched_send_delay`` for view tests.

    Mirrors ``matches/tests/test_services.py::patched_send_delay`` so
    we can assert on ``send_notification.delay.call_args_list``
    without a live Q2 broker. Kept module-local (not in conftest.py)
    so the matches test suite stays self-contained — same trade-off
    the ``auth_client`` fixture makes above.
    """
    mock = MagicMock()
    import notifications.tasks as tasks_module

    monkeypatch.setattr(tasks_module, "send_notification", mock)
    return mock


def _build_admin_match_with_player(auth_client):
    """Build: dedicated club + admin user (admin of that club) + host
    User + joined player User + match with host + player joined.

    Returns ``(admin_client, admin_user, match, host, joined_player)``
    so each test can drive the right assertions.

    Mirrors the existing ``TestAdminMatchActions.test_cancel_by_admin``
    pattern: a dedicated club the admin owns, a court + slot in that
    club, a host User, a second joined player User, and the match
    built via ``create_match_from_slot`` + ``join_match(force=True)``
    (``force=True`` skips the level-range check; this helper only
    cares about cancel-side wiring).
    """
    from clubs.models import Court as _Court
    from matches.services import create_match_from_slot, join_match

    admin_client, admin = auth_client("m_cv_adm", role=User.Role.CLUB_ADMIN)
    admin_club = Club.objects.create(name="CV", address="CV 1", created_by=admin)
    admin_club.admins.add(admin)
    court = _Court.objects.create(club=admin_club, name="CV Court")
    start = timezone.now() + timedelta(hours=1)
    slot = MatchSlot.objects.create(
        court=court,
        start_time=start,
        end_time=start + timedelta(minutes=90),
    )
    host = User.objects.create(
        username="m_cv_h", email="m_cv_h@example.com", level=3.50
    )
    joined = User.objects.create(
        username="m_cv_p", email="m_cv_p@example.com", level=3.50
    )
    match = create_match_from_slot(slot=slot, host=host)
    join_match(match=match, user=joined, force=True)
    return admin_client, admin, match, host, joined


@pytest.mark.django_db
class TestCancelMatchView:
    """Integration tests for ``CancelMatchView.post`` (REQ-WIRE-009, REQ-WIRE-010).

    The non-admin 403 path is already covered by the existing
    ``TestAdminMatchActions::test_cancel_by_non_admin_returns_403``
    (REQ-WIRE-009 scenario 2). Here we focus on the happy path:
    admin POST cancels the match AND fires ``send_notification.delay``
    once per ``MatchPlayer``.

    The notification-fan-out test
    (``test_post_triggers_notifications_for_all_players``) is currently
    RED because the view mutates ``match.is_cancelled`` inline — no
    ``transaction.on_commit`` is registered so ``send_notification.delay``
    is never called. The view refactor (Commit 7, Task 7) will turn
    this GREEN by delegating to ``cancel_match(match)`` which handles
    the save + the on_commit registration + the idempotency guard.
    """

    URL_TMPL = "/api/v1/matches/{id}/cancel/"

    def test_post_as_admin_cancels_match(self, auth_client) -> None:
        """Admin POST returns 200 and sets ``match.is_cancelled=True``.

        Mirrors the existing ``TestAdminMatchActions::test_cancel_by_admin``
        happy-path assertion: 200 status code + ``is_cancelled`` flipped
        after a ``refresh_from_db``. Currently passes regardless of the
        view refactor — the inline mutation already sets the flag —
        but we keep this as a regression net for the 200 status code
        after the service-delegation refactor.
        """
        admin_client, _admin, match, _host, _joined = _build_admin_match_with_player(
            auth_client
        )
        response = admin_client.post(self.URL_TMPL.format(id=match.pk))
        assert response.status_code == 200, response.data
        match.refresh_from_db()
        assert match.is_cancelled is True

    def test_post_triggers_notifications_for_all_players(
        self,
        auth_client,
        patched_send_delay_view,
        django_capture_on_commit_callbacks,
    ) -> None:
        """Admin POST fires ``send_notification.delay`` for every MatchPlayer.

        The on_commit callback from ``cancel_match`` only fires inside
        ``django_capture_on_commit_callbacks(execute=True)`` (matches
        the pattern in ``clubs/tests/test_views.py:191-209``). The
        match has host + 1 joined player = 2 recipients. The current
        view mutates ``match.is_cancelled`` inline so this test FAILS
        with ``call_count == 0`` (expected: 2) until the view
        delegates to ``cancel_match`` (Task 7).
        """
        admin_client, _admin, match, _host, _joined = _build_admin_match_with_player(
            auth_client
        )
        with django_capture_on_commit_callbacks(execute=True):
            response = admin_client.post(self.URL_TMPL.format(id=match.pk))
        assert response.status_code == 200, response.data
        # host + 1 joined player = 2 cancel notifications.
        assert patched_send_delay_view.delay.call_count == 2


# ---------------------------------------------------------------------------
# MatchListView (REQ-MATCH-001..008, SCENARIO-MATCH-01..03)
# ---------------------------------------------------------------------------
def _create_match_for_listing(
    court: Court,
    host: User,
    start_offset_minutes: int,
) -> Match:
    """Create a fresh slot + open Match on ``court`` for TestMatchListView.

    Each call builds its own MatchSlot so the matches are independent
    (different ``start_time`` values → different rows in the response).
    The match is open by default (host only, ``is_cancelled=False``).
    """
    from matches.services import create_match_from_slot

    start = timezone.now() + timedelta(minutes=start_offset_minutes)
    slot = MatchSlot.objects.create(
        court=court,
        start_time=start,
        end_time=start + timedelta(minutes=90),
    )
    return create_match_from_slot(slot=slot, host=host)


@pytest.mark.django_db
class TestMatchListView:
    """Tests for GET /api/v1/clubs/<int:pk>/matches/ (REQ-MATCH-001..008).

    Covers SCENARIO-MATCH-01..03:

    - (a) anonymous GET returns 401 (REQ-MATCH-005)
    - (b) club with no matches → 200, ``[]``
    - (c) club with 1 open + 1 cancelled + 1 full → 200, ``[open]``
      (SCENARIO-MATCH-01; the conftest ``club_with_matches`` fixture
      provides the data)
    - (d) 3 open matches at out-of-order start_times → response is
      sorted by ``start_time`` ASC (SCENARIO-MATCH-02)
    - (e) GET on a nonexistent club → 404 (SCENARIO-MATCH-03)

    Tests use inline helpers rather than ``setUp`` because each test
    needs a slightly different data shape (e.g. ordering needs 3 open
    matches; the empty test needs none).
    """

    URL_TMPL = "/api/v1/clubs/{pk}/matches/"

    def test_unauthenticated_returns_401(self) -> None:
        """Anonymous GET → 401 (REQ-MATCH-005, REQ-MATCH-008(a))."""
        club, _, _ = _make_club_court_slot()
        client = APIClient()
        response = client.get(self.URL_TMPL.format(pk=club.pk))
        assert response.status_code == 401

    def test_returns_empty_list_when_no_open_matches(
        self, auth_client
    ) -> None:
        """Club exists but has no matches → 200, ``[]`` (REQ-MATCH-008(b))."""
        club, _, _ = _make_club_court_slot()
        client, _ = auth_client("m_lm_empty", level=3.50)
        response = client.get(self.URL_TMPL.format(pk=club.pk))
        assert response.status_code == 200, response.data
        assert response.json() == []

    def test_returns_only_open_matches(
        self, auth_client, club_with_matches
    ) -> None:
        """1 open + 1 cancelled + 1 full → 200, list of 1 (the open one).

        Covers REQ-MATCH-002 (``is_cancelled=False`` + ``total<4`` filter)
        + REQ-MATCH-008(c) + SCENARIO-MATCH-01. The conftest fixture
        ``club_with_matches`` builds the three data points.
        """
        club, _court, open_match, _cancelled, _full = club_with_matches
        client, _ = auth_client("m_lm_only", level=3.50)
        response = client.get(self.URL_TMPL.format(pk=club.pk))
        assert response.status_code == 200, response.data
        data = response.json()
        assert len(data) == 1
        assert data[0]["id"] == open_match.pk

    def test_orders_by_start_time_ascending(self, auth_client) -> None:
        """3 open matches at T+5h, T+1h, T+3h → response is T+1h, T+3h, T+5h.

        Covers REQ-MATCH-003 (``order_by("match_slot__start_time")``) +
        REQ-MATCH-008(d) + SCENARIO-MATCH-02. Created in non-sorted
        order to prove the endpoint sorts rather than relying on DB
        insertion order.
        """
        club, court, _ = _make_club_court_slot()
        host = User.objects.create(
            username="m_lm_oh2", email="m_lm_oh2@example.com", level=3.50
        )
        # Insert in T+5h, T+1h, T+3h order — NOT the expected response order.
        m_t5 = _create_match_for_listing(court, host, start_offset_minutes=300)
        m_t1 = _create_match_for_listing(court, host, start_offset_minutes=60)
        m_t3 = _create_match_for_listing(court, host, start_offset_minutes=180)

        client, _ = auth_client("m_lm_ord", level=3.50)
        response = client.get(self.URL_TMPL.format(pk=club.pk))
        assert response.status_code == 200, response.data
        data = response.json()
        assert len(data) == 3
        assert data[0]["id"] == m_t1.pk  # T+1h first
        assert data[1]["id"] == m_t3.pk  # T+3h second
        assert data[2]["id"] == m_t5.pk  # T+5h last

    def test_returns_404_for_nonexistent_club(self, auth_client) -> None:
        """GET /api/v1/clubs/99999/matches/ → 404 (REQ-MATCH-008(e), SCENARIO-MATCH-03)."""
        client, _ = auth_client("m_lm_404", level=3.50)
        response = client.get(self.URL_TMPL.format(pk=99999))
        assert response.status_code == 404
