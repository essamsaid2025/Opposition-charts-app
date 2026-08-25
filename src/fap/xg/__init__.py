"""Internal xG integration layer for the FAP application.

This subpackage is the ONLY place the app talks to the frozen standalone
Internal xG Model v1.0. It contains adapters (coordinate + shot schema) that
translate the app's canonical event data into the xG model's input contract and
delegate all scoring to the frozen ``xg`` package — the app never re-implements
any xG feature/formula.

Phase-2 Checkpoint 1 ships only the coordinate adapter (pure, isolated, tested).
The shot-schema adapter and API wiring are added in later checkpoints after
review.
"""
