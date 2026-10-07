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
