"""The fake core banking system — a system the bank bought in 1998. §11.

It speaks HTTP and nothing else. Nothing in this package imports the Temporal
SDK, and a test asserts it: the demo's claim is that idempotency is enforced by
the *external* system, not by Temporal, and an SDK import here would make that
claim circular (§20.1).
"""
