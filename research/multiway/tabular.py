"""Flattened game trees and full-width solvers for small n-player OpenSpiel games.

Research code for the multiway spike (docs/research/multiway.md). It is not part of the
StrategyBench package: `src/strategybench/analysis` is two-player only by design.

The whole game tree is enumerated once into numpy arrays, so one full-width pass (reach
probabilities, values, counterfactual regrets or a best response) is a handful of
vectorised operations per depth level. That makes tens of thousands of CFR or fictitious
play iterations on three-player Kuhn poker (601 nodes) take seconds.

Conventions:
* A strategy profile is a flat vector `sigma` over *sequences* (infostate, action) pairs,
  for all players at once. `sigma[s]` is the probability of the action at its infostate.
* `best_response_value(player, weights)` takes per-terminal weights for the opponents and
  chance. With weights from a single profile it is the usual best response; with weights
  averaged over many profiles it is the best response to that mixture (used for the
  coarse-correlated-equilibrium gap of CFR's sequence of iterates).
"""

from __future__ import annotations

import numpy as np
import pyspiel
from open_spiel.python import policy as policy_lib

CHANCE = -1
TERMINAL = -2


class GameTree:
    """The full tree of a small OpenSpiel game, flattened into arrays."""

    def __init__(self, game: pyspiel.Game) -> None:
        self.game = game
        self.num_players = game.num_players()
        n_players = self.num_players

        parent: list[int] = []
        depth: list[int] = []
        edge_seq: list[int] = []
        edge_chance: list[float] = []
        node_player: list[int] = []
        node_infoset: list[int] = []
        children: list[list[int]] = []
        terminal_nodes: list[int] = []
        terminal_returns: list[list[float]] = []

        self.infoset_keys: list[str] = []
        self.infoset_player: list[int] = []
        self.infoset_actions: list[list[int]] = []
        self.infoset_first_seq: list[int] = []
        self.infoset_parent_seq: list[int] = []
        self.infoset_depth: list[int] = []
        self.infoset_state: list[pyspiel.State] = []
        self.infoset_node: list[int] = []
        index: dict[str, int] = {}
        seq_infoset: list[int] = []
        seq_k: list[int] = []

        def visit(state, par, eseq, eprob, d, last_seq):
            idx = len(parent)
            parent.append(par)
            depth.append(d)
            edge_seq.append(eseq)
            edge_chance.append(eprob)
            children.append([])
            if par >= 0:
                children[par].append(idx)
            if state.is_terminal():
                node_player.append(TERMINAL)
                node_infoset.append(-1)
                terminal_nodes.append(idx)
                terminal_returns.append(list(state.returns()))
                return
            if state.is_chance_node():
                node_player.append(CHANCE)
                node_infoset.append(-1)
                for action, prob in state.chance_outcomes():
                    visit(state.child(action), idx, -1, prob, d + 1, last_seq)
                return
            player = state.current_player()
            key = state.information_state_string(player)
            actions = list(state.legal_actions())
            if key not in index:
                info = len(self.infoset_keys)
                index[key] = info
                self.infoset_keys.append(key)
                self.infoset_player.append(player)
                self.infoset_actions.append(actions)
                self.infoset_first_seq.append(len(seq_infoset))
                self.infoset_parent_seq.append(last_seq[player])
                self.infoset_depth.append(d)
                self.infoset_state.append(state.clone())
                self.infoset_node.append(idx)
                for k in range(len(actions)):
                    seq_infoset.append(info)
                    seq_k.append(k)
            info = index[key]
            # Perfect recall, identical legal actions, and (for the vectorised best response)
            # every node of an infostate at the same depth.
            assert self.infoset_actions[info] == actions, key
            assert self.infoset_parent_seq[info] == last_seq[player], key
            assert self.infoset_depth[info] == d, key
            node_player.append(player)
            node_infoset.append(info)
            first = self.infoset_first_seq[info]
            for k, action in enumerate(actions):
                nxt = list(last_seq)
                nxt[player] = first + k
                visit(state.child(action), idx, first + k, 1.0, d + 1, tuple(nxt))

        visit(game.new_initial_state(), -1, -1, 1.0, 0, tuple([-1] * n_players))

        self.num_nodes = len(parent)
        self.num_infosets = len(self.infoset_keys)
        self.num_seqs = len(seq_infoset)
        self.parent = np.array(parent)
        self.depth = np.array(depth)
        self.edge_seq = np.array(edge_seq)
        self.edge_chance = np.array(edge_chance)
        self.node_player = np.array(node_player)
        self.node_infoset = np.array(node_infoset)
        self.terminal_nodes = np.array(terminal_nodes)
        self.terminal_returns = np.array(terminal_returns)
        self.seq_infoset = np.array(seq_infoset)
        self.seq_k = np.array(seq_k)
        self.seq_player = np.array(self.infoset_player)[self.seq_infoset]
        self.infoset_index = index
        self.infoset_player_arr = np.array(self.infoset_player)
        self.infoset_node_arr = np.array(self.infoset_node)
        self.infoset_parent_seq_arr = np.array(self.infoset_parent_seq)
        self.infoset_num_actions = np.array([len(a) for a in self.infoset_actions])
        self.max_actions = int(self.infoset_num_actions.max())
        edge_player = np.full(self.num_nodes, -1)
        has_parent = self.parent >= 0
        edge_player[has_parent] = self.node_player[self.parent[has_parent]]
        edge_player[self.edge_seq < 0] = -1
        self.edge_player = edge_player

        # Child matrix padded with a dummy node index (num_nodes) whose value is always 0.
        width = max(len(c) for c in children)
        self.child = np.full((self.num_nodes, width), self.num_nodes)
        for n, cs in enumerate(children):
            self.child[n, : len(cs)] = cs

        self.max_depth = int(self.depth.max())
        self.levels = [np.flatnonzero(self.depth == d) for d in range(self.max_depth + 1)]
        # Decision edges: nodes entered by a player's action.
        self.dec_edges = np.flatnonzero(self.edge_seq >= 0)
        self.dec_parent = self.parent[self.dec_edges]
        self.dec_player = self.edge_player[self.dec_edges]
        self.dec_seq = self.edge_seq[self.dec_edges]
        self.dec_own_mask = np.arange(n_players)[None, :] == self.dec_player[:, None]
        # Infostates grouped by the length of their player's own sequence, for realization plans.
        own_level = np.zeros(self.num_infosets, dtype=int)
        for info in range(self.num_infosets):
            ps = self.infoset_parent_seq[info]
            own_level[info] = 0 if ps < 0 else own_level[self.seq_infoset[ps]] + 1
        self.own_levels = [np.flatnonzero(own_level == lv) for lv in range(own_level.max() + 1)]
        self.seq_parent_seq = self.infoset_parent_seq_arr[self.seq_infoset]
        self.terminal_mask_other = [
            np.arange(n_players) != i for i in range(n_players)
        ]  # used for opponent weights

    # ----------------------------------------------------------------- strategies
    def uniform(self) -> np.ndarray:
        return 1.0 / self.infoset_num_actions[self.seq_infoset]

    def random_strategy(self, rng: np.random.Generator) -> np.ndarray:
        """A strategy drawn uniformly from the simplex at every infostate."""
        x = rng.exponential(size=self.num_seqs)
        return x / self.infoset_sum(x)[self.seq_infoset]

    def infoset_sum(self, x: np.ndarray) -> np.ndarray:
        return np.bincount(self.seq_infoset, weights=x, minlength=self.num_infosets)

    def normalize(self, x: np.ndarray, fallback: np.ndarray | None = None) -> np.ndarray:
        """Per-infostate normalisation; infostates with zero mass get `fallback` (uniform)."""
        total = self.infoset_sum(x)[self.seq_infoset]
        fb = self.uniform() if fallback is None else fallback
        out = np.where(total > 0, x / np.where(total > 0, total, 1.0), fb)
        return out

    # ----------------------------------------------------------------- tree passes
    def edge_prob(self, sigma: np.ndarray) -> np.ndarray:
        p = self.edge_chance.copy()
        mask = self.edge_seq >= 0
        p[mask] = sigma[self.edge_seq[mask]]
        return p

    def reach(self, sigma: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Per-node reach of each player's own actions, and chance reach."""
        reach = np.ones((self.num_nodes, self.num_players))
        chance = np.ones(self.num_nodes)
        for d in range(1, self.max_depth + 1):
            nodes = self.levels[d]
            par = self.parent[nodes]
            reach[nodes] = reach[par]
            chance[nodes] = chance[par] * self.edge_chance[nodes]
            dec = nodes[self.edge_seq[nodes] >= 0]
            reach[dec, self.edge_player[dec]] *= sigma[self.edge_seq[dec]]
        return reach, chance

    def values(self, sigma: np.ndarray) -> np.ndarray:
        """Expected returns of every player conditional on reaching each node."""
        v = np.zeros((self.num_nodes, self.num_players))
        v[self.terminal_nodes] = self.terminal_returns
        p = self.edge_prob(sigma)
        for d in range(self.max_depth, 0, -1):
            nodes = self.levels[d]
            np.add.at(v, self.parent[nodes], p[nodes, None] * v[nodes])
        return v

    def expected_returns(self, sigma: np.ndarray) -> np.ndarray:
        return self.values(sigma)[0]

    def instant_regrets(self, sigma, reach, chance, v) -> np.ndarray:
        """Immediate counterfactual regret of every sequence under `sigma` (all players)."""
        reach_h = reach[self.dec_parent]
        others = np.prod(np.where(self.dec_own_mask, 1.0, reach_h), axis=1)
        cf_reach = chance[self.dec_parent] * others
        q = cf_reach * v[self.dec_edges, self.dec_player]
        cfv_seq = np.bincount(self.dec_seq, weights=q, minlength=self.num_seqs)
        cfv_info = self.infoset_sum(sigma * cfv_seq)
        return cfv_seq - cfv_info[self.seq_infoset]

    def own_reach_seq(self, reach: np.ndarray) -> np.ndarray:
        """Each sequence's player's own reach probability of the sequence's infostate."""
        info_reach = reach[self.infoset_node_arr, self.infoset_player_arr]
        return info_reach[self.seq_infoset]

    def opponent_weights(self, reach: np.ndarray, chance: np.ndarray, player: int) -> np.ndarray:
        """Chance times the other players' reach, per terminal."""
        z = self.terminal_nodes
        return chance[z] * np.prod(reach[z][:, self.terminal_mask_other[player]], axis=1)

    def best_response_value(
        self, player: int, weights: np.ndarray, utility: np.ndarray | None = None
    ) -> tuple[float, np.ndarray]:
        """Best-response value of `player` against opponent/chance terminal weights.

        Returns the (unnormalised) value sum_z w(z) pi_br(z) u(z) and the chosen action
        index per infostate of `player` (-1 for other players' infostates). `utility`
        replaces the player's own terminal returns (for example, minus another player's
        returns, to find the deviation that hurts that player most).
        """
        u = np.zeros(self.num_nodes + 1)
        own = self.terminal_returns[:, player] if utility is None else utility
        u[self.terminal_nodes] = weights * own
        choice = np.full(self.num_infosets, -1)
        for d in range(self.max_depth, -1, -1):
            nodes = self.levels[d]
            nodes = nodes[self.node_player[nodes] != TERMINAL]
            if len(nodes) == 0:
                continue
            mine = nodes[self.node_player[nodes] == player]
            rest = nodes[self.node_player[nodes] != player]
            if len(rest):
                u[rest] = u[self.child[rest]].sum(axis=1)
            if len(mine):
                infos = self.node_infoset[mine]
                q = np.full((self.num_infosets, self.max_actions), -np.inf)
                touched = np.unique(infos)
                for k in range(self.max_actions):
                    ok = touched[k < self.infoset_num_actions[touched]]
                    q[ok, k] = 0.0
                for k in range(self.max_actions):
                    valid = k < self.infoset_num_actions[infos]
                    np.add.at(q[:, k], infos[valid], u[self.child[mine[valid], k]])
                best = np.argmax(q[touched], axis=1)
                choice[touched] = best
                u[mine] = u[self.child[mine, choice[infos]]]
        return float(u[0]), choice

    def gains(self, sigma: np.ndarray) -> dict:
        """Per-player best-response gains and expected returns of a profile."""
        reach, chance = self.reach(sigma)
        ev = self.values(sigma)[0]
        gains = np.zeros(self.num_players)
        for i in range(self.num_players):
            br, _ = self.best_response_value(i, self.opponent_weights(reach, chance, i))
            gains[i] = br - ev[i]
        return {"gains": gains, "ev": ev}

    # ----------------------------------------------------------------- sequence form
    def realization_plan(self, sigma: np.ndarray) -> np.ndarray:
        x = np.zeros(self.num_seqs)
        for infos in self.own_levels:
            seqs = np.flatnonzero(np.isin(self.seq_infoset, infos))
            ps = self.seq_parent_seq[seqs]
            x[seqs] = sigma[seqs] * np.where(ps >= 0, x[np.maximum(ps, 0)], 1.0)
        return x

    def behavioral(self, x: np.ndarray, fallback: np.ndarray) -> np.ndarray:
        ps = self.seq_parent_seq
        denom = np.where(ps >= 0, x[np.maximum(ps, 0)], 1.0)
        return np.where(denom > 0, x / np.where(denom > 0, denom, 1.0), fallback)

    def pure_from_choice(self, choice: np.ndarray, player: int) -> np.ndarray:
        """Behavioural strategy (for `player`'s sequences) that plays `choice` everywhere."""
        sigma = (self.seq_k == choice[self.seq_infoset]).astype(float)
        return np.where(self.seq_player == player, sigma, 0.0)

    # ----------------------------------------------------------------- OpenSpiel interop
    def to_openspiel(self, sigma: np.ndarray) -> policy_lib.TabularPolicy:
        pol = policy_lib.TabularPolicy(self.game)
        for info, key in enumerate(self.infoset_keys):
            row = pol.state_lookup[key]
            first = self.infoset_first_seq[info]
            pol.action_probability_array[row, :] = 0.0
            for k, action in enumerate(self.infoset_actions[info]):
                pol.action_probability_array[row, action] = sigma[first + k]
        return pol

    def from_openspiel(self, pol) -> np.ndarray:
        """Read a python Policy or a pyspiel.Policy into a flat profile."""
        sigma = np.zeros(self.num_seqs)
        for info, state in enumerate(self.infoset_state):
            if isinstance(pol, pyspiel.Policy):
                probs = dict(pol.get_state_policy(state))
            else:
                probs = pol.action_probabilities(state)
            first = self.infoset_first_seq[info]
            for k, action in enumerate(self.infoset_actions[info]):
                sigma[first + k] = probs.get(action, 0.0)
        return self.normalize(sigma)


# --------------------------------------------------------------------- solvers
def run_cfr(
    tree: GameTree,
    iterations: int,
    checkpoints: list[int],
    variant: str = "cfr",
    init: np.ndarray | None = None,
    alternating: bool = False,
) -> dict:
    """Full-width CFR, with simultaneous (default) or alternating updates.

    variant: "cfr" (regret matching, uniform averaging), "cfr+" (regret matching+, linear
    averaging) or "linear" (linear CFR: regrets and average both weighted by t).
    `init` replaces the first iterate (normally uniform); regrets start at zero.

    Records, at each checkpoint, the per-player gains of the average-strategy profile and
    the coarse-correlated-equilibrium (CCE) gap of the weighted empirical distribution of
    the iterates: for each player, the best-response value against the mixture of the
    other players' iterate profiles minus the player's average iterate value. The CCE
    gap is only recorded for simultaneous updates, where every player's regret is measured
    against the same sequence of profiles (the no-regret-to-CCE argument needs that).

    With `alternating=True` players are updated in turn within an iteration, each seeing
    the others' latest strategies (the order OpenSpiel's CFR solvers use). It converges
    much faster in practice but has no single sequence of joint profiles to report.
    """
    if alternating:
        return _run_cfr_alternating(tree, iterations, checkpoints, variant, init)
    n = tree.num_players
    regrets = np.zeros(tree.num_seqs)
    avg_num = np.zeros(tree.num_seqs)
    w_bar = np.zeros((n, len(tree.terminal_nodes)))
    u_bar = np.zeros(n)
    w_sum = 0.0
    out = []
    marks = set(checkpoints)
    for t in range(1, iterations + 1):
        if t == 1 and init is not None:
            sigma = init.copy()
        else:
            pos = np.maximum(regrets, 0.0)
            sigma = tree.normalize(pos)
        reach, chance = tree.reach(sigma)
        v = tree.values(sigma)
        r = tree.instant_regrets(sigma, reach, chance, v)
        weight = 1.0 if variant == "cfr" else float(t)
        if variant == "cfr":
            regrets += r
        elif variant == "cfr+":
            regrets = np.maximum(regrets + r, 0.0)
        elif variant == "linear":
            regrets += t * r
        else:
            raise ValueError(variant)
        avg_num += weight * tree.own_reach_seq(reach) * sigma
        for i in range(n):
            w_bar[i] += weight * tree.opponent_weights(reach, chance, i)
        u_bar += weight * v[0]
        w_sum += weight
        if t in marks:
            avg = tree.normalize(avg_num)
            g = tree.gains(avg)
            cce = np.array(
                [tree.best_response_value(i, w_bar[i] / w_sum)[0] - u_bar[i] / w_sum for i in range(n)]
            )
            out.append(
                {
                    "iteration": t,
                    "gains": g["gains"].tolist(),
                    "ev": g["ev"].tolist(),
                    "cce_gap": cce.tolist(),
                    "cce_ev": (u_bar / w_sum).tolist(),
                }
            )
    return {"checkpoints": out, "average": tree.normalize(avg_num)}


def _rm(tree: GameTree, regrets: np.ndarray) -> np.ndarray:
    return tree.normalize(np.maximum(regrets, 0.0))


def _run_cfr_alternating(tree, iterations, checkpoints, variant, init) -> dict:
    n = tree.num_players
    regrets = np.zeros(tree.num_seqs)
    avg_num = np.zeros(tree.num_seqs)
    sigma = tree.uniform() if init is None else init.copy()
    out = []
    marks = set(checkpoints)
    for t in range(1, iterations + 1):
        weight = 1.0 if variant == "cfr" else float(t)
        for i in range(n):
            mine = tree.seq_player == i
            reach, chance = tree.reach(sigma)
            v = tree.values(sigma)
            r = tree.instant_regrets(sigma, reach, chance, v)
            if variant == "cfr":
                regrets[mine] += r[mine]
            elif variant == "cfr+":
                regrets[mine] = np.maximum(regrets[mine] + r[mine], 0.0)
            elif variant == "linear":
                regrets[mine] += t * r[mine]
            else:
                raise ValueError(variant)
            avg_num[mine] += weight * (tree.own_reach_seq(reach) * sigma)[mine]
            sigma = np.where(mine, _rm(tree, regrets), sigma)
        if t in marks:
            avg = tree.normalize(avg_num)
            g = tree.gains(avg)
            out.append({"iteration": t, "gains": g["gains"].tolist(), "ev": g["ev"].tolist()})
    return {"checkpoints": out, "average": tree.normalize(avg_num)}


def run_fictitious_play(
    tree: GameTree, iterations: int, checkpoints: list[int], init: np.ndarray | None = None
) -> dict:
    """Full-width extensive-form fictitious play with simultaneous best responses.

    The average is kept in sequence form (realization plans) and mixed with step 1/(t+1),
    which is the standard XFP update (Heinrich, Lanctot and Silver, 2015). `init` is the
    starting average (uniform if omitted).
    """
    n = tree.num_players
    sigma0 = tree.uniform() if init is None else init.copy()
    x_bar = tree.realization_plan(sigma0)
    sigma_bar = sigma0
    out = []
    marks = set(checkpoints)
    for t in range(1, iterations + 1):
        reach, chance = tree.reach(sigma_bar)
        x_br = np.zeros(tree.num_seqs)
        for i in range(n):
            _, choice = tree.best_response_value(i, tree.opponent_weights(reach, chance, i))
            x_br += tree.realization_plan(tree.pure_from_choice(choice, i))
        x_bar = x_bar + (x_br - x_bar) / (t + 1)
        sigma_bar = tree.behavioral(x_bar, fallback=sigma_bar)
        if t in marks:
            g = tree.gains(sigma_bar)
            out.append({"iteration": t, "gains": g["gains"].tolist(), "ev": g["ev"].tolist()})
    return {"checkpoints": out, "average": sigma_bar}
