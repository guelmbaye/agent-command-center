"""ACC domain layer — pure, dependency-free business model.

Architectural rule (Doc 07 §3): business logic never lives inside a prompt.
This package performs no I/O: no Firestore, no HTTP, no Gemini.
"""
