"""Offline evaluation of the AI players and the AI game master.

    python -m app.evals.run --provider scripted --out eval-out

Cases are real positions taken from seeded games, so every run asks the same
questions. What is measured is what the server can check for itself: whether an
answer was well-formed, legal and on time. Whether a narration's *facts* are
right is left to a person; see `report.label_sheet`.
"""
