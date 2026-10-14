"""The JSON API's validation and the HTTP layer: routes, same-origin checks, body limits, a full hand."""

import http.client
import json
import math
import threading

import pytest
import server
from sbgui.app import ApiError, App


@pytest.fixture
def app(runs_dir):
    app = App(runs_dir)
    yield app
    app.close()


@pytest.fixture
def http_server(app):
    srv = server.make_server(app, port=0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv
    srv.shutdown()
    srv.server_close()


def call(srv, method, path, body=None, headers=None):
    port = srv.server_address[1]
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
    headers = dict(headers or {})
    data = None
    if body is not None:
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        headers.setdefault("Content-Type", "application/json")
    conn.request(method, path, body=data, headers=headers)
    res = conn.getresponse()
    raw = res.read()
    conn.close()
    content_type = res.getheader("Content-Type", "")
    payload = json.loads(raw) if content_type.startswith("application/json") else raw
    return res.status, res, payload


def api_error(fn, *args):
    with pytest.raises(ApiError) as caught:
        fn(*args)
    return caught.value.status, caught.value.message


def test_seat_validation(app, run_id):
    two = [{"kind": "human"}, {"kind": "uniform"}]
    assert api_error(app.create_session, {"game": "kuhn", "seats": two[:1]})[0] == 400
    status, message = api_error(app.create_session, {"game": "kuhn", "seats": [{"kind": "robot"}, two[1]]})
    assert status == 400 and "kind must be one of" in message
    status, message = api_error(
        app.create_session, {"game": "kuhn_poker(players=3)", "seats": [*two, {"kind": "run", "run": run_id}]}
    )
    assert status == 400 and "only for registered games" in message
    status, message = api_error(
        app.create_session, {"game": "kuhn", "seats": [two[0], {"kind": "run", "run": "nope"}]}
    )
    assert status == 400 and "no run 'nope'" in message
    status, message = api_error(app.create_session, {"game": "mancala", "seats": [two[0], {"kind": "cfr"}]})
    assert status == 400 and "information states" in message
    status, message = api_error(app.create_session, {"game": "kuhn", "seats": two, "seed": "x"})
    assert status == 400 and "seed" in message

    view = app.create_session({"game": "kuhn", "seats": [two[0], {"kind": "run", "run": run_id}], "seed": 1})
    assert view["seats"][1]["name"] == "test-first-action"
    assert view["seats"][1]["kind_name"] == "Run strategy"


def test_session_lookup_and_stale_hints(app):
    assert api_error(app.view, "nope")[0] == 404
    view = app.create_session({"game": "kuhn", "seats": [{"kind": "human"}, {"kind": "uniform"}], "seed": 1})
    assert api_error(app.hint, view["id"], view["ply"] + 1)[0] == 409
    assert api_error(app.hint, view["id"], "x")[0] == 400


def test_explore_api(app, run_id):
    assert "information states" in api_error(app.explore, {"game": "mancala"})[1]
    assert "too large" in api_error(app.explore, {"game": "leduc_poker(players=4)"})[1]
    out = app.explore({"game": "kuhn", "run": run_id, "player": "1", "q": "king"})
    assert out["weighting"] == "run" and out["run"]["id"] == run_id
    assert out["matched"] == 2 and out["total"] == 12
    assert api_error(app.explore, {"game": "kuhn", "run": "nope"})[0] == 400


def test_page_static_files_and_security_headers(http_server):
    status, res, body = call(http_server, "GET", "/")
    assert status == 200 and b"StrategyBench" in body
    assert "default-src 'self'" in res.getheader("Content-Security-Policy")
    assert res.getheader("X-Content-Type-Options") == "nosniff"
    assert call(http_server, "GET", "/static/app.js")[0] == 200
    status, _, payload = call(http_server, "GET", "/static/../server.py")
    assert status == 404 and "no route" in payload["error"]


def test_requests_from_other_sites_are_refused(http_server):
    port = http_server.server_address[1]
    assert call(http_server, "GET", "/api/games", headers={"Host": "evil.example"})[0] == 403
    assert call(http_server, "GET", "/api/games", headers={"Origin": "http://evil.example"})[0] == 403
    same = {"Origin": f"http://localhost:{port}", "Host": f"localhost:{port}"}
    status, _, payload = call(http_server, "GET", "/api/games", headers=same)
    assert status == 200 and {g["ref"] for g in payload["registered"]} >= {"kuhn", "leduc", "liars_dice"}


def test_bad_request_bodies(http_server):
    text = {"Content-Type": "text/plain"}
    assert call(http_server, "POST", "/api/inspect", b'{"game": "kuhn"}', text)[0] == 415
    assert call(http_server, "POST", "/api/inspect", b"{not json")[0] == 400
    assert call(http_server, "POST", "/api/inspect", b"[1, 2]")[0] == 400
    # Announce an oversized body without sending it: the server must refuse before reading.
    conn = http.client.HTTPConnection("127.0.0.1", http_server.server_address[1], timeout=30)
    conn.putrequest("POST", "/api/inspect")
    conn.putheader("Content-Type", "application/json")
    conn.putheader("Content-Length", str(server.MAX_BODY + 1))
    conn.endheaders()
    assert conn.getresponse().status == 413
    conn.close()


def test_a_whole_hand_over_http(http_server):
    seats = [{"kind": "uniform"}, {"kind": "uniform"}]
    status, _, view = call(http_server, "POST", "/api/sessions", {"game": "kuhn", "seats": seats, "seed": 4})
    assert status == 201 and view["phase"] == "chance" and view["revealed"]
    sid = view["id"]
    while view["phase"] != "terminal":
        status, _, view = call(http_server, "POST", f"/api/sessions/{sid}/step", {"ply": view["ply"]})
        assert status == 200
    assert sum(view["returns"]) == 0
    assert call(http_server, "POST", f"/api/sessions/{sid}/step", {"ply": view["ply"]})[0] == 409
    status, _, view = call(http_server, "POST", f"/api/sessions/{sid}/next", {"hand": view["hand"]})
    assert status == 200 and view["hand"] == 2 and view["hands_played"] == 1

    status, res, export = call(http_server, "GET", f"/api/sessions/{sid}/export")
    assert status == 200 and "attachment" in res.getheader("Content-Disposition")
    assert export["hands_played"] == 1 and export["seed"] == 4


def test_numbers_json_cannot_hold_become_null():
    assert server._finite({"a": math.nan, "b": [1.0, math.inf], "c": "x"}) == {
        "a": None,
        "b": [1.0, None],
        "c": "x",
    }
