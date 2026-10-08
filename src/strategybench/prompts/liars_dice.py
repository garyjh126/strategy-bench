from strategybench.prompts.base import PromptTemplate

LIARS_DICE_V1 = PromptTemplate(
    version="liars_dice-v1",
    system="""You are playing Liar's Dice, a two-player bluffing game.
Your goal is to maximise your expected winnings.

Rules:
- Each player rolls one die with three faces: 1, 2 and 3. You see only your own die.
- A bid QxF claims that at least Q of the two dice show face F.
- 3s are wild: a die showing 3 also counts towards a bid on face 1 or face 2. A bid on face 3
  counts only dice showing 3. For example, 1x2 is true if at least one die shows 2 or 3, and
  2x3 is true only if both dice show 3.
- Player 1 makes the first bid. The players then take turns.
- On your turn, either make a higher bid or call LIAR to challenge the current bid.
  LIAR cannot be called before the first bid.
- A higher bid has a higher quantity, or the same quantity and a higher face. From lowest to
  highest the bids are 1x1, 1x2, 1x3, 2x1, 2x2, 2x3. After 2x3, LIAR is the only option.
- When LIAR is called, both dice are revealed. If the current bid is true, the player who made it
  wins; otherwise the player who called LIAR wins.
- The winner gains 1 point and the loser loses 1 point. The game ends when LIAR is called.

You will be told your seat, your die and the bids so far, then asked for your action.""",
)


# Robustness ablation: same rules, different wording and order.
LIARS_DICE_V1_PARA = PromptTemplate(
    version="liars_dice-v1-para",
    system="""This is a game of Liar's Dice between two players.
Play to win as many points as possible on average.

How the game works:
- There are two dice, one per player. Each die has three faces (1, 2 and 3), and each player
  looks only at their own die.
- Players bid on what the two dice show together. The bid QxF means "at least Q of the two dice
  show F".
- The face 3 is wild. When counting for a bid on 1 or on 2, dice showing 3 count as well; when
  counting for a bid on 3, only actual 3s count. So 2x1 is true when each die shows 1 or 3, and
  1x3 is true when at least one die shows 3.
- Ranked from weakest to strongest, the bids are 1x1, 1x2, 1x3, 2x1, 2x2, 2x3: quantity first,
  then face.
- Player 1 must start with a bid. After that the players alternate, and on each turn a player
  either bids higher than the current bid or calls LIAR. Once 2x3 has been bid, calling LIAR is
  the only choice.
- Calling LIAR ends the game and both dice are shown. A true bid wins for the player who made it;
  a false bid wins for the player who called LIAR.
- The winner receives 1 point from the loser.

Each turn you will see your seat, your die and the bidding so far, and you will choose an action.""",
)
