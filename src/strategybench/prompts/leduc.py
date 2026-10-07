from strategybench.prompts.base import PromptTemplate

LEDUC_V1 = PromptTemplate(
    version="leduc-v1",
    system="""You are playing Leduc poker, a two-player card game.
Your goal is to maximise your expected winnings.

Rules:
- The deck has six cards: two Jacks, two Queens and two Kings. Suits do not matter.
- Each player antes 1 chip and is dealt one private card.
- There are two betting rounds. After the first round, one public card is dealt face up.
- Player 1 acts first in each round.
- If nobody has bet in the current round, you may CHECK or BET.
- Facing a bet you may FOLD, CALL or RAISE (raise means calling the bet and adding the bet size).
- The bet size is 2 chips in round 1 and 4 chips in round 2.
- Each round allows at most one bet and one raise. After that, the only options are FOLD or CALL.
- A round ends when both players check, or when a bet or raise is called. Folding forfeits the pot.
- At showdown, a player whose private card matches the public card (a pair) wins.
  Otherwise the higher card wins (King > Queen > Jack). Equal cards split the pot.

You will be told your seat, your card, the public card once dealt, the betting so far and the pot,
then asked for your action.""",
)


# Robustness ablation: same rules, different wording and order.
LEDUC_V1_PARA = PromptTemplate(
    version="leduc-v1-para",
    system="""This is a game of Leduc poker between two players.
Play to win as many chips as possible on average.

How the game works:
- Six cards are used: Jack, Queen and King, two of each. Suits play no role.
- Both players put 1 chip into the pot and each receives one hidden card.
- The hand has two betting rounds; between them a single shared card is turned face up.
- In both rounds Player 1 speaks first. With no bet in the round so far, the choices are CHECK or BET.
- Facing a bet, the choices are FOLD, CALL, or RAISE (match the bet, then add one more bet).
- A bet is 2 chips in the first round and 4 chips in the second round.
- At most two bets per round are allowed (one bet and one raise); after that only FOLD or CALL remain.
- The round is over once both players check or a bet is called. A player who folds loses the pot.
- If nobody folds, cards are compared: holding the same rank as the shared card (a pair) beats any
  unpaired card; otherwise King beats Queen beats Jack, and identical ranks share the pot.

Each turn you will see your seat, your card, the shared card once it is shown, the betting so far
and the pot, and you will choose an action.""",
)
