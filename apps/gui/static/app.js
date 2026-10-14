// StrategyBench Play: the single-page client for apps/gui/server.py.
// Every piece of game text is inserted with textContent (via h()), never as HTML.
(function () {
  "use strict";

  // ---------------------------------------------------------------- helpers

  function $(id) {
    return document.getElementById(id);
  }

  function append(el, child) {
    if (child == null || child === false) return;
    if (Array.isArray(child)) child.forEach((c) => append(el, c));
    else if (typeof child === "string" || typeof child === "number") el.appendChild(document.createTextNode(String(child)));
    else el.appendChild(child);
  }

  function h(tag, attrs, ...children) {
    const el = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (v == null || v === false) continue;
      if (k === "class") el.className = v;
      else if (k === "text") el.textContent = v;
      else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
      else if (v === true) el.setAttribute(k, "");
      else el.setAttribute(k, String(v));
    }
    children.forEach((c) => append(el, c));
    return el;
  }

  function clear(el) {
    while (el.firstChild) el.removeChild(el.firstChild);
    return el;
  }

  function store(key, value) {
    try {
      localStorage.setItem(key, JSON.stringify(value));
    } catch (e) {
      /* storage unavailable: the setting lasts for this page only */
    }
  }

  function recall(key, fallback) {
    try {
      const v = localStorage.getItem(key);
      return v == null ? fallback : JSON.parse(v);
    } catch (e) {
      return fallback;
    }
  }

  async function api(method, path, body) {
    const opts = { method, headers: {} };
    if (body !== undefined) {
      opts.headers["Content-Type"] = "application/json";
      opts.body = JSON.stringify(body);
    }
    const res = await fetch(path, opts);
    let data = null;
    try {
      data = await res.json();
    } catch (e) {
      /* not JSON */
    }
    if (!res.ok) {
      const err = new Error((data && data.error) || res.status + " " + res.statusText);
      err.status = res.status;
      throw err;
    }
    return data;
  }

  function flash(message, kind) {
    const el = clear($("flash"));
    if (!message) {
      el.hidden = true;
      return;
    }
    el.className = "notice " + (kind || "error");
    el.setAttribute("role", kind === "info" ? "status" : "alert");
    append(el, [
      kind === "info" ? null : h("strong", { text: "Problem: " }),
      message,
      " ",
      h("button", { type: "button", class: "linkish", text: "Dismiss", onclick: () => flash(null) }),
    ]);
    el.hidden = false;
  }

  // ---------------------------------------------------------------- formatting

  const MINUS = "−";

  function signed(x, digits) {
    if (x == null) return "–";
    const d = digits != null ? digits : Number.isInteger(x) ? 0 : 2;
    const s = Math.abs(x).toFixed(d);
    if (Number(s) === 0) return (0).toFixed(d);
    return (x > 0 ? "+" : MINUS) + s;
  }

  function pct(p) {
    if (p == null) return "–";
    if (p <= 0) return "0%";
    if (p < 0.001) return "<0.1%";
    if (p >= 1) return "100%";
    if (p > 0.999) return ">99.9%";
    return (p * 100).toFixed(1) + "%";
  }

  function num(x) {
    return x == null ? "–" : Number(x).toLocaleString("en-US");
  }

  function small(x) {
    if (x == null) return "–";
    if (x !== 0 && Math.abs(x) < 0.001) return x.toExponential(1).replace("-", MINUS);
    return x.toFixed(4);
  }

  function duration(s) {
    if (s == null) return "";
    if (s < 60) return Math.max(1, Math.round(s)) + " s";
    if (s < 3600) return Math.round(s / 60) + " min";
    return (s / 3600).toFixed(1) + " h";
  }

  function clock(s) {
    const m = Math.floor(s / 60);
    const r = Math.floor(s % 60);
    return m + ":" + String(r).padStart(2, "0");
  }

  function seatName(i) {
    return "Player " + (i + 1);
  }

  // ---------------------------------------------------------------- state

  const S = {
    games: null,
    entries: {}, // game ref -> /api/inspect result
    inspect: null, // the game chosen on the setup screen
    view: null, // the table being played
    parked: null, // a table left via "Change setup"
    timer: null,
    profileTimer: null,
    busy: false,
    pace: recall("sb-pace", "450"),
    reveal: false,
    autodeal: recall("sb-autodeal", true),
    coach: recall("sb-coach", false),
    hint: recall("sb-hint", false),
    hintData: null,
    hintPending: null,
    openHands: new Set(),
    ex: null,
    lastAnnounced: "",
  };

  // ---------------------------------------------------------------- routing

  function route() {
    const view = location.hash === "#explore" ? "explore" : "play";
    $("setup").hidden = view !== "play" || !!S.view;
    $("table").hidden = view !== "play" || !S.view;
    $("explore").hidden = view !== "explore";
    document.querySelectorAll("[data-nav]").forEach((a) => {
      if (a.dataset.nav === view) a.setAttribute("aria-current", "page");
      else a.removeAttribute("aria-current");
    });
    if (view === "explore") initExplorer();
    else schedule();
  }

  // ---------------------------------------------------------------- setup screen

  async function loadGames() {
    if (S.games) return S.games;
    S.games = await api("GET", "/api/games");
    renderGameList();
    renderExamples();
    if (S.games.registry_error) flash("Could not import the game registry: " + S.games.registry_error);
    return S.games;
  }

  function gameMeta(g) {
    const size = g.size;
    const parts = [g.players + " players"];
    if (size.infostates_total != null) parts.push(num(size.infostates_total) + " infostates");
    else if (size.decision_nodes != null) parts.push("≈" + num(size.decision_nodes) + " decision nodes");
    parts.push(g.load_string);
    return parts.join(" · ");
  }

  function renderGameList() {
    const list = clear($("game-list"));
    list.setAttribute("role", "radiogroup");
    list.setAttribute("aria-label", "Registered games");
    if (!S.games.registered.length) list.appendChild(h("p", { class: "empty", text: "No registered games found." }));
    S.games.registered.forEach((g) => {
      const id = "game-" + g.ref;
      list.appendChild(
        h(
          "label",
          { class: "game-option", for: id },
          h("input", { type: "radio", name: "game", id, value: g.ref, onchange: () => selectGame(g.ref) }),
          h("span", { class: "title", text: g.title }),
          h("span", { class: "desc", text: g.summary }),
          h("span", { class: "meta", text: gameMeta(g) }),
        ),
      );
    });
  }

  function renderExamples() {
    const box = clear($("custom-help"));
    append(box, h("span", { text: "Try:" }));
    S.games.examples.forEach((ex) => {
      box.appendChild(
        h("button", {
          type: "button",
          class: "linkish mono",
          text: ex.ref,
          title: ex.note,
          onclick: () => {
            $("custom-game").value = ex.ref;
            selectGame(ex.ref);
          },
        }),
      );
    });
  }

  function setStartNote(text) {
    $("start-note").textContent = text || "";
  }

  async function selectGame(ref) {
    $("start").disabled = true;
    setStartNote("Loading " + ref + "…");
    let info;
    try {
      info = await api("POST", "/api/inspect", { game: ref });
    } catch (e) {
      flash(e.message);
      setStartNote("");
      return;
    }
    flash(null);
    S.inspect = info;
    S.entries[info.game.ref] = info;
    document.querySelectorAll('input[name="game"]').forEach((r) => {
      r.checked = r.value === info.game.ref;
    });
    if (!info.game.registered) $("custom-game").value = info.game.ref;
    renderFacts(info.game);
    renderSeatRows(info);
    renderSetupProfile();
    $("start").disabled = false;
    setStartNote(info.game.registered ? "" : "Custom game: OpenSpiel's own text is shown for situations and actions.");
    watchProfile();
  }

  function renderFacts(g) {
    const dl = clear($("game-facts"));
    const size = g.size;
    const nodes =
      size.decision_nodes == null
        ? "more than 10 billion (estimated)"
        : (size.exact ? "" : "≈") + num(size.decision_nodes) + (size.exact ? "" : " (estimated)");
    const facts = [
      ["Game", g.title],
      ["Players", String(g.players)],
      ["Decision nodes", nodes],
      ["Infostates", size.infostates_total != null ? num(size.infostates_total) : "not counted"],
      ["Payoffs", g.utility + (g.two_player_zero_sum ? " (two-player)" : "")],
      ["Text", g.has_spec ? "plain language (GameSpec)" : "OpenSpiel strings"],
    ];
    facts.forEach(([k, v]) => dl.appendChild(h("div", null, h("dt", { text: k }), h("dd", { text: v }))));
  }

  function runLabel(r) {
    const n = r.n_samples == null ? "exact" : "N=" + r.n_samples;
    return r.name + " · " + n + (r.smoke_test ? " · smoke test" : "") + " · " + (r.created || "").slice(0, 10);
  }

  function renderSeatRows(info) {
    const box = clear($("seat-rows"));
    const g = info.game;
    const cfrOk = info.profile.state !== "refused";
    for (let i = 0; i < g.players; i++) {
      const id = "seat-" + i;
      const select = h("select", { id, "aria-describedby": id + "-desc", onchange: () => describeSeat(i) });
      select.appendChild(h("option", { value: "human", text: "Human" }));
      select.appendChild(h("option", { value: "uniform", text: "Uniform random" }));
      select.appendChild(
        h("option", { value: "cfr", text: cfrOk ? "CFR profile" : "CFR profile (unavailable)", disabled: !cfrOk }),
      );
      if (info.runs.length) {
        const group = h("optgroup", { label: "Measured strategies (runs)" });
        info.runs.forEach((r) => group.appendChild(h("option", { value: "run:" + r.id, text: runLabel(r) })));
        select.appendChild(group);
      }
      select.value = i === 0 ? "human" : cfrOk ? "cfr" : "uniform";
      box.appendChild(
        h(
          "div",
          { class: "seat-row" },
          h("label", { for: id, text: seatName(i) }),
          select,
          h("span", { class: "sub", id: id + "-desc" }),
        ),
      );
      describeSeat(i);
    }
    if (!g.has_spec) box.appendChild(h("p", { class: "note", text: "Run strategies exist only for registered games." }));
    else if (!info.runs.length) box.appendChild(h("p", { class: "note", text: "No runs for this game in the runs directory." }));
  }

  function describeSeat(i) {
    const info = S.inspect;
    const value = $("seat-" + i).value;
    let text = "";
    if (value === "human") text = "You choose this seat's moves.";
    else if (value === "uniform") text = "Picks every legal action with equal probability.";
    else if (value === "cfr") {
      text =
        info.profile.guarantee.kind === "nash"
          ? "Samples the CFR profile, an approximate Nash equilibrium."
          : "Samples the CFR profile. No equilibrium guarantee with this game (see the CFR profile box).";
    } else if (value.startsWith("run:")) {
      const r = info.runs.find((x) => "run:" + x.id === value);
      if (r) {
        text = r.description + " · prompt " + r.prompt_version + " · " + r.id;
        if (r.smoke_test) text += " · fewer than 30 samples per situation: a smoke test, not a result";
      }
    }
    $("seat-" + i + "-desc").textContent = text;
  }

  function guaranteeNode(guarantee) {
    const nash = guarantee.kind === "nash";
    return h(
      "p",
      { class: "guarantee" },
      h("span", { class: "chip " + (nash ? "accent" : "warn"), text: guarantee.title }),
      guarantee.text,
    );
  }

  // Shared by the setup screen, the coach and the waiting banner.
  function profileNodes(status, gameRef) {
    const out = [];
    const plan = status.plan;
    if (status.state === "ready") {
      const p = status.profile;
      let line = p.method_name + " average strategy after " + num(p.iterations) + " iterations";
      if (p.exploitability != null) line += "; exploitability " + small(p.exploitability_norm) + " " + p.unit + " per hand.";
      else line += "; NashConv " + small(p.nash_conv) + " " + p.unit + "s.";
      out.push(h("p", null, h("span", { class: "chip accent", text: "Ready" }), " ", line));
      if (p.values) {
        const vals = p.values.map((v, i) => seatName(i) + " " + signed(v, 3)).join(", ");
        out.push(h("p", { class: "note", text: "Seat values when every seat plays it: " + vals + "." }));
      }
      out.push(h("p", { class: "sub", text: p.source }));
    } else if (status.state === "running") {
      const job = status.job;
      const bar = h("progress", { max: job.total || 1 });
      let text;
      if (job.phase === "iterating") {
        bar.value = job.iteration;
        text = "Iteration " + num(job.iteration) + " of " + num(job.total) + " · " + clock(job.elapsed) + " elapsed";
        if (job.iteration > 0 && job.iteration < job.total) {
          text += " · about " + duration((job.elapsed / job.iteration) * (job.total - job.iteration)) + " left";
        }
      } else if (job.phase === "loading") {
        text = "Loading the cached equilibrium… " + clock(job.elapsed);
      } else if (job.phase === "solving") {
        text = "Solving with CFR+ (" + num(plan.iterations) + " iterations, roughly " + duration(plan.est_seconds);
        text += "); OpenSpiel reports no progress here. " + clock(job.elapsed) + " elapsed.";
      } else if (job.phase === "measuring") {
        bar.value = job.total;
        text = "Measuring NashConv…";
      } else {
        text = "Starting the solver…";
      }
      out.push(h("div", { class: "progress" }, bar, h("span", { class: "note", text })));
      out.push(
        h("button", {
          type: "button",
          text: "Cancel",
          onclick: () => profileAction("cancel", gameRef),
        }),
      );
    } else if (status.state === "idle") {
      out.push(
        h("p", {
          text:
            "Not computed yet: " +
            plan.method_name +
            ", " +
            num(plan.iterations) +
            " iterations, roughly " +
            duration(plan.est_seconds) +
            " on a laptop. It runs in the background.",
        }),
      );
      out.push(h("button", { type: "button", text: "Compute now", onclick: () => profileAction("start", gameRef) }));
    } else if (status.state === "refused") {
      out.push(h("p", { text: "No CFR profile: " + status.reason + ". Human, uniform and run seats still work." }));
    } else if (status.state === "error") {
      out.push(h("p", { class: "notice error", text: "The solver failed: " + ((status.job && status.job.error) || "unknown error") }));
      out.push(h("button", { type: "button", text: "Try again", onclick: () => profileAction("start", gameRef) }));
    }
    return out;
  }

  function renderSetupProfile() {
    const info = S.inspect;
    const box = clear($("profile-box"));
    if (!info) return;
    append(box, profileNodes(info.profile, info.game.ref));
    if (info.profile.state !== "refused") box.appendChild(guaranteeNode(info.profile.guarantee));
  }

  async function profileAction(action, gameRef) {
    try {
      const status = await api("POST", "/api/profile/" + action, { game: gameRef });
      applyProfileStatus(gameRef, status);
    } catch (e) {
      flash(e.message);
    }
  }

  function applyProfileStatus(gameRef, status) {
    if (S.inspect && S.inspect.game.ref === gameRef) {
      S.inspect.profile = status;
      renderSetupProfile();
    }
    if (S.view && S.view.game.ref === gameRef) {
      S.view.profile = status;
      renderTable();
    }
    watchProfile();
  }

  // Poll the setup screen's profile while it is being computed.
  function watchProfile() {
    clearTimeout(S.profileTimer);
    const info = S.inspect;
    if (!info || info.profile.state !== "running" || $("setup").hidden) return;
    S.profileTimer = setTimeout(async () => {
      try {
        const status = await api("GET", "/api/profile?game=" + encodeURIComponent(info.game.ref));
        if (S.inspect === info) {
          info.profile = status;
          renderSetupProfile();
        }
      } catch (e) {
        flash(e.message);
        return;
      }
      watchProfile();
    }, 1000);
  }

  async function startTable() {
    const g = S.inspect.game;
    const seats = [];
    for (let i = 0; i < g.players; i++) {
      const v = $("seat-" + i).value;
      seats.push(v.startsWith("run:") ? { kind: "run", run: v.slice(4) } : { kind: v });
    }
    const body = { game: g.ref, seats, reveal: S.reveal };
    const seed = $("seed").value.trim();
    if (seed) body.seed = Number(seed);
    $("start").disabled = true;
    try {
      enterTable(await api("POST", "/api/sessions", body));
    } catch (e) {
      flash(e.message);
    } finally {
      $("start").disabled = false;
    }
  }

  // ---------------------------------------------------------------- table

  function setTableParam(id) {
    const url = new URL(location.href);
    if (id) url.searchParams.set("table", id);
    else url.searchParams.delete("table");
    history.replaceState(null, "", url);
  }

  function enterTable(view) {
    flash(null);
    S.view = view;
    setTableParam(view.id);
    S.parked = null;
    S.hintData = null;
    S.openHands.clear();
    $("table-pace").value = S.pace;
    $("table-reveal").checked = S.reveal;
    route();
    renderTable(true);
    schedule();
  }

  function hasHumans(v) {
    return v.seats.some((s) => s.kind === "human");
  }

  function renderTable(focus) {
    const v = S.view;
    if (!v) return;
    const turn = $("turn");
    const refocus = focus || turn.contains(document.activeElement) || document.activeElement === document.body;
    renderHead(v);
    renderSeatStrip(v);
    renderTurn(v);
    renderLog(v);
    renderCoach(v);
    renderHint(v);
    renderHistory(v);
    announce(v);
    if (refocus && !$("table").hidden) {
      const target = turn.querySelector(".action-btn, select, [data-primary]");
      if (target) target.focus({ preventScroll: true });
    }
  }

  function renderHead(v) {
    $("table-title").textContent = v.game.title;
    let sub = "Hand " + v.hand + " · " + v.hands_played + " finished · seed " + v.seed;
    if (hasHumans(v) && v.revealed && v.phase !== "terminal") sub += " · hidden information shown";
    $("table-sub").textContent = sub;
  }

  function renderSeatStrip(v) {
    const strip = clear($("seat-strip"));
    v.seats.forEach((s) => {
      const toAct = v.to_act === s.index;
      const chips = [h("span", { class: "chip" + (s.kind === "human" ? " accent" : ""), text: s.kind_name })];
      if (v.viewer === s.index && !v.revealed) chips.push(h("span", { class: "chip", text: "your view" }));
      const who = s.kind === "run" ? s.name : s.detail;
      strip.appendChild(
        h(
          "li",
          { class: "seat-card" + (toAct ? " to-act" : ""), "aria-current": toAct ? "true" : null },
          h("div", { class: "top" }, h("span", { class: "seat", text: s.seat }), h("span", null, chips)),
          h("div", { class: "who", text: who, title: s.kind === "run" ? s.detail : null }),
          h(
            "div",
            { class: "total " + (s.total > 0 ? "pos" : s.total < 0 ? "neg" : "") },
            signed(s.total),
            h("span", { class: "sub", text: "total" }),
          ),
          h("div", {
            class: "sub",
            text:
              (s.mean != null ? "mean " + signed(s.mean, 3) + " per hand" : "no hands finished") +
              (s.payoff != null ? " · this hand " + signed(s.payoff) : ""),
          }),
        ),
      );
    });
  }

  function actionButtons(d) {
    if (d.actions.length > 24) {
      const select = h("select", { id: "action-select", "aria-label": "Action" });
      d.actions.forEach((a) => select.appendChild(h("option", { value: a.action, text: a.label })));
      return h(
        "div",
        { class: "row" },
        select,
        h("button", {
          type: "button",
          class: "button-primary",
          text: "Play",
          onclick: () => act(Number(select.value)),
        }),
      );
    }
    const row = h("div", { class: "actions", role: "group", "aria-label": "Legal actions" });
    d.actions.forEach((a, i) => {
      row.appendChild(
        h(
          "button",
          {
            type: "button",
            class: "action-btn",
            "aria-keyshortcuts": i < 9 ? String(i + 1) : null,
            onclick: () => act(a.action),
          },
          h("span", { text: a.label }),
          i < 9 ? h("kbd", { text: String(i + 1), "aria-hidden": "true" }) : null,
        ),
      );
    });
    return row;
  }

  function renderTurn(v) {
    const box = clear($("turn"));
    if (v.phase === "human") {
      const d = v.decision;
      const several = v.seats.filter((s) => s.kind === "human").length > 1;
      box.appendChild(h("h2", { text: several ? seatName(d.player) + " to move" : "Your move (" + seatName(d.player) + ")" }));
      box.appendChild(h("div", { class: "situation" + (d.plain ? "" : " raw"), text: d.situation }));
      box.appendChild(actionButtons(d));
      if (d.actions.length <= 24) box.appendChild(h("p", { class: "caption", text: "Keys 1–9 choose an action." }));
    } else if (v.phase === "terminal") {
      box.appendChild(h("h2", { text: "Hand " + v.hand + " is over" }));
      const list = h("ul", { class: "result-list" });
      v.seats.forEach((s) =>
        list.appendChild(
          h(
            "li",
            null,
            h("span", { text: s.seat + " · " + (s.kind === "run" ? s.name : s.kind_name) }),
            h("strong", { class: s.payoff > 0 ? "pos" : s.payoff < 0 ? "neg" : "", text: signed(s.payoff) }),
          ),
        ),
      );
      box.appendChild(list);
      box.appendChild(
        h(
          "button",
          { type: "button", class: "button-primary", "data-primary": true, onclick: nextHand, "aria-keyshortcuts": "N" },
          "Deal hand " + (v.hand + 1) + " ",
          h("kbd", { text: "N", "aria-hidden": "true" }),
        ),
      );
      if (!hasHumans(v) && S.autodeal && S.pace !== "manual")
        box.appendChild(h("p", { class: "caption", text: "Dealing automatically (no human seats)." }));
    } else {
      const seat = v.to_act != null ? v.seats[v.to_act] : null;
      const who = v.phase === "chance" ? "Chance" : seat.seat + " (" + (seat.kind === "run" ? seat.name : seat.kind_name) + ")";
      box.appendChild(h("h2", { text: who + " to act" }));
      if (v.waiting && v.profile) {
        box.appendChild(h("p", { text: "This seat plays the CFR profile, which is not ready yet." }));
        append(box, profileNodes(v.profile, v.game.ref));
      } else {
        box.appendChild(
          h("p", {
            class: "note",
            text: S.pace === "manual" ? "Press Step to continue." : "Moving automatically. Choose “Step manually” above to go one move at a time.",
          }),
        );
      }
      box.appendChild(
        h(
          "button",
          {
            type: "button",
            "data-primary": true,
            onclick: step,
            disabled: !!v.waiting,
            "aria-keyshortcuts": "S",
          },
          "Step ",
          h("kbd", { text: "S", "aria-hidden": "true" }),
        ),
      );
    }
  }

  function logItems(events, seats) {
    return events.map((e) => {
      if (e.kind === "chance") {
        const text = e.text + (!e.hidden && e.prob != null && e.prob < 1 ? " (" + pct(e.prob) + ")" : "");
        return h("li", { class: "chance" + (e.hidden ? " hidden" : ""), text });
      }
      const seat = seats[e.player];
      const li = h("li", { class: "move" + (e.hidden ? " hidden" : "") });
      li.appendChild(h("span", { class: "who" + (seat && seat.kind === "human" ? " human" : ""), text: seatName(e.player) }));
      if (e.hidden) {
        li.appendChild(h("span", { text: e.text }));
      } else {
        li.appendChild(h("span", { class: "label", text: e.label }));
        if (e.probs) {
          const dist = e.probs.map((p) => p.label + " " + pct(p.p)).join(" · ");
          li.appendChild(h("span", { class: "extra", text: (seat ? seat.kind_name : "Bot") + ": " + dist }));
        } else if (seat && seat.kind !== "human" && !e.hidden) {
          li.appendChild(h("span", { class: "extra", text: "probabilities shown when the hand ends" }));
        }
        if (e.coach_prob != null) li.appendChild(h("span", { class: "extra", text: "CFR profile plays this " + pct(e.coach_prob) }));
      }
      if (e.note) li.appendChild(h("span", { class: "note", text: e.note }));
      return li;
    });
  }

  function renderLog(v) {
    const list = clear($("log"));
    if (!v.log.length) list.appendChild(h("li", { class: "empty", text: "Nothing has happened yet." }));
    append(list, logItems(v.log, v.seats));
    if (v.returns) {
      const res = v.returns.map((r, i) => seatName(i) + " " + signed(r)).join(", ");
      list.appendChild(h("li", { class: "end", text: "Result: " + res }));
    }
  }

  function sbRow(label, p, tick, nums, ref) {
    const track = h("div", { class: "sb-track", "aria-hidden": "true" });
    const bar = h("div", { class: "sb-bar" + (ref ? " ref" : "") });
    bar.style.width = Math.max(0, Math.min(1, p || 0)) * 100 + "%";
    track.appendChild(bar);
    if (tick != null) {
      const t = h("div", { class: "sb-tick" });
      t.style.left = Math.max(0, Math.min(1, tick)) * 100 + "%";
      track.appendChild(t);
    }
    return h("div", { class: "sb-row" }, h("span", { class: "sb-label", text: label }), track, h("span", { class: "sb-nums", text: nums }));
  }

  function renderCoach(v) {
    const body = clear($("coach-body"));
    $("coach-toggle").checked = S.coach;
    if (!S.coach) {
      body.appendChild(h("p", { class: "empty", text: "Shows the CFR profile's action probabilities at your decisions." }));
      return;
    }
    if (!v.game.has_infostates || !v.profile) {
      body.appendChild(h("p", { class: "empty", text: "No CFR profile: OpenSpiel gives no information states for this game." }));
      return;
    }
    const status = v.profile;
    if (status.state === "refused") {
      body.appendChild(h("p", { class: "empty", text: "No CFR profile: " + status.reason + "." }));
      return;
    }
    if (v.phase === "human" && v.decision.coach && v.decision.coach.status === "ready") {
      const c = v.decision.coach;
      if (c.missing) body.appendChild(h("p", { text: "This situation is not in the CFR profile." }));
      else {
        const bars = h("div", { class: "sbars", role: "list", "aria-label": "CFR profile probabilities" });
        c.actions.forEach((a) => {
          const row = sbRow(a.label, a.p, null, pct(a.p));
          row.setAttribute("role", "listitem");
          bars.appendChild(row);
        });
        body.appendChild(bars);
        const p = c.profile;
        body.appendChild(
          h("p", {
            class: "caption",
            text:
              "What the " + p.method_name + " average strategy (" + num(p.iterations) + " iterations) plays in exactly this situation" +
              (p.exploitability != null
                ? "; exploitability " + small(p.exploitability_norm) + " " + p.unit + " per hand."
                : "; NashConv " + small(p.nash_conv) + " " + p.unit + "s."),
          }),
        );
      }
    } else if (status.state !== "ready") {
      append(body, profileNodes(status, v.game.ref));
    } else {
      body.appendChild(h("p", { class: "empty", text: "The coach speaks at a human seat's decisions." }));
    }
    body.appendChild(guaranteeNode(status.guarantee));
  }

  function renderHint(v) {
    const panel = $("hint-panel");
    panel.hidden = v.game.players !== 2;
    if (panel.hidden) return;
    const body = clear($("hint-body"));
    $("hint-toggle").checked = S.hint;
    if (!S.hint) {
      body.appendChild(
        h("p", {
          class: "empty",
          text: "What each action is worth against the other seat's policy, if you best-respond for the rest of the hand.",
        }),
      );
      return;
    }
    if (v.phase !== "human") {
      body.appendChild(h("p", { class: "empty", text: "Available at a human seat's decisions." }));
      return;
    }
    const key = v.id + ":" + v.ply;
    if (!S.hintData || S.hintData.key !== key) {
      body.appendChild(h("p", { class: "empty", text: "Computing the best response…" }));
      fetchHint(key);
      return;
    }
    const data = S.hintData.data;
    if (!data.available) {
      body.appendChild(h("p", { class: "empty", text: data.reason }));
      return;
    }
    const table = h("table", { class: "values" });
    table.appendChild(
      h("thead", null, h("tr", null, h("th", { scope: "col", text: "Action" }), h("th", { scope: "col", class: "r", text: "Value per hand" }))),
    );
    const tbody = h("tbody");
    data.values.forEach((row) =>
      tbody.appendChild(
        h(
          "tr",
          { class: row.best ? "best" : null },
          h("th", { scope: "row" }, row.label, row.best ? h("span", { class: "badge-best", text: "best" }) : null),
          h("td", { class: "r", text: signed(row.value / (data.unit_size || 1), 3) }),
        ),
      ),
    );
    table.appendChild(tbody);
    body.appendChild(table);
    body.appendChild(
      h("p", {
        class: "caption",
        text:
          "Expected payoff for the whole hand, in " + data.unit + "s, if you take the action and then best-respond, " +
          "weighting the other seat's possible private information by how likely its policy makes it. Assumes " +
          seatName(data.against.seat) + " keeps playing " + data.against.name + " and that you know that policy.",
      }),
    );
  }

  async function fetchHint(key) {
    if (S.hintPending === key) return;
    S.hintPending = key;
    const v = S.view;
    let data;
    try {
      data = await api("GET", "/api/sessions/" + v.id + "/hint?ply=" + v.ply);
    } catch (e) {
      data = { available: false, reason: e.message };
    }
    S.hintPending = null;
    S.hintData = { key, data };
    if (S.view && S.view.id + ":" + S.view.ply === key) renderHint(S.view);
  }

  function renderHistory(v) {
    const list = clear($("history"));
    if (!v.history.length) {
      list.appendChild(h("li", { class: "empty", text: "Finished hands appear here, newest first." }));
      return;
    }
    v.history.forEach((hand) => {
      const res = hand.returns.map((r, i) => "P" + (i + 1) + " " + signed(r)).join(", ");
      const details = h(
        "details",
        { open: S.openHands.has(hand.hand) },
        h("summary", { text: "Hand " + hand.hand + ": " + res }),
        h("ol", { class: "log" }, logItems(hand.events, v.seats)),
      );
      details.addEventListener("toggle", () => {
        if (details.open) S.openHands.add(hand.hand);
        else S.openHands.delete(hand.hand);
      });
      list.appendChild(h("li", null, details));
    });
    if (v.hands_played > v.history.length)
      list.appendChild(h("li", { class: "note", text: "Older hands are in the JSON export." }));
  }

  function announce(v) {
    let text = "";
    if (v.phase === "terminal" && v.returns) text = "Hand over. " + v.returns.map((r, i) => seatName(i) + " " + signed(r)).join(", ");
    else if (v.phase === "human") text = "Your move as " + seatName(v.decision.player);
    else if (v.log.length) text = v.log[v.log.length - 1].text;
    if (text && text !== S.lastAnnounced) {
      S.lastAnnounced = text;
      $("live").textContent = text;
    }
  }

  async function send(path, body) {
    if (S.busy || !S.view) return;
    S.busy = true;
    clearTimeout(S.timer);
    try {
      S.view = await api("POST", "/api/sessions/" + S.view.id + "/" + path, Object.assign({ reveal: S.reveal }, body));
      renderTable();
    } catch (e) {
      if (e.status === 409) await refresh().catch((err) => flash(err.message));
      else flash(e.message);
    } finally {
      S.busy = false;
      schedule();
    }
  }

  function act(action) {
    return send("act", { action, ply: S.view.ply });
  }

  function step() {
    return send("step", { ply: S.view.ply });
  }

  function nextHand() {
    return send("next", { hand: S.view.hand });
  }

  async function refresh() {
    S.view = await api("GET", "/api/sessions/" + S.view.id + "?reveal=" + (S.reveal ? 1 : 0));
    renderTable();
  }

  async function poll() {
    if (S.busy) return schedule();
    S.busy = true;
    try {
      await refresh();
    } catch (e) {
      flash(e.message);
      S.busy = false;
      return;
    }
    S.busy = false;
    schedule();
  }

  function schedule() {
    clearTimeout(S.timer);
    const v = S.view;
    if (!v || $("table").hidden) return;
    const profileRunning = v.profile && v.profile.state === "running";
    if (v.waiting || (profileRunning && S.coach)) {
      S.timer = setTimeout(poll, 1000);
      return;
    }
    if (S.pace === "manual") return;
    const delay = Number(S.pace) || 0;
    if (v.phase === "chance") S.timer = setTimeout(step, Math.min(delay, 250));
    else if (v.phase === "bot") S.timer = setTimeout(step, delay);
    else if (v.phase === "terminal" && S.autodeal && !hasHumans(v)) S.timer = setTimeout(nextHand, Math.max(2 * delay, 150));
  }

  function leaveTable() {
    clearTimeout(S.timer);
    S.parked = S.view;
    S.view = null;
    setTableParam(null);
    route();
    const note = $("start-note");
    clear(note);
    append(note, [
      "Your table is kept for this page. ",
      h("button", {
        type: "button",
        class: "linkish",
        text: "Return to it",
        onclick: () => enterTable(S.parked),
      }),
    ]);
    watchProfile();
  }

  // ---------------------------------------------------------------- explorer

  async function initExplorer() {
    try {
      await loadGames();
    } catch (e) {
      flash(e.message);
      return;
    }
    const select = $("ex-game");
    const refs = S.games.registered.filter((g) => g.size.enumerable && g.has_infostates).map((g) => [g.ref, g.title]);
    Object.values(S.entries).forEach((info) => {
      if (!info.game.registered && info.explorer) refs.push([info.game.ref, info.game.ref]);
    });
    const current = S.ex ? S.ex.ref : S.inspect && S.inspect.explorer ? S.inspect.game.ref : refs.length ? refs[0][0] : null;
    clear(select);
    refs.forEach(([ref, title]) => select.appendChild(h("option", { value: ref, text: title })));
    if (!current) return;
    select.value = current;
    if (!S.ex || S.ex.ref !== current) exploreGame(current);
  }

  async function exploreGame(ref) {
    let info = S.entries[ref];
    try {
      if (!info) info = S.entries[ref] = await api("POST", "/api/inspect", { game: ref });
    } catch (e) {
      flash(e.message);
      return;
    }
    S.ex = { ref, offset: 0, info };
    const runSelect = clear($("ex-run"));
    runSelect.appendChild(h("option", { value: "", text: "No run (CFR profile only)" }));
    info.runs.forEach((r) => runSelect.appendChild(h("option", { value: r.id, text: runLabel(r) })));
    if (info.runs.length) runSelect.value = info.runs.find((r) => !r.smoke_test) ? info.runs.find((r) => !r.smoke_test).id : info.runs[0].id;
    const playerSelect = clear($("ex-player"));
    playerSelect.appendChild(h("option", { value: "all", text: "All seats" }));
    for (let i = 0; i < info.game.players; i++) playerSelect.appendChild(h("option", { value: String(i), text: seatName(i) }));
    loadExplore(true);
  }

  async function loadExplore(reset) {
    const ex = S.ex;
    if (!ex) return;
    if (reset) ex.offset = 0;
    const params = new URLSearchParams({
      game: ex.ref,
      run: $("ex-run").value,
      player: $("ex-player").value,
      q: $("ex-q").value,
      forced: $("ex-forced").checked ? "show" : "hide",
      offset: String(ex.offset),
      limit: "50",
    });
    const token = (ex.token = (ex.token || 0) + 1);
    const summary = clear($("ex-summary"));
    if (reset) summary.appendChild(h("p", { class: "note", text: "Loading…" }));
    let data;
    try {
      data = await api("GET", "/api/explore?" + params.toString());
    } catch (e) {
      clear(summary);
      flash(e.message);
      return;
    }
    if (token !== ex.token || S.ex !== ex) return;
    const list = $("ex-list");
    if (reset) clear(list);
    clear(summary);
    const hasRun = !!data.run;
    const cfrReady = data.profile && data.profile.state === "ready";
    const weighting = { run: "the run's measured strategy", cfr: "the CFR profile", uniform: "uniform play" }[data.weighting];
    summary.appendChild(
      h("p", {
        class: "note",
        text:
          num(data.matched) + " of " + num(data.total) + " situations match" +
          ($("ex-forced").checked ? "" : " (forced moves hidden)") +
          ". Sorted by reach: how often the situation arises when every seat plays " + weighting + ", chance included.",
      }),
    );
    const legend = h("p", { class: "legend" });
    if (hasRun) legend.appendChild(h("span", null, h("span", { class: "key-bar" }), "Run: " + data.run.name));
    else legend.appendChild(h("span", null, h("span", { class: "key-bar" }), "CFR profile"));
    if (hasRun && cfrReady) legend.appendChild(h("span", null, h("span", { class: "key-tick" }), "CFR profile"));
    summary.appendChild(legend);
    if (data.profile && data.profile.state === "running") {
      summary.appendChild(h("p", { class: "note", text: "The CFR profile is still being computed; this list refreshes when it is ready." }));
      clearTimeout(ex.poll);
      ex.poll = setTimeout(() => S.ex === ex && !$("explore").hidden && loadExplore(true), 2000);
    } else if (data.profile && data.profile.state !== "ready") {
      summary.appendChild(h("p", { class: "note", text: "No CFR profile for this game yet; compute it from the Play screen." }));
    }
    data.rows.forEach((r) => list.appendChild(exploreRow(r, hasRun, cfrReady)));
    ex.offset = data.offset + data.rows.length;
    $("ex-more").hidden = ex.offset >= data.matched;
  }

  function exploreRow(r, hasRun, cfrReady) {
    const meta = ["reach " + pct(r.reach)];
    if (hasRun) meta.push("N=" + r.support);
    if (r.distance != null) meta.push("distance from CFR " + r.distance.toFixed(2));
    const bars = h("div", { class: "sbars" });
    r.labels.forEach((label) => {
      const main = hasRun ? r.run[label] : r.cfr ? r.cfr[label] : null;
      const tick = hasRun && cfrReady && r.cfr ? r.cfr[label] : null;
      let nums = pct(main);
      if (tick != null) nums += " · CFR " + pct(tick);
      bars.appendChild(sbRow(label, main, tick, nums));
    });
    return h(
      "li",
      { class: "explore-row" },
      h(
        "div",
        { class: "head" },
        h("span", { class: "chip", text: r.seat }),
        h("span", { class: "short", text: r.short }),
        h("span", { class: "meta", text: meta.join(" · ") }),
      ),
      bars,
      r.note ? h("p", { class: "note", text: r.note }) : null,
      h("details", null, h("summary", { text: "Situation" }), h("div", { class: "situation", text: r.situation })),
    );
  }

  // ---------------------------------------------------------------- wiring

  function wire() {
    $("custom-load").addEventListener("click", () => {
      const v = $("custom-game").value.trim();
      if (v) selectGame(v);
    });
    $("custom-game").addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        e.preventDefault();
        $("custom-load").click();
      }
    });
    $("start").addEventListener("click", startTable);
    $("pace").value = S.pace;
    $("autodeal").checked = S.autodeal;
    for (const id of ["pace", "table-pace"]) {
      $(id).addEventListener("change", (e) => {
        S.pace = e.target.value;
        store("sb-pace", S.pace);
        $("pace").value = $("table-pace").value = S.pace;
        if (S.view) renderTable();
        schedule();
      });
    }
    $("autodeal").addEventListener("change", (e) => {
      S.autodeal = e.target.checked;
      store("sb-autodeal", S.autodeal);
    });
    for (const id of ["reveal", "table-reveal"]) {
      $(id).addEventListener("change", (e) => {
        S.reveal = e.target.checked;
        $("reveal").checked = $("table-reveal").checked = S.reveal;
        if (S.view) refresh().catch((err) => flash(err.message));
      });
    }
    $("coach-toggle").addEventListener("change", (e) => {
      S.coach = e.target.checked;
      store("sb-coach", S.coach);
      if (S.view) renderCoach(S.view);
      schedule();
    });
    $("hint-toggle").addEventListener("change", (e) => {
      S.hint = e.target.checked;
      store("sb-hint", S.hint);
      if (S.view) renderHint(S.view);
    });
    $("back").addEventListener("click", leaveTable);
    $("export").addEventListener("click", () => {
      if (!S.view) return;
      const a = h("a", { href: "/api/sessions/" + S.view.id + "/export", download: "strategybench-hands-" + S.view.id + ".json" });
      document.body.appendChild(a);
      a.click();
      a.remove();
    });
    $("ex-game").addEventListener("change", (e) => exploreGame(e.target.value));
    for (const id of ["ex-run", "ex-player", "ex-forced"]) $(id).addEventListener("change", () => loadExplore(true));
    let typing = null;
    $("ex-q").addEventListener("input", () => {
      clearTimeout(typing);
      typing = setTimeout(() => loadExplore(true), 250);
    });
    $("ex-more").addEventListener("click", () => loadExplore(false));

    document.addEventListener("keydown", (e) => {
      const v = S.view;
      if (!v || $("table").hidden || e.altKey || e.ctrlKey || e.metaKey) return;
      const t = e.target;
      if (t && (t.tagName === "SELECT" || t.tagName === "TEXTAREA" || (t.tagName === "INPUT" && t.type !== "checkbox"))) return;
      if (v.phase === "human" && /^[1-9]$/.test(e.key)) {
        const a = v.decision.actions[Number(e.key) - 1];
        if (a && v.decision.actions.length <= 24) {
          e.preventDefault();
          act(a.action);
        }
      } else if ((e.key === "s" || e.key === "S") && (v.phase === "bot" || v.phase === "chance") && !v.waiting) {
        e.preventDefault();
        step();
      } else if ((e.key === "n" || e.key === "N") && v.phase === "terminal") {
        e.preventDefault();
        nextHand();
      }
    });

    const toggle = document.querySelector(".theme-toggle");
    toggle.addEventListener("click", () => {
      const root = document.documentElement;
      const current =
        root.dataset.theme || (window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
      const next = current === "dark" ? "light" : "dark";
      root.dataset.theme = next;
      try {
        localStorage.setItem("sb-theme", next);
      } catch (err) {
        /* storage unavailable: the choice lasts for this page only */
      }
    });
    window.addEventListener("hashchange", route);
  }

  async function init() {
    wire();
    const params = new URLSearchParams(location.search);
    for (const name of ["coach", "hint"]) {
      if (params.has(name)) {
        S[name] = params.get(name) === "1";
        store("sb-" + name, S[name]);
      }
    }
    try {
      const games = await loadGames();
      const wanted = params.get("game");
      if (wanted) await selectGame(wanted);
      else if (games.registered.length) await selectGame(games.registered[0].ref);
    } catch (e) {
      flash("Could not reach the server: " + e.message);
      return;
    }
    route();
    const table = params.get("table");
    if (table) {
      try {
        S.reveal = params.get("reveal") === "1";
        $("reveal").checked = S.reveal;
        enterTable(await api("GET", "/api/sessions/" + encodeURIComponent(table) + "?reveal=" + (S.reveal ? 1 : 0)));
      } catch (e) {
        setTableParam(null);
        flash("That table is gone (" + e.message + "). Start a new one below.", "info");
      }
    }
  }

  init();
})();
