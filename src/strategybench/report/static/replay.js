// Match replay. Renders hands from window.SB_REPLAY (a run's replay.json). Every displayed
// number arrives pre-formatted from the build, so pages and replays always agree; raw values are
// used only for bar widths. All text is inserted with textContent.
(function () {
  "use strict";
  var D = window.SB_REPLAY;
  var select = document.getElementById("hand-select");
  if (!D || !select) return;

  var stepsEl = document.getElementById("steps");
  var summaryEl = document.getElementById("hand-summary");
  var GROUPS = {
    key: "Where the best responder gains most",
    played: "Played hands",
    simulated: "Simulated hands"
  };
  var NOTES = {
    key: "Constructed example: the deal and betting where switching to the best response gains most, then the best response and the subject's most likely actions.",
    played: "Played live against the " + D.opponent + " opponent; each of the subject's decisions was a fresh query.",
    simulated: "Simulated from the estimated strategy against the equilibrium (not played live)."
  };
  var STATUS = { ok: "valid", parse_failure: "not a single label", illegal: "illegal action" };

  function el(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined && text !== null) node.textContent = text;
    return node;
  }

  function pct(x) {
    return Math.max(0, Math.min(100, 100 * x)).toFixed(2) + "%";
  }

  function seatName(p) {
    return "Player " + (p + 1);
  }

  // Hand picker, grouped.
  var byId = {};
  var order = [];
  ["key", "played", "simulated"].forEach(function (group) {
    var hands = D.hands.filter(function (h) { return h.group === group; });
    if (!hands.length) return;
    var og = el("optgroup");
    og.label = GROUPS[group];
    hands.forEach(function (h) {
      var seat = group === "key" ? "" : " \u00b7 subject as " + seatName(h.subject_seat);
      var opt = el("option", null, h.title + seat + " \u00b7 " + h.payoff_text);
      opt.value = h.id;
      og.appendChild(opt);
      byId[h.id] = h;
      order.push(h.id);
    });
    select.appendChild(og);
  });

  function strategyRow(label, width, tickAt, numsText, chips, refBar) {
    var row = el("div", "sb-row");
    row.appendChild(el("span", "sb-label", label));
    var track = el("span", "sb-track");
    var bar = el("span", refBar ? "sb-bar ref" : "sb-bar");
    bar.style.width = pct(width);
    track.appendChild(bar);
    if (tickAt !== null) {
      var tick = el("span", "sb-tick");
      tick.style.left = pct(tickAt);
      track.appendChild(tick);
    }
    row.appendChild(track);
    var nums = el("span", "sb-nums", numsText);
    chips.forEach(function (c) { nums.appendChild(c); });
    row.appendChild(nums);
    return row;
  }

  function decisionStep(hand, step) {
    var info = D.infostates[step.infostate];
    var subject = step.role === "subject";
    var li = el("li", "step decision");
    if (!subject && hand.focus === step.infostate) li.className += " focus";

    var head = el("div", "step-head");
    head.appendChild(el("span", "role " + step.role, subject ? "Subject" : "Opponent"));
    head.appendChild(el("strong", null, seatName(step.player)));
    head.appendChild(el("span", "muted", info.short));
    li.appendChild(head);
    li.appendChild(el("div", "situation", info.situation));

    var bars = el("div", "sbars");
    info.labels.forEach(function (label) {
      var chips = [];
      if (label === step.action) chips.push(el("span", "played", "played"));
      if (subject) {
        bars.appendChild(strategyRow(label, info.estimated[label], info.equilibrium[label],
          info.text.estimated[label] + " \u00b7 eq " + info.text.equilibrium[label] + " ", chips, false));
      } else {
        var r = info.responder;
        var text = "eq " + info.text.equilibrium[label] + " ";
        if (r && r.values[label] !== null) text += "\u00b7 " + r.text.values[label] + " per visit ";
        if (r && label === r.best_response && r.edge !== null && r.edge > 1e-9) chips.unshift(el("span", "badge-br", "best response"));
        bars.appendChild(strategyRow(label, info.equilibrium[label], null, text, chips, true));
      }
    });
    li.appendChild(bars);

    if (subject && step.attempts && step.attempts.length) {
      var list = el("ol", "attempts");
      step.attempts.forEach(function (a) {
        var item = el("li", null, "Reply: ");
        item.appendChild(el("code", null, a.raw));
        item.appendChild(document.createTextNode(" \u2192 " + (STATUS[a.status] || a.status)));
        list.appendChild(item);
      });
      li.appendChild(list);
    }
    if (subject && step.fallback) {
      li.appendChild(el("p", "step-note", "Every attempt failed, so this action was drawn uniformly at random (counted as a fallback)."));
    }
    var note = subject ? info.subject_note : info.responder_note;
    if (note) li.appendChild(el("p", "step-note", note));
    if (subject && info.replies && info.replies.failures) {
      var p = el("p", "step-note muted",
        "In direct mode, " + info.replies.failures + " of " + info.replies.attempts + " replies here were not a valid label.");
      if (info.replies.examples.length) {
        p.appendChild(document.createTextNode(" Example: "));
        p.appendChild(el("code", null, info.replies.examples[0].raw));
      }
      li.appendChild(p);
    }
    return li;
  }

  function render(id) {
    var hand = byId[id] || byId[order[0]];
    if (!hand) return;
    select.value = hand.id;

    summaryEl.textContent = "";
    summaryEl.appendChild(el("h2", null, hand.title));
    summaryEl.appendChild(el("p", "muted",
      "Subject as " + seatName(hand.subject_seat) + " \u00b7 result for the subject: " + hand.payoff_text + " " + D.payoff_unit + "s"));
    summaryEl.appendChild(el("p", "note", NOTES[hand.group]));

    stepsEl.textContent = "";
    hand.steps.forEach(function (step) {
      if (step.kind === "chance") stepsEl.appendChild(el("li", "step chance", step.text));
      else stepsEl.appendChild(decisionStep(hand, step));
    });
    var amount = hand.payoff_text.replace(/^[+\u2212]/, "") + " " + D.payoff_unit + "s";
    var outcome = hand.subject_payoff > 0 ? "wins " + amount : hand.subject_payoff < 0 ? "loses " + amount : "breaks even";
    stepsEl.appendChild(el("li", "step result", "Hand over: the subject " + outcome + "."));
  }

  function fromHash() {
    var m = /hand=([^&]+)/.exec(window.location.hash);
    return m ? decodeURIComponent(m[1]) : null;
  }

  function go(id) {
    render(id);
    if (history.replaceState) history.replaceState(null, "", "#hand=" + encodeURIComponent(select.value));
  }

  function step(delta) {
    var i = order.indexOf(select.value);
    go(order[(i + delta + order.length) % order.length]);
  }

  select.addEventListener("change", function () { go(select.value); });
  document.getElementById("hand-prev").addEventListener("click", function () { step(-1); });
  document.getElementById("hand-next").addEventListener("click", function () { step(1); });
  window.addEventListener("hashchange", function () { render(fromHash()); });
  render(fromHash());
})();
