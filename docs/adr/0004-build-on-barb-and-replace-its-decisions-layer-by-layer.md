# 0004. Build on BARb and replace its decisions layer by layer

- **Status:** Accepted
- **Date:** 2026-11-22

## Context

BARb, the AI that ships with BAR, already plays whole games: pathing,
placement, threat maps, production and army control ([`barb.md`](../barb.md)).
A learned model that covers only part of the game still needs something to
play the rest. Apex replaced BARb's army control with its own and lost to
stock BARb twice before reverting ([`related-work.md`](../related-work.md)).

## Decision

Reason8 is a BARb variant. Learned models replace BARb's decisions one layer
at a time: openings first, then macro (what to build for the whole game), then
production. Army control and unit micro stay with BARb until there's a reason
to change that. The first hook is BARb's opener tables, which need no C++
changes.

## Consequences

- The bot can always finish a game, whatever layer the model covers.
- We depend on BARb's code, its profiles and its hidden rules: timers and
  limits in its configuration can silently refuse a unit the model asked for,
  so the in-game side has to check what was actually built.
- Deeper layers may need a C++ build of the AI (CircuitAI) later.
- A custom variant needs its own AI short name to load instead of stock BARb.
