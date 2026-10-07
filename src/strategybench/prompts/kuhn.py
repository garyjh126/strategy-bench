from strategybench.prompts.base import PromptTemplate

KUHN_V1 = PromptTemplate(
    version="kuhn-v1",
    system="""You are playing Kuhn poker, a two-player card game.
Your goal is to maximise your expected winnings.

Rules:
- The deck has three cards: Jack, Queen, King (King is highest).
- Each player antes 1 chip and is dealt one private card. The third card is not used.
- Player 1 acts first and may CHECK or BET (1 chip).
- If Player 1 checks, Player 2 may CHECK (go to showdown) or BET (1 chip).
- A player facing a bet may FOLD (forfeit the pot) or CALL (match the bet and go to showdown).
- There is at most one bet per hand. At showdown the higher card wins the pot.

You will be told your seat, your card and the actions so far, then asked for your action.""",
)


# Robustness ablation: same rules, different wording and order.
KUHN_V1_PARA = PromptTemplate(
    version="kuhn-v1-para",
    system="""This is a game of Kuhn poker between two players.
Play to win as many chips as possible on average.

How the game works:
- Three cards are used: Jack (lowest), Queen and King (highest).
- Both players put 1 chip into the pot and each receives one hidden card; one card stays unused.
- Only one bet of 1 chip can be made in a hand.
- Player 1 starts by choosing CHECK or BET. After a check, Player 2 chooses CHECK or BET.
- Facing a bet, a player chooses CALL (add 1 chip, then cards are compared) or FOLD (give up the pot).
- If both players check, or a bet is called, the player holding the higher card takes the pot.

Each turn you will see your seat, your card and what has happened so far, and you will choose an action.""",
)
